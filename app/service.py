import hmac
import hashlib
import uuid
import logging
from typing import Dict, Any, Tuple
from app.config import settings
from app.db import (
    is_event_processed,
    mark_event_processed,
    get_all_rules,
    reserve_user_rule_execution,
    cancel_pending_dms_for_comment,
    enqueue_dm
)

logger = logging.getLogger(__name__)

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verifies HMAC-SHA256 signature against the raw request body using API_KEY as secret.
    Signature header format: 'sha256=<hex_digest>'
    """
    if not settings.VERIFY_SIGNATURE or not settings.API_KEY:
        # Signature verification bypassed if no API key is configured
        return True
    
    if not signature_header:
        logger.warning("Missing signature header")
        return False
    
    parts = signature_header.split("sha256=")
    if len(parts) != 2:
        logger.warning("Invalid signature header format: %s", signature_header)
        return False
    
    expected_sig = parts[1].strip()
    computed_sig = hmac.new(
        key=settings.API_KEY.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    is_valid = hmac.compare_digest(computed_sig, expected_sig)
    if not is_valid:
        logger.warning("Signature mismatch: computed=%s expected=%s", computed_sig, expected_sig)
    return is_valid

async def process_webhook_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processes an incoming event from the mock Instagram API.
    Handles event deduplication, comment deletions, rule matching,
    and user-rule deduplication.
    """
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data", {})
    
    if not event_id:
        return {"status": "error", "message": "missing_event_id"}
    
    # 1. Event Deduplication: Ignore if this exact event_id was already processed
    if await is_event_processed(event_id):
        logger.info(f"Duplicate event received and ignored: {event_id}")
        return {"status": "ignored", "reason": "duplicate_event", "event_id": event_id}
    
    # Mark event as processed
    await mark_event_processed(event_id, event_type or "unknown")
    
    # 2. Handle comment.deleted event
    if event_type == "comment.deleted":
        comment_id = data.get("comment_id")
        if comment_id:
            cancelled_count = await cancel_pending_dms_for_comment(comment_id)
            logger.info(f"Comment deleted: {comment_id}, cancelled {cancelled_count} pending DMs")
            return {"status": "comment_deleted", "comment_id": comment_id, "cancelled_count": cancelled_count}
        return {"status": "ignored", "reason": "missing_comment_id"}
    
    # 3. Handle comment.created event
    if event_type == "comment.created":
        comment_id = data.get("comment_id")
        text = data.get("text", "")
        from_user = data.get("from", {})
        user_id = from_user.get("user_id")
        
        if not comment_id or not user_id or not text:
            return {"status": "ignored", "reason": "invalid_comment_payload"}
        
        # Load active rules
        rules = await get_all_rules()
        if not rules:
            return {"status": "no_rules_matched", "matched_count": 0}
        
        matched_count = 0
        enqueued_count = 0
        blocked_duplicates = 0
        
        lower_text = text.lower()
        
        for rule in rules:
            keyword = rule["keyword"].lower()
            if keyword in lower_text:
                matched_count += 1
                rule_id = rule["rule_id"]
                dm_message = rule["dm_message"]
                
                # Atomically reserve (user_id, rule_id)
                reserved = await reserve_user_rule_execution(user_id, rule_id, comment_id)
                
                if not reserved:
                    # User already received DM for this rule
                    blocked_duplicates += 1
                    logger.info(f"Blocked duplicate DM for user {user_id} and rule {rule_id}")
                else:
                    # Enqueue DM for background delivery
                    task_id = f"task_{uuid.uuid4().hex[:12]}"
                    idempotency_key = f"dm_{rule_id}_{user_id}"
                    
                    enqueued = await enqueue_dm(
                        task_id=task_id,
                        recipient_user_id=user_id,
                        message=dm_message,
                        comment_id=comment_id,
                        rule_id=rule_id,
                        idempotency_key=idempotency_key
                    )
                    if enqueued:
                        enqueued_count += 1
                        logger.info(f"Enqueued DM task {task_id} for user {user_id} on rule {rule_id}")
        
        return {
            "status": "processed",
            "matched_rules": matched_count,
            "enqueued_dms": enqueued_count,
            "blocked_duplicates": blocked_duplicates
        }
    
    return {"status": "unhandled_event_type", "event_type": event_type}
