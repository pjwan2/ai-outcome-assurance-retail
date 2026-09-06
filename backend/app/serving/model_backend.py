"""Deterministic fake model backend for the serving slice.

No live LLM call anywhere in this repository (see docs/production_gap_register.md) —
`DeterministicFakeModel` exists to exercise real async-serving engineering
(streaming, timeouts, cancellation, retries, backpressure) against a backend
whose behaviour is fully controllable and reproducible in tests, not to
simulate any specific real model's outputs.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed


class TransientBackendError(Exception):
    """A failure a retry should recover from. Raised before any token is
    yielded, so a retry never risks re-sending output already seen by a
    client (app/serving/streaming.py only retries the pre-stream "prime"
    step, never the stream body)."""


class PermanentBackendError(Exception):
    """A failure retries cannot fix — either raised immediately (before any
    token) or mid-stream, simulating a backend that dies partway through a
    generation. Either way, the caller must fail gracefully, not retry."""


@dataclass(frozen=True)
class ModelInfo:
    model_name: str
    model_version: str
    checkpoint_id: str


DEFAULT_MODEL_INFO = ModelInfo(
    model_name="deterministic-fake-model",
    model_version="v1",
    checkpoint_id=hashlib.sha256(b"deterministic-fake-model-v1").hexdigest()[:12],
)


class DeterministicFakeModel:
    """Given a prompt, deterministically derives a token sequence (hash-seeded)
    and yields tokens with configurable per-token latency.

    `fail_mode` is a construction-time testing knob — set only by whoever
    builds the model instance (a test, via FastAPI's dependency-override
    mechanism; never a client), not a field on the public request schema. A
    real caller of `POST /api/generate/stream` has no way to influence it.
    Values:
      - "transient": fails before yielding anything, but only while
        `attempt` is below the model's own recovery point — a subsequent
        retry with a higher `attempt` succeeds.
      - "permanent": always fails before yielding anything, regardless of
        attempt — retries are exhausted, never recover.
      - "mid_stream": succeeds past the retryable pre-stream step, then
        fails partway through the token stream — the caller must end the
        stream gracefully, not retry (partial output was already sent).
    """

    def __init__(
        self,
        token_delay_seconds: float = 0.01,
        num_tokens: int = 8,
        fail_mode: str | None = None,
        info: ModelInfo | None = None,
    ) -> None:
        self.token_delay_seconds = token_delay_seconds
        self.num_tokens = num_tokens
        self.fail_mode = fail_mode
        self.info = info or DEFAULT_MODEL_INFO

    def _tokens_for(self, prompt: str) -> list[str]:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        span = max(1, len(digest) // self.num_tokens)
        return [digest[i : i + span] for i in range(0, span * self.num_tokens, span)]

    async def generate(self, prompt: str, *, attempt: int = 1) -> AsyncIterator[str]:
        if self.fail_mode == "transient" and attempt < 3:
            raise TransientBackendError(f"simulated transient failure (attempt {attempt})")
        if self.fail_mode == "permanent":
            raise PermanentBackendError("simulated permanent failure")

        for index, token in enumerate(self._tokens_for(prompt)):
            if self.fail_mode == "mid_stream" and index == 3:
                raise PermanentBackendError("simulated mid-stream failure")
            await asyncio.sleep(self.token_delay_seconds)
            yield token


async def prime_generation(
    model: DeterministicFakeModel,
    prompt: str,
    *,
    max_attempts: int = 3,
    on_retry: Callable[[], None] | None = None,
) -> tuple[AsyncIterator[str], str]:
    """Retryable "handshake" step: acquire a generator and pull its first
    token. Only `TransientBackendError` raised here is retried — a
    `PermanentBackendError` (or a `TransientBackendError` that never
    recovers within `max_attempts`) propagates to the caller, which must
    fail the request gracefully. Retrying is confined to before any token
    reaches the client, so a retry never duplicates visible output.
    """
    attempt_counter = {"n": 0}

    async def _attempt() -> tuple[AsyncIterator[str], str]:
        attempt_counter["n"] += 1
        gen = model.generate(prompt, attempt=attempt_counter["n"])
        first_token = await gen.__anext__()
        return gen, first_token

    def _before_sleep(_retry_state: object) -> None:
        if on_retry is not None:
            on_retry()

    retrying = AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_fixed(0.02),
        retry=retry_if_exception_type(TransientBackendError),
        before_sleep=_before_sleep,
        reraise=True,
    )
    return await retrying(_attempt)
