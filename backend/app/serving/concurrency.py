"""Bounded in-flight concurrency plus a bounded wait queue for the model
serving slice. Once both are full, a new request is rejected immediately
(HTTP 503) rather than queued unboundedly — real backpressure, not an
unbounded memory/latency time bomb.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class BackpressureRejected(Exception):
    """Raised when both the in-flight slots and the wait queue are full."""


class ConcurrencyLimiter:
    def __init__(self, max_in_flight: int, max_queued: int) -> None:
        self.max_in_flight = max_in_flight
        self.max_queued = max_queued
        self._in_flight = 0
        self._queued = 0
        self._condition = asyncio.Condition()

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def queued(self) -> int:
        return self._queued

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire one in-flight slot, waiting in the bounded queue if
        necessary. Raises BackpressureRejected immediately (no waiting) if
        the queue is also full. Releasing the slot — including on
        cancellation, since `finally` runs through a CancelledError — always
        notifies the next waiter."""
        async with self._condition:
            if self._in_flight >= self.max_in_flight:
                if self._queued >= self.max_queued:
                    raise BackpressureRejected(
                        f"{self._in_flight} in flight, {self._queued} queued; both at capacity"
                    )
                self._queued += 1
                try:
                    await self._condition.wait_for(lambda: self._in_flight < self.max_in_flight)
                finally:
                    self._queued -= 1
            self._in_flight += 1
        try:
            yield
        finally:
            async with self._condition:
                self._in_flight -= 1
                self._condition.notify()
