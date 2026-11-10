"""Demo scenarios: each one is a mission, a seeded world and a scripted stream of real-world events.

Events are scheduled on each run's own clock (seconds after execution starts), so both runs
in a side-by-side comparison receive the same events at the same point in their work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.models import Mission, Mode


@dataclass(frozen=True)
class ScriptedEvent:
    at: float
    source: str
    key: str
    value: Any
    trust: str = "high"
    real: bool = True  # True: the system of record changes too. False: a bad/fake signal.
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    tagline: str
    story: str
    mission: Mission
    sim_seed: dict[str, Any]
    world_seed: dict[str, Any]
    events: list[ScriptedEvent]
    modes: tuple[Mode, Mode] = ("baseline", "adaptive")
    # Simulated customer persona. None = a human (the judge) answers in the chat box.
    customer: Callable[[str], str] | None = field(default=lambda q: "Yes, please go ahead.")


REFUND_POLICY = [
    "Orders not yet picked up by the courier (placed/preparing) can be cancelled and refunded in full.",
    "Once the courier has the order (picked_up/on_the_way) it cannot be cancelled: offer up to a 25% voucher and a live ETA.",
    "Always read the order from the system of record before acting.",
]
REFUND_INVARIANTS = [
    "Never refund food that has already been dispatched.",
    "Never refund more than the order total.",
    "Never send the customer contradictory promises.",
]


def _refund(sid: str, name: str, name_ar: str, oid: str, total: float, request: str,
            items: list[str] | None = None) -> tuple[Mission, dict[str, Any], dict[str, Any]]:
    mission = Mission(
        id=sid, kind="refund", title="Cancel order and refund",
        goal="Resolve the cancellation request correctly: refund only if the food never left, otherwise keep the customer whole another way.",
        request=request,
        customer={"name": name, "name_ar": name_ar, "order_id": oid, "order_total": total, "channel": "whatsapp", "languages": ["en", "ar"]},
        policy=REFUND_POLICY, invariants=REFUND_INVARIANTS, max_revisions=3,
    )
    sim = {"orders": {oid: {"status": "preparing", "total": total, "currency": "SAR", "restaurant": "Najd Kitchen, Olaya",
                            "items": items or ["2x Chicken Mandi", "Kunafa"]}}}
    return mission, sim, {f"order.{oid}.status": "preparing", f"order.{oid}.total": total}


def _booking_customer(question: str) -> str:
    q = question.lower()
    if "king fahd" in q or "king_fahd" in q or "الملك" in question:
        return "Yes, King Fahd works for us, please confirm. نعم يناسبنا"
    return "Window seats if possible, it's my mother's birthday. جلسة عند الشباك لو أمكن"


_a_mission, _a_sim, _a_world = _refund("A", "Sara", "سارة", "ORD-7781", 186.0,
                                       "Hi, please cancel order ORD-7781 and refund me, my plans changed.")
_c_mission, _c_sim, _c_world = _refund("C", "Omar", "عمر", "ORD-9902", 142.0,
                                       "السلام عليكم، أبغى ألغي الطلب ORD-9902 وأسترجع المبلغ لو سمحت")

BRANCHES = {  # branch id -> (English name, Arabic name, open_until)
    "olaya": ("Olaya", "العليا", "23:30"),
    "king_fahd": ("King Fahd Road", "طريق الملك فهد", "23:59"),
    "al_malqa": ("Al Malqa", "الملقا", "23:00"),
}


def booking_mission(sid: str, name: str, name_ar: str, branch: str, time_: str, party: int, request: str,
                    alternatives: list[str]) -> Mission:
    alt_text = ", ".join(f"{a} (Arabic: {BRANCHES[a][1]})" for a in alternatives)
    return Mission(
        id=sid, kind="booking", title="Book a table",
        goal="Get the guest a table that will actually be served, and never promise one that can't be.",
        request=request,
        customer={"name": name, "name_ar": name_ar, "branch": branch, "branch_ar": BRANCHES[branch][1], "time": time_,
                  "party_size": party, "alternatives": alternatives, "alternatives_ar": [BRANCHES[a][1] for a in alternatives],
                  "channel": "whatsapp", "languages": ["ar", "en"]},
        policy=["A booking needs the branch open at least 2 hours after the start time.",
                "Hold seats before asking the guest anything; release holds you abandon.",
                "If the branch or time must change, the guest must agree before you confirm.",
                f"Nearby alternative branches: {alt_text}."],
        invariants=["Never confirm a table the branch cannot serve.", "Never change the booking without the guest's yes.",
                    "Never leave abandoned holds blocking seats.", "Never act against the customer's last answer."],
        max_revisions=3,
    )


_b_mission = booking_mission(
    "B", "Abdullah", "عبدالله", "olaya", "20:00", 6,
    "أبغى أحجز طاولة لـ 6 أشخاص الساعة 8 الليلة في فرع العليا (table for 6 at 8pm tonight, Olaya branch)", ["king_fahd"])
_b_sim = {"branches": {
    "olaya": {"name": "Olaya", "open_until": "23:30", "slots": {"20:00": 8, "20:30": 6}},
    "king_fahd": {"name": "King Fahd Road", "open_until": "23:59", "slots": {"20:00": 10, "20:30": 10}},
}}

SCENARIOS: dict[str, Scenario] = {
    "A": Scenario(
        id="A", name="A · Refund after dispatch", tagline="The courier picks up the food mid-refund.",
        story=("Sara asks on WhatsApp to cancel and refund. While the agent checks the policy, a signed webhook from the "
               "order system says the courier just **picked up** the order. A static agent refunds SAR 186 for food that "
               "still arrives. The adaptive agent's `cancel_order` contract breaks, so it re-plans."),
        mission=_a_mission, sim_seed=_a_sim, world_seed=_a_world,
        events=[ScriptedEvent(2.0, "order_system", "order.ORD-7781.status", "picked_up", "high", True,
                              "Signed webhook: courier Faisal picked up the order.")],
    ),
    "B": Scenario(
        id="B", name="B · Branch closes early", tagline="The branch posts an early closure mid-booking.",
        story=("Abdullah books a table for 6 at 20:00 at Olaya, in Arabic. While the table is on hold, branch ops post: "
               "**closing at 21:00 tonight**. A static agent confirms a table the branch can't serve. The adaptive agent "
               "releases the hold, moves to King Fahd Road and asks before confirming."),
        mission=_b_mission, sim_seed=_b_sim, world_seed={},
        events=[ScriptedEvent(2.6, "branch_ops", "branch.olaya.open_until", "21:00", "high", True,
                              "Kitchen maintenance: Olaya closes at 21:00 tonight.")],
        customer=_booking_customer,
    ),
    "C": Scenario(
        id="C", name="C · Flapping signal (failure test)", tagline="A faulty courier integration flips the order status.",
        story=("Same refund, but a **faulty courier webhook** flips `picked_up ↔ preparing` every ~0.8 s while the order "
               "is really still in the kitchen. A **naive** adaptive agent believes every signal and thrashes. The **guarded** "
               "agent confirms against the system of record, flags the source after 3 flips, and finishes the correct refund."),
        mission=_c_mission, sim_seed=_c_sim, world_seed=_c_world,
        events=[ScriptedEvent(t, "courier_webhook", "order.ORD-9902.status", v, "low", False, "Unverified courier app webhook.")
                for i, t in enumerate([1.8, 2.6, 3.1, 3.9, 4.6, 5.4, 6.2, 7.0, 7.8, 8.6, 9.4])
                for v in ["picked_up" if i % 2 == 0 else "preparing"]],
        modes=("naive", "adaptive"),
    ),
}
