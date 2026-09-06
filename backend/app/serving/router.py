"""Model-serving HTTP surface: SSE streaming generation with rate limiting
and bounded concurrency/backpressure in front of app.serving.streaming's
timeout/cancellation/retry logic. Deliberately independent of
app.services.workflow — this is a parallel serving slice demonstrating
async-serving engineering, not part of the case-assurance domain pipeline.

Requires the same bearer-token auth as every mutating case-pipeline endpoint
(`app.auth.require_auth`) — the rate limiter is keyed by the authenticated
principal, not a client-supplied session_id, so a caller cannot reset its own
limit by sending a new session_id on the next request. `session_id` in the
request body is correlation/tracing only, never a security identity.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.auth import Principal, require_auth
from app.serving.concurrency import BackpressureRejected, ConcurrencyLimiter
from app.serving.metrics import (
    CONTENT_TYPE_LATEST,
    ERRORS_TOTAL,
    IN_FLIGHT,
    RATE_LIMITED_TOTAL,
    render_metrics,
)
from app.serving.model_backend import DeterministicFakeModel
from app.serving.rate_limit import RateLimitExceeded, TokenBucketRateLimiter
from app.serving.streaming import stream_generation

router = APIRouter()

MAX_IN_FLIGHT = int(os.environ.get("SERVING_MAX_IN_FLIGHT", "20"))
MAX_QUEUED = int(os.environ.get("SERVING_MAX_QUEUE", "20"))
RATE_LIMIT_CAPACITY = int(os.environ.get("SERVING_RATE_LIMIT_CAPACITY", "20"))
RATE_LIMIT_REFILL_PER_SECOND = float(os.environ.get("SERVING_RATE_LIMIT_REFILL", "5"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("SERVING_DEFAULT_TIMEOUT_SECONDS", "10"))
MAX_TIMEOUT_SECONDS = float(os.environ.get("SERVING_MAX_TIMEOUT_SECONDS", "60"))
# Token pacing is env-configurable so a load test (backend/loadtest/) can
# make each stream take long enough (real LLM-response-shaped, ~1-2s) to
# actually exercise concurrency/backpressure at realistic user counts — the
# fast defaults below exist for tests, where speed matters more than realism.
TOKEN_DELAY_SECONDS = float(os.environ.get("SERVING_TOKEN_DELAY_SECONDS", "0.01"))
NUM_TOKENS = int(os.environ.get("SERVING_NUM_TOKENS", "8"))

# Module-level singletons — tests monkeypatch these (e.g. tiny concurrency
# limits, a slower fake model) rather than reconstructing the app per case.
LIMITER = ConcurrencyLimiter(max_in_flight=MAX_IN_FLIGHT, max_queued=MAX_QUEUED)
RATE_LIMITER = TokenBucketRateLimiter(capacity=RATE_LIMIT_CAPACITY, refill_rate=RATE_LIMIT_REFILL_PER_SECOND)
MODEL = DeterministicFakeModel(token_delay_seconds=TOKEN_DELAY_SECONDS, num_tokens=NUM_TOKENS)


def get_model_backend() -> DeterministicFakeModel:
    """FastAPI dependency, overridden in tests
    (`app.dependency_overrides[get_model_backend] = ...`) to inject a model
    configured with a specific `fail_mode` — that is the only way to make a
    request fail on demand; it is not a field a real client can set (see
    app.serving.model_backend.DeterministicFakeModel)."""
    return MODEL


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    # Correlation/tracing only — never used as a security or rate-limit key.
    session_id: str | None = Field(default=None, max_length=128)
    timeout_seconds: float | None = Field(default=None, gt=0, le=MAX_TIMEOUT_SECONDS)


def _json_error(status_code: int, error_code: str, message: str, *, headers: dict[str, str] | None = None) -> Response:
    return Response(
        status_code=status_code,
        content=json.dumps({"error_code": error_code, "message": message}),
        media_type="application/json",
        headers=headers,
    )


@router.post("/api/generate/stream")
async def generate_stream(
    request: Request,
    body: GenerateRequest,
    principal: Principal = Depends(require_auth),
    model: DeterministicFakeModel = Depends(get_model_backend),
) -> Response:
    request_id = f"REQ-{uuid.uuid4().hex[:12]}"
    session_id = body.session_id or request_id
    deadline = time.monotonic() + (body.timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    try:
        RATE_LIMITER.check(principal.reviewer_id)
    except RateLimitExceeded as exc:
        RATE_LIMITED_TOTAL.inc()
        return _json_error(
            429,
            "RATE_LIMITED",
            str(exc),
            headers={"Retry-After": str(max(1, int(exc.retry_after_seconds) + 1))},
        )

    slot = LIMITER.slot()
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        await asyncio.wait_for(slot.__aenter__(), timeout=remaining)
    except BackpressureRejected as exc:
        ERRORS_TOTAL.labels(reason="backpressure").inc()
        return _json_error(503, "SERVER_BUSY", str(exc))
    except TimeoutError:
        ERRORS_TOTAL.labels(reason="queue_timeout").inc()
        return _json_error(503, "QUEUE_TIMEOUT", "Timed out waiting for a free concurrency slot")

    IN_FLIGHT.inc()

    async def _generate_and_release():
        try:
            async for event in stream_generation(
                model=model,
                prompt=body.prompt,
                deadline=deadline,
                request_id=request_id,
                session_id=session_id,
                is_disconnected=request.is_disconnected,
            ):
                yield event
        finally:
            IN_FLIGHT.dec()
            await slot.__aexit__(None, None, None)

    return EventSourceResponse(_generate_and_release())


@router.get("/metrics")
def metrics_endpoint() -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
