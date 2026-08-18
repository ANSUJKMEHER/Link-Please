import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from app.db import get_db, reset_database
from app.rate_limiter import rate_limiter
from app.config import settings

router = APIRouter(prefix="/api", tags=["Admin & Dashboard"])

class SimulateStartRequest(BaseModel):
    webhook_url: str
    count: int = 500
    duration_seconds: int = 10

@router.get("/rate_limiter", summary="Get rate limiter internal status")
async def get_rate_limiter_status():
    return await rate_limiter.get_status()

@router.get("/queue", summary="List recent items in the DM queue")
async def get_queue_items(limit: int = 50):
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT id, recipient_user_id, message, comment_id, rule_id, status, attempts, next_attempt_at, dm_id, error_detail, created_at, updated_at
            FROM dm_queue
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/events", summary="List recent processed events")
async def get_recent_events(limit: int = 50):
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT event_id, event_type, processed_at
            FROM processed_events
            ORDER BY processed_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.post("/reset", summary="Reset all state for testing")
async def reset_all_state():
    await reset_database()
    return {"status": "success", "message": "Database and stats reset successfully"}

@router.post("/simulate/start", summary="Trigger mock API simulation test")
async def trigger_simulation(req: SimulateStartRequest):
    url = f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/simulate/start"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": settings.API_KEY
    }
    payload = {
        "webhook_url": req.webhook_url,
        "count": req.count,
        "duration_seconds": req.duration_seconds
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, json=payload, headers=headers, timeout=15.0)
            if res.status_code == 200:
                return res.json()
            else:
                raise HTTPException(status_code=res.status_code, detail=res.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Mock API: {str(e)}")

@router.get("/simulate/{run_id}/truth", summary="Fetch simulation truth data from mock API")
async def get_simulation_truth(run_id: str):
    url = f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/simulate/{run_id}/truth"
    headers = {
        "X-API-Key": settings.API_KEY
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, headers=headers, timeout=15.0)
            if res.status_code == 200:
                return res.json()
            else:
                raise HTTPException(status_code=res.status_code, detail=res.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Mock API: {str(e)}")
