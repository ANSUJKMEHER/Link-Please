import asyncio
import logging
import httpx
from typing import Optional
from app.config import settings
from app.db import (
    fetch_accepted_dms_for_reconciliation,
    update_dm_terminal_status,
    update_dm_polled_time,
    requeue_failed_accepted_dm
)

logger = logging.getLogger(__name__)

class DeliveryReconciler:
    """
    Delivery status reconciler worker (Part C).
    Polls GET /v1/dm/{dm_id} for accepted DMs to verify whether they became
    'delivered' or 'failed'. Note: Reads do not count against the 10 req/60s rate limit.
    """
    def __init__(self):
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self):
        self.is_running = True
        self.client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Delivery Reconciler started.")

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
        logger.info("Delivery Reconciler stopped.")

    async def _run_loop(self):
        while self.is_running:
            try:
                # 1. Fetch batch of accepted DMs waiting for final status
                pending_dms = await fetch_accepted_dms_for_reconciliation(limit=15)
                
                if not pending_dms:
                    await asyncio.sleep(settings.RECONCILER_POLL_INTERVAL_SECONDS)
                    continue

                for dm in pending_dms:
                    if not self.is_running:
                        break
                    await self._reconcile_single_dm(dm)

                await asyncio.sleep(settings.RECONCILER_POLL_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Delivery Reconciler loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)

    async def _reconcile_single_dm(self, task: dict):
        dm_id = task.get("dm_id")
        task_id = task.get("id")

        if not dm_id:
            return

        url = f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/dm/{dm_id}"
        headers = {
            "X-API-Key": settings.API_KEY
        }

        try:
            response = await self.client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status")

                if status == "delivered":
                    # Terminal Success: Counted in 'sent'
                    logger.info(f"Reconciled DM {dm_id} (task {task_id}): DELIVERED")
                    await update_dm_terminal_status(task_id, "delivered")

                elif status == "failed":
                    # Terminal Failure from platform! Re-queue for retry or mark failed
                    logger.warning(f"Reconciled DM {dm_id} (task {task_id}): FAILED by platform. Re-evaluating retry.")
                    await requeue_failed_accepted_dm(task_id)

                elif status == "queued":
                    # Still in mock API delivery pipeline, update poll timestamp
                    await update_dm_polled_time(task_id)

            elif response.status_code == 404:
                logger.warning(f"Reconciled DM {dm_id} not found (404).")
                await update_dm_polled_time(task_id)

            else:
                logger.warning(f"Reconciliation check HTTP {response.status_code} for DM {dm_id}")
                await update_dm_polled_time(task_id)

        except httpx.RequestError as exc:
            logger.warning(f"Network error during reconciliation of DM {dm_id}: {exc}")

delivery_reconciler = DeliveryReconciler()
