"""Per-principal token-bucket rate limiter for the model serving slice.

In-memory, single-process — consistent with the rest of this repository's
"no external infra" posture (see docs/production_gap_register.md). A
multi-process deployment would need a shared store (e.g. Redis); that gap is
listed there, not hidden.

Keyed by the authenticated caller (`Principal.reviewer_id` from
`app.auth.require_auth`), not a client-supplied session_id — a client cannot
reset its own limit just by sending a new session_id on the next request. The
bucket store itself is bounded (an LRU eviction cap), not an unbounded dict,
so an attacker (or just many distinct callers over time) cannot grow it
without limit.
"""

from __future__ import annotations

import time
from collections import OrderedDict


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded, retry after {retry_after_seconds:.2f}s")


class TokenBucketRateLimiter:
    """One bucket per key: `capacity` tokens, refilled continuously at
    `refill_rate` tokens/second. Each request consumes one token; a bucket
    with less than one token raises RateLimitExceeded with an estimated
    retry-after rather than silently dropping or queuing the request.

    At most `max_tracked_keys` buckets are kept at once — the least-recently
    checked key is evicted (and starts fresh, at full capacity, if it comes
    back) once that cap is hit, bounding memory regardless of how many
    distinct keys are ever seen."""

    def __init__(self, capacity: int, refill_rate: float, max_tracked_keys: int = 10_000) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_tracked_keys = max_tracked_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def check(self, key: str) -> None:
        now = time.monotonic()
        tokens, last = self._buckets.pop(key, (float(self.capacity), now))
        tokens = min(float(self.capacity), tokens + (now - last) * self.refill_rate)
        if tokens < 1.0:
            retry_after = (1.0 - tokens) / self.refill_rate
            self._buckets[key] = (tokens, now)
            raise RateLimitExceeded(retry_after)
        self._buckets[key] = (tokens - 1.0, now)
        if len(self._buckets) > self.max_tracked_keys:
            self._buckets.popitem(last=False)
