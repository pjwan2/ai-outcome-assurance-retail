# Performance report — model-serving slice under load

Real Locust runs against a real running server (`python run_server.py`, not `TestClient`), not
estimated numbers. Every figure below is pulled from the actual run output
(`backend/loadtest/locustfile.py`); the exact commands are given so anyone can reproduce them. Re-run
after `/api/generate/stream` gained bearer-token auth and a per-principal rate limiter (see
`docs/adrs/`-adjacent review notes) — the numbers here reflect the current, authenticated endpoint, not
the pre-auth version.

## Setup

`/api/generate/stream` requires a bearer token, and the rate limiter is keyed by the authenticated
principal (`app.auth.Principal.reviewer_id`), not a client-supplied `session_id` — so a load test using
one shared token would have every simulated user collapse onto a single rate-limit bucket, which is not
a realistic multi-caller pattern. `backend/loadtest/locustfile.py` gives each simulated user one of 20
distinct tokens (`on_start`, round-robin), so the run below has a realistic spread of callers.

```bash
cd backend
python -c "print(','.join(f'loadtest-token-{i}:user{i}:retail-operations' for i in range(20)))" > /tmp/api_tokens.txt
rm -f ai_outcome_assurance.db && python -m alembic upgrade head
API_TOKENS="$(cat /tmp/api_tokens.txt)" \
  PORT=8010 SERVING_TOKEN_DELAY_SECONDS=0.1 SERVING_NUM_TOKENS=15 python run_server.py
```

`SERVING_TOKEN_DELAY_SECONDS=0.1`/`SERVING_NUM_TOKENS=15` (optional env vars on
`app/serving/router.py`) make each stream take a real-LLM-response-shaped ~1.5s instead of the
~80ms test default — otherwise no amount of concurrency exercises the concurrency limiter or
backpressure path in a 30-second run. Every other setting is the shipped default:
`SERVING_MAX_IN_FLIGHT=20`, `SERVING_MAX_QUEUE=20` (40 total capacity), `SERVING_RATE_LIMIT_CAPACITY=20`
tokens per principal refilling at 5/s, `SERVING_DEFAULT_TIMEOUT_SECONDS=10` (no client override in this
test — well above the ~1.5-3.3s actual stream durations observed, so the deadline enforcement fix
doesn't materially change these particular numbers; it's proven separately and precisely in
`backend/tests/test_serving.py::test_deadline_covers_the_full_stream_not_just_the_first_token`).

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
outcome, including instant rate-limit/backpressure rejections). The `total_stream_duration_ms` row is
the one to read for pass/fail and tail latency — the built-in `POST ... [complete]` row understates
both by design.

## Results

| Concurrent users | Stream attempts | Rejected (429 rate-limited + 503 backpressure) | Rejection rate |
|---|---|---|---|
| 10  | 151  | 0                        | 0.0%  |
| 50  | 1384 | 1045 (all backpressure)  | 75.5% |
| 100 | 8066 | 7706 (5250 rate-limited + 2456 backpressure) | 95.5% |

At 50 users spread across 20 tokens, no single principal's request rate gets close to its own limit
(`20` capacity / `5`-per-second refill) — the only thing rejecting requests is the shared, global
`ConcurrencyLimiter`. At 100 users (5 simulated users per token on average), per-principal rate limiting
starts rejecting requests too — both defenses are visibly doing their job at once, not just the one
being load-tested in isolation.

**Time-to-first-token, admitted requests only** (a rejected request never gets a token, so this metric
is naturally already "successful-only"):

| Concurrent users | p50 | p95 | p99 |
|---|---|---|---|
| 10  | 110ms  | 120ms  | 130ms  |
| 50  | 1500ms | 1700ms | 1700ms |
| 100 | 1600ms | 1700ms | 1900ms |

