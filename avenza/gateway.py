"""Shared request budget for the Forge platform gateway.

The bank sandbox and Huawei MaaS share one limit: 60 requests a minute per
team (guide §5.1, §7.2). Going over returns 429 for everything, including the
call that moves money. This sliding-window limiter keeps Avenza under the
limit and gives bank calls priority: model calls only run while a reserve of
the budget is left for the bank.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class GatewayBusy(RuntimeError):
    """The minute's budget is spent; the call was not made."""


class GatewayLimiter:
    def __init__(self, per_minute: int = 55, window_s: float = 60.0):
        self.per_minute = max(1, per_minute)
        self.window_s = window_s
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    def _trim(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window_s:
            self._calls.popleft()

    @property
    def remaining(self) -> int:
        self._trim(time.monotonic())
        return self.per_minute - len(self._calls)

    def try_acquire(self, reserve: int = 0) -> bool:
        """Take one slot now if more than ``reserve`` slots stay free."""
        now = time.monotonic()
        self._trim(now)
        if self.per_minute - len(self._calls) > reserve:
            self._calls.append(now)
            return True
        return False

    async def acquire(self, max_wait_s: float = 10.0) -> None:
        """Wait for a slot (bank calls). Raises GatewayBusy after ``max_wait_s``."""
        deadline = time.monotonic() + max_wait_s
        while True:
            async with self._lock:
                if self.try_acquire():
                    return
                now = time.monotonic()
                wait = self.window_s - (now - self._calls[0]) if self._calls else 0.05
            if time.monotonic() + wait > deadline:
                raise GatewayBusy("platform gateway request budget is spent for this minute")
            await asyncio.sleep(min(max(wait, 0.05), 1.0))


_LIMITERS: dict[int, GatewayLimiter] = {}


def gateway_limiter(per_minute: int = 55) -> GatewayLimiter:
    """One limiter per process: every caller shares the team's budget."""
    limiter = _LIMITERS.get(per_minute)
    if limiter is None:
        limiter = _LIMITERS[per_minute] = GatewayLimiter(per_minute)
    return limiter


# Bank calls always get these slots; model calls stop when only these are left.
LLM_RESERVE = 20
