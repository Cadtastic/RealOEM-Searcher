"""Queue admission for cache-miss fetches on the hosted server (design 4.7).

Every fetch that has to go to RealOEM waits for the one request lock. The gate decides, before
the wait, whether the fetch may queue at all and for how long: never past the day's quota or the
server-wide cap, never past the tool call's deadline, and only while the queue is short.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from realoem_mcp.config import Settings
from realoem_mcp.current_user import time_left
from realoem_mcp.errors import Busy, CallDeadline
from realoem_mcp.http_client import Admission
from realoem_mcp.quota import Quota

MAX_PER_SUBJECT = 4  # waiting-or-in-flight cache-miss fetches of one user
MAX_OVERALL = 20  # the same, for everyone together
MAX_WAIT_S = 60.0  # longest wait for a turn
GATE_KEY = "gate"  # services.extras key under which the hosted server keeps its FetchGate


class FetchGate:
    def __init__(
        self, settings: Settings, quota: Quota, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._settings = settings
        self._quota = quota
        self._clock = clock  # the same clock CallClock stamps call_started_at with
        self._active: Counter[str] = Counter()

    @property
    def waiting_or_in_flight(self) -> int:
        return sum(self._active.values())

    def time_left(self) -> float | None:
        """Seconds until the current tool call's deadline; None outside a tool call."""
        return time_left(self._settings, self._clock)

    @asynccontextmanager
    async def admit(self, subject: str) -> AsyncIterator[Admission]:
        """Admit one cache-miss fetch by subject, or raise without counting anything.

        Raises QuotaExceeded (the user is already at the day's limit, or the server-wide cap is
        reached), CallDeadline (the tool call is out of time) or Busy (too many fetches are
        already waiting). The counters are released when the context exits, however it exits.
        """
        if (refusal := self._quota.refusal(subject)) is not None:
            raise refusal
        left = self.time_left()
        if left is not None and left <= 0:
            raise CallDeadline()
        if self._active[subject] >= MAX_PER_SUBJECT or self.waiting_or_in_flight >= MAX_OVERALL:
            raise Busy()
        self._active[subject] += 1
        try:
            if left is not None and left < MAX_WAIT_S:
                yield Admission(wait_s=left, deadline_bound=True)
            else:
                yield Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
        finally:
            self._active[subject] -= 1
            if not self._active[subject]:
                del self._active[subject]
