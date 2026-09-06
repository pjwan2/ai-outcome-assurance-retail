"""Per-session token-bucket rate limiter for the model serving slice.

In-memory, single-process — consistent with the rest of this repository's
"no external infra" posture (see docs/production_gap_register.md). A
multi-process deployment would need a shared store (e.g. Redis); that gap is
listed there, not hidden.
"""

from __future__ import annotations

import time


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded, retry after {retry_after_seconds:.2f}s")


class TokenBucketRateLimiter:
    """One bucket per session_id: `capacity` tokens, refilled continuously at
    `refill_rate` tokens/second. Each request consumes one token; a bucket
    with less than one token raises RateLimitExceeded with an estimated
    retry-after rather than silently dropping or queuing the request."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, session_id: str) -> None:
        now = time.monotonic()
        tokens, last = self._buckets.get(session_id, (float(self.capacity), now))
        tokens = min(float(self.capacity), tokens + (now - last) * self.refill_rate)
        if tokens < 1.0:
            retry_after = (1.0 - tokens) / self.refill_rate
            self._buckets[session_id] = (tokens, now)
            raise RateLimitExceeded(retry_after)
        self._buckets[session_id] = (tokens - 1.0, now)
