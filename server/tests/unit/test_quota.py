"""Quota: per-user daily limits, the new-account limit and the server-wide cap (design 4.7)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded
from realoem_mcp.quota import EVERYONE, Quota

NOON = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        yield connection


def _quota(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    created: dict[str, datetime] | None = None,
    **settings: int,
) -> Quota:
    accounts = created or {}
    return Quota(
        conn,
        Settings(mode="http", **settings),  # type: ignore[arg-type]
        account_created_at=lambda subject: accounts.get(subject, OLD_ACCOUNT),
        now=clock or Clock(),
    )


def test_charges_up_to_the_limit_then_refuses_without_counting(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=2)
    quota.charge("github:1")
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:1")
    assert (refused.value.limit, refused.value.server_wide) == (2, False)
    assert quota.status("github:1").used_today == 2  # the refused attempt is not counted
    quota.charge("github:2")  # other users are unaffected
    assert quota.status("github:2").used_today == 1


def test_refusal_reports_without_counting(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=1)
    assert quota.refusal("github:1") is None
    quota.charge("github:1")
    refusal = quota.refusal("github:1")
    assert isinstance(refusal, QuotaExceeded) and refusal.limit == 1
    assert quota.status("github:1").used_today == 1


def test_a_new_utc_day_starts_from_zero(conn: sqlite3.Connection) -> None:
    clock = Clock(datetime(2026, 10, 2, 23, 59, tzinfo=UTC))
    quota = _quota(conn, clock, user_daily_limit=1)
    quota.charge("github:1")
    status = quota.status("github:1")
    assert (status.used_today, status.resets_at) == (1, datetime(2026, 10, 3, tzinfo=UTC))
    clock.now = datetime(2026, 10, 3, 0, 1, tzinfo=UTC)
    quota.charge("github:1")
    assert quota.status("github:1").used_today == 1


def test_young_github_accounts_get_the_new_user_limit(conn: sqlite3.Connection) -> None:
    created = {"github:new": NOON - timedelta(days=29), "github:old": NOON - timedelta(days=30)}
    quota = _quota(conn, created=created, user_daily_limit=300, new_user_daily_limit=1)
    assert (quota.limit_for("github:new"), quota.limit_for("github:old")) == (1, 300)
    quota.charge("github:new")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:new")
    assert refused.value.limit == 1


def test_an_unknown_account_age_gets_the_new_account_limit(conn: sqlite3.Connection) -> None:
    quota = Quota(
        conn,
        Settings(mode="http", user_daily_limit=5, new_user_daily_limit=1),
        account_created_at=lambda subject: None,
        now=Clock(),
    )
    assert quota.limit_for("github:1") == 1  # fail closed


def test_zero_means_unlimited(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=0)
    for _ in range(50):
        quota.charge("github:1")
    status = quota.status("github:1")
    assert (status.used_today, status.limit) == (50, 0)


def test_the_server_wide_cap_refuses_everyone_and_rolls_back_the_users_count(
    conn: sqlite3.Connection,
) -> None:
    quota = _quota(conn, user_daily_limit=10, global_daily_limit=2)
    quota.charge("github:1")
    quota.charge("github:2")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:3")
    assert (refused.value.limit, refused.value.server_wide) == (2, True)
    assert quota.status("github:3").used_today == 0  # rolled back with the global row
    assert quota.used_by_everyone_today() == 2
    refusal = quota.refusal("github:1")
    assert refusal is not None and (refusal.limit, refusal.server_wide) == (2, True)


def test_everyone_is_counted_while_the_cap_is_off(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, global_daily_limit=0)
    quota.charge("github:1")
    quota.charge("github:2")
    assert quota.used_by_everyone_today() == 2  # ready if the cap is switched on mid-day
    row = conn.execute("SELECT requests FROM usage WHERE subject = ?", (EVERYONE,)).fetchone()
    assert row == (2,)


def test_charge_leaves_no_transaction_open_after_a_refusal(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded):
        quota.charge("github:1")
    assert conn.in_transaction is False
