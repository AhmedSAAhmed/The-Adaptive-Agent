"""Small in-memory sliding-window rate limiter (single instance on the free tier)."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimited(Exception):
    pass


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window_s = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, who: str) -> None:
        now, q = time.time(), self.hits[who]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            wait = int(self.window_s - (now - q[0])) + 1
            raise RateLimited(f"Rate limit reached: please try again in {wait} s.")
        q.append(now)


# Shared by the UI and the API: a custom run costs LLM calls (parse + plan + re-plans).
custom_runs = RateLimiter(limit=6, window_s=600)
