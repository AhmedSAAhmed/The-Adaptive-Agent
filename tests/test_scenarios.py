"""End-to-end: the original plan fails silently, the adaptive agent adapts, the guards contain bad signals."""
import asyncio

from app.core.agent import Agent
from app.core.models import Event
from app.core.planner import Planner
from app.core.session import SessionManager
from app.core.world import WorldModel
from app.scenarios import SCENARIOS
from app.sim.systems import SimSystems
from app.store.db import Store

STEP = 0.25


def run(scenario: str) -> dict:
    async def go() -> dict:
        m = SessionManager(Store())
        s = m.start(scenario, step_seconds=STEP)
        await s.task
        return s.agents

    return asyncio.run(go())


def test_a_refund_baseline_fails_silently_adaptive_replans() -> None:
    agents = run("A")
    base, ada = agents["baseline"], agents["adaptive"]
    assert base.outcome["verdict"] == "silent_failure"
    assert base.status == "done"  # it believes it succeeded
    assert ada.outcome["verdict"] == "success"
    assert [r.decision for r in ada.revisions] == ["replan"]
    assert ada.revisions[0].broken[0].step_tool == "cancel_order"
    assert ada.sim.refunds == []


def test_b_booking_baseline_fails_silently_adaptive_moves_with_consent() -> None:
    agents = run("B")
    assert agents["baseline"].outcome["verdict"] == "silent_failure"
    ada = agents["adaptive"]
    assert ada.outcome["verdict"] == "success"
    assert ada.sim.bookings[0]["branch"] == "king_fahd"
    assert not [h for h in ada.sim.holds if h["active"]]  # abandoned hold was released
    tools = [s.tool for s in ada.plan.steps if s.status == "done"]
    assert tools.index("ask_customer") < tools.index("confirm_booking")


def test_c_flapping_signal_is_contained() -> None:
    agents = run("C")
    naive, guarded = agents["naive"], agents["adaptive"]
    assert sum(r.decision == "replan" for r in naive.revisions) >= 1  # believed the bad signal
    assert guarded.outcome["verdict"] == "success"
    assert not [r for r in guarded.revisions if r.decision == "replan"]
    assert any(r.decision == "hold" for r in guarded.revisions)  # flap detector fired
    assert any(t["team"] == "ops" for t in guarded.sim.tickets)
    assert "courier_webhook" in guarded.unhealthy_sources


def test_revision_budget_escalates_to_human() -> None:
    async def go() -> Agent:
        sc = SCENARIOS["A"]
        mission = sc.mission.model_copy(update={"max_revisions": 0})
        planner = Planner()
        plan = await planner.initial_plan(mission, WorldModel(sc.world_seed))
        sim = SimSystems(sc.sim_seed)
        agent = Agent("run_t", "adaptive", mission, plan, sim, WorldModel(sc.world_seed), planner, None, lambda: None, STEP)
        task = asyncio.create_task(agent.run())
        await agent.started.wait()
        await asyncio.sleep(STEP * 1.2)
        sim.apply_truth("order.ORD-7781.status", "picked_up")
        await agent.publish(Event(source="order_system", key="order.ORD-7781.status", value="picked_up"))
        await task
        return agent

    agent = asyncio.run(go())
    assert agent.status == "escalated"
    assert agent.revisions[-1].decision == "escalate"
    assert agent.sim.refunds == [] and agent.sim.tickets


def test_precommit_recheck_catches_change_the_monitor_never_saw() -> None:
    """The system of record changes silently (no event): the irreversible step still refuses to run."""
    async def go() -> Agent:
        sc = SCENARIOS["A"]
        planner = Planner()
        plan = await planner.initial_plan(sc.mission, WorldModel(sc.world_seed))
        sim = SimSystems(sc.sim_seed)
        agent = Agent("run_p", "adaptive", sc.mission, plan, sim, WorldModel(sc.world_seed), planner, None, lambda: None, STEP)
        task = asyncio.create_task(agent.run())
        await agent.started.wait()
        await asyncio.sleep(STEP * 1.5)
        sim.apply_truth("order.ORD-7781.status", "picked_up")  # no webhook was ever sent
        await task
        return agent

    agent = asyncio.run(go())
    assert any(r.decision == "precommit-replan" for r in agent.revisions)
    assert agent.sim.refunds == []
