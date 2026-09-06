"""Locust load test for POST /api/generate/stream (backend/app/serving/).

Locust's own request-time instrumentation measures time-to-response-object,
not time spent reading a streaming body — so this file manually times two
things that actually matter for a streaming endpoint and reports them as
custom Locust metrics:

  - time_to_first_token_ms: latency from request start to the first SSE
    token event (what a user actually perceives as "it started responding").
  - total_stream_duration_ms: latency from request start to stream
    completion (any terminal state: done, error, or client-side give-up).

Run against a real running server (not TestClient) — see
docs/performance_report.md for exact commands and results.
"""

from __future__ import annotations

import json
import time

from locust import HttpUser, between, events, task


def _fire(request_type: str, name: str, response_time_ms: float, exception: Exception | None = None) -> None:
    events.request.fire(
        request_type=request_type,
        name=name,
        response_time=response_time_ms,
        response_length=0,
        exception=exception,
        context={},
    )


class GenerateUser(HttpUser):
    wait_time = between(0.05, 0.3)

    @task(6)
    def stream_to_completion(self) -> None:
        start = time.perf_counter()
        first_token_at: float | None = None
        status = "ok"
        try:
            with self.client.post(
                "/api/generate/stream",
                json={"prompt": "load test prompt, please stream a response"},
                stream=True,
                catch_response=True,
                name="/api/generate/stream [complete]",
            ) as resp:
                if resp.status_code == 503:
                    status = "backpressure_503"
                    resp.success()  # a correct, intended response under load, not a failure
                elif resp.status_code == 429:
                    status = "rate_limited_429"
                    resp.success()
                elif resp.status_code != 200:
                    status = f"http_{resp.status_code}"
                    resp.failure(status)
                else:
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line or not raw_line.startswith("data:"):
                            continue
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                        payload = json.loads(raw_line.removeprefix("data:").strip())
                        if "reason" in payload:
                            status = f"stream_error_{payload['reason']}"
                    resp.success()
        except Exception as exc:  # connection-level failure, not an HTTP status
            status = f"exception_{type(exc).__name__}"

        total_ms = (time.perf_counter() - start) * 1000
        if first_token_at is not None:
            _fire("SSE", "time_to_first_token_ms", (first_token_at - start) * 1000)
        _fire(
            "SSE",
            "total_stream_duration_ms",
            total_ms,
            exception=None if status == "ok" else Exception(status),
        )

    @task(1)
    def client_cancels_mid_stream(self) -> None:
        """Connects, reads a couple of tokens, then gives up early — exercises
        the server's client-disconnect-releases-its-slot path under load."""
        start = time.perf_counter()
        try:
            with self.client.post(
                "/api/generate/stream",
                json={"prompt": "cancel me halfway through"},
                stream=True,
                catch_response=True,
                name="/api/generate/stream [client-cancelled]",
            ) as resp:
                for i, raw_line in enumerate(resp.iter_lines(decode_unicode=True)):
                    if raw_line and i >= 2:
                        break
                resp.success()
        except Exception:
            pass
        _fire("SSE", "client_cancelled_stream_ms", (time.perf_counter() - start) * 1000)
