"""World model (belief state) and the assumption monitor.

The monitor indexes assumptions by key, so an event only re-checks the assumptions
that depend on the key it changed. No timers, no re-prompting: change detection is
a lookup plus a predicate.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Any

from app.core.models import BrokenAssumption, Event, Step


class WorldModel:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._beliefs: dict[str, dict[str, Any]] = {}
        for key, value in (initial or {}).items():
            self._beliefs[key] = {"value": value, "source": "seed", "ts": time.time()}

    def get(self, key: str) -> Any:
        entry = self._beliefs.get(key)
        return entry["value"] if entry else None

    def set(self, key: str, value: Any, source: str) -> Any:
        previous = self.get(key)
        self._beliefs[key] = {"value": value, "source": source, "ts": time.time()}
        return previous

    def apply(self, event: Event) -> Any:
        return self.set(event.key, event.value, event.source)

    def snapshot(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in sorted(self._beliefs.items())}


CONSENT_KEY = "customer.consent"
_NO = ["no", "nope", "not", "don't", "dont", "do not", "cancel", "instead", "rather", "prefer", "change", "different",
       "too far", "make it", "can't", "cannot", "won't", "لا", "مو ", "ما ابغى", "ما أبغى", "مابي", "ما يناسب", "بدل", "غير", "ألغ", "الغ"]
_YES = ["yes", "yeah", "yep", "ok", "okay", "sure", "fine", "go ahead", "confirm", "works", "perfect", "sounds good",
        "نعم", "ايوه", "أيوه", "تمام", "موافق", "اوكي", "أوكي", "يناسب", "طيب", "اكد", "أكد", "ماشي"]


_AR_PREFIX = ("ألغ", "الغ", "يناسب", "اكد", "أكد", "موافق")


def _has(words: list[str], t: str) -> bool:
    exact = re.findall(r"[ء-ي]+", t)
    tokens = exact + [tok[1:] for tok in exact if tok.startswith(("و", "ف")) and len(tok) > 3]  # never strip "ولا"
    for w in words:
        w = w.strip()
        if w.isascii():
            if re.search(rf"(?<![a-z']){re.escape(w)}(?![a-z])", t):
                return True
        elif " " in w:
            if w in t:
                return True
        elif w in _AR_PREFIX:
            if any(tok.startswith(w) for tok in tokens):
                return True
        elif w in (exact if w == "لا" else tokens):
            return True
    return False


def classify_reply(text: str) -> str:
    """yes / no / info. Deterministic on purpose: consent must not depend on an LLM's mood."""
    t = f" {str(text).lower().strip()} "
    if t.strip().startswith("(no reply"):
        return "no"
    if _has(_NO, t):
        return "no"
    return "yes" if _has(_YES, t) else "info"


SELF_PREFIXES = ("booking.",)  # state the agent itself produces (holds, confirmations)


def is_self_state(key: str) -> bool:
    return key.startswith(SELF_PREFIXES)


class AssumptionMonitor:
    """Finds assumptions of not-yet-executed steps that the current world contradicts.

    Assumptions about the agent's own state (e.g. "we hold this table") are produced by earlier
    steps of the same plan, so they are only checked at pre-commit (include_self=True), never
    by the event monitor.
    """

    @staticmethod
    def broken(steps: list[Step], world: WorldModel, only_key: str | None = None,
               include_self: bool = False) -> list[BrokenAssumption]:
        found: list[BrokenAssumption] = []
        ask_ahead = False  # a not-yet-sent question will refresh the customer's consent before later steps run
        for step in steps:
            if step.status not in ("pending", "waiting"):
                continue
            for a in step.assumptions:
                if a.key == CONSENT_KEY and ask_ahead:
                    continue
                if only_key is not None and a.key != only_key:
                    continue
                if is_self_state(a.key) and not include_self:
                    continue
                actual = world.get(a.key)
                if a.holds(actual) is False:
                    found.append(BrokenAssumption(step_id=step.id, step_tool=step.tool, assumption=a, actual=actual))
            if step.tool == "ask_customer" and step.status == "pending":
                ask_ahead = True
        return found

    @staticmethod
    def watched_keys(steps: list[Step]) -> set[str]:
        return {a.key for s in steps if s.status in ("pending", "waiting") for a in s.assumptions}


class FlapDetector:
    """Counts value flips per key inside a sliding window."""

    def __init__(self, window_s: float = 30.0, threshold: int = 3) -> None:
        self.window_s = window_s
        self.threshold = threshold
        self._flips: dict[str, deque[float]] = defaultdict(deque)
        self._last: dict[str, Any] = {}

    def record(self, key: str, value: Any, now: float | None = None) -> int:
        now = now or time.time()
        if key in self._last and self._last[key] != value:
            self._flips[key].append(now)
        self._last[key] = value
        q = self._flips[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        return len(q)

    def is_flapping(self, key: str) -> bool:
        return len(self._flips[key]) >= self.threshold
