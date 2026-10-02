"""Sliding-window rate limits, kept in memory (one server process; hosted design 4.9)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

SWEEP_EVERY = 1_000  # records between sweeps of idle keys


class SlidingWindow:
    """At most `limit` events per `window_s` seconds for each key."""

    def __init__(
        self, limit: int, window_s: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._records = 0

    def retry_after(self, key: str) -> float | None:
        """None when one more event is allowed now; else seconds until one is. Records nothing."""
        now = self._clock()
        events = self._events.get(key)
        if events is None:
            return None
        while events and events[0] <= now - self._window_s:
            events.popleft()
        if not events:
            del self._events[key]  # nothing recent: forget the key
            return None
        if len(events) < self._limit:
            return None
        return events[0] + self._window_s - now

    def record(self, key: str) -> None:
        now = self._clock()
        self._events.setdefault(key, deque()).append(now)
        self._records += 1
        if self._records % SWEEP_EVERY == 0:  # forget keys with no recent events
            cutoff = now - self._window_s
            for idle in [
                k for k, events in self._events.items() if not events or events[-1] <= cutoff
            ]:
                del self._events[idle]
