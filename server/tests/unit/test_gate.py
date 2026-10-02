"""FetchGate: who may queue for RealOEM, and for how long (design 4.7)."""

import sqlite3
from collections.abc import Iterator
from contextlib import AsyncExitStack, closing
from datetime import UTC, datetime

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.current_user import call_started_at
from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded
from realoem_mcp.gate import MAX_OVERALL, MAX_PER_SUBJECT, MAX_WAIT_S, FetchGate
from realoem_mcp.http_client import Admission
from realoem_mcp.quota import Quota

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        yield connection


def _gate(conn: sqlite3.Connection, clock: Clock, **settings: float) -> tuple[FetchGate, Quota]:
    config = Settings(mode="http", **settings)  # type: ignore[arg-type]
    quota = Quota(
        conn,
        config,
        account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),  # established
        now=lambda: datetime(2026, 10, 2, tzinfo=UTC),
    )
    return FetchGate(config, quota, clock=clock), quota


def test_the_limits_are_the_designed_ones() -> None:
    assert (MAX_PER_SUBJECT, MAX_OVERALL, MAX_WAIT_S) == (4, 20, 60.0)


async def test_outside_a_tool_call_the_wait_is_the_queue_limit(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with gate.admit("github:1") as admission:
        assert admission == Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
        assert gate.waiting_or_in_flight == 1
    assert gate.waiting_or_in_flight == 0


async def test_the_call_deadline_shortens_the_wait(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=50.0)
    token = call_started_at.set(clock.now - 20.0)  # the call started 20 s ago
    try:
        async with gate.admit("github:1") as admission:
            assert admission == Admission(wait_s=30.0, deadline_bound=True)
    finally:
        call_started_at.reset(token)


async def test_a_distant_deadline_leaves_the_queue_limit(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=120.0)
    token = call_started_at.set(clock.now - 10.0)  # 110 s left
    try:
        async with gate.admit("github:1") as admission:
            assert admission == Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
    finally:
        call_started_at.reset(token)


async def test_a_failure_inside_the_admission_releases_it(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    with pytest.raises(Busy):
        async with gate.admit("github:1"):
            raise Busy()  # as the client's timed wait for the lock does
    assert gate.waiting_or_in_flight == 0


async def test_a_call_past_its_deadline_is_refused(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=50.0)
    token = call_started_at.set(clock.now - 51.0)
    try:
        with pytest.raises(CallDeadline):
            async with gate.admit("github:1"):
                pass
    finally:
        call_started_at.reset(token)
    assert gate.waiting_or_in_flight == 0


async def test_a_user_already_at_the_limit_never_queues(conn: sqlite3.Connection) -> None:
    gate, quota = _gate(conn, Clock(), user_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded):
        async with gate.admit("github:1"):
            pass
    assert gate.waiting_or_in_flight == 0


async def test_nobody_queues_once_the_server_wide_cap_is_reached(
    conn: sqlite3.Connection,
) -> None:
    gate, quota = _gate(conn, Clock(), global_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded) as refused:
        async with gate.admit("github:2"):
            pass
    assert refused.value.server_wide is True


async def test_each_user_may_have_only_a_few_fetches_waiting(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with AsyncExitStack() as stack:
        for _ in range(MAX_PER_SUBJECT):
            await stack.enter_async_context(gate.admit("github:1"))
        with pytest.raises(Busy):
            async with gate.admit("github:1"):
                pass
        assert gate.waiting_or_in_flight == MAX_PER_SUBJECT  # the refusal counted nothing
        async with gate.admit("github:2"):  # another user still gets in
            pass
    async with gate.admit("github:1"):  # released on exit
        pass


async def test_everyone_together_may_have_only_twenty_waiting(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with AsyncExitStack() as stack:
        for user in range(MAX_OVERALL):
            await stack.enter_async_context(gate.admit(f"github:{user}"))
        with pytest.raises(Busy):
            async with gate.admit("github:999"):
                pass
    assert gate.waiting_or_in_flight == 0
