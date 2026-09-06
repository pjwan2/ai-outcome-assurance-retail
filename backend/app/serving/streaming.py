"""Core SSE event-generation logic for /api/generate/stream, deliberately
decoupled from FastAPI/Starlette: `stream_generation` takes a plain
`is_disconnected` callable rather than a `Request`, which is what makes its
timeout/cancellation/retry/error paths unit-testable without spinning up an
HTTP transport (see backend/tests/test_serving.py).

Rate limiting and concurrency/backpressure are handled by the caller
(app/serving/router.py) before this function is ever invoked — this module
owns only what happens once a request has already been admitted.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from app.serving.logging_utils import log_event
from app.serving.metrics import (
    ERRORS_TOTAL,
    REQUESTS_TOTAL,
    RETRIES_TOTAL,
    TIME_TO_FIRST_TOKEN_SECONDS,
    TOKENS_GENERATED_TOTAL,
    TOTAL_DURATION_SECONDS,
)
from app.serving.model_backend import (
    DeterministicFakeModel,
    PermanentBackendError,
    TransientBackendError,
    prime_generation,
)

RETRY_MAX_ATTEMPTS = 3


async def stream_generation(
    *,
    model: DeterministicFakeModel,
    prompt: str,
    fail_mode: str | None,
    timeout_seconds: float,
    request_id: str,
    session_id: str,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    """Yields SSE-shaped dicts (`event`/`data`) for one generation request.
    Always ends with exactly one terminal event: `done`, or `error` on
    timeout/backend failure, or nothing further (a silent stop) on client
    disconnect — there is nothing left to tell a client that already left.
    """
    started = time.monotonic()
    tokens_emitted = 0
    status = "completed"

    try:
        try:
            gen, first_token = await asyncio.wait_for(
                prime_generation(
                    model,
                    prompt,
                    fail_mode,
                    max_attempts=RETRY_MAX_ATTEMPTS,
                    on_retry=RETRIES_TOTAL.inc,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            status = "timeout"
            ERRORS_TOTAL.labels(reason="timeout").inc()
            log_event("generate_timeout", request_id=request_id, session_id=session_id)
            yield {"event": "error", "data": _error_payload(request_id, "TIMEOUT")}
            return
        except (TransientBackendError, PermanentBackendError) as exc:
            status = "backend_error"
            ERRORS_TOTAL.labels(reason=type(exc).__name__).inc()
            log_event(
                "generate_backend_error", request_id=request_id, session_id=session_id, error=str(exc)
            )
            yield {"event": "error", "data": _error_payload(request_id, "BACKEND_ERROR")}
            return

        TIME_TO_FIRST_TOKEN_SECONDS.observe(time.monotonic() - started)
        tokens_emitted = 1
        TOKENS_GENERATED_TOTAL.inc()
        yield {"event": "token", "data": _token_payload(first_token)}

        try:
            async for token in gen:
                if await is_disconnected():
                    status = "cancelled"
                    return
                tokens_emitted += 1
                TOKENS_GENERATED_TOTAL.inc()
                yield {"event": "token", "data": _token_payload(token)}
        except (TransientBackendError, PermanentBackendError) as exc:
            status = "backend_error"
            ERRORS_TOTAL.labels(reason=type(exc).__name__).inc()
            log_event(
                "generate_mid_stream_error",
                request_id=request_id,
                session_id=session_id,
                tokens_emitted=tokens_emitted,
                error=str(exc),
            )
            yield {"event": "error", "data": _error_payload(request_id, "BACKEND_ERROR")}
            return

        yield {
            "event": "done",
            "data": _done_payload(request_id, model, tokens_emitted),
        }
    finally:
        REQUESTS_TOTAL.labels(status=status).inc()
        TOTAL_DURATION_SECONDS.observe(time.monotonic() - started)
        log_event(
            "generate_finished",
            request_id=request_id,
            session_id=session_id,
            status=status,
            tokens_emitted=tokens_emitted,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            model_version=model.info.model_version,
        )


def _token_payload(token: str) -> str:
    return json.dumps({"token": token})


def _error_payload(request_id: str, reason: str) -> str:
    return json.dumps({"request_id": request_id, "reason": reason})


def _done_payload(request_id: str, model: DeterministicFakeModel, tokens_emitted: int) -> str:
    return json.dumps(
        {
            "request_id": request_id,
            "model_name": model.info.model_name,
            "model_version": model.info.model_version,
            "checkpoint_id": model.info.checkpoint_id,
            "tokens_emitted": tokens_emitted,
        }
    )
