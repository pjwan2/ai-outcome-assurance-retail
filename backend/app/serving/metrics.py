"""Prometheus metrics for the model serving slice.

Uses a dedicated CollectorRegistry (not the global default) so re-importing
this module in tests never raises a duplicate-timeseries registration error.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "serving_requests_total",
    "Total /api/generate/stream requests by terminal status",
    ["status"],
    registry=REGISTRY,
)
IN_FLIGHT = Gauge(
    "serving_in_flight_requests", "Requests currently holding a concurrency slot", registry=REGISTRY
)
TIME_TO_FIRST_TOKEN_SECONDS = Histogram(
    "serving_time_to_first_token_seconds",
    "Latency from request received to first token emitted",
    registry=REGISTRY,
)
TOTAL_DURATION_SECONDS = Histogram(
    "serving_total_duration_seconds",
    "Latency from request received to stream completion (any terminal state)",
    registry=REGISTRY,
)
TOKENS_GENERATED_TOTAL = Counter(
    "serving_tokens_generated_total", "Total tokens streamed to clients", registry=REGISTRY
)
ERRORS_TOTAL = Counter(
    "serving_errors_total", "Total errors by reason", ["reason"], registry=REGISTRY
)
RATE_LIMITED_TOTAL = Counter(
    "serving_rate_limited_total", "Total requests rejected by the rate limiter", registry=REGISTRY
)
RETRIES_TOTAL = Counter(
    "serving_retries_total", "Total backend retry attempts (pre-stream only)", registry=REGISTRY
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


__all__ = [
    "CONTENT_TYPE_LATEST",
    "ERRORS_TOTAL",
    "IN_FLIGHT",
    "RATE_LIMITED_TOTAL",
    "REQUESTS_TOTAL",
    "RETRIES_TOTAL",
    "TIME_TO_FIRST_TOKEN_SECONDS",
    "TOKENS_GENERATED_TOTAL",
    "TOTAL_DURATION_SECONDS",
    "render_metrics",
]
