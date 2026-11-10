"""Simulated business systems a Doo-style agent acts in: orders, payments, branches, WhatsApp.

Each run gets its own copy, so the baseline's refund never leaks into the adaptive run.
`truth()` is the system of record: the second source the guarded agent verifies against.
"""
from __future__ import annotations

import copy
import time
from typing import Any


class SimSystems:
    def __init__(self, seed: dict[str, Any]) -> None:
        data = copy.deepcopy(seed)
        self.orders: dict[str, dict[str, Any]] = data.get("orders", {})
        self.branches: dict[str, dict[str, Any]] = data.get("branches", {})
        self.refunds: list[dict[str, Any]] = []
        self.vouchers: list[dict[str, Any]] = []
        self.cancellations: list[dict[str, Any]] = []
        self.holds: list[dict[str, Any]] = []
        self.bookings: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self.tickets: list[dict[str, Any]] = []

    # ---- system of record -------------------------------------------------
    def truth(self, key: str) -> Any:
        parts = key.split(".")
        try:
            if parts[0] == "order" and len(parts) == 3:
                return self.orders[parts[1]][parts[2]]
            if parts[0] == "branch" and len(parts) == 3:
                return self.branches[parts[1]][parts[2]]
            if parts[0] == "branch" and len(parts) == 4 and parts[2] == "slot":
                return self.branches[parts[1]]["slots"].get(parts[3])
        except KeyError:
            return None
        return None

    def apply_truth(self, key: str, value: Any) -> None:
        """A real-world change (courier picked up, branch closes early) hits the system of record."""
        parts = key.split(".")
        if parts[0] == "order" and len(parts) == 3 and parts[1] in self.orders:
            self.orders[parts[1]][parts[2]] = value
        elif parts[0] == "branch" and len(parts) == 3 and parts[1] in self.branches:
            self.branches[parts[1]][parts[2]] = value
        elif parts[0] == "branch" and len(parts) == 4 and parts[1] in self.branches:
            self.branches[parts[1]]["slots"][parts[3]] = value

    def send(self, kind: str, en: str, ar: str) -> dict[str, Any]:
        msg = {"ts": time.time(), "kind": kind, "en": en, "ar": ar}
        self.outbox.append(msg)
        return msg

    def summary(self) -> dict[str, Any]:
        return {
            "refunds": self.refunds,
            "vouchers": self.vouchers,
            "cancellations": self.cancellations,
            "holds": self.holds,
            "bookings": self.bookings,
            "messages": len(self.outbox),
            "tickets": self.tickets,
        }
