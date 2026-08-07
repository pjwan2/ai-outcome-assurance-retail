# ADR 0004: Public-retail sourcing and fully synthetic data

## Status
Accepted

## Context
This is an independent public prototype (PRD §2), not affiliated with or built from any employer's
internal systems, data, or proprietary terminology. It must be safe to show without any confidentiality
risk, and must not make or imply a legal-entitlement determination.

## Decision
- Only public retailer policy pages and public ACCC guidance are referenced, as metadata (URL, title,
  source class, retrieved/effective dates, content hash, version) in `app/fixtures/source_manifest.json`
  and `app/fixtures/eval_sources.json` — see the source manifest in PRD §3 for the canonical URLs.
- All case, order, seller, customer, and product identifiers are synthetic (`ORD-1001`, `SELLER-900`,
  `PROD-LAPTOP-01`, etc.) — none reference any real order or customer.
- `MAJOR_FAILURE_ESTABLISHED` and the refund decision are explicitly never resolved to an automatic
  statutory determination — see ADR 0002 and ADR 0003. The system's job is to route to human review
  with evidence, not to decide entitlement.

## Consequences
The prototype is demonstrable without exposing or implying access to any real retailer's internal
systems, and without making a claim this system is not qualified to make (a legal determination of
consumer-guarantee entitlement).
