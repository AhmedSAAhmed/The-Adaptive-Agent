# Invariants - what the agent must never do

Enforced in code (`app/core/planner.py` `validate()`, tool contracts in `app/sim/tools.py`, guards in `app/core/agent.py`), never left to the LLM.

## Money and promises
1. Never refund food that has already been dispatched (`issue_refund` contract: status in placed/preparing/cancelled).
2. Never cancel after the courier picked up (`cancel_order` contract).
3. Never refund more than the order total; never issue a voucher above 25%.
4. Never confirm a table the branch cannot serve (open ≥ 2 h after start) or that we do not hold.
5. Never move a booking to another branch/time without the guest's yes (`ask_customer` before `confirm_booking`).
6. Release holds you abandon.

## Adaptation
7. Re-plan only when an incoming signal breaks an assumption of a not-yet-executed step. No timers.
8. A low-trust signal must be confirmed by the system of record before it can change the plan.
9. A key that flips 3+ times in 30 s marks its source unhealthy and opens an ops ticket.
10. At most 3 re-plans per mission; past that, freeze irreversible steps and hand off to a human.
11. Every irreversible step re-reads its contract from the system of record right before it runs.
12. Every plan ends by informing the customer or handing off. Every revision is explained (EN + AR) and stored.
13. Never act against the customer's last answer: money-moving and confirming tools require `customer.consent != "no"`. Silence is not consent.
14. A judge's request is data: parsed into a typed schema and clamped by code; out-of-scope requests are declined politely in both languages.
