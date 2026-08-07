"""Governed, read-only investigation tool registry (PRD section 13).

The DeterministicInvestigationPlanner (and any future model-backed planner)
may only invoke tools from this allow-list, and every call is validated with
a strict Pydantic schema (extra="forbid") before it runs. Unknown tools and
unexpected/extra arguments are rejected before any tool executes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError


class UnknownToolError(Exception):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' is not in the governed allow-list")


class InvalidToolArgumentsError(Exception):
    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Invalid arguments for tool '{tool_name}': {detail}")


class FixtureLexicalSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    query: str | None = None


class ExactSpanLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    locator: str


TOOL_REGISTRY: dict[str, type[BaseModel]] = {
    "fixture_lexical_search": FixtureLexicalSearchArgs,
    "exact_span_lookup": ExactSpanLookupArgs,
}


def validate_tool_call(tool_name: str, arguments: dict) -> BaseModel:
    """Reject unknown tools and unknown/extra arguments before any tool runs."""
    schema = TOOL_REGISTRY.get(tool_name)
    if schema is None:
        raise UnknownToolError(tool_name)
    try:
        return schema(**arguments)
    except ValidationError as exc:
        raise InvalidToolArgumentsError(tool_name, str(exc)) from exc
