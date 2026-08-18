import asyncio
import time
from typing import List
from app.config import settings

class SlidingWindowRateLimiter:
    """
    Thread-safe and async-safe Sliding Window Rate Limiter.
    Strictly enforces max_requests within rolling window_seconds (default 10 req / 60s).
    Also supports dynamic cooldown when 429 Retry-After is encountered.
    """
    def __init__(self, max_requests: int = settings.RATE_LIMIT_MAX_REQUESTS, window_seconds: float = settings.RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []
        self.lock = asyncio.Lock()
        self.cooldown_until: float = 0.0

    async def acquire(self):
        """
        Blocks until a request slot is available under the sliding window.
        """
        while True:
            async with self.lock:
                now = time.time()
                
                # Check external cooldown (e.g. from 429 Retry-After)
                if now < self.cooldown_until:
                    sleep_time = self.cooldown_until - now
                else:
                    # Prune expired timestamps outside the rolling window
                    cutoff = now - self.window_seconds
                    self.timestamps = [ts for ts in self.timestamps if ts > cutoff]
                    
                    if len(self.timestamps) < self.max_requests:
                        # Slot available!
                        self.timestamps.append(now)
                        return
                    else:
                        # Window full: wait until the oldest timestamp slides out of the window
                        oldest = self.timestamps[0]
                        sleep_time = max(0.05, (oldest + self.window_seconds) - now + 0.05)
            
            # Sleep outside the lock so other coroutines can inspect state if needed
            await asyncio.sleep(sleep_time)

    async def report_429(self, retry_after_seconds: float):
        """
        In case a 429 response is encountered, dynamically apply cooldown.
        """
        async with self.lock:
            now = time.time()
            self.cooldown_until = max(self.cooldown_until, now + retry_after_seconds + 0.1)
            # Clear timestamps to align with external reset if needed
            self.timestamps.clear()

    async def get_status(self) -> dict:
        """Returns the current rate limiter metrics."""
        async with self.lock:
            now = time.time()
            cutoff = now - self.window_seconds
            active_ts = [ts for ts in self.timestamps if ts > cutoff]
            return {
                "active_requests_in_window": len(active_ts),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
                "cooldown_active": now < self.cooldown_until,
                "cooldown_remaining_seconds": max(0.0, self.cooldown_until - now)
            }

# Global singleton rate limiter instance
rate_limiter = SlidingWindowRateLimiter()
