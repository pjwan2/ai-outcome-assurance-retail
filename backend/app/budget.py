"""Run budgets (PRD section 9): every investigation run has a maximum number
of tool calls. Exhausting the budget is a typed, controlled termination
(CONTROL_BLOCKED), not an unhandled exception hiding a runaway loop.
"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceededError(Exception):
    def __init__(self, resource: str, limit: int) -> None:
        self.resource = resource
        self.limit = limit
        super().__init__(f"Budget exceeded for {resource}: limit={limit}")


@dataclass
class RunBudget:
    max_tool_calls: int = 10
    max_steps: int = 50

    def __post_init__(self) -> None:
        self._tool_calls = 0
        self._steps = 0

    def consume_tool_call(self) -> None:
        self._tool_calls += 1
        if self._tool_calls > self.max_tool_calls:
            raise BudgetExceededError("tool_calls", self.max_tool_calls)

    def consume_step(self) -> None:
        self._steps += 1
        if self._steps > self.max_steps:
            raise BudgetExceededError("steps", self.max_steps)

    @property
    def tool_calls_used(self) -> int:
        return self._tool_calls

    @property
    def steps_used(self) -> int:
        return self._steps
