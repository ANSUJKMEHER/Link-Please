import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import reset_database, get_system_stats, get_db

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await reset_database()
    yield
    await reset_database()

@pytest.mark.asyncio
async def test_case_insensitive_matching_and_substrings():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule for "link"
        await client.post("/rules", json={"keyword": "LINK", "dm_message": "Here is the link!"})

        comments = [
            ("usr_1", "cmt_1", "evt_1", "Please send me the LiNk! 🙏"),
            ("usr_2", "cmt_2", "evt_2", "Link please"),
            ("usr_3", "cmt_3", "evt_3", "send link"),
            ("usr_4", "cmt_4", "evt_4", "I LOVE THIS! NO LINK NEEDED"),  # contains 'LINK'
            ("usr_5", "cmt_5", "evt_5", "Amazing photo!"),               # does not contain link
        ]

        for user_id, cmt_id, evt_id, text in comments:
            await client.post("/webhook", json={
                "event_id": evt_id,
                "event_type": "comment.created",
                "sent_at": "2026-08-10T09:14:22.000Z",
                "data": {
                    "comment_id": cmt_id,
                    "post_id": "post_1",
                    "text": text,
                    "created_at": "2026-08-10T09:14:21.000Z",
                    "from": {"user_id": user_id, "username": f"user_{user_id}"}
                }
            })

        stats = await get_system_stats()
        # usr_1, usr_2, usr_3, usr_4 matched; usr_5 did not
        assert stats["queued"] == 4
        assert stats["duplicates_blocked"] == 0

@pytest.mark.asyncio
async def test_high_concurrency_race_conditions():
    """
    Simulates concurrent requests hitting the webhook simultaneously
    where multiple comments from the SAME user arrive concurrently.
    Only 1 DM should ever be queued, and the rest marked duplicates_blocked.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/rules", json={"keyword": "DISCOUNT", "dm_message": "Code: 50OFF"})

        # Fire 20 concurrent webhook requests from usr_spammer
        async def send_comment(idx: int):
            return await client.post("/webhook", json={
                "event_id": f"evt_spam_{idx}",
                "event_type": "comment.created",
                "sent_at": "2026-08-10T09:14:22.000Z",
                "data": {
                    "comment_id": f"cmt_spam_{idx}",
                    "post_id": "post_1",
                    "text": f"DISCOUNT please #{idx}",
                    "created_at": "2026-08-10T09:14:21.000Z",
                    "from": {"user_id": "usr_spammer", "username": "spam_bot"}
                }
            })

        tasks = [send_comment(i) for i in range(20)]
        responses = await asyncio.gather(*tasks)

        for res in responses:
            assert res.status_code == 200

        stats = await get_system_stats()
        # Exactly 1 queued DM for usr_spammer, and 19 blocked duplicates!
        assert stats["queued"] == 1
        assert stats["duplicates_blocked"] == 19
