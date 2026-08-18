import os
import time
import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from app.config import settings

DATABASE_PATH = settings.DATABASE_PATH

@asynccontextmanager
async def get_db():
    """Async context manager yielding a configured SQLite connection in WAL mode."""
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA busy_timeout=5000;")
        yield db

async def init_db():
    """Initialize database tables and indexes."""
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                keyword TEXT NOT NULL,
                dm_message TEXT NOT NULL,
                created_at REAL NOT NULL
            );
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                processed_at REAL NOT NULL
            );
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_rule_executions (
                user_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                executed_at REAL NOT NULL,
                PRIMARY KEY (user_id, rule_id)
            );
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dm_queue (
                id TEXT PRIMARY KEY,
                recipient_user_id TEXT NOT NULL,
                message TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at REAL NOT NULL,
                dm_id TEXT,
                reconcile_attempts INTEGER NOT NULL DEFAULT 0,
                last_polled_at REAL,
                error_detail TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
        """)
        
        # Initialize duplicates_blocked counter if not exists
        await db.execute("""
            INSERT OR IGNORE INTO counters (key, value) VALUES ('duplicates_blocked', 0);
        """)
        
        # Performance indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_queue_status_attempt ON dm_queue(status, next_attempt_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_queue_comment_id ON dm_queue(comment_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_queue_dm_id ON dm_queue(dm_id);")
        
        # Seed default rules if database is empty
        cursor = await db.execute("SELECT COUNT(*) as count FROM rules")
        row = await cursor.fetchone()
        if row and row["count"] == 0:
            now = time.time()
            await db.execute(
                "INSERT INTO rules (id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
                ("rule_default_price", "PRICE", "Here is our price list: https://example.com/pricing", now)
            )
            await db.execute(
                "INSERT INTO rules (id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
                ("rule_default_catalog", "CATALOG", "Here is our catalog: https://example.com/catalog", now)
            )
            await db.execute(
                "INSERT INTO rules (id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
                ("rule_default_link", "LINK", "Here is the link: https://example.com/shop", now)
            )
        
        await db.commit()

# --- Rule Database Operations ---

async def create_rule(rule_id: str, keyword: str, dm_message: str) -> Dict[str, Any]:
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO rules (id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
            (rule_id, keyword, dm_message, now)
        )
        await db.commit()
    return {"rule_id": rule_id, "keyword": keyword, "dm_message": dm_message}

async def get_all_rules() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id as rule_id, keyword, dm_message, created_at FROM rules ORDER BY created_at ASC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_rule(rule_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await db.commit()
        return cursor.rowcount > 0

# --- Event Deduplication ---

async def is_event_processed(event_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,))
        row = await cursor.fetchone()
        return row is not None

async def mark_event_processed(event_id: str, event_type: str):
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO processed_events (event_id, event_type, processed_at) VALUES (?, ?, ?)",
            (event_id, event_type, time.time())
        )
        await db.commit()

# --- User-Rule Deduplication & Atomic Reservation ---

async def reserve_user_rule_execution(user_id: str, rule_id: str, comment_id: str) -> bool:
    """
    Atomically attempts to reserve the (user_id, rule_id) pair.
    Returns True if reserved successfully (first time user matches this rule).
    Returns False if user already received a DM for this rule.
    """
    now = time.time()
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO user_rule_executions (user_id, rule_id, comment_id, status, executed_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, rule_id, comment_id, "queued", now)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            # Duplicate detected! Increment duplicate counter
            await db.execute("UPDATE counters SET value = value + 1 WHERE key = 'duplicates_blocked'")
            await db.commit()
            return False

async def cancel_pending_dms_for_comment(comment_id: str) -> int:
    """
    Handles comment.deleted: if a DM for this comment is still pending or queued, cancel it.
    """
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE dm_queue SET status = 'cancelled', updated_at = ? WHERE comment_id = ? AND status IN ('pending', 'retry_scheduled')",
            (now, comment_id)
        )
        await db.commit()
        return cursor.rowcount

# --- DM Queue Operations ---

async def enqueue_dm(
    task_id: str,
    recipient_user_id: str,
    message: str,
    comment_id: str,
    rule_id: str,
    idempotency_key: str
) -> bool:
    now = time.time()
    async with get_db() as db:
        try:
            await db.execute("""
                INSERT INTO dm_queue (
                    id, recipient_user_id, message, comment_id, rule_id, idempotency_key,
                    status, attempts, max_attempts, next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
            """, (
                task_id, recipient_user_id, message, comment_id, rule_id, idempotency_key,
                settings.MAX_SEND_ATTEMPTS, now, now, now
            ))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def fetch_next_pending_dm() -> Optional[Dict[str, Any]]:
    """Fetch next eligible pending DM for the outbound sender."""
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT * FROM dm_queue
            WHERE status IN ('pending', 'retry_scheduled') AND next_attempt_at <= ?
            ORDER BY next_attempt_at ASC
            LIMIT 1
        """, (now,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def update_dm_accepted(task_id: str, dm_id: str):
    now = time.time()
    async with get_db() as db:
        await db.execute("""
            UPDATE dm_queue
            SET status = 'accepted', dm_id = ?, attempts = attempts + 1, updated_at = ?, last_polled_at = ?
            WHERE id = ?
        """, (dm_id, now, now, task_id))
        await db.commit()

async def update_dm_retry(task_id: str, backoff_seconds: float, error_detail: str):
    now = time.time()
    next_attempt = now + backoff_seconds
    async with get_db() as db:
        await db.execute("""
            UPDATE dm_queue
            SET status = CASE WHEN attempts + 1 >= max_attempts THEN 'failed' ELSE 'retry_scheduled' END,
                attempts = attempts + 1,
                next_attempt_at = ?,
                error_detail = ?,
                updated_at = ?
            WHERE id = ?
        """, (next_attempt, error_detail, now, task_id))
        await db.commit()

async def update_dm_failed(task_id: str, error_detail: str):
    now = time.time()
    async with get_db() as db:
        await db.execute("""
            UPDATE dm_queue
            SET status = 'failed', error_detail = ?, updated_at = ?
            WHERE id = ?
        """, (error_detail, now, task_id))
        await db.commit()

async def update_dm_terminal_status(task_id: str, status: str):
    now = time.time()
    async with get_db() as db:
        await db.execute("""
            UPDATE dm_queue
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (status, now, task_id))
        await db.commit()

async def fetch_accepted_dms_for_reconciliation(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch DMs accepted by Mock API that need status verification."""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT * FROM dm_queue
            WHERE status = 'accepted' AND dm_id IS NOT NULL
            ORDER BY last_polled_at ASC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def update_dm_polled_time(task_id: str):
    now = time.time()
    async with get_db() as db:
        await db.execute("UPDATE dm_queue SET last_polled_at = ?, reconcile_attempts = reconcile_attempts + 1 WHERE id = ?", (now, task_id))
        await db.commit()

async def requeue_failed_accepted_dm(task_id: str):
    """If Mock API accepted a DM but later marked it failed, re-queue it if retry budget permits."""
    now = time.time()
    async with get_db() as db:
        await db.execute("""
            UPDATE dm_queue
            SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
                next_attempt_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, task_id))
        await db.commit()

# --- Stats Aggregation ---

async def get_system_stats() -> Dict[str, int]:
    """
    Returns accurate live numbers:
    - sent: DMs confirmed delivered
    - failed: DMs permanently failed (400, max retries reached, or terminal failure)
    - queued: DMs waiting to send, waiting retry, or waiting reconciliation
    - duplicates_blocked: DMs prevented by (user_id, rule_id) deduplication
    """
    async with get_db() as db:
        # Count by status in dm_queue
        cursor = await db.execute("""
            SELECT status, COUNT(*) as cnt
            FROM dm_queue
            GROUP BY status
        """)
        rows = await cursor.fetchall()
        status_counts = {row["status"]: row["cnt"] for row in rows}
        
        # Get duplicates_blocked counter
        cursor = await db.execute("SELECT value FROM counters WHERE key = 'duplicates_blocked'")
        dup_row = await cursor.fetchone()
        duplicates_blocked = dup_row["value"] if dup_row else 0
        
        sent = status_counts.get("delivered", 0)
        failed = status_counts.get("failed", 0)
        queued = (
            status_counts.get("pending", 0) +
            status_counts.get("sending", 0) +
            status_counts.get("retry_scheduled", 0) +
            status_counts.get("accepted", 0)
        )
        
        return {
            "sent": sent,
            "failed": failed,
            "queued": queued,
            "duplicates_blocked": duplicates_blocked
        }

async def reset_database():
    """Reset all tables for clean testing."""
    await init_db()
    async with get_db() as db:
        await db.execute("DELETE FROM rules;")
        await db.execute("DELETE FROM processed_events;")
        await db.execute("DELETE FROM user_rule_executions;")
        await db.execute("DELETE FROM dm_queue;")
        await db.execute("UPDATE counters SET value = 0 WHERE key = 'duplicates_blocked';")
        await db.commit()
