import asyncio
from typing import Any

import pytest

from app.core.models import Assumption, BrokenAssumption
from app.core.planner import Planner, PlanError, validate
from app.core.world import WorldModel
from app.llm.client import LLMResult, parse_json
from app.scenarios import SCENARIOS

A = SCENARIOS["A"].mission
B = SCENARIOS["B"].mission
NOTIFY = {"tool": "notify_customer", "args": {"message_en": "hi", "message_ar": "مرحبا"}}


def world_a(status: str = "preparing") -> WorldModel:
    return WorldModel({"order.ORD-7781.status": status, "order.ORD-7781.total": 186.0})


def test_rejects_unknown_tool() -> None:
    with pytest.raises(PlanError):
        validate([{"tool": "wire_money", "args": {}}, NOTIFY], A, world_a(), [])


def test_rejects_refund_above_total() -> None:
    with pytest.raises(PlanError, match="exceeds"):
        validate([{"tool": "issue_refund", "args": {"order_id": "ORD-7781", "amount": 999}}, NOTIFY], A, world_a(), [])


def test_rejects_voucher_above_cap() -> None:
    with pytest.raises(PlanError, match="25%"):
        validate([{"tool": "issue_voucher", "args": {"order_id": "ORD-7781", "percent": 50}}, NOTIFY], A, world_a("picked_up"), [])


def test_rejects_irreversible_step_whose_contract_is_already_false() -> None:
    with pytest.raises(PlanError, match="contract already false"):
        validate([{"tool": "cancel_order", "args": {"order_id": "ORD-7781"}}, NOTIFY], A, world_a("picked_up"), [])


def test_rejects_plan_that_does_not_resolve() -> None:
    with pytest.raises(PlanError, match="must end"):
        validate([{"tool": "ask_customer", "args": {"question_en": "?", "question_ar": "؟"}}], A, world_a(), [])


def test_rejects_moved_booking_without_asking() -> None:
    steps = [{"tool": "confirm_booking", "args": {"branch": "king_fahd", "time": "20:00", "party_size": 6}}, NOTIFY]
    with pytest.raises(PlanError, match="not asked"):
        validate(steps, B, WorldModel({"branch.king_fahd.open_until": "23:59"}), [])


def test_contracts_are_attached_by_code_not_llm() -> None:
    steps = validate([{"tool": "issue_refund", "args": {"order_id": "ORD-7781", "amount": 186}}, NOTIFY], A, world_a(), [])
    assert steps[0].irreversible
    assert any(a.origin == "tool_contract" and a.key == "order.ORD-7781.status" for a in steps[0].assumptions)


class FakeLLM:
    available = True

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def complete_json(self, *args: Any, **kw: Any) -> LLMResult:
        return LLMResult(data=self.data, provider="fake", model="m", latency_ms=1)


def test_invalid_llm_replan_falls_back_to_deterministic() -> None:
    bad = {"reason_en": "x", "steps": [{"tool": "issue_refund", "args": {"order_id": "ORD-7781", "amount": 186}}, NOTIFY]}
    planner = Planner(FakeLLM(bad))  # type: ignore[arg-type]
    world = world_a("picked_up")
    plan = asyncio.run(planner.initial_plan(A, world_a()))
    broken = [BrokenAssumption(step_id="s", step_tool="cancel_order",
                               assumption=Assumption(key="order.ORD-7781.status", op="in", value=["placed"]), actual="picked_up")]
    steps, _, en, _, by = asyncio.run(planner.replan(A, world, plan, broken, None))
    assert by == "deterministic"
    assert [s.tool for s in steps] == ["issue_voucher", "notify_customer"]
    assert "changed my mind" in en


def test_valid_llm_plan_is_used() -> None:
    good = {"rationale": "r", "steps": [{"tool": "lookup_order", "args": {"order_id": "ORD-7781"}}, NOTIFY]}
    plan = asyncio.run(Planner(FakeLLM(good)).initial_plan(A, world_a()))  # type: ignore[arg-type]
    assert plan.created_by == "fake:m"
    assert [s.tool for s in plan.steps] == ["lookup_order", "notify_customer"]


def test_parse_json_handles_fences() -> None:
    assert parse_json('Sure:\n```json\n{"a": 1}\n```') == {"a": 1}