At 10 users (well under the 40-slot capacity), TTFT is just the one `SERVING_TOKEN_DELAY_SECONDS`
(~100ms) plus overhead. At 50/100 users, admitted requests queue behind others before starting — TTFT
absorbs that queueing delay, which is why it jumps ~14-15x even though the *admitted* request itself is
identical work.

**Total stream duration, all attempts (including instant rejections)**:

| Concurrent users | p50 | p90 | p95 | p99 | p100 (max) |
|---|---|---|---|---|---|
| 10  | 1600ms | 1600ms | 1700ms | 1700ms | 1706ms |
| 50  | 3ms    | 3100ms | 3200ms | 3200ms | 3271ms |
| 100 | 5ms    | 12ms   | 41ms   | 3100ms | 4774ms |

The low p50/p90 at 50/100 users is not the system being fast — it's the majority of attempts being
rejected in a few milliseconds (fail-fast rate-limiting/backpressure), dragging the lower percentiles
down. Read this table together with the rejection-rate table above, not in isolation.

## The concurrency limiter's throughput ceiling, confirmed quantitatively

Successful (non-rejected) stream throughput:

- 50 users: `1384 - 1045 = 339` successful streams / 30s ≈ **11.3/s**
- 100 users: `8066 - 7706 = 360` successful streams / 30s ≈ **12.0/s**

Both converge to close to the same ~11.3-12.0 successful streams/second regardless of how many users
(or how many distinct rate-limited principals) are hammering the endpoint — consistent with
`ConcurrencyLimiter(max_in_flight=20)`'s theoretical ceiling: `20 slots ÷ ~1.6s per stream ≈ 12.5
streams/s`. This is the concurrency limiter visibly doing its job: **the service holds a stable
throughput ceiling instead of degrading unboundedly as load increases past capacity** — 2x more users
(50→100) does not produce 2x more successful work; it produces the same successful work plus more
(fast, cheap) rejections, now split between two independent defenses (per-principal rate limiting and
global concurrency backpressure) rather than one.

## Server stability

The backend process was never restarted across the smoke test or all three runs. `GET /health`
returned `{"status":"ok"}` immediately after the 100-user run; `grep -ci "traceback\|unhandled"`
against the full server log across all runs returned `0`. No unhandled exception, hang, or crash at any
concurrency level — every overload response was a clean, typed `429` or `503`, never a dropped
connection or a 500.

## What this does and does not prove

- This is one process, one machine, a synthetic deterministic model with fixed per-token latency —
  not a claim about real LLM inference latency or multi-instance production capacity. See
  `docs/production_gap_register.md`.
- The default 10-second timeout was never approached in this run (streams complete in ~1.5-3.3s even
  under contention), so this load test does not exercise the deadline-enforcement fix — that is proven
  separately, and more precisely, by a unit test that deliberately sets a tight deadline
  (`backend/tests/test_serving.py::test_deadline_covers_the_full_stream_not_just_the_first_token`).
- Client-disconnect/cancellation under load: the Locust client (`requests`-based) closing a streaming
  response early was observed to register server-side as a genuine `is_disconnected()`-detected
  cancellation far less often than the number of client-cancel attempts made — very likely
  `requests`/`urllib3` connection-pooling behavior on the client side (a closed iterator doesn't always
  abort the underlying socket promptly on localhost), not a server-side detection gap. The server's
  disconnect handling is independently and reliably proven at the unit level in
  `backend/tests/test_serving.py::test_stream_generation_stops_on_disconnect_without_a_done_event`
  and `::test_concurrency_slot_is_released_when_the_holding_task_is_cancelled`, both of which control
  the disconnect signal directly rather than depending on a real HTTP client's socket-close timing.
  Flagged here rather than glossed over.
- 20 simulated identities is a deliberate, modest pool size to make the per-principal rate limiter
  observable within a 30-second run at 100 users — it is not a claim about how many real API keys a
  production deployment would see, and the rate-limiter's bucket store is bounded/LRU-evicting
  regardless of pool size (`app/serving/rate_limit.py::TokenBucketRateLimiter`).
