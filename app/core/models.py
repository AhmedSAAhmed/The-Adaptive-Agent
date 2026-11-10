"""Typed vocabulary of the loop: mission, plan, step, assumption, event, revision."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Op = Literal["eq", "ne", "in", "not_in", "gte", "lte"]
Trust = Literal["high", "low"]
StepStatus = Literal["pending", "running", "waiting", "done", "skipped", "failed", "blocked"]
Mode = Literal["baseline", "naive", "adaptive"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Assumption(BaseModel):
    """A checkable belief a step depends on. Broken assumption -> the step is no longer safe."""

    key: str
    op: Op
    value: Any
    why: str = ""
    origin: Literal["tool_contract", "planner"] = "planner"

    def holds(self, actual: Any) -> bool | None:
        """True/False when the actual value is known, None when the world has no belief yet."""
        if actual is None:
            return None
        try:
            if self.op == "eq":
                return actual == self.value
            if self.op == "ne":
                return actual != self.value
            if self.op == "in":
                return actual in list(self.value)
            if self.op == "not_in":
                return actual not in list(self.value)
            if self.op == "gte":
                return actual >= self.value
            if self.op == "lte":
                return actual <= self.value
        except TypeError:
            return False
        return False

    def describe(self) -> str:
        sym = {"eq": "==", "ne": "!=", "in": "in", "not_in": "not in", "gte": ">=", "lte": "<="}[self.op]
        return f"{self.key} {sym} {self.value!r}"


class Step(BaseModel):
    id: str = Field(default_factory=lambda: new_id("st"))
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    assumptions: list[Assumption] = Field(default_factory=list)
    irreversible: bool = False
    status: StepStatus = "pending"
    result: dict[str, Any] | None = None


class Plan(BaseModel):
    version: int = 1
    steps: list[Step]
    rationale: str = ""
    created_by: str = "deterministic"

    def remaining(self) -> list[Step]:
        return [s for s in self.steps if s.status in ("pending", "running", "waiting")]


class Mission(BaseModel):
    id: str
    kind: Literal["refund", "booking"]
    title: str
    goal: str
    request: str
    customer: dict[str, Any]
    policy: list[str]
    invariants: list[str]
    max_revisions: int = 3


class Event(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ev"))
    source: str
    key: str
    value: Any
    trust: Trust = "high"
    ts: float = Field(default_factory=time.time)
    note: str = ""
    handled_as: str = "pending"  # applied | ignored | unconfirmed | flapping | observed-only


class BrokenAssumption(BaseModel):
    step_id: str
    step_tool: str
    assumption: Assumption
    actual: Any


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rv"))
    ts: float = Field(default_factory=time.time)
    trigger_event_id: str | None = None
    trigger: str = ""
    decision: Literal["replan", "escalate", "ignore", "hold", "precommit-replan"]
    broken: list[BrokenAssumption] = Field(default_factory=list)
    from_version: int
    to_version: int
    reason_en: str
    reason_ar: str = ""
    planner: str = "deterministic"
