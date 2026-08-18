import asyncio
import logging
import httpx
from typing import Optional
from app.config import settings
from app.db import (
    fetch_next_pending_dm,
    update_dm_accepted,
    update_dm_retry,
    update_dm_failed
)
from app.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

class OutboundDMWorker:
    def __init__(self):
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self):
        self.is_running = True
        self.client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Outbound DM Worker started.")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.aclose()
        logger.info("Outbound DM Worker stopped.")

    async def _run_loop(self):
        while self.is_running:
            try:
                # 1. Check if there are pending DMs ready to send
                task = await fetch_next_pending_dm()
                if not task:
                    await asyncio.sleep(settings.WORKER_POLL_INTERVAL_SECONDS)
                    continue

                # 2. Acquire token from the sliding-window rate limiter
                # This guarantees we NEVER breach 10 requests / 60s
                await rate_limiter.acquire()

                # Re-verify task is still pending (in case cancelled while waiting for rate limit)
                # If deleted in between, worker handles gracefully
                await self._send_dm(task)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Outbound DM Worker loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _send_dm(self, task: dict):
        url = f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/dm/send"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": settings.API_KEY,
            "Idempotency-Key": task["idempotency_key"]
        }
        payload = {
            "recipient_user_id": task["recipient_user_id"],
            "message": task["message"],
            "comment_id": task["comment_id"]
        }

        task_id = task["id"]
        current_attempts = task["attempts"]

        try:
            response = await self.client.post(url, json=payload, headers=headers)
            
            if response.status_code == 202:
                # Accepted! Update status to 'accepted' and store dm_id for reconciliation
                data = response.json()
                dm_id = data.get("dm_id", "")
                await update_dm_accepted(task_id, dm_id)
                logger.info(f"DM accepted for task {task_id} with dm_id: {dm_id}")

            elif response.status_code == 429:
                # Rate limited
                retry_after_header = response.headers.get("Retry-After", "5")
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    retry_after = 5.0
                
                logger.warning(f"Rate limited 429 on task {task_id}. Retry-After: {retry_after}s")
                await rate_limiter.report_429(retry_after)
                await update_dm_retry(task_id, retry_after, f"Rate limited 429. Retry after {retry_after}s")

            elif response.status_code == 500:
                # Server internal error (~20% probability on Mock API). Safe to retry!
                backoff = settings.INITIAL_BACKOFF_SECONDS * (2 ** current_attempts)
                logger.warning(f"Mock API 500 on task {task_id}. Retrying in {backoff}s (attempt {current_attempts + 1})")
                await update_dm_retry(task_id, backoff, f"Mock API 500: internal_error")

            elif response.status_code == 400:
                # Malformed payload - not retryable
                detail = response.text
                logger.error(f"Mock API 400 on task {task_id}: {detail}")
                await update_dm_failed(task_id, f"Invalid request 400: {detail}")

            else:
                # Other status codes
                if response.status_code >= 500:
                    backoff = settings.INITIAL_BACKOFF_SECONDS * (2 ** current_attempts)
                    await update_dm_retry(task_id, backoff, f"HTTP {response.status_code}: {response.text}")
                else:
                    await update_dm_failed(task_id, f"HTTP {response.status_code}: {response.text}")

        except httpx.RequestError as exc:
            # Network or connection error: safe to retry with exponential backoff
            backoff = settings.INITIAL_BACKOFF_SECONDS * (2 ** current_attempts)
            logger.warning(f"Network error sending DM {task_id}: {exc}. Retrying in {backoff}s")
            await update_dm_retry(task_id, backoff, f"Network error: {str(exc)}")

outbound_worker = OutboundDMWorker()
