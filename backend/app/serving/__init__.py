"""Model-serving slice: async streaming generation over a deterministic fake
model, with the async-serving engineering a real inference service needs
(timeouts, cancellation, bounded concurrency/backpressure, rate limiting,
retry, structured logging, metrics) — independent of app.services.workflow's
case-assurance domain logic. See docs/architecture.md and
docs/production_gap_register.md for what this is and is not a substitute
for (no live model is ever called here).
"""
