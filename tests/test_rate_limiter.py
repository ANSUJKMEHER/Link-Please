import pytest
import time
import asyncio
from app.rate_limiter import SlidingWindowRateLimiter

@pytest.mark.asyncio
async def test_sliding_window_rate_limiter():
    # Test a small window: 3 requests per 0.5s
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=0.5)

    start_time = time.time()
    
    # 3 immediate acquires should complete almost instantly (< 50ms)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    
    elapsed_immediate = time.time() - start_time
    assert elapsed_immediate < 0.1

    # 4th acquire must wait until the window slides (approx 0.5s)
    await limiter.acquire()
    elapsed_total = time.time() - start_time
    assert elapsed_total >= 0.45

@pytest.mark.asyncio
async def test_rate_limiter_429_cooldown():
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=10.0)

    # Report 429 cooldown of 0.4s
    await limiter.report_429(0.4)
    start_time = time.time()
    
    await limiter.acquire()
    elapsed = time.time() - start_time
    assert elapsed >= 0.38
