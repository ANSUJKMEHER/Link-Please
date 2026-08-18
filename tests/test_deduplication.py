import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import reset_database, get_system_stats

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await reset_database()
    yield
    await reset_database()

@pytest.mark.asyncio
async def test_event_id_deduplication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule
        await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list"})

        payload = {
            "event_id": "evt_duplicate_stream_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.481Z",
            "data": {
                "comment_id": "cmt_1",
                "post_id": "post_1",
                "text": "What is the price?",
                "created_at": "2026-08-10T09:14:21.900Z",
                "from": {"user_id": "usr_buyer_1", "username": "buyer1"}
            }
        }

        # First delivery
        res1 = await client.post("/webhook", json=payload)
        assert res1.status_code == 200
        assert res1.json()["result"]["status"] == "processed"
        assert res1.json()["result"]["enqueued_dms"] == 1

        # Redelivery of same event_id (~8% mock API redelivery rate)
        res2 = await client.post("/webhook", json=payload)
        assert res2.status_code == 200
        assert res2.json()["result"]["status"] == "ignored"
        assert res2.json()["result"]["reason"] == "duplicate_event"

        stats = await get_system_stats()
        assert stats["queued"] == 1
        assert stats["duplicates_blocked"] == 0

@pytest.mark.asyncio
async def test_user_rule_deduplication():
    """
    Requirement Part A: The same user never gets DMed twice for the same rule,
    no matter how many times they comment.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule for "CATALOG"
        await client.post("/rules", json={"keyword": "CATALOG", "dm_message": "Catalog download"})

        # First comment by usr_alice
        res1 = await client.post("/webhook", json={
            "event_id": "evt_alice_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.000Z",
            "data": {
                "comment_id": "cmt_alice_1",
                "post_id": "post_1",
                "text": "Send me the CATALOG please!",
                "created_at": "2026-08-10T09:14:21.000Z",
                "from": {"user_id": "usr_alice", "username": "alice.wonder"}
            }
        })
        assert res1.status_code == 200
        assert res1.json()["result"]["enqueued_dms"] == 1
        assert res1.json()["result"]["blocked_duplicates"] == 0

        # Second comment by usr_alice (different comment_id, different event_id, same keyword/rule)
        res2 = await client.post("/webhook", json={
            "event_id": "evt_alice_2",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:15:22.000Z",
            "data": {
                "comment_id": "cmt_alice_2",
                "post_id": "post_2",
                "text": "Hey I need the CATALOG again",
                "created_at": "2026-08-10T09:15:21.000Z",
                "from": {"user_id": "usr_alice", "username": "alice.changed_username"}
            }
        })
        assert res2.status_code == 200
        assert res2.json()["result"]["enqueued_dms"] == 0
        assert res2.json()["result"]["blocked_duplicates"] == 1

        # Third comment by usr_bob (different user, same rule -> should be enqueued)
        res3 = await client.post("/webhook", json={
            "event_id": "evt_bob_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:16:22.000Z",
            "data": {
                "comment_id": "cmt_bob_1",
                "post_id": "post_1",
                "text": "CATALOG please",
                "created_at": "2026-08-10T09:16:21.000Z",
                "from": {"user_id": "usr_bob", "username": "bob_builder"}
            }
        })
        assert res3.status_code == 200
        assert res3.json()["result"]["enqueued_dms"] == 1
        assert res3.json()["result"]["blocked_duplicates"] == 0

        # Check GET /stats
        stats_res = await client.get("/stats")
        stats = stats_res.json()
        assert stats["queued"] == 2  # Alice + Bob
        assert stats["duplicates_blocked"] == 1  # Alice's 2nd comment blocked
