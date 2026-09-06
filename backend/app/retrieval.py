"""Deterministic, offline retrieval scoring (TF-IDF + cosine similarity).

`app/agents.py::RetrievalAgent` previously returned candidates with no
ranking signal at all — a source was a "match" purely because its
`source_id` appeared in `case["source_refs"]`. This module adds a real,
explainable relevance score on top of that lookup, using only the standard
library: no embedding model, no vector database, no network call. That is a
deliberate choice, not a placeholder — see
docs/adrs/0006-rag-guardrails-are-non-authoritative.md and the "What must NOT
be claimed" section of docs/interview_evidence.md.

Every function here is pure and deterministic: the same query and candidate
pool always produce the same scores, which is what makes them safe to use in
tests, evaluation, and the tamper-evident trace.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

RELEVANCE_THRESHOLD = 0.05

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small, fixed stopword list — with a per-case corpus this tiny (a query plus
# a handful of short excerpts), IDF alone barely dampens common words, so
# they're dropped outright rather than left to add coincidental similarity.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on",
        "and", "or", "but", "can", "may", "for", "with", "this", "that", "it", "please",
    }
)


def _normalize(token: str) -> str:
    """Cheap plural-stripping ("refunds" -> "refund") so lexical overlap
    survives simple morphology without pulling in a real stemming library —
    a deliberately crude heuristic, not a claim of proper NLP normalization."""
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_normalize(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def build_query(case: dict[str, Any]) -> str:
    """Derive a deterministic query string from a case fixture's own fields
    — no free-text intake, consistent with the rest of this repository."""
    event = case.get("event", {})
    parts = [
        case.get("customer_request", ""),
        case.get("product_ref", ""),
        *[str(v) for v in event.values() if isinstance(v, str)],
    ]
    return " ".join(p for p in parts if p)


def _term_frequencies(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)


def _idf(term: str, documents: list[list[str]]) -> float:
    containing = sum(1 for doc in documents if term in doc)
    # Smoothed IDF (add-one) so a term present in every document still gets a
    # small positive weight instead of exactly zero.
    return math.log((1 + len(documents)) / (1 + containing)) + 1.0


def _vector(tokens: list[str], vocabulary: list[str], documents: list[list[str]]) -> list[float]:
    tf = _term_frequencies(tokens)
    return [tf.get(term, 0) * _idf(term, documents) for term in vocabulary]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def score_candidates(query: str, candidates: list[dict[str, Any]]) -> dict[str, float]:
    """Score each candidate's excerpt against the query with TF-IDF cosine
    similarity, over a per-case corpus (the query plus every candidate's
    excerpt). Returns a score in [0, 1] keyed by source_id. Deterministic:
    calling this twice with the same arguments returns identical floats."""
    query_tokens = tokenize(query)
    candidate_tokens = [tokenize(c.get("excerpt", "")) for c in candidates]
    documents = [query_tokens, *candidate_tokens]
    vocabulary = sorted({term for doc in documents for term in doc})

    if not vocabulary or not query_tokens:
        return {c["source_id"]: 0.0 for c in candidates}

    query_vector = _vector(query_tokens, vocabulary, documents)
    scores: dict[str, float] = {}
    for candidate, tokens in zip(candidates, candidate_tokens, strict=True):
        candidate_vector = _vector(tokens, vocabulary, documents)
        scores[candidate["source_id"]] = round(_cosine_similarity(query_vector, candidate_vector), 6)
    return scores


def is_low_relevance(score: float) -> bool:
    return score < RELEVANCE_THRESHOLD
