"""The plan -> execute -> observe -> re-evaluate loop.

Modes (same planner, same tools, same event stream, so the comparison is fair):
- baseline: executes the plan as written; events are not observed.
- naive:    observes and re-plans on every contradiction, trusting every signal (no guards).
- adaptive: observes, and re-plans only through the guards:
            1. confirm low-trust signals against the system of record before believing them,
            2. flap detection: a key that flips repeatedly marks its source unhealthy and alerts ops,
            3. revision budget: past N revisions, freeze irreversible steps and escalate to a human,
            4. pre-commit re-check: every irreversible step re-reads its contract from the system of record,
            5. validated plans: LLM plans are rebuilt and checked against tool contracts + invariants.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from app.core.models import BrokenAssumption, Event, Mission, Mode, Plan, Revision, Step
from app.core.planner import Planner, build_step
from app.core.world import AssumptionMonitor, FlapDetector, WorldModel
from app.sim.audit import audit
from app.sim.systems import SimSystems
from app.sim.tools import TOOLS
from app.store.db import Store

log = logging.getLogger(__name__)
NAIVE_HARD_CAP = 6  # even the naive agent needs a circuit breaker so the demo terminates


class Agent:
    def __init__(self, run_id: str, mode: Mode, mission: Mission, plan: Plan, sim: SimSystems, world: WorldModel,
                 planner: Planner, store: Store | None, on_change: Callable[[], None], step_seconds: float,
                 customer: Callable[[str], str] | None = None) -> None:
        self.run_id, self.mode, self.mission = run_id, mode, mission
        self.plan = plan
        self.plans: list[Plan] = [plan.model_copy(deep=True)]
        self.sim, self.world, self.planner, self.store = sim, world, planner, store
        self.on_change, self.step_seconds = on_change, step_seconds
        self.customer = customer or (lambda question: "Yes, please go ahead.")
        self.inbox: asyncio.Queue[Event] = asyncio.Queue()
        self.events: list[Event] = []
        self.revisions: list[Revision] = []
        self.flaps = FlapDetector(window_s=30, threshold=3)
        self.unhealthy_sources: set[str] = set()
        self.pending: tuple[Event | None, list[BrokenAssumption], str] | None = None
        self.status = "ready"
        self.frozen = False
        self.llm_calls = 0
        self.outcome: dict[str, Any] | None = None
        self.started = asyncio.Event()
        self.t0 = 0.0
        self.t0_wall = time.time()
        self._wake = asyncio.Event()
        self._finished = False

    # ------------------------------------------------------------------ helpers
    def _changed(self) -> None:
        try:
            self.on_change()
        except Exception:  # noqa: BLE001
            log.exception("on_change failed")

    async def _llm_observer(self, rec: dict[str, Any]) -> None:
        if not str(rec.get("error") or "").startswith("skipped"):
            self.llm_calls += 1
        if self.store:
            self.store.llm_call(self.run_id, rec)

    def _record(self, rv: Revision) -> None:
        self.revisions.append(rv)
        if self.store:
            self.store.revision(self.run_id, rv)
        self._changed()

    @property
    def finished(self) -> bool:
        return self._finished

    async def publish(self, event: Event) -> None:
        await self.inbox.put(event.model_copy(deep=True))

    # ------------------------------------------------------------------ observe
    async def _consume(self) -> None:
        while True:
            ev = await self.inbox.get()
            try:
                self._on_event(ev)
            except Exception:  # noqa: BLE001
                log.exception("event handling failed")
            if self.store:
                self.store.event(self.run_id, ev)
            self.events.append(ev)
            self._changed()

    def _on_event(self, ev: Event) -> None:
        if ev.key == "customer.reply":
            self.world.apply(ev)
            ev.handled_as = "applied"
            self._wake.set()
            return
        if self._finished:
            ev.handled_as = "after-finish"
            return
        if self.mode == "baseline":
            ev.handled_as = "not observed"
            return

        if self.mode == "adaptive":
            flips = self.flaps.record(ev.key, ev.value)
            if ev.trust == "low" or ev.source in self.unhealthy_sources:
                truth = self.sim.truth(ev.key)  # confirm with a second, authoritative source
                if truth is not None and truth != ev.value:
                    ev.handled_as = "unconfirmed"
                    self.world.set(ev.key, truth, "system_of_record")
                    self._record(Revision(
                        trigger_event_id=ev.id, trigger=f"{ev.source}: {ev.key}={ev.value!r}", decision="ignore",
                        from_version=self.plan.version, to_version=self.plan.version, planner="guard:confirm",
                        reason_en=(f"I did NOT change my mind: {ev.source} says {ev.key} = {ev.value!r}, but the system of record "
                                   f"says {truth!r}. A low-trust signal must be confirmed before it can change the plan."),
                        reason_ar=f"لم أغيّر الخطة: الإشارة من {ev.source} غير مؤكدة، والنظام الأساسي يقول إن القيمة {truth!r}.",
                    ))
                    if flips >= self.flaps.threshold and ev.source not in self.unhealthy_sources:
                        self.unhealthy_sources.add(ev.source)
                        self.sim.tickets.append({"id": f"T-{len(self.sim.tickets) + 1:03d}", "team": "ops", "ts": time.time(),
                                                 "reason": f"{ev.source} is flapping on {ev.key} ({flips} flips in 30s)"})
                        self._record(Revision(
                            trigger_event_id=ev.id, trigger=f"{flips} flips on {ev.key}", decision="hold",
                            from_version=self.plan.version, to_version=self.plan.version, planner="guard:flap-detector",
                            reason_en=(f"{ev.source} flipped {ev.key} {flips} times in 30 s. I marked the source unhealthy, opened an "
                                       "ops ticket, and will keep trusting only the system of record for this key."),
                            reason_ar=f"المصدر {ev.source} يتذبذب ({flips} مرات خلال 30 ثانية). تم تعليمه كمصدر غير موثوق وإبلاغ فريق العمليات.",
                        ))
                    return
                if truth is not None:
                    ev.note = (ev.note + " Confirmed by system of record.").strip()

        self.world.apply(ev)
        ev.handled_as = "applied"
        broken = AssumptionMonitor.broken(self.plan.remaining(), self.world, only_key=ev.key)
        if broken:
            ev.handled_as = "contradiction"
            self.pending = (ev, broken, "event")
            self._wake.set()

    # ------------------------------------------------------------------ re-evaluate
    async def _revise(self) -> None:
        assert self.pending is not None
        ev, broken, kind = self.pending
        self.pending = None
        n = sum(1 for r in self.revisions if r.decision in ("replan", "precommit-replan"))
        budget = self.mission.max_revisions if self.mode == "adaptive" else NAIVE_HARD_CAP
        if n >= budget:
            await self._escalate(ev, broken, f"revision budget of {budget} reached")
            return
        self.status = "re-planning"
        self._changed()
        steps, rationale, en, ar, by = await self.planner.replan(self.mission, self.world, self.plan, broken, ev, self._llm_observer)
        for s in self.plan.remaining():
            s.status = "skipped"
        done = [s for s in self.plan.steps if s.status != "skipped"]
        new = Plan(version=self.plan.version + 1, steps=done + steps, rationale=rationale, created_by=by)
        self._record(Revision(
            trigger_event_id=ev.id if ev else None,
            trigger=f"{ev.source}: {ev.key}={ev.value!r}" if ev else "pre-commit re-check",
            decision="replan" if kind == "event" else "precommit-replan", broken=broken,
            from_version=self.plan.version, to_version=new.version, planner=by,
            reason_en=en or f"I changed my mind because {broken[0].assumption.describe()} no longer holds.", reason_ar=ar,
        ))
        self.plan = new
        self.plans.append(new.model_copy(deep=True))
        if self.store:
            self.store.plan(self.run_id, new)
        # Events may have arrived while we were thinking: re-check the fresh plan against the latest world.
        again = AssumptionMonitor.broken(self.plan.remaining(), self.world)
        if again and self.pending is None:
            self.pending = (self.events[-1] if self.events else None, again, "event")
        self.status = "executing"
        self._changed()

    async def _escalate(self, ev: Event | None, broken: list[BrokenAssumption], why: str) -> None:
        self.frozen = True
        for s in self.plan.remaining():
            s.status = "skipped"
        handoff = build_step("create_handoff", {"team": "support", "reason": f"Agent escalated: {why}. Last trigger: "
                                                + (f"{ev.key}={ev.value!r}" if ev else "pre-commit check")})
        new = Plan(version=self.plan.version + 1, steps=[s for s in self.plan.steps if s.status == "done"] + [handoff],
                   rationale="Escalation: hand off to a human, freeze irreversible actions.", created_by="guard:budget")
        self._record(Revision(
            trigger_event_id=ev.id if ev else None, trigger=why, decision="escalate", broken=broken,
            from_version=self.plan.version, to_version=new.version, planner="guard:budget",
            reason_en=f"I stopped adapting because the {why}. Irreversible steps are frozen and a human takes over with the full trace.",
            reason_ar="توقفت عن تعديل الخطة لأن حد المراجعات تم تجاوزه. تم تجميد الإجراءات غير القابلة للتراجع وتحويل الحالة لموظف.",
        ))
        self.plan = new
        self.plans.append(new.model_copy(deep=True))
        if self.store:
            self.store.plan(self.run_id, new)

    # ------------------------------------------------------------------ execute
    def _next_step(self) -> Step | None:
        return next((s for s in self.plan.steps if s.status == "pending"), None)

    async def _wait_reply(self, timeout: float = 25.0) -> bool:
        deadline = time.monotonic() + timeout
        while self.world.get("customer.reply") is None:
            if self.pending is not None:
                return False  # a contradiction arrived while waiting: re-evaluate first
            self._wake.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return False
        return True

    async def _simulate_customer(self) -> None:
        await asyncio.sleep(self.step_seconds * 0.9)
        last = next((m for m in reversed(self.sim.outbox) if m["kind"] == "question"), {"en": "", "ar": ""})
        reply = self.customer(f"{last['en']} {last['ar']}")
        await self.publish(Event(source="whatsapp", key="customer.reply", value=reply, note="customer replied"))

    async def run(self) -> None:
        if self.store:
            self.store.plan(self.run_id, self.plan)
        consumer = asyncio.create_task(self._consume())
        self.status = "executing"
        self.t0 = time.monotonic()
        self.t0_wall = time.time()
        self.started.set()
        self._changed()
        try:
            await self._loop()
        except Exception as exc:  # noqa: BLE001
            log.exception("agent crashed")
            self.status = f"crashed: {type(exc).__name__}"
        finally:
            self._finished = True
            await asyncio.sleep(0)  # let queued events drain into the trace
            consumer.cancel()
            reps = sum(1 for r in self.revisions if r.decision in ("replan", "precommit-replan"))
            self.outcome = audit(self.mission, self.sim, reps, self.llm_calls)
            if not self.status.startswith("crashed"):
                self.status = "escalated" if self.frozen else "done"
            if self.store:
                self.store.run_finished(self.run_id, self.status, self.outcome)
            self._changed()

    async def _loop(self) -> None:
        while True:
            if self.pending is not None and self.mode != "baseline":
                await self._revise()
                continue
            step = self._next_step()
            if step is None:
                return
            if self.frozen and step.irreversible:
                step.status = "blocked"
                continue
            if self.mode == "adaptive" and step.irreversible:
                for a in step.assumptions:  # pre-commit: re-read the contract from the system of record
                    truth = self.sim.truth(a.key)
                    if truth is not None:
                        self.world.set(a.key, truth, "system_of_record")
                broken = AssumptionMonitor.broken([step], self.world, include_self=True)
                if broken:
                    self.pending = (None, broken, "precommit")
                    continue
            step.status = "running"
            self._changed()
            await asyncio.sleep(self.step_seconds)  # the API call is in flight; the world keeps moving
            spec = TOOLS[step.tool]
            step.result = spec.run(self.sim, self.world, step.args)
            if step.result.get("awaiting"):
                step.status = "waiting"
                self._changed()
                asyncio.create_task(self._simulate_customer())
                got = await self._wait_reply()
                if not got and self.pending is not None:
                    step.status = "done"
                    step.result = {**step.result, "reply": None, "interrupted": True}
                    continue
                step.result = {**step.result, "reply": self.world.get("customer.reply")}
            step.status = "done" if step.result.get("ok", True) else "failed"
            if self.store:
                self.store.step(self.run_id, self.plan.version, step)
            self._changed()
