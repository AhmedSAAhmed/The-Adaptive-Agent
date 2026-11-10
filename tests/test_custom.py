"""'Try it yourself': parsing a judge's own request, and a human customer who says no."""
import asyncio
from typing import Any

import pytest

from app.core.session import SessionManager
from app.core.world import classify_reply
from app.llm.client import LLMResult
from app.scenarios.custom import build_custom, parse_request
from app.store.db import Store

STEP = 0.25


@pytest.mark.parametrize("text,kind,field,value", [
    ("Hi, I'm Lina. Please cancel order 5521 and refund me, SAR 230", "refund", "order_id", "ORD-5521"),
    ("السلام عليكم معك فهد، أبغى ألغي طلبي رقم ٤٤١٢ وأسترجع فلوسي", "refund", "order_id", "ORD-4412"),
    ("Book a table for 4 at 9 at King Fahd please", "booking", "branch", "king_fahd"),
    ("أبغى أحجز طاولة لـ 8 أشخاص الساعة 8 في الملقا", "booking", "party_size", 8),
    ("change my phone plan", "out_of_scope", "kind", "out_of_scope"),
])
def test_deterministic_parser(text: str, kind: str, field: str, value: Any) -> None:
    req = asyncio.run(parse_request(text))
    assert req.kind == kind
    assert getattr(req, field) == value


def test_evening_times_and_clamping() -> None:
    req = asyncio.run(parse_request("table for 2 at 9 olaya"))
    assert req.time == "21:00"
    late = asyncio.run(parse_request("table for 2 at 23:30 al malqa"))
    assert late.time == "21:00" and late.notes  # needs 2 h before Al Malqa closes at 23:00


class FakeLLM:
    available = True

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def complete_json(self, *a: Any, **k: Any) -> LLMResult:
        return LLMResult(data=self.data, provider="fake", model="m", latency_ms=1)


def test_llm_output_is_clamped_by_code() -> None:
    hostile = {"kind": "refund", "order_id": "ORD-77; DROP TABLE", "order_total": 99999, "items": ["x" * 500], "name_en": "<script>"}
    req = asyncio.run(parse_request("cancel order 77 please", FakeLLM(hostile)))  # type: ignore[arg-type]
    assert req.order_id == "ORD-77"
    assert req.order_total == 2000.0
    assert len(req.items[0]) <= 40
    assert "<" not in req.name_en


def test_reply_classifier() -> None:
    assert classify_reply("Yes, please confirm") == "yes"
    assert classify_reply("نعم أكد الحجز") == "yes"
    assert classify_reply("ولا يهمك موافق") == "yes"
    assert classify_reply("No, make it 21:30 at Olaya") == "no"
    assert classify_reply("لا، ما يناسبني") == "no"
    assert classify_reply("Window seat please") == "info"
    assert classify_reply("(no reply within 90 s)") == "no"


def _run(text: str, twist: str = "auto", human: bool = False, on_wait: Any = None) -> dict:
    async def go() -> dict:
        req = await parse_request(text)
        m = SessionManager(Store())
        s = m.start_scenario(build_custom(req, text, twist, human), step_seconds=STEP)  # type: ignore[arg-type]
        replied = False
        while not s.finished:
            await s.wait_change(timeout=0.5)
            for a in s.agents.values():
                a.human_wait_s = 4.0
            ada = s.agents.get("adaptive")
            if on_wait and ada and not replied and ada.waiting_for_customer and ada.revisions:
                replied = True
                await s.reply(on_wait)
        await s.task
        return s.agents

    return asyncio.run(go())


def test_custom_refund_runs_side_by_side() -> None:
    agents = _run("please cancel order 5521 and refund me, SAR 230")
    assert agents["baseline"].outcome["verdict"] == "silent_failure"
    assert agents["adaptive"].outcome["verdict"] == "success"


def test_custom_flapping_booking_is_contained() -> None:
    agents = _run("table for 4 at 20:00 at olaya", twist="flapping")
    assert set(agents) == {"naive", "adaptive"}
    guarded = agents["adaptive"]
    assert guarded.outcome["verdict"] == "success"
    assert guarded.sim.bookings[0]["branch"] == "olaya"
    assert any(r.decision == "hold" for r in guarded.revisions)


def test_human_says_no_and_only_the_adaptive_agent_listens() -> None:
    agents = _run("Book a table for 4 at 20:00 at Olaya", human=True, on_wait="No, King Fahd is too far for us")
    ada = agents["adaptive"]
    assert any("customer.reply" in r.trigger for r in ada.revisions)
    assert all(bk.get("consent") != "no" for bk in ada.sim.bookings)
    assert ada.outcome["verdict"] in ("escalated", "success")
    assert agents["baseline"].outcome["verdict"] == "silent_failure"
