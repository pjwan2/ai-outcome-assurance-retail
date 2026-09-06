"""Tests for the model-serving slice (backend/app/serving): a deterministic
fake model behind real async-serving engineering — SSE streaming, timeouts,
cancellation, retry, bounded concurrency/backpressure, rate limiting,
structured logging, and Prometheus metrics. No live model is ever called
here — see docs/production_gap_register.md.

Every request here goes through the same bearer-token auth as the rest of
the API; the rate limiter is keyed by the authenticated principal, not a
client-supplied session_id — several tests below exist specifically to prove
that boundary, not just the happy path.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

import app.serving.router as router_module
from app.api import app
from app.auth import DEFAULT_DEV_TOKEN
from app.serving.concurrency import ConcurrencyLimiter
from app.serving.model_backend import DeterministicFakeModel
from app.serving.rate_limit import TokenBucketRateLimiter
from app.serving.router import get_model_backend
from app.serving.streaming import stream_generation

AUTH_HEADERS = {"Authorization": f"Bearer {DEFAULT_DEV_TOKEN}"}


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@contextlib.contextmanager
def _model_override(model: DeterministicFakeModel) -> Iterator[None]:
    """Inject a specific (possibly failure-configured) model instance for
    the duration of one test — the only way to make a request fail on
    demand; a real client has no `fail_mode` field to set (see
    app.serving.model_backend.DeterministicFakeModel)."""
    app.dependency_overrides[get_model_backend] = lambda: model
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_model_backend, None)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_type = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line.removeprefix("event:").strip()
        elif line.startswith("data:") and event_type is not None:
            events.append((event_type, json.loads(line.removeprefix("data:").strip())))
            event_type = None
    return events


# --- Auth boundary ---------------------------------------------------------


def test_generate_stream_requires_auth(client):
    resp = client.post("/api/generate/stream", json={"prompt": "hello"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["error_code"] == "MISSING_BEARER_TOKEN"


# --- Request validation ------------------------------------------------


def test_empty_prompt_is_rejected(client):
    resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": ""})
    assert resp.status_code == 422


def test_overlong_prompt_is_rejected(client):
    resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x" * 4001})
    assert resp.status_code == 422


def test_out_of_range_timeout_is_rejected(client):
    resp = client.post(
        "/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "hi", "timeout_seconds": 999}
    )
    assert resp.status_code == 422


# --- Happy path / determinism -----------------------------------------


def test_happy_path_streams_tokens_then_a_done_event_with_model_version(client):
    resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "hello world"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert [e for e, _ in events[:-1]] == ["token"] * (len(events) - 1)
    last_event, last_data = events[-1]
    assert last_event == "done"
    assert last_data["request_id"].startswith("REQ-")
    assert last_data["model_name"] == "deterministic-fake-model"
    assert last_data["model_version"] == "v1"
    assert last_data["checkpoint_id"]
    assert last_data["tokens_emitted"] == len(events) - 1


def test_repeated_prompt_is_deterministic(client):
    first = _parse_sse(client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "same prompt"}).text)
    second = _parse_sse(client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "same prompt"}).text)
    first_tokens = [d["token"] for e, d in first if e == "token"]
    second_tokens = [d["token"] for e, d in second if e == "token"]
    assert first_tokens == second_tokens


# --- Failure modes, injected via dependency override, never via the wire ---


def test_transient_failure_recovers_via_retry_and_still_succeeds(client):
    with _model_override(DeterministicFakeModel(token_delay_seconds=0.001, fail_mode="transient")):
        resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"})
    events = _parse_sse(resp.text)
    assert events[-1][0] == "done"
    assert not any(e == "error" for e, _ in events)


def test_permanent_failure_exhausts_retries_and_ends_gracefully(client):
    with _model_override(DeterministicFakeModel(token_delay_seconds=0.001, fail_mode="permanent")):
        resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events == [("error", events[0][1])]
    assert events[0][1]["reason"] == "BACKEND_ERROR"


def test_mid_stream_failure_emits_partial_tokens_then_a_graceful_error(client):
    with _model_override(DeterministicFakeModel(token_delay_seconds=0.001, fail_mode="mid_stream")):
        resp = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"})
    events = _parse_sse(resp.text)
    assert [e for e, _ in events[:-1]] == ["token"] * (len(events) - 1)
    assert len(events) - 1 == 3  # DeterministicFakeModel fails at token index 3
    assert events[-1] == ("error", events[-1][1])
    assert events[-1][1]["reason"] == "BACKEND_ERROR"


def test_timeout_before_first_token_produces_a_graceful_error_not_a_hang(client):
    with _model_override(DeterministicFakeModel(token_delay_seconds=1.0, num_tokens=5)):
        resp = client.post(
            "/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x", "timeout_seconds": 0.01}
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events == [("error", {"request_id": events[0][1]["request_id"], "reason": "TIMEOUT"})]


def test_deadline_covers_the_full_stream_not_just_the_first_token(client):
    """Regression: an earlier version only bounded the pre-stream "prime"
    step with the timeout, so a model that produced its first token quickly
    but then stalled could run well past `timeout_seconds` in total. The
    deadline must cover every subsequent token too.

    The first-token delay is a small fraction of the timeout (not a near
    match) deliberately: an earlier version used 0.05s vs a 0.12s timeout,
    which was tight enough that a busy CI runner could occasionally miss the
    first token's own deadline check and produce a flaky failure unrelated
    to the behaviour under test. A wide margin here still proves the same
    thing — mid-stream enforcement — without being a timing race."""
    # First token arrives comfortably within the timeout (25x margin); the
    # full 30-token stream (30 * 0.05s = 1.5s) does not.
    with _model_override(DeterministicFakeModel(token_delay_seconds=0.05, num_tokens=30)):
        resp = client.post(
            "/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x", "timeout_seconds": 1.0}
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["reason"] == "TIMEOUT"
    # Some tokens got through before the deadline hit, but not all 30 —
    # proves the deadline was enforced mid-stream, not just once at the start.
    token_count = sum(1 for e, _ in events if e == "token")
    assert 0 < token_count < 30


# --- Rate limiting: keyed by principal, not client-supplied session_id -----


def test_rate_limit_returns_429_with_retry_after_once_bucket_is_empty(client, monkeypatch):
    monkeypatch.setattr(router_module, "RATE_LIMITER", TokenBucketRateLimiter(capacity=2, refill_rate=0.001))
    statuses = [
        client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"}).status_code
        for _ in range(4)
    ]
    assert statuses == [200, 200, 429, 429]

    limited = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
    assert limited.json()["error_code"] == "RATE_LIMITED"


def test_rate_limit_is_keyed_by_principal_not_client_supplied_session_id(client, monkeypatch):
    """A client cannot reset its own rate limit by rotating session_id —
    the limiter key is the authenticated principal (app.auth.Principal),
    which session_id has no influence over."""
    monkeypatch.setattr(router_module, "RATE_LIMITER", TokenBucketRateLimiter(capacity=1, refill_rate=0.001))
    first = client.post(
        "/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x", "session_id": "session-a"}
    )
    second = client.post(
        "/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x", "session_id": "session-b"}
    )
    assert (first.status_code, second.status_code) == (200, 429)


def test_rate_limit_is_scoped_per_principal(client, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(router_module, "RATE_LIMITER", TokenBucketRateLimiter(capacity=1, refill_rate=0.001))
    auth_module._TOKEN_MAP["other-principal-token"] = auth_module.Principal("bob", "retail-operations")
    try:
        a = client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "x"})
        b = client.post(
            "/api/generate/stream",
            headers={"Authorization": "Bearer other-principal-token"},
            json={"prompt": "x"},
        )
        assert (a.status_code, b.status_code) == (200, 200)
    finally:
        del auth_module._TOKEN_MAP["other-principal-token"]


# --- Bounded concurrency / backpressure ------------------------------------


@pytest.mark.asyncio
async def test_bounded_concurrency_rejects_the_nth_plus_one_request(monkeypatch):
    monkeypatch.setattr(router_module, "LIMITER", ConcurrencyLimiter(max_in_flight=2, max_queued=0))
    monkeypatch.setattr(router_module, "MODEL", DeterministicFakeModel(token_delay_seconds=0.2, num_tokens=5))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as async_client:
        held = [
            asyncio.create_task(async_client.post("/api/generate/stream", json={"prompt": f"p{i}"}))
            for i in range(2)
        ]
        await asyncio.sleep(0.05)  # let both held requests acquire their slot

        rejected = await async_client.post("/api/generate/stream", json={"prompt": "reject-me"})
        assert rejected.status_code == 503
        assert rejected.json()["error_code"] == "SERVER_BUSY"

        results = await asyncio.gather(*held)
        assert all(r.status_code == 200 for r in results)


async def test_concurrency_slot_is_released_when_the_holding_task_is_cancelled():
    """The resource-release-on-disconnect guarantee, tested at the primitive
    level: a cancelled task must not leak its concurrency slot. `finally`
    runs through CancelledError the same as any other exception."""
    limiter = ConcurrencyLimiter(max_in_flight=1, max_queued=0)

    async def hold_forever():
        async with limiter.slot():
            await asyncio.sleep(10)

    task = asyncio.create_task(hold_forever())
    await asyncio.sleep(0.05)
    assert limiter.in_flight == 1

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert limiter.in_flight == 0


async def test_stream_generation_stops_on_disconnect_without_a_done_event():
    model = DeterministicFakeModel(token_delay_seconds=0.001, num_tokens=10)
    calls = {"n": 0}

    async def is_disconnected() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    events = [
        event
        async for event in stream_generation(
            model=model,
            prompt="x",
            deadline=time.monotonic() + 5,
            request_id="REQ-TEST",
            session_id="SESSION-TEST",
            is_disconnected=is_disconnected,
        )
    ]
    # 1 token from the pre-stream "prime" step (never disconnect-checked) +
    # 2 more from the loop before the 3rd disconnect check trips.
    assert len(events) == 3
    assert all(e["event"] == "token" for e in events)


# --- Observability -----------------------------------------------------


def test_metrics_endpoint_exposes_prometheus_text_format(client):
    client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "for metrics"})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    for name in (
        "serving_requests_total",
        "serving_in_flight_requests",
        "serving_time_to_first_token_seconds",
        "serving_tokens_generated_total",
    ):
        assert name in resp.text


def test_structured_log_line_has_expected_fields(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.serving"):
        client.post("/api/generate/stream", headers=AUTH_HEADERS, json={"prompt": "log me"})
    finished = [json.loads(r.message) for r in caplog.records if '"generate_finished"' in r.message]
    assert finished, "expected a generate_finished structured log line"
    payload = finished[-1]
    assert payload["event"] == "generate_finished"
    assert payload["status"] == "completed"
    assert set(payload) >= {"request_id", "session_id", "status", "tokens_emitted", "duration_ms", "model_version"}
