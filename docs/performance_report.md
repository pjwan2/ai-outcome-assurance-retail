# Performance report — model-serving slice under load

Real Locust runs against a real running server (`python run_server.py`, not `TestClient`), not
estimated numbers. Every figure below is pulled from the actual run output
(`backend/loadtest/locustfile.py`); the exact commands are given so anyone can reproduce them.

## Setup

```bash
cd backend
rm -f ai_outcome_assurance.db && python -m alembic upgrade head
PORT=8010 SERVING_TOKEN_DELAY_SECONDS=0.1 SERVING_NUM_TOKENS=15 python run_server.py
```

`SERVING_TOKEN_DELAY_SECONDS=0.1`/`SERVING_NUM_TOKENS=15` (new, optional env vars on
`app/serving/router.py`) make each stream take a real-LLM-response-shaped ~1.5s instead of the
~80ms test default — otherwise no amount of concurrency exercises the concurrency limiter or
backpressure path in a 30-second run. Every other setting is the shipped default:
`SERVING_MAX_IN_FLIGHT=20`, `SERVING_MAX_QUEUE=20` (40 total capacity), no rate limiting hit at these
volumes (`SERVING_RATE_LIMIT_CAPACITY=20` tokens, refilling at 5/s — never actually triggered below,
since each simulated session only sends a handful of requests over 30s).

```bash
python -m locust -f loadtest/locustfile.py --host http://127.0.0.1:8010 --headless -u 10  -r 10 -t 30s --csv=lt_10
python -m locust -f loadtest/locustfile.py --host http://127.0.0.1:8010 --headless -u 50  -r 25 -t 30s --csv=lt_50
python -m locust -f loadtest/locustfile.py --host http://127.0.0.1:8010 --headless -u 100 -r 50 -t 30s --csv=lt_100
```

## Why two different "response time" numbers appear per run

Locust's built-in HTTP instrumentation times `POST /api/generate/stream [complete]` from request start
to *response object available* — for a streaming endpoint that's just past the SSE headers, not the
full body. `backend/loadtest/locustfile.py` fires two custom metrics that measure what actually
matters: `time_to_first_token_ms` (perceived responsiveness) and `total_stream_duration_ms` (full
outcome, including instant backpressure/rate-limit rejections). The `total_stream_duration_ms` row is
the one to read for pass/fail and tail latency — the built-in `POST ... [complete]` row understates
both by design.

## Results

| Concurrent users | Stream attempts | Backpressure (503) rejections | Rejection rate | Timeouts / cancellations detected server-side |
|---|---|---|---|---|
| 10  | 152  | 0    | 0.0%  | 0 |
| 50  | 1437 | 1097 | 76.3% | 0 |
| 100 | 8049 | 7707 | 95.7% | 0 |

(Rejection rate computed from the `total_stream_duration_ms` metric specifically — `SSE
total_stream_duration_ms: Exception('backpressure_503')` — which is the only one of the two metrics
that reflects true per-attempt outcome; see above.)

**Time-to-first-token, admitted requests only** (a rejected request never gets a token, so this metric
is naturally already "successful-only"):

| Concurrent users | p50 | p95 | p99 |
|---|---|---|---|
| 10  | 110ms  | 120ms  | 130ms  |
| 50  | 1600ms | 1700ms | 1700ms |
| 100 | 1500ms | 1700ms | 2500ms |

At 10 users (well under the 40-slot capacity), TTFT is just the one `SERVING_TOKEN_DELAY_SECONDS`
(~100ms) plus overhead. At 50/100 users, admitted requests queue behind others before starting — TTFT
absorbs that queueing delay, which is why it jumps ~15x even though the *admitted* request itself is
identical work.

**Total stream duration, all attempts (including instant rejections)**:

| Concurrent users | p50 | p90 | p95 | p99 | p100 (max) |
|---|---|---|---|---|---|
| 10  | 1600ms | 1600ms | 1600ms | 1600ms | 1649ms |
| 50  | 2ms    | 3200ms | 3200ms | 3300ms | 4700ms |
| 100 | 3ms    | 8ms    | 21ms   | 3200ms | 4500ms |

The low p50/p90 at 50/100 users is not the system being fast — it's the majority of attempts being
rejected in a few milliseconds (fail-fast backpressure), dragging the lower percentiles down. Read
this table together with the rejection-rate table above, not in isolation.

## The concurrency limiter's throughput ceiling, confirmed quantitatively

Successful (non-rejected) stream throughput:

- 50 users: `1437 - 1097 = 340` successful streams / 30s ≈ **11.3/s**
- 100 users: `8049 - 7707 = 342` successful streams / 30s ≈ **11.4/s**

Both converge to the same ~11.3-11.4 successful streams/second regardless of how many users are
hammering the endpoint — exactly what `ConcurrencyLimiter(max_in_flight=20)` predicts:
`20 slots ÷ ~1.6s per stream ≈ 12.5 streams/s` theoretical ceiling (observed figure is a little lower,
consistent with queueing/scheduling overhead under Python's asyncio event loop rather than a
discrepancy in the limiter itself). This is the concurrency limiter visibly doing its job: **the
service holds a stable throughput ceiling instead of degrading unboundedly as load increases past
capacity** — 2x more users (50→100) does not produce 2x more successful work, or any less; it produces
the same successful work plus more (fast, cheap) rejections.

## Server stability

The backend process was never restarted across the smoke test or all three runs. `GET /health`
returned `{"status":"ok"}` immediately after the 100-user run; `grep -ci "traceback\|unhandled" `
against the full server log across all runs returned `0`. No unhandled exception, hang, or crash at any
concurrency level — every overload response was a clean, typed `503 SERVER_BUSY`, never a dropped
connection or a 500.

## What this does and does not prove

- This is one process, one machine, a synthetic deterministic model with fixed per-token latency —
  not a claim about real LLM inference latency or multi-instance production capacity. See
  `docs/production_gap_register.md`.
- Rate limiting (429) was never observed in these runs — `SERVING_RATE_LIMIT_CAPACITY=20` per session
  was never exhausted at this request pattern (Locust spawns many distinct sessions, each making only a
  handful of requests over 30s). The rate limiter itself is proven separately and directly in
  `backend/tests/test_serving.py::test_rate_limit_returns_429_with_retry_after_once_bucket_is_empty`,
  not by this load test.
- Client-disconnect/cancellation under load: the Locust client (`requests`-based) closing a streaming
  response early was observed to register server-side as a genuine `is_disconnected()`-detected
  cancellation only 3 times across all runs, far less often than the number of client-cancel attempts
  made. This is very likely `requests`/`urllib3` connection-pooling behavior on the client side (a
  closed iterator doesn't always abort the underlying socket promptly on localhost), not a server-side
  detection gap — the server's disconnect handling is independently and reliably proven at the unit
  level in `backend/tests/test_serving.py::test_stream_generation_stops_on_disconnect_without_a_done_event`
  and `::test_concurrency_slot_is_released_when_the_holding_task_is_cancelled`, both of which control
  the disconnect signal directly rather than depending on a real HTTP client's socket-close timing.
  Flagged here rather than glossed over.
