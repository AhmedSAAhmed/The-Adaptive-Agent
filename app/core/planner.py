"""Planner: LLM proposes, code disposes.

1. The LLM drafts (or re-drafts) the plan from the tool catalog, policy and current beliefs.
2. `validate()` rebuilds every step from the tool registry: unknown tools/args are rejected,
   tool contracts are attached by code, and mission invariants are enforced.
3. If the LLM is unavailable or its plan is invalid, a deterministic planner produces a safe plan.

Detection of change is never delegated to the LLM. The LLM only decides *what to do next*.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.models import Assumption, BrokenAssumption, Event, Mission, Plan, Step
from app.core.world import AssumptionMonitor, WorldModel
from app.llm.client import LLMClient, Observer
from app.sim.tools import CANCELLABLE, TOOLS, catalog_text, norm_time

log = logging.getLogger(__name__)

SYSTEM = """You are the planning module of a production customer-service ACTION agent built on DOO \
(AI customer service on WhatsApp for brands in Saudi Arabia and the GCC). You do not chat; you output a plan of tool calls.

Rules:
- Output ONE JSON object only, no prose, no markdown fences.
- Use only the tools listed. Use exact argument names. Times are "HH:MM" 24h.
- Respect the business policy and invariants exactly. Never plan an irreversible tool whose contract is already false.
- Every customer-facing message must be given in English AND Arabic (Gulf-friendly, polite, short, WhatsApp tone).
- At most 7 steps. Do not repeat steps that are already completed.
- A plan must carry the case to its resolution: never end on ask_customer. After a question, plan the action that follows assuming the customer agrees (the agent re-plans if they refuse), and END with notify_customer (or create_handoff).
- Keep text short: descriptions under 15 words, messages under 45 words.
- For each step you may add extra "assumptions": beliefs about the world (key/op/value) that, if they change, \
should make the agent reconsider. Use world keys you have been shown. ops: eq, ne, in, not_in, gte, lte.

