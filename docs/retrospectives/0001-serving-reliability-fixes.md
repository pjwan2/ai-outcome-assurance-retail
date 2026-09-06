# Retrospective: serving reliability and auth fixes

**Status note (read this first):** this work was committed directly to `master`
(`fd135e4`, "Fix real bugs in the serving slice; tone down credibility docs"), not merged through a
pull request. This document is a retrospective write-up in PR-description format, added after the
fact for an honest, complete record — it is not a claim that a PR review happened, and the commit
history is not rewritten to suggest one did. Later work in this repository (see
`docs/retrospectives/` for subsequent entries, if any, and the repo's PR history from this point
forward) uses a real branch-and-PR workflow; this entry documents why that mattered enough to adopt.

## Problem

A review of `backend/app/serving/` (the model-serving slice: SSE streaming over a deterministic fake
model) found four real defects, not stylistic issues:

1. **Timeout didn't cover the whole request.** `timeout_seconds` only bounded the pre-stream "prime"
   step (acquiring the first token). A model that answered quickly but then stalled mid-stream could
   run well past the timeout a client was told to expect.
2. **`/api/generate/stream` had no authentication**, and its rate limiter was keyed by a
   client-supplied `session_id` — trivially bypassed by sending a new one on every request.
3. **`fail_mode` was a public request-body field.** Any real caller could set
   `{"fail_mode": "permanent"}` and force the server into its own failure/error-handling paths.
4. **No bound on the rate limiter's memory.** `TokenBucketRateLimiter`'s bucket dict grew without limit
   as new keys were seen, and request fields (`prompt`, `session_id`, `timeout_seconds`) had no length
   or range validation.

## Design decisions

- **A single absolute deadline, not a per-step timeout.** `app/serving/streaming.py::stream_generation`
  takes one `deadline: float` (an absolute `time.monotonic()` value) computed once at the top of the
  request in `router.py`, before the concurrency slot is even acquired. Every subsequent await point —
  slot acquisition, the retryable "prime" step, and each token pulled from the generator — is wrapped
  in `asyncio.wait_for(..., timeout=deadline - time.monotonic())` via a small `_await_within_deadline`
  helper, rather than resetting a fresh per-step timeout at each stage (which was the original bug).
- **Auth reuses the existing boundary.** `require_auth` (`app/auth.py`) already gated every mutating
  case-pipeline endpoint; `/api/generate/stream` now uses the same dependency rather than inventing a
  second auth mechanism. The rate limiter keys on `Principal.reviewer_id` (the authenticated identity),
  and `session_id` was demoted to a correlation/logging field only, documented as such in
  `GenerateRequest`.
- **Failure injection via dependency override, not a wire field.** `fail_mode` moved from a per-call
  argument to a construction-time property of a `DeterministicFakeModel` instance
  (`app/serving/model_backend.py`). Tests inject a pre-configured failing instance through FastAPI's
  `app.dependency_overrides[get_model_backend]` — the same mechanism FastAPI documents for exactly this
  purpose — so the public `GenerateRequest` schema has no failure-control surface at all.
- **Bounded rate-limiter store.** `TokenBucketRateLimiter` gained a `max_tracked_keys` cap (default
  10,000) with LRU eviction (`collections.OrderedDict`, oldest entry evicted on overflow) rather than
  a TTL-based sweep — simpler to reason about and test deterministically, and sufficient for the actual
  failure mode (unbounded distinct keys), not a claim that it matches a production rate-limiter's full
  feature set.

## Failure modes considered

- A model that fails before any token (retryable via `tenacity`, confined to the pre-stream step so a
  retry never re-sends output the client already saw) vs. mid-stream (not retried — partial output was
  already sent, so the only safe response is a graceful terminal SSE `error` event).
- A client that disconnects mid-stream (checked via `request.is_disconnected()`, releasing the
  concurrency slot through the same `finally` block that runs on any other exit path, including
  `asyncio.CancelledError`).
- Two different rejection reasons that must stay distinguishable end to end: `429` (over the caller's
  own rate limit — a client problem) vs. `503` (server-wide capacity exhausted — not specific to any
  one caller). Both are typed, both are logged and counted separately in Prometheus metrics.

## Tests added

`backend/tests/test_serving.py` grew from 13 to 19 tests, including:

- `test_deadline_covers_the_full_stream_not_just_the_first_token` — the direct regression test for the
  main bug: a model configured to answer its first token quickly but stall over the full stream must
  still time out at the overall deadline.
- `test_generate_stream_requires_auth`, `test_rate_limit_is_keyed_by_principal_not_client_supplied_session_id`,
  `test_rate_limit_is_scoped_per_principal` — the auth/rate-limit-identity fixes.
- `test_empty_prompt_is_rejected`, `test_overlong_prompt_is_rejected`, `test_out_of_range_timeout_is_rejected`
  — the new Pydantic `Field` constraints.
- The existing transient/permanent/mid-stream failure tests were rewritten to use
  `app.dependency_overrides[get_model_backend]` instead of a `fail_mode` request field.

## Rollback impact

Pure application-code and test changes — no schema migration, no new external dependency, no change to
`backend/requirements.txt`. Reverting `fd135e4` would restore the four defects above but would not
leave the database or any persisted state in an inconsistent shape; the serving slice is stateless
between requests (in-memory concurrency/rate-limit state resets on process restart regardless).

## Verification commands

```bash
cd backend
python -m pytest -q                       # 87 passed
python -m ruff check app tests loadtest   # clean
python -m mypy app                        # clean
curl -s -X POST http://127.0.0.1:8000/api/generate/stream \
  -H "Content-Type: application/json" -d '{"prompt":"x"}'   # now 401 without a bearer token
```

Load test re-run against the authenticated endpoint at 10/50/100 concurrent users — see
[`docs/performance_report.md`](../performance_report.md) for the real numbers, including the observed
interaction between the (now per-principal) rate limiter and the concurrency-based backpressure at high
load.
