from fastapi import APIRouter
from pydantic import BaseModel
from app.db import get_system_stats

router = APIRouter(tags=["Stats"])

class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int

@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get live delivery metrics and duplicate blocking stats"
)
async def get_stats():
    """
    Returns accurate live numbers:
    - sent: DMs the mock API confirmed as delivered
    - failed: you gave up after retries
    - queued: waiting to send or waiting on a retry
    - duplicates_blocked: DMs you correctly chose not to send
    """
    stats = await get_system_stats()
    return stats
