"""Daily quota of RealOEM requests per user, plus an optional server-wide cap (design 4.7).

What is counted: cache-miss page fetches, once per fetch that goes to the network. Cache hits,
retries and redirect hops are free. Days are UTC days.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded
from realoem_mcp.storage_guard import AUTH, Runner, run_directly

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
  subject TEXT NOT NULL, day TEXT NOT NULL, requests INTEGER NOT NULL,
  PRIMARY KEY (subject, day))
"""
EVERYONE = "*"  # the subject of the server-wide row
QUOTA_KEY = "quota"  # services.extras key under which the hosted server keeps its Quota


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QuotaStatus:
    used_today: int
    limit: int  # 0 = unlimited
    resets_at: datetime  # the next 00:00 UTC


class Quota:
    """Counts requests in the `usage` table of the given SQLite connection.

    The connection must be in autocommit mode (isolation_level=None): charge() runs its own
    BEGIN IMMEDIATE ... COMMIT so the check and the increment are one atomic step.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        account_created_at: Callable[[str], datetime | None],
        now: Callable[[], datetime] = _utc_now,
        run: Runner = run_directly,
    ) -> None:
        """account_created_at returns the subject's GitHub account creation time, timezone-aware,
        or None when unknown; an unknown age gets the new-account limit (fail closed). run is
        the hosted server's storage guard: the usage table lives in the auth database."""
        self._conn = conn
        self._settings = settings
        self._account_created_at = account_created_at
        self._now = now
        self._run = run
        conn.execute(USAGE_SCHEMA)

    def _day(self) -> str:
        return self._now().astimezone(UTC).date().isoformat()

    def limit_for(self, subject: str) -> int:
        """The subject's daily limit: lower while its GitHub account is new. 0 = unlimited."""
        created = self._account_created_at(subject)
        young = timedelta(days=self._settings.min_account_age_days)
        if created is None or self._now() - created < young:
            return self._settings.new_user_daily_limit
        return self._settings.user_daily_limit

    def _used(self, subject: str, day: str) -> int:
        row = self._run(
            AUTH,
            lambda: self._conn.execute(
                "SELECT requests FROM usage WHERE subject = ? AND day = ?", (subject, day)
            ).fetchone(),
        )
        return row[0] if row else 0

    def refusal(self, subject: str) -> QuotaExceeded | None:
        """Why a request by subject would be refused right now, without counting anything."""
        day = self._day()
        limit = self.limit_for(subject)
        if limit and self._used(subject, day) >= limit:
            return QuotaExceeded(limit)
        cap = self._settings.global_daily_limit
        if cap and self._used(EVERYONE, day) >= cap:
            return QuotaExceeded(cap, server_wide=True)
        return None

    def charge(self, subject: str) -> None:
        """Count one request, or raise QuotaExceeded and count nothing."""
        day = self._day()
        limit = self.limit_for(subject)
        cap = self._settings.global_daily_limit
        self._run(AUTH, lambda: self._charge(subject, day, limit, cap))

    def _charge(self, subject: str, day: str, limit: int, cap: int) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if not self._bump(subject, day, limit):
                raise QuotaExceeded(limit)
            # The server-wide row is always counted, so the cap can be switched on mid-day.
            if not self._bump(EVERYONE, day, cap):
                raise QuotaExceeded(cap, server_wide=True)
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _bump(self, subject: str, day: str, limit: int) -> bool:
        self._conn.execute(
            "INSERT OR IGNORE INTO usage (subject, day, requests) VALUES (?, ?, 0)", (subject, day)
        )
        cursor = self._conn.execute(
            "UPDATE usage SET requests = requests + 1 "
            "WHERE subject = ? AND day = ? AND (? = 0 OR requests < ?)",
            (subject, day, limit, limit),
        )
        return cursor.rowcount == 1

    def status(self, subject: str) -> QuotaStatus:
        now = self._now().astimezone(UTC)
        midnight = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
        return QuotaStatus(
            used_today=self._used(subject, self._day()),
            limit=self.limit_for(subject),
            resets_at=midnight,
        )

    def used_by_everyone_today(self) -> int:
        return self._used(EVERYONE, self._day())
