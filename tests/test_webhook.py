import pytest
import pytest_asyncio
import hmac
import hashlib
import json
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import reset_database, get_system_stats
from app.config import settings

def compute_sig(body_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await reset_database()
    yield
    await reset_database()

@pytest.mark.asyncio
async def test_webhook_signature_verification():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Configure API key for signature testing
        original_api_key = settings.API_KEY
        original_verify = settings.VERIFY_SIGNATURE
        settings.API_KEY = "test_secret_key_12345"
        settings.VERIFY_SIGNATURE = True

        payload = {
            "event_id": "evt_sig_test_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.481Z",
            "data": {
                "comment_id": "cmt_1",
                "post_id": "post_1",
                "text": "Hello world",
                "created_at": "2026-08-10T09:14:21.900Z",
                "from": {"user_id": "usr_1", "username": "user1"}
            }
        }
        raw_body = json.dumps(payload).encode("utf-8")

        # 1. Invalid signature should return 401
        res_invalid = await client.post(
            "/webhook",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-PseudoGram-Signature": "sha256=invalidhex"}
        )
        assert res_invalid.status_code == 401

        # 2. Valid signature should return 200
        valid_sig = compute_sig(raw_body, settings.API_KEY)
        res_valid = await client.post(
            "/webhook",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-PseudoGram-Signature": valid_sig}
        )
        assert res_valid.status_code == 200

        # Restore settings
        settings.API_KEY = original_api_key
        settings.VERIFY_SIGNATURE = original_verify

@pytest.mark.asyncio
async def test_webhook_rule_matching():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule for "PRICE"
        await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list sent!"})

        # Send matching comment: "PRICE please 🙏"
        payload_match = {
            "event_id": "evt_match_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.481Z",
            "data": {
                "comment_id": "cmt_match_1",
                "post_id": "post_1",
                "text": "PRICE please 🙏",
                "created_at": "2026-08-10T09:14:21.900Z",
                "from": {"user_id": "usr_shoots", "username": "arjun.shoots"}
            }
        }
        res_match = await client.post("/webhook", json=payload_match)
        assert res_match.status_code == 200
        assert res_match.json()["result"]["enqueued_dms"] == 1

        stats = await get_system_stats()
        assert stats["queued"] == 1
        assert stats["duplicates_blocked"] == 0

        # Send non-matching comment
        payload_non_match = {
            "event_id": "evt_non_match_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.481Z",
            "data": {
                "comment_id": "cmt_non_match_1",
                "post_id": "post_1",
                "text": "Great photo!",
                "created_at": "2026-08-10T09:14:21.900Z",
                "from": {"user_id": "usr_fan", "username": "fan123"}
            }
        }
        res_non_match = await client.post("/webhook", json=payload_non_match)
        assert res_non_match.status_code == 200
        assert res_non_match.json()["result"]["enqueued_dms"] == 0
