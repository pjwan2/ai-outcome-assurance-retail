"""Tests for the model-serving slice (backend/app/serving): a deterministic
fake model behind real async-serving engineering — SSE streaming, timeouts,
cancellation, retry, bounded concurrency/backpressure, rate limiting,
structured logging, and Prometheus metrics. No live model is ever called
here — see docs/production_gap_register.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.serving.router as router_module
from app.api import app
from app.serving.concurrency import ConcurrencyLimiter
from app.serving.model_backend import DeterministicFakeModel
from app.serving.rate_limit import TokenBucketRateLimiter
from app.serving.streaming import stream_generation


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


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


def test_happy_path_streams_tokens_then_a_done_event_with_model_version(client):
    resp = client.post("/api/generate/stream", json={"prompt": "hello world"})
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
    first = _parse_sse(client.post("/api/generate/stream", json={"prompt": "same prompt"}).text)
    second = _parse_sse(client.post("/api/generate/stream", json={"prompt": "same prompt"}).text)
    first_tokens = [d["token"] for e, d in first if e == "token"]
    second_tokens = [d["token"] for e, d in second if e == "token"]
    assert first_tokens == second_tokens


def test_transient_failure_recovers_via_retry_and_still_succeeds(client):
    resp = client.post("/api/generate/stream", json={"prompt": "x", "fail_mode": "transient"})
    events = _parse_sse(resp.text)
    assert events[-1][0] == "done"
    assert not any(e == "error" for e, _ in events)


def test_permanent_failure_exhausts_retries_and_ends_gracefully(client):
    resp = client.post("/api/generate/stream", json={"prompt": "x", "fail_mode": "permanent"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events == [("error", events[0][1])]
    assert events[0][1]["reason"] == "BACKEND_ERROR"


def test_mid_stream_failure_emits_partial_tokens_then_a_graceful_error(client):
    resp = client.post("/api/generate/stream", json={"prompt": "x", "fail_mode": "mid_stream"})
    events = _parse_sse(resp.text)
    assert [e for e, _ in events[:-1]] == ["token"] * (len(events) - 1)
    assert len(events) - 1 == 3  # DeterministicFakeModel fails at token index 3
    assert events[-1] == ("error", events[-1][1])
    assert events[-1][1]["reason"] == "BACKEND_ERROR"


def test_timeout_produces_a_graceful_error_not_a_hang(client):
    resp = client.post("/api/generate/stream", json={"prompt": "x", "timeout_seconds": 0.001})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events == [("error", {"request_id": events[0][1]["request_id"], "reason": "TIMEOUT"})]


def test_rate_limit_returns_429_with_retry_after_once_bucket_is_empty(client, monkeypatch):
    monkeypatch.setattr(router_module, "RATE_LIMITER", TokenBucketRateLimiter(capacity=2, refill_rate=0.001))
    statuses = [
        client.post("/api/generate/stream", json={"prompt": "x", "session_id": "SAME"}).status_code
        for _ in range(4)
    ]
    assert statuses == [200, 200, 429, 429]

    limited = client.post("/api/generate/stream", json={"prompt": "x", "session_id": "SAME"})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
    assert limited.json()["error_code"] == "RATE_LIMITED"


def test_rate_limit_is_scoped_per_session(client, monkeypatch):
    monkeypatch.setattr(router_module, "RATE_LIMITER", TokenBucketRateLimiter(capacity=1, refill_rate=0.001))
    a1 = client.post("/api/generate/stream", json={"prompt": "x", "session_id": "A"})
    b1 = client.post("/api/generate/stream", json={"prompt": "x", "session_id": "B"})
    a2 = client.post("/api/generate/stream", json={"prompt": "x", "session_id": "A"})
    assert (a1.status_code, b1.status_code, a2.status_code) == (200, 200, 429)


@pytest.mark.asyncio
async def test_bounded_concurrency_rejects_the_nth_plus_one_request(monkeypatch):
    monkeypatch.setattr(router_module, "LIMITER", ConcurrencyLimiter(max_in_flight=2, max_queued=0))
    monkeypatch.setattr(router_module, "MODEL", DeterministicFakeModel(token_delay_seconds=0.2, num_tokens=5))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
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
            fail_mode=None,
            timeout_seconds=5,
            request_id="REQ-TEST",
            session_id="SESSION-TEST",
            is_disconnected=is_disconnected,
        )
    ]
    # 1 token from the pre-stream "prime" step (never disconnect-checked) +
    # 2 more from the loop before the 3rd disconnect check trips.
    assert len(events) == 3
    assert all(e["event"] == "token" for e in events)


def test_metrics_endpoint_exposes_prometheus_text_format(client):
    client.post("/api/generate/stream", json={"prompt": "for metrics"})
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
        client.post("/api/generate/stream", json={"prompt": "log me"})
    finished = [json.loads(r.message) for r in caplog.records if '"generate_finished"' in r.message]
    assert finished, "expected a generate_finished structured log line"
    payload = finished[-1]
    assert payload["event"] == "generate_finished"
    assert payload["status"] == "completed"
    assert set(payload) >= {"request_id", "session_id", "status", "tokens_emitted", "duration_ms", "model_version"}
