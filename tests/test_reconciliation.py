import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import (
    reset_database,
    get_system_stats,
    update_dm_accepted,
    update_dm_terminal_status,
    fetch_accepted_dms_for_reconciliation
)

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await reset_database()
    yield
    await reset_database()

@pytest.mark.asyncio
async def test_comment_deleted_cancellation():
    """
    Requirement Part C: Handle comment.deleted events sensibly.
    If comment is deleted while DM is queued/pending, cancel the DM.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule
        await client.post("/rules", json={"keyword": "DISCOUNT", "dm_message": "Use code SAVE50"})

        # Send comment.created
        await client.post("/webhook", json={
            "event_id": "evt_c1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.000Z",
            "data": {
                "comment_id": "cmt_to_delete",
                "post_id": "post_1",
                "text": "DISCOUNT please",
                "created_at": "2026-08-10T09:14:21.000Z",
                "from": {"user_id": "usr_buyer_99", "username": "buyer99"}
            }
        })

        stats_before = await get_system_stats()
        assert stats_before["queued"] == 1

        # Send comment.deleted
        res_del = await client.post("/webhook", json={
            "event_id": "evt_c2_del",
            "event_type": "comment.deleted",
            "sent_at": "2026-08-10T09:14:23.000Z",
            "data": {
                "comment_id": "cmt_to_delete"
            }
        })
        assert res_del.status_code == 200
        assert res_del.json()["result"]["cancelled_count"] == 1

        # DM queue status should reflect cancelled (not counted as queued)
        stats_after = await get_system_stats()
        assert stats_after["queued"] == 0

@pytest.mark.asyncio
async def test_stats_reconciliation_terminal_states():
    """
    Test delivery status transitions:
    pending -> accepted -> delivered (counts towards 'sent')
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/rules", json={"keyword": "VIP", "dm_message": "VIP invite"})

        # 1. Ingest comment
        await client.post("/webhook", json={
            "event_id": "evt_vip_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.000Z",
            "data": {
                "comment_id": "cmt_vip_1",
                "post_id": "post_vip",
                "text": "Send me VIP invite",
                "created_at": "2026-08-10T09:14:21.000Z",
                "from": {"user_id": "usr_vip_1", "username": "vip1"}
            }
        })

        stats1 = (await client.get("/stats")).json()
        assert stats1["queued"] == 1
        assert stats1["sent"] == 0

        # Simulate accepted by Mock API
        dms = await fetch_accepted_dms_for_reconciliation(limit=10)
        # Note: it is in pending status right now in DB
        from app.db import fetch_next_pending_dm
        pending = await fetch_next_pending_dm()
        assert pending is not None
        task_id = pending["id"]

        await update_dm_accepted(task_id, "dm_mock_12345")
        
        # Accepted DM is still in 'queued' count until delivered
        stats2 = (await client.get("/stats")).json()
        assert stats2["queued"] == 1
        assert stats2["sent"] == 0

        # Reconciled as delivered
        await update_dm_terminal_status(task_id, "delivered")

        # Now reflects in 'sent' and removed from 'queued'
        stats3 = (await client.get("/stats")).json()
        assert stats3["queued"] == 0
        assert stats3["sent"] == 1
        assert stats3["failed"] == 0
