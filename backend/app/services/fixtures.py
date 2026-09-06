"""Versioned fixture loading for the case pipeline. There is no free-text
case intake anywhere in this repository — every case is one of these.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class UnknownCaseError(Exception):
    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        super().__init__(f"No runnable fixture for case_id '{case_id}'")


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def valid_bindings() -> list[dict[str, str]]:
    return load_fixture("case_registry.json")["valid_bindings"]


def list_available_case_ids() -> list[str]:
    """Case IDs with a runnable fixture, in a stable, deterministic order."""
    extra_ids = sorted(p.stem for p in (FIXTURES_DIR / "cases").glob("*.json"))
    return ["CASE-RET-001", *extra_ids]


def load_case_fixture(case_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the (case, sources) fixture pair for a given case_id from the
    versioned fixture registry. Raises UnknownCaseError for anything not in
    `list_available_case_ids()` — there is no free-text case intake."""
    if case_id == "CASE-RET-001":
        return load_fixture("synthetic_case.json"), load_fixture("source_manifest.json")["sources"]
    path = FIXTURES_DIR / "cases" / f"{case_id}.json"
    if not path.exists():
        raise UnknownCaseError(case_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["case"], data["sources"]
