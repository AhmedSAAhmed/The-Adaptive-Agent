"""Tool registry. Each tool declares:

- its arguments,
- whether it is irreversible (money moved, booking confirmed),
- a *contract*: assumptions that must hold for the call to be safe. Contracts come from the
  tool, not from the LLM, so a planner can never "forget" the precondition of a refund.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.models import Assumption
from app.core.world import WorldModel
from app.sim.systems import SimSystems

CANCELLABLE = ["placed", "preparing"]
REFUNDABLE = ["placed", "preparing", "cancelled"]
DISPATCHED = ["picked_up", "on_the_way", "delivered"]


def add_hours(hhmm: str, hours: int) -> str:
    h, m = (int(x) for x in str(hhmm).split(":"))
    return f"{min(h + hours, 23):02d}:{m:02d}" if h + hours < 24 else "23:59"


def norm_time(value: Any) -> str:
    h, m = (int(x) for x in str(value).strip().split(":")[:2])
    return f"{h:02d}:{m:02d}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]
    run: Callable[[SimSystems, WorldModel, dict[str, Any]], dict[str, Any]]
    irreversible: bool = False
    contract: Callable[[dict[str, Any]], list[Assumption]] = field(default=lambda a: [])
    customer_facing: bool = False


# ---------------------------------------------------------------- orders / refunds
def _lookup_order(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    oid = a["order_id"]
    order = sim.orders.get(oid)
    if not order:
        return {"ok": False, "error": f"order {oid} not found"}
    for k in ("status", "total"):
        world.set(f"order.{oid}.{k}", order[k], "order_api")
    return {"ok": True, "status": order["status"], "total": order["total"], "currency": order["currency"], "items": order["items"]}


def _check_refund_policy(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    status = world.get(f"order.{a['order_id']}.status")
    if status in CANCELLABLE:
        return {"ok": True, "status_seen": status, "eligible": "full_refund", "rule": "Not yet dispatched: cancel and refund in full."}
    if status in ("picked_up", "on_the_way"):
        return {"ok": True, "status_seen": status, "eligible": "voucher", "rule": "Already dispatched: cannot cancel. Offer up to 25% voucher and a live ETA."}
    return {"ok": True, "status_seen": status, "eligible": "complaint", "rule": "Delivered: open a quality complaint, no automatic refund."}


def _cancel_order(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    oid = a["order_id"]
    order = sim.orders[oid]
    # The restaurant API accepts the request asynchronously; it does not know the courier left.
    sim.cancellations.append({"order_id": oid, "ts": time.time(), "true_status_at_cancel": order["status"]})
    if order["status"] in CANCELLABLE:
        order["status"] = "cancelled"
        world.set(f"order.{oid}.status", "cancelled", "order_api")
    return {"ok": True, "accepted": True}


def _issue_refund(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    oid = a["order_id"]
    amount = float(a.get("amount") or sim.orders[oid]["total"])
    sim.refunds.append({"order_id": oid, "amount": amount, "ts": time.time(), "true_status": sim.orders[oid]["status"],
                        "consent": world.get("customer.consent")})
    return {"ok": True, "refunded": amount, "currency": sim.orders[oid]["currency"]}


def _issue_voucher(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    pct = min(int(a.get("percent", 15)), 25)
    code = f"DOO{len(sim.vouchers) + 1:03d}{pct}"
    sim.vouchers.append({"order_id": a["order_id"], "percent": pct, "code": code, "ts": time.time(),
                         "true_status": sim.orders[a["order_id"]]["status"], "consent": world.get("customer.consent")})
    return {"ok": True, "voucher": code, "percent": pct}


# ---------------------------------------------------------------- bookings
def _check_availability(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    b, t = a["branch"], norm_time(a["time"])
    br = sim.branches.get(b)
    if not br:
        return {"ok": False, "error": f"unknown branch {b}"}
    seats = br["slots"].get(t, 0)
    world.set(f"branch.{b}.open_until", br["open_until"], "branch_api")
    world.set(f"branch.{b}.slot.{t}", seats, "branch_api")
    return {"ok": True, "branch": br["name"], "open_until": br["open_until"], "seats_free": seats}


def _hold_table(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    b, t, n = a["branch"], norm_time(a["time"]), int(a["party_size"])
    slots = sim.branches[b]["slots"]
    if slots.get(t, 0) < n:
        return {"ok": False, "error": "not enough seats"}
    slots[t] -= n
    world.set(f"branch.{b}.slot.{t}", slots[t], "branch_api")
    hold = {"hold_id": f"H-{len(sim.holds) + 1}", "branch": b, "time": t, "party_size": n, "active": True}
    sim.holds.append(hold)
    world.set("booking.active_hold", f"{b}@{t}", "agent")
    return {"ok": True, **hold}


def _release_hold(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    b, t = a["branch"], norm_time(a["time"])
    for h in sim.holds:
        if h["active"] and h["branch"] == b and h["time"] == t:
            h["active"] = False
            sim.branches[b]["slots"][t] = sim.branches[b]["slots"].get(t, 0) + h["party_size"]
            world.set("booking.active_hold", None, "agent")
            return {"ok": True, "released": h["hold_id"]}
    return {"ok": True, "released": None}


def _confirm_booking(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    b, t, n = a["branch"], norm_time(a["time"]), int(a["party_size"])
    hold = next((h for h in sim.holds if h["active"] and h["branch"] == b and h["time"] == t), None)
    if hold:
        hold["active"] = False
    world.set("booking.active_hold", None, "agent")
    world.set("booking.confirmed", f"{b}@{t}", "agent")
    ref = f"BK-{len(sim.bookings) + 1:04d}"
    sim.bookings.append({"ref": ref, "branch": b, "time": t, "party_size": n, "true_open_until": sim.branches[b]["open_until"],
                         "had_hold": hold is not None, "consent": world.get("customer.consent")})
    return {"ok": True, "booking_ref": ref, "branch": sim.branches[b]["name"], "time": t}


def _open_long_enough(b: Any, t: str) -> Assumption:
    return Assumption(key=f"branch.{b}.open_until", op="gte", value=add_hours(t, 2), origin="tool_contract",
                      why="The branch must stay open at least 2 hours after the booking starts.")


def _hold_contract(a: dict[str, Any]) -> list[Assumption]:
    b, t, n = a.get("branch"), norm_time(a.get("time", "20:00")), int(a.get("party_size", 1))
    return [_open_long_enough(b, t),
            Assumption(key=f"branch.{b}.slot.{t}", op="gte", value=n, origin="tool_contract",
                       why="The slot must have enough free seats for the party.")]


def _confirm_contract(a: dict[str, Any]) -> list[Assumption]:
    b, t = a.get("branch"), norm_time(a.get("time", "20:00"))
    return [_open_long_enough(b, t),
            Assumption(key="booking.active_hold", op="eq", value=f"{b}@{t}", origin="tool_contract",
                       why="Only confirm seats we are actually holding.")]


# ---------------------------------------------------------------- messaging / people
def _notify_customer(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    msg = sim.send("notify", a.get("message_en", ""), a.get("message_ar", ""))
    return {"ok": True, "channel": "whatsapp", "sent_at": msg["ts"]}


def _ask_customer(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    world.set("customer.reply", None, "agent")
    world.set("customer.consent", None, "agent")
    sim.send("question", a.get("question_en", ""), a.get("question_ar", ""))
    return {"ok": True, "awaiting": "customer.reply"}


def _create_handoff(sim: SimSystems, world: WorldModel, a: dict[str, Any]) -> dict[str, Any]:
    ticket = {"id": f"T-{len(sim.tickets) + 1:03d}", "team": a.get("team", "support"), "reason": a.get("reason", ""), "ts": time.time()}
    sim.tickets.append(ticket)
    return {"ok": True, **ticket}


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec("lookup_order", "Read the order from the order system of record (status, total, items).",
                 {"order_id": "str"}, _lookup_order),
        ToolSpec("check_refund_policy", "Decide what the policy allows for this order given its current status.",
                 {"order_id": "str"}, _check_refund_policy),
        ToolSpec("cancel_order", "Send a cancellation request to the restaurant. Irreversible.",
                 {"order_id": "str"}, _cancel_order, irreversible=True,
                 contract=lambda a: [Assumption(key=f"order.{a.get('order_id')}.status", op="in", value=CANCELLABLE, origin="tool_contract",
                                                why="An order can only be cancelled before the courier picks it up.")]),
        ToolSpec("issue_refund", "Refund money to the customer's card. Irreversible.",
                 {"order_id": "str", "amount": "float"}, _issue_refund, irreversible=True,
                 contract=lambda a: [Assumption(key=f"order.{a.get('order_id')}.status", op="in", value=REFUNDABLE, origin="tool_contract",
                                                why="Refund only food that was never dispatched.")]),
        ToolSpec("issue_voucher", "Give a goodwill voucher (max 25%) when the order can no longer be cancelled.",
                 {"order_id": "str", "percent": "int"}, _issue_voucher,
                 contract=lambda a: [Assumption(key=f"order.{a.get('order_id')}.status", op="in", value=["picked_up", "on_the_way"], origin="tool_contract",
                                                why="The voucher path only applies once the order is already on its way.")]),
        ToolSpec("check_availability", "Check a branch's opening hours and free seats for a time slot.",
                 {"branch": "str", "time": "str", "party_size": "int"}, _check_availability),
        ToolSpec("hold_table", "Place a temporary hold on seats (reversible with release_hold).",
                 {"branch": "str", "time": "str", "party_size": "int"}, _hold_table, contract=_hold_contract),
        ToolSpec("release_hold", "Release a previously held table (compensation step).",
                 {"branch": "str", "time": "str"}, _release_hold),
        ToolSpec("confirm_booking", "Confirm the reservation with the branch. Irreversible promise to the guest.",
                 {"branch": "str", "time": "str", "party_size": "int"}, _confirm_booking, irreversible=True, contract=_confirm_contract),
        ToolSpec("ask_customer", "Ask the customer a question on WhatsApp and wait for the reply.",
                 {"question_en": "str", "question_ar": "str"}, _ask_customer, customer_facing=True),
        ToolSpec("notify_customer", "Send the customer a WhatsApp message (English + Arabic).",
                 {"message_en": "str", "message_ar": "str"}, _notify_customer, customer_facing=True),
        ToolSpec("create_handoff", "Hand the case to a human team (support or ops) with a reason.",
                 {"reason": "str", "team": "str"}, _create_handoff),
    ]
}


CONSENT_TOOLS = {"cancel_order", "issue_refund", "issue_voucher", "confirm_booking"}


def consent_assumption() -> Assumption:
    return Assumption(key="customer.consent", op="ne", value="no", origin="tool_contract",
                      why="Never act against the customer's last answer.")


def catalog_text() -> str:
    lines = []
    for t in TOOLS.values():
        args = ", ".join(f"{k}: {v}" for k, v in t.args.items())
        flag = " [IRREVERSIBLE]" if t.irreversible else ""
        sample = {"order_id": "ORD", "branch": "BR", "time": "20:00", "party_size": 2}
        contract = "; ".join(c.describe().replace("ORD", "{order_id}").replace("BR", "{branch}") for c in t.contract(sample))
        lines.append(f"- {t.name}({args}){flag}: {t.description}" + (f" Contract: {contract}." if contract else ""))
    return "\n".join(lines)