Tools:
{catalog}
"""

PLAN_SCHEMA = """Return JSON: {"rationale": str, "steps": [{"tool": str, "args": {...}, "description": str, \
"assumptions": [{"key": str, "op": str, "value": any, "why": str}]}]}"""

REPLAN_SCHEMA = """Return JSON: {"reason_en": "I changed my mind because ... (one or two sentences, concrete: what changed, \
which assumption broke, what you will do instead)", "reason_ar": "<same reason in Arabic>", "rationale": str, \
"steps": [<remaining steps only, same shape as before>]}"""


class PlanError(ValueError):
    pass


class Planner:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    # ------------------------------------------------------------------ public
    async def initial_plan(self, mission: Mission, world: WorldModel, observer: Observer | None = None) -> Plan:
        user = "\n".join([
            _mission_block(mission),
            f"Current beliefs: {json.dumps(world.snapshot(), ensure_ascii=False)}",
            "Draft the plan from the very first step (start by reading the record of truth).",
            PLAN_SCHEMA,
        ])
        res = await self.llm.complete_json(SYSTEM.format(catalog=catalog_text()), user, "initial_plan", observer)
        if res:
            try:
                steps = validate(res.data.get("steps", []), mission, world, completed=[])
                return Plan(version=1, steps=steps, rationale=str(res.data.get("rationale", "")), created_by=f"{res.provider}:{res.model}")
            except PlanError as exc:
                log.warning("LLM initial plan rejected: %s", exc)
        return Plan(version=1, steps=fallback_initial(mission), rationale="Deterministic plan (LLM unavailable or rejected).")

    async def replan(self, mission: Mission, world: WorldModel, plan: Plan, broken: list[BrokenAssumption],
                     trigger: Event | None, observer: Observer | None = None) -> tuple[list[Step], str, str, str, str]:
        """Returns (new remaining steps, rationale, reason_en, reason_ar, created_by)."""
        completed = [s for s in plan.steps if s.status == "done"]
        user = "\n".join([
            _mission_block(mission),
            "Completed steps (already executed, do NOT repeat): " + json.dumps(
                [{"tool": s.tool, "args": s.args, "result": s.result} for s in completed], ensure_ascii=False, default=str),
            "Steps that were still planned: " + json.dumps([{"tool": s.tool, "args": s.args} for s in plan.remaining()], ensure_ascii=False),
            f"What changed: {_trigger_text(trigger)}",
            "Broken assumptions: " + json.dumps(
                [{"step": b.step_tool, "assumption": b.assumption.describe(), "why": b.assumption.why, "actual": b.actual} for b in broken],
                ensure_ascii=False, default=str),
            f"Current beliefs: {json.dumps(world.snapshot(), ensure_ascii=False, default=str)}",
            "Re-plan the remaining work so the mission still succeeds safely. If you abandon a held table, release it first. "
            "If the customer must accept a change to what they asked for, ask them before confirming.",
            REPLAN_SCHEMA,
        ])
        res = await self.llm.complete_json(SYSTEM.format(catalog=catalog_text()), user, "replan", observer)
        if res:
            try:
                steps = validate(res.data.get("steps", []), mission, world, completed=completed)
                return (steps, str(res.data.get("rationale", "")), str(res.data.get("reason_en", "")).strip(),
                        str(res.data.get("reason_ar", "")).strip(), f"{res.provider}:{res.model}")
            except PlanError as exc:
                log.warning("LLM replan rejected by validator: %s", exc)
        steps, en, ar = fallback_replan(mission, world, completed, broken)
        return steps, "Deterministic re-plan (LLM unavailable or its plan failed validation).", en, ar, "deterministic"


# ---------------------------------------------------------------------- validation
def build_step(tool: str, args: dict[str, Any], description: str = "", extra: list[dict[str, Any]] | None = None) -> Step:
    spec = TOOLS.get(tool)
    if spec is None:
        raise PlanError(f"unknown tool {tool!r}")
    clean: dict[str, Any] = {}
    for name, typ in spec.args.items():
        if name not in args or args[name] in (None, ""):
            if name in ("amount", "percent", "team"):
                continue  # optional, tool has a default
            raise PlanError(f"{tool}: missing arg {name}")
        v = args[name]
        try:
            clean[name] = int(v) if typ == "int" else float(v) if typ == "float" else str(v)
        except (TypeError, ValueError) as exc:
            raise PlanError(f"{tool}: bad {name}={v!r}") from exc
    if "time" in clean:
        clean["time"] = norm_time(clean["time"])
    assumptions = list(spec.contract(clean))
    seen = {(x.key, x.op, json.dumps(x.value, sort_keys=True, default=str)) for x in assumptions}
    for a in extra or []:
        try:
            sig = (str(a["key"]), a["op"], json.dumps(a["value"], sort_keys=True, default=str))
            if sig in seen:
                continue  # the tool contract already guarantees this one
            seen.add(sig)
            assumptions.append(Assumption(key=str(a["key"]), op=a["op"], value=a["value"], why=str(a.get("why", "")), origin="planner"))
        except Exception:  # noqa: BLE001 - a malformed soft assumption is dropped, not fatal
            continue
    return Step(tool=tool, args=clean, description=description or spec.description, assumptions=assumptions,
                irreversible=spec.irreversible)


def validate(raw_steps: list[dict[str, Any]], mission: Mission, world: WorldModel, completed: list[Step]) -> list[Step]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanError("empty plan")
    if len(raw_steps) > 8:
        raise PlanError("plan too long")
    steps = [build_step(str(r.get("tool")), dict(r.get("args") or {}), str(r.get("description", "")), r.get("assumptions"))
             for r in raw_steps]
    if steps[-1].tool not in ("notify_customer", "create_handoff"):
        raise PlanError("plan must end by informing the customer (notify_customer) or handing off (create_handoff)")
    done_irreversible = {(s.tool, json.dumps(s.args, sort_keys=True)) for s in completed if s.irreversible}
    asked = False
    for s in steps:
        if (s.tool, json.dumps(s.args, sort_keys=True)) in done_irreversible:
            raise PlanError(f"repeats completed irreversible step {s.tool}")
        if s.tool == "issue_refund":
            total = world.get(f"order.{s.args['order_id']}.total") or mission.customer.get("order_total", 0)
            if s.args.get("amount", total) > total:
                raise PlanError("invariant: refund exceeds order total")
        if s.tool == "issue_voucher" and s.args.get("percent", 0) > 25:
            raise PlanError("invariant: voucher above 25%")
        if s.tool == "ask_customer":
            asked = True
        if s.tool == "confirm_booking":
            changed = s.args["branch"] != mission.customer.get("branch") or s.args["time"] != mission.customer.get("time")
            if changed and not asked:
                raise PlanError("invariant: booking differs from the request and the customer was not asked")
        if s.irreversible:
            broken = [b for b in AssumptionMonitor.broken([s], world) if b.assumption.origin == "tool_contract"]
            if broken:
                raise PlanError(f"{s.tool} contract already false: {broken[0].assumption.describe()} (actual {broken[0].actual!r})")
    return steps


# ---------------------------------------------------------------------- deterministic planner
def fallback_initial(mission: Mission) -> list[Step]:
    c = mission.customer
    if mission.kind == "refund":
        oid = c["order_id"]
        return [
            build_step("lookup_order", {"order_id": oid}),
            build_step("check_refund_policy", {"order_id": oid}),
            build_step("cancel_order", {"order_id": oid}),
            build_step("issue_refund", {"order_id": oid, "amount": c["order_total"]}),
            build_step("notify_customer", {
                "message_en": f"Hi {c['name']}, your order {oid} is cancelled and SAR {c['order_total']:.0f} is refunded to your card.",
                "message_ar": f"مرحباً {c['name_ar']}، تم إلغاء طلبك {oid} واسترداد {c['order_total']:.0f} ريال إلى بطاقتك.",
            }),
        ]
    b, t, n = c["branch"], c["time"], c["party_size"]
    return [
        build_step("check_availability", {"branch": b, "time": t, "party_size": n}),
        build_step("hold_table", {"branch": b, "time": t, "party_size": n}),
        build_step("ask_customer", {"question_en": "Any seating preference or occasion we should know about?",
                                    "question_ar": "هل لديكم تفضيل للجلسة أو مناسبة خاصة نعرفها؟"}),
        build_step("confirm_booking", {"branch": b, "time": t, "party_size": n}),
        build_step("notify_customer", {"message_en": f"Your table for {n} at {t} is confirmed. See you soon!",
                                       "message_ar": f"تم تأكيد طاولتكم لـ {n} أشخاص الساعة {t}. بانتظاركم!"}),
    ]


def fallback_replan(mission: Mission, world: WorldModel, completed: list[Step],
                    broken: list[BrokenAssumption]) -> tuple[list[Step], str, str]:
    c = mission.customer
    what = "; ".join(f"{b.assumption.describe()} is no longer true (now {b.actual!r})" for b in broken) or "the world changed"
    if mission.kind == "refund":
        oid = c["order_id"]
        status = world.get(f"order.{oid}.status")
        if status in CANCELLABLE + ["cancelled"]:
            steps = [s for s in fallback_initial(mission) if s.tool in ("cancel_order", "issue_refund", "notify_customer")]
            if status == "cancelled":
                steps = [s for s in steps if s.tool != "cancel_order"]
            en = (f"I changed my mind because {what}. The latest order status is {status!r}, so it can still be "
                  "cancelled: going back to cancel-and-refund.")
            ar = "غيّرت الخطة لأن حالة الطلب تغيّرت، وما زال بالإمكان إلغاؤه، لذلك سأعود إلى الإلغاء والاسترداد."
            return steps, en, ar
        steps = [
            build_step("issue_voucher", {"order_id": oid, "percent": 15}),
            build_step("notify_customer", {
                "message_en": f"Hi {c['name']}, your order already left the restaurant, so it can't be cancelled. "
                              "Here is a 15% voucher for the trouble; your courier is on the way.",
                "message_ar": f"مرحباً {c['name_ar']}، طلبك خرج من المطعم ولا يمكن إلغاؤه الآن. "
                              "أرسلنا لك قسيمة خصم 15% تقديراً لك، والمندوب في الطريق إليك.",
            }),
        ]
        en = (f"I changed my mind because {what}. The latest order status is {status!r}: the courier already has the food, "
              "so cancelling and refunding would pay for food that still arrives. Offering a voucher and ETA instead.")
        ar = "غيّرت رأيي لأن المندوب استلم الطلب بالفعل، والاسترداد الآن يعني دفع ثمن طعام سيصل. سأقدّم قسيمة خصم وموعد الوصول بدلاً من ذلك."
        return steps, en, ar
    # booking: move to the first alternative branch that is open long enough
    b, t, n = c["branch"], c["time"], c["party_size"]
    alt = c["alternatives"][0]
    steps = []
    if world.get("booking.active_hold") == f"{b}@{t}":
        steps.append(build_step("release_hold", {"branch": b, "time": t}))
    steps += [
        build_step("check_availability", {"branch": alt, "time": t, "party_size": n}),
        build_step("hold_table", {"branch": alt, "time": t, "party_size": n}),
        build_step("ask_customer", {
            "question_en": f"Sorry, {b.replace('_', ' ').title()} closes early tonight. We're holding a table for {n} at {t} at {alt.replace('_', ' ').title()} instead. Shall I confirm it?",
            "question_ar": f"نعتذر، فرع {c['branch_ar']} سيغلق مبكراً الليلة. حجزنا لكم مبدئياً طاولة لـ {n} أشخاص الساعة {t} في فرع {c['alternatives_ar'][0]}. هل أؤكد الحجز؟",
        }),
        build_step("confirm_booking", {"branch": alt, "time": t, "party_size": n}),
        build_step("notify_customer", {"message_en": f"Confirmed: table for {n} at {t}, {alt.replace('_', ' ').title()} branch.",
                                       "message_ar": f"تم التأكيد: طاولة لـ {n} أشخاص الساعة {t} في فرع {c['alternatives_ar'][0]}."}),
    ]
    en = f"I changed my mind because {what}. Confirming would promise a table the branch can't serve, so I'm moving the booking (with the customer's OK)."
    ar = "غيّرت الخطة لأن الفرع سيغلق مبكراً، وتأكيد الحجز يعني وعداً لا يمكن الوفاء به، لذلك سأنقل الحجز لفرع آخر بعد موافقة العميل."
    return steps, en, ar


# ---------------------------------------------------------------------- prompt helpers
def _mission_block(m: Mission) -> str:
    return "\n".join([
        f"Mission: {m.title}. Goal: {m.goal}",
        f"Customer request (on WhatsApp): {m.request}",
        f"Customer context: {json.dumps(m.customer, ensure_ascii=False)}",
        "Business policy:\n- " + "\n- ".join(m.policy),
        "Invariants (never break):\n- " + "\n- ".join(m.invariants),
    ])


def _trigger_text(ev: Event | None) -> str:
    if ev is None:
        return "Pre-commit re-check against the system of record failed."
    return f"event from {ev.source} (trust {ev.trust}): {ev.key} = {ev.value!r}. {ev.note}"
