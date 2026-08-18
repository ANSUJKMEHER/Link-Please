import pytest
import pytest_asyncio
import hmac
import hashlib
import json
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import reset_database
from app.config import settings

@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    await reset_database()
    yield
    await reset_database()

@pytest.mark.asyncio
async def test_create_and_list_rules():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create rule
        payload = {
            "keyword": "PRICE",
            "dm_message": "Here's our 2026 pricing catalog: https://example.com/pricing"
        }
        res = await client.post("/rules", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert "rule_id" in data
        assert data["keyword"] == "PRICE"
        assert data["dm_message"] == payload["dm_message"]
        rule_id = data["rule_id"]

        # List rules
        res_list = await client.get("/rules")
        assert res_list.status_code == 200
        rules = res_list.json()
        assert len(rules) == 1
        assert rules[0]["rule_id"] == rule_id

        # Delete rule
        res_del = await client.delete(f"/rules/{rule_id}")
        assert res_del.status_code == 200

        # List rules after deletion
        res_list_after = await client.get("/rules")
        assert len(res_list_after.json()) == 0
