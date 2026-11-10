"""Ground-truth auditor: judges a finished run against the system of record, not against the agent's beliefs.

This is what makes silent failures visible: the baseline's plan "succeeds", the audit says it lost money.
"""
from __future__ import annotations

from typing import Any

from app.core.models import Mission
from app.sim.systems import SimSystems
from app.sim.tools import CANCELLABLE, add_hours


def audit(mission: Mission, sim: SimSystems, revisions: int, llm_calls: int) -> dict[str, Any]:
    details: list[str] = []
    verdict, headline = "success", ""
    messages = sim.outbox
    metrics = {"customer_messages": len(messages), "revisions": revisions, "llm_calls": llm_calls, "tickets": len(sim.tickets)}

    if mission.kind == "refund":
        oid = mission.customer["order_id"]
        order = sim.orders[oid]
        refunded = sum(r["amount"] for r in sim.refunds)
        bad_refunds = [r for r in sim.refunds if r["true_status"] not in CANCELLABLE + ["cancelled"]]
        bad_cancels = [c for c in sim.cancellations if c["true_status_at_cancel"] not in CANCELLABLE]
        metrics.update({"refunded": refunded, "vouchers": len(sim.vouchers)})
        if bad_refunds or bad_cancels:
            loss = sum(r["amount"] for r in bad_refunds)
            verdict = "silent_failure"
            headline = f"Refunded {order['currency']} {loss:.0f} for food already on its way. The plan reported success."
            details.append(f"True order status: {order['status']}. Cancellation sent after dispatch; the courier still delivers.")
        elif sim.tickets and not sim.refunds and not sim.vouchers:
            verdict = "escalated"
            headline = "Escalated to a human with full context. No money moved on uncertain data."
        elif order["status"] == "cancelled" and refunded == 0:
            verdict = "failure"
            headline = "Cancelled the order but never refunded it: the customer paid for food they will not get."
        elif sim.refunds and sim.vouchers:
            verdict = "degraded"
            headline = f"Double compensation: refunded {order['currency']} {refunded:.0f} AND issued a voucher for the same order."
        elif order["status"] == "cancelled" and refunded > 0:
            headline = f"Cancelled before dispatch and refunded {order['currency']} {refunded:.0f}. Correct."
        elif order["status"] in ("picked_up", "on_the_way") and sim.vouchers and not sim.refunds:
            headline = f"Order already dispatched: no refund, {sim.vouchers[-1]['percent']}% voucher + ETA. Correct per policy."
        elif sim.vouchers and order["status"] in CANCELLABLE:
            verdict = "failure"
            headline = "Believed a false 'picked up' signal: the customer was denied a cancellation they were entitled to."
        else:
            verdict = "failure"
            headline = "Request not resolved."
        if len(sim.vouchers) > 1:
            details.append(f"{len(sim.vouchers)} vouchers issued for one order.")
    else:
        req = mission.customer
        valid = [bk for bk in sim.bookings if bk["true_open_until"] >= add_hours(bk["time"], 2)]
        invalid = [bk for bk in sim.bookings if bk not in valid]
        dangling = [h for h in sim.holds if h["active"]]
        metrics.update({"bookings": len(sim.bookings), "dangling_holds": len(dangling)})
        if invalid:
            bk = invalid[0]
            verdict = "silent_failure"
            headline = f"Confirmed {bk['time']} at a branch that closes at {bk['true_open_until']}. {req['party_size']} guests will be turned away."
        elif valid:
            bk = valid[0]
            moved = bk["branch"] != req["branch"]
            headline = f"Booked {bk['time']} at {bk['branch'].replace('_', ' ').title()}" + (" (customer agreed to the move)." if moved else ".")
        elif sim.tickets:
            verdict = "escalated"
            headline = "Escalated to a human; no unsafe confirmation was sent."
        else:
            verdict = "failure"
            headline = "No booking made."
        if dangling:
            details.append(f"{len(dangling)} table hold(s) left active (seats blocked for other guests).")

    notifies = [m for m in messages if m["kind"] == "notify"]
    if len(notifies) >= 2 and mission.kind == "refund":
        details.append(f"{len(notifies)} different outcome messages sent to the customer: they saw the agent change its story.")
        if verdict == "success":
            verdict = "degraded"
    elif len(messages) >= 4:
        details.append(f"{len(messages)} WhatsApp messages sent: the customer saw the agent change its story repeatedly.")
        if verdict == "success":
            verdict = "degraded"
    return {"verdict": verdict, "headline": headline, "details": details, "metrics": metrics}
