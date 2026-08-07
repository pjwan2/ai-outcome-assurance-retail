"""Demo smoke test (PRD section 22 `make demo-smoke`).

Resets the database, creates the synthetic hero case, runs the deterministic
pipeline, and asserts every expected controlled outcome is present. Exits
non-zero if any expected outcome is missing so this can be used as a CI gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Base, DATABASE_URL, SessionLocal, engine  # noqa: E402
from app.persistence import persist_case_run  # noqa: E402
from app.services.workflow import run_case_pipeline  # noqa: E402


def main() -> int:
    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if db_path.exists():
        db_path.unlink()

    Base.metadata.create_all(bind=engine)

    artifacts = run_case_pipeline()
    session = SessionLocal()
    try:
        case_row = persist_case_run(session, artifacts)
        case_id = case_row.case_id
    finally:
        session.close()

    checks = {
        "case created": case_id.startswith("CASE-"),
        "evidence validated": len(artifacts.evidence) >= 2,
        "claims resolved": len(artifacts.claims) == 8,
        "major failure claim UNKNOWN": any(
            c.claim_type == "MAJOR_FAILURE_ESTABLISHED" and c.status.value == "UNKNOWN"
            for c in artifacts.claims
        ),
        "authority decision REQUIRE_HUMAN": artifacts.authority.decision.value == "REQUIRE_HUMAN",
        "review task created": artifacts.review is not None,
        "trace events recorded": len(artifacts.trace_events) >= 6,
        "termination status NEEDS_REVIEW": artifacts.termination_status.value == "NEEDS_REVIEW",
    }

    print(f"Case ID: {case_id}")
    print("API URLs for manual inspection (after `python run_server.py`):")
    print(f"  GET  http://127.0.0.1:8000/api/cases/{case_id}")
    print(f"  GET  http://127.0.0.1:8000/api/cases/{case_id}/claims")
    print(f"  GET  http://127.0.0.1:8000/api/cases/{case_id}/trace")
    print("  GET  http://127.0.0.1:8000/api/reviews")
    print()

    all_passed = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\ndemo-smoke FAILED: an expected controlled outcome is missing.")
        return 1

    print("\ndemo-smoke PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
