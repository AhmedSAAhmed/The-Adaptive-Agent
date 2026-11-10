"""A session runs one scenario as two agents side by side on the same event stream."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.core.agent import Agent
from app.core.models import Event, Plan, new_id
from app.core.planner import Planner
from app.core.world import WorldModel
from app.scenarios import SCENARIOS, Scenario
from app.sim.systems import SimSystems
from app.store.db import Store

log = logging.getLogger(__name__)


class Session:
    def __init__(self, scenario: Scenario, planner: Planner, store: Store | None, step_seconds: float,
                 llm_records: list[dict[str, Any]] | None = None) -> None:
        self.pre_llm_records = list(llm_records or [])  # e.g. the request-parsing call of a custom run
        self.id = new_id("ss")
        self.scenario = scenario
        self.planner, self.store, self.step_seconds = planner, store, step_seconds
        self.agents: dict[str, Agent] = {}
        self.status = "planning"
        self.created = time.time()
        self.initial_plan: Plan | None = None
        self.version = 0
        self._changed = asyncio.Event()
        self._subscribers: list[asyncio.Queue[int]] = []
        self.task: asyncio.Task[None] | None = None

    # ---- change notification (event-driven UI / SSE) ----------------------
    def notify(self) -> None:
        self.version += 1
        self._changed.set()
        for q in list(self._subscribers):
            q.put_nowait(self.version)

    async def wait_change(self, timeout: float = 1.0) -> None:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        self._changed.clear()

    def subscribe(self) -> asyncio.Queue[int]:
        q: asyncio.Queue[int] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[int]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    @property
    def finished(self) -> bool:
        return self.status == "finished"

    # ---- lifecycle --------------------------------------------------------
    async def run(self) -> None:
        sc = self.scenario
        if self.store:
            self.store.session_started(self.id, sc.id if sc.id in SCENARIOS else "custom")
        self.notify()
        llm_records: list[dict[str, Any]] = list(self.pre_llm_records)  # skipped (circuit-open) attempts are logged, not counted
        plan = await self.planner.initial_plan(sc.mission, WorldModel(sc.world_seed), llm_records.append)
        self.initial_plan = plan
        for mode in sc.modes:
            rid = new_id("run")
            if self.store:
                self.store.run_started(rid, self.id, mode)
                for rec in llm_records:
                    self.store.llm_call(rid, rec)
            agent = Agent(rid, mode, sc.mission, plan.model_copy(deep=True), SimSystems(sc.sim_seed), WorldModel(sc.world_seed),
                          self.planner, self.store, self.notify, self.step_seconds, sc.customer)
            agent.llm_calls = sum(1 for r in llm_records if not str(r.get("error") or "").startswith("skipped"))
            self.agents[mode] = agent
        self.status = "running"
        self.notify()
        tasks = [asyncio.create_task(a.run()) for a in self.agents.values()]
        players = [asyncio.create_task(self._play(a)) for a in self.agents.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        for p in players:
            p.cancel()
        self.status = "finished"
        if self.store:
            self.store.session_finished(self.id, {m: a.outcome for m, a in self.agents.items()})
        self.notify()

    async def _play(self, agent: Agent) -> None:
        """Deliver the scenario's real-world events to one agent on its own clock."""
        await agent.started.wait()
        scale = self.step_seconds / 1.6  # scenario times are authored for 1.6 s steps
        for se in self.scenario.events:
            delay = se.at * scale - (time.monotonic() - agent.t0)
            if delay > 0:
                await asyncio.sleep(delay)
            if agent.finished:
                return
            if se.real:
                agent.sim.apply_truth(se.key, se.value)
            await agent.publish(Event(source=se.source, key=se.key, value=se.value, trust=se.trust, note=se.note))  # type: ignore[arg-type]

    async def reply(self, text: str) -> int:
        """The human customer answers on WhatsApp: goes to agents waiting for an answer (else to all running)."""
        running = [a for a in self.agents.values() if not a.finished]
        targets = [a for a in running if a.waiting_for_customer] or running
        for a in targets:
            await a.publish(Event(source="whatsapp", key="customer.reply", value=text[:300], note="customer (you) replied"))
        return len(targets)

    async def inject(self, event: Event, real: bool = True) -> int:
        """External webhook event: fan out to every agent still running."""
        n = 0
        for agent in self.agents.values():
            if agent.finished:
                continue
            if real and event.trust == "high":
                agent.sim.apply_truth(event.key, event.value)
            await agent.publish(event)
            n += 1
        return n


class SessionManager:
    def __init__(self, store: Store | None, planner: Planner | None = None, max_running: int = 4) -> None:
        self.store = store
        self.planner = planner or Planner()
        self.max_running = max_running
        self.sessions: dict[str, Session] = {}

    def running(self) -> list[Session]:
        return [s for s in self.sessions.values() if not s.finished]

    def start(self, scenario_id: str, step_seconds: float | None = None) -> Session:
        if scenario_id not in SCENARIOS:
            raise KeyError(scenario_id)
        return self.start_scenario(SCENARIOS[scenario_id], step_seconds)

    def start_scenario(self, scenario: Scenario, step_seconds: float | None = None,
                       llm_records: list[dict[str, Any]] | None = None) -> Session:
        if len(self.running()) >= self.max_running:
            raise RuntimeError("Too many demos running right now, please retry in a few seconds.")
        s = Session(scenario, self.planner, self.store, step_seconds or settings.step_seconds, llm_records)
        self.sessions[s.id] = s
        s.task = asyncio.create_task(s.run())
        # keep memory bounded on a 512 MB instance
        if len(self.sessions) > 30:
            for sid in [k for k, v in self.sessions.items() if v.finished][:10]:
                self.sessions.pop(sid, None)
        return s

    def latest_running(self) -> Session | None:
        live = self.running()
        return max(live, key=lambda s: s.created) if live else None
