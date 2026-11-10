"""Event-sourced persistence (Postgres in production, SQLite locally) via SQLAlchemy Core.

Append-only tables: every event, plan version, revision, step transition and LLM call is kept,
so any run can be audited or exported as a plain-text trace after the fact.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, create_engine, desc, insert, select,
                        update)
from sqlalchemy.engine import Engine

from app.config import settings

log = logging.getLogger(__name__)
meta = MetaData()

sessions = Table("sessions", meta,
                 Column("id", String(40), primary_key=True), Column("scenario", String(40)), Column("status", String(20)),
                 Column("created_at", Float), Column("finished_at", Float, nullable=True), Column("summary", Text, nullable=True))
runs = Table("runs", meta,
             Column("id", String(40), primary_key=True), Column("session_id", String(40), index=True), Column("mode", String(20)),
             Column("status", String(20)), Column("created_at", Float), Column("finished_at", Float, nullable=True),
             Column("outcome", Text, nullable=True))
events = Table("events", meta,
               Column("seq", Integer, primary_key=True, autoincrement=True), Column("id", String(40)),
               Column("run_id", String(40), index=True), Column("ts", Float), Column("source", String(60)), Column("key", String(120)),
               Column("value", Text), Column("trust", String(10)), Column("handled_as", String(30)), Column("note", Text))
plans = Table("plans", meta,
              Column("seq", Integer, primary_key=True, autoincrement=True), Column("run_id", String(40), index=True),
              Column("version", Integer), Column("created_by", String(120)), Column("rationale", Text), Column("steps", Text),
              Column("created_at", Float))
revisions = Table("revisions", meta,
                  Column("id", String(40), primary_key=True), Column("run_id", String(40), index=True), Column("ts", Float),
                  Column("decision", String(30)), Column("trigger", Text), Column("broken", Text), Column("from_version", Integer),
                  Column("to_version", Integer), Column("reason_en", Text), Column("reason_ar", Text), Column("planner", String(120)))
step_log = Table("step_log", meta,
                 Column("seq", Integer, primary_key=True, autoincrement=True), Column("run_id", String(40), index=True),
                 Column("ts", Float), Column("plan_version", Integer), Column("step_id", String(40)), Column("tool", String(60)),
                 Column("status", String(20)), Column("args", Text), Column("result", Text))
llm_calls = Table("llm_calls", meta,
                  Column("seq", Integer, primary_key=True, autoincrement=True), Column("run_id", String(40), index=True),
                  Column("ts", Float), Column("provider", String(40)), Column("model", String(120)), Column("purpose", String(60)),
                  Column("ok", Integer), Column("latency_ms", Integer), Column("tokens_in", Integer, nullable=True),
                  Column("tokens_out", Integer, nullable=True), Column("error", Text, nullable=True))


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class Store:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.database_url
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        self.engine: Engine = create_engine(self.url, **kwargs)
        meta.create_all(self.engine)

    @property
    def backend(self) -> str:
        return self.engine.dialect.name

    def _write(self, stmt: Any) -> None:
        try:
            with self.engine.begin() as conn:
                conn.execute(stmt)
        except Exception:  # noqa: BLE001 - persistence must never crash the agent loop
            log.exception("store write failed")

    # ---- writes ---------------------------------------------------------
    def session_started(self, sid: str, scenario: str) -> None:
        self._write(insert(sessions).values(id=sid, scenario=scenario, status="running", created_at=time.time()))

    def session_finished(self, sid: str, summary: dict[str, Any]) -> None:
        self._write(update(sessions).where(sessions.c.id == sid).values(status="finished", finished_at=time.time(), summary=_j(summary)))

    def run_started(self, rid: str, sid: str, mode: str) -> None:
        self._write(insert(runs).values(id=rid, session_id=sid, mode=mode, status="running", created_at=time.time()))

    def run_finished(self, rid: str, status: str, outcome: dict[str, Any]) -> None:
        self._write(update(runs).where(runs.c.id == rid).values(status=status, finished_at=time.time(), outcome=_j(outcome)))

    def event(self, rid: str, ev: Any) -> None:
        self._write(insert(events).values(id=ev.id, run_id=rid, ts=ev.ts, source=ev.source, key=ev.key, value=_j(ev.value),
                                          trust=ev.trust, handled_as=ev.handled_as, note=ev.note))

    def plan(self, rid: str, plan: Any) -> None:
        self._write(insert(plans).values(run_id=rid, version=plan.version, created_by=plan.created_by, rationale=plan.rationale,
                                         steps=_j([s.model_dump() for s in plan.steps]), created_at=time.time()))

    def revision(self, rid: str, rv: Any) -> None:
        self._write(insert(revisions).values(id=rv.id, run_id=rid, ts=rv.ts, decision=rv.decision, trigger=rv.trigger,
                                             broken=_j([b.model_dump() for b in rv.broken]), from_version=rv.from_version,
                                             to_version=rv.to_version, reason_en=rv.reason_en, reason_ar=rv.reason_ar, planner=rv.planner))

    def step(self, rid: str, version: int, step: Any) -> None:
        self._write(insert(step_log).values(run_id=rid, ts=time.time(), plan_version=version, step_id=step.id, tool=step.tool,
                                            status=step.status, args=_j(step.args), result=_j(step.result)))

    def llm_call(self, rid: str, rec: dict[str, Any]) -> None:
        self._write(insert(llm_calls).values(run_id=rid, ts=time.time(), provider=rec.get("provider"), model=rec.get("model"),
                                             purpose=rec.get("purpose"), ok=int(bool(rec.get("ok"))), latency_ms=rec.get("latency_ms"),
                                             tokens_in=rec.get("tokens_in"), tokens_out=rec.get("tokens_out"), error=rec.get("error")))

    # ---- reads ----------------------------------------------------------
    def recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(sessions).order_by(desc(sessions.c.created_at)).limit(limit)).mappings().all()
            out = []
            for r in rows:
                rr = conn.execute(select(runs).where(runs.c.session_id == r["id"])).mappings().all()
                out.append({**dict(r), "summary": json.loads(r["summary"]) if r["summary"] else None,
                            "runs": [{**dict(x), "outcome": json.loads(x["outcome"]) if x["outcome"] else None} for x in rr]})
            return out

    def run_trace(self, rid: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            run = conn.execute(select(runs).where(runs.c.id == rid)).mappings().first()
            if not run:
                return {}
            q = lambda t, order: conn.execute(select(t).where(t.c.run_id == rid).order_by(order)).mappings().all()  # noqa: E731
            return {
                "run": dict(run),
                "events": [dict(r) for r in q(events, events.c.seq)],
                "plans": [dict(r) for r in q(plans, plans.c.seq)],
                "revisions": [dict(r) for r in q(revisions, revisions.c.ts)],
                "steps": [dict(r) for r in q(step_log, step_log.c.seq)],
                "llm_calls": [dict(r) for r in q(llm_calls, llm_calls.c.seq)],
            }


def trace_markdown(trace: dict[str, Any]) -> str:
    if not trace:
        return "# Run not found\n"
    run = trace["run"]
    out = [f"# Run {run['id']} ({run['mode']})", "", f"Status: {run['status']}", ""]
    if run.get("outcome"):
        o = json.loads(run["outcome"])
        out += [f"Outcome: **{o.get('verdict')}**: {o.get('headline')}", ""]
    out += ["## Plans", ""]
    for p in trace["plans"]:
        out.append(f"### v{p['version']} by {p['created_by']}")
        out.append(p["rationale"] or "")
        for i, s in enumerate(json.loads(p["steps"]), 1):
            out.append(f"{i}. `{s['tool']}` {json.dumps(s['args'], ensure_ascii=False)}")
        out.append("")
    out += ["## I changed my mind because...", ""]
    for r in trace["revisions"]:
        out.append(f"- **{r['decision']}** (v{r['from_version']} -> v{r['to_version']}, {r['planner']}): {r['reason_en']}")
        if r["reason_ar"]:
            out.append(f"  - {r['reason_ar']}")
    out += ["", "## Events", ""]
    for e in trace["events"]:
        out.append(f"- {e['source']} `{e['key']}` = {e['value']} (trust {e['trust']}) -> {e['handled_as']}")
    out += ["", "## LLM calls", ""]
    for c in trace["llm_calls"]:
        out.append(f"- {c['purpose']}: {c['provider']}/{c['model']} ok={c['ok']} {c['latency_ms']} ms {c['error'] or ''}")
    return "\n".join(out) + "\n"
