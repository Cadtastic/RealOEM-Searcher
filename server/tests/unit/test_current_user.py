"""current_user / require_user and the CallClock middleware (hosted design 4.1)."""

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.current_user import (
    CallClock,
    CurrentUser,
    call_started_at,
    current_user,
    require_user,
    time_left,
)
from realoem_mcp.errors import RealOemError
from tests.auth_helpers import signed_in

SETTINGS = Settings(mode="http", admins=frozenset({"github:1"}))


def test_without_a_token_there_is_no_user() -> None:
    assert current_user(SETTINGS) is None
    with pytest.raises(RealOemError, match="not signed in"):
        require_user(SETTINGS)


def test_the_subject_and_the_admin_flag_come_from_the_token() -> None:
    with signed_in("github:1"):
        assert current_user(SETTINGS) == CurrentUser("github:1", True)
    with signed_in("github:2"):
        assert require_user(SETTINGS) == CurrentUser("github:2", False)
    assert current_user(SETTINGS) is None  # the helper restores the previous state


def test_a_token_without_a_subject_is_not_a_user() -> None:
    with signed_in(None):
        assert current_user(SETTINGS) is None
    with signed_in(""):
        assert current_user(SETTINGS) is None


def test_time_left_counts_down_from_the_start_of_the_call() -> None:
    settings = Settings(mode="http", call_deadline_s=50.0)
    assert time_left(settings, lambda: 100.0) is None  # outside a tool call
    token = call_started_at.set(90.0)
    try:
        assert time_left(settings, lambda: 100.0) == 40.0
        assert time_left(settings, lambda: 150.0) == -10.0
    finally:
        call_started_at.reset(token)


@pytest.mark.anyio
async def test_call_clock_stamps_each_message_and_resets_afterwards() -> None:
    ticks = iter([10.0, 20.0])
    clock = CallClock(lambda: next(ticks))
    seen: list[float | None] = []

    async def call_next(ctx: object) -> str:
        seen.append(call_started_at.get())
        return "result"

    assert await clock(object(), call_next) == "result"  # type: ignore[arg-type]
    await clock(object(), call_next)  # type: ignore[arg-type]
    assert seen == [10.0, 20.0]
    assert call_started_at.get() is None


@pytest.mark.anyio
async def test_call_clock_resets_even_when_the_handler_fails() -> None:
    async def call_next(ctx: object) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await CallClock(lambda: 5.0)(object(), call_next)  # type: ignore[arg-type]
    assert call_started_at.get() is None
