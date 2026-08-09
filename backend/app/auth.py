"""Lightweight bearer-token auth for the demo API.

This is NOT enterprise IAM (see docs/production_gap_register.md) — it is a
static, environment-configured token-to-principal map, deliberately simple
so the prototype has *some* real authn/authz boundary instead of none. Every
mutating endpoint requires a valid bearer token; review decisions
additionally check the caller's role against the review's assigned_role
rather than trusting a client-supplied reviewer_id.

Configure via the API_TOKENS environment variable:
    API_TOKENS="token1:alice:retail-operations,token2:bob:retail-operations"

If API_TOKENS is unset, a single default dev token is used so the demo still
runs zero-config offline — this is intentionally insecure and is logged
loudly so it is never mistaken for a real deployment configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

DEFAULT_DEV_TOKEN = "dev-local-demo-token"
DEFAULT_DEV_REVIEWER_ID = "demo-reviewer"
DEFAULT_DEV_ROLE = "retail-operations"


@dataclass(frozen=True)
class Principal:
    reviewer_id: str
    role: str


def _load_token_map() -> dict[str, Principal]:
    raw = os.environ.get("API_TOKENS")
    if not raw:
        return {DEFAULT_DEV_TOKEN: Principal(DEFAULT_DEV_REVIEWER_ID, DEFAULT_DEV_ROLE)}

    tokens: dict[str, Principal] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        token, reviewer_id, role = entry.split(":", 2)
        tokens[token] = Principal(reviewer_id, role)
    return tokens


_TOKEN_MAP = _load_token_map()


def require_auth(authorization: str | None = Header(default=None)) -> Principal:
    """FastAPI dependency: validates `Authorization: Bearer <token>` and
    returns the resolved Principal, or raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "MISSING_BEARER_TOKEN", "message": "Authorization: Bearer <token> is required"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    principal = _TOKEN_MAP.get(token)
    if principal is None:
        raise HTTPException(
            status_code=401, detail={"error_code": "INVALID_TOKEN", "message": "Unrecognised bearer token"}
        )
    return principal
