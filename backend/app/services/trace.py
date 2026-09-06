"""The tamper-evident TraceEvent hash chain, extracted so validate.py,
resolve.py, and authorise.py can all record to it without importing
workflow.py (which imports them) — this module has no dependency on any of
its siblings, breaking what would otherwise be a circular import.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.models import TraceEvent
from app.state_machine import CaseStatus, validate_transition


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TraceRecorder:
    """Accumulates ordered TraceEvent records for one case run as a hash
    chain: each event's `state_after_hash` folds in the previous event's
    hash, its own content, and (for tool calls) an argument hash. Replaying
    the same fixture through `verify_trace_chain` must reproduce the same
    chain — any inserted, reordered, or edited event breaks it.
    """

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self._sequence = 0
        self._chain_hash = _sha256(f"CASE:{case_id}")
        self.events: list[TraceEvent] = []

    def record(
        self,
        stage: str,
        event_type: str,
        *,
        tool_name: str | None = None,
        evidence_ids: list[str] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        self._sequence += 1
        evidence_ids = evidence_ids or []
        state_before_hash = self._chain_hash
        argument_hash = _sha256(json.dumps(arguments, sort_keys=True)) if arguments is not None else None
        result_payload = json.dumps(
            {
                "sequence": self._sequence,
                "stage": stage,
                "event_type": event_type,
                "tool_name": tool_name,
                "evidence_ids": evidence_ids,
            },
            sort_keys=True,
        )
        result_hash = _sha256(result_payload)
        state_after_hash = _sha256(state_before_hash + result_hash + (argument_hash or ""))
        self._chain_hash = state_after_hash

        self.events.append(
            TraceEvent(
                trace_id=f"TRACE-{self.case_id}-{self._sequence:03d}",
                case_id=self.case_id,
                sequence=self._sequence,
                stage=stage,
                event_type=event_type,
                tool_name=tool_name,
                argument_hash=argument_hash,
                result_hash=result_hash,
                state_before_hash=state_before_hash,
                state_after_hash=state_after_hash,
                evidence_ids=evidence_ids,
                timestamp=datetime.now(timezone.utc),
            )
        )

    def transition(self, current: CaseStatus, target: CaseStatus) -> CaseStatus:
        """Validate and record a CaseStatus transition. Fails closed:
        raises InvalidTransitionError (not caught here) on an illegal
        transition rather than recording it."""
        validate_transition(current, target)
        self.record("STATE", "STATE_TRANSITION", arguments={"from": current.value, "to": target.value})
        return target


def verify_trace_chain(case_id: str, events: list[TraceEvent]) -> bool:
    """Recompute the hash chain for a stored/replayed trace and confirm it
    matches what was recorded. Returns False if any event was altered,
    reordered, inserted, or removed."""
    chain_hash = _sha256(f"CASE:{case_id}")
    for event in sorted(events, key=lambda e: e.sequence):
        if event.state_before_hash != chain_hash:
            return False
        result_payload = json.dumps(
            {
                "sequence": event.sequence,
                "stage": event.stage,
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "evidence_ids": event.evidence_ids,
            },
            sort_keys=True,
        )
        expected_result_hash = _sha256(result_payload)
        if event.result_hash != expected_result_hash:
            return False
        expected_state_after = _sha256(chain_hash + expected_result_hash + (event.argument_hash or ""))
        if event.state_after_hash != expected_state_after:
            return False
        chain_hash = expected_state_after
    return True
