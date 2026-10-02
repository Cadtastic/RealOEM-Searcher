"""update_vehicle_index on the hosted server: single-flight with an hourly cooldown (design 4.8)."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.current_user import call_started_at
from realoem_mcp.errors import CallDeadline
from realoem_mcp.server import build_server
from realoem_mcp.tools import vehicles
from realoem_mcp.tools.vehicles import UPDATE_STATE_KEY, _UpdateState, update_index_shared
from tests.auth_helpers import signed_in
from tests.harness import FakeClock
from tests.shared_env import shared_services
from tests.vehicle_data import SyntheticIndex, numbered
from tests.vehicle_env import install_baseline, settings_for

pytestmark = pytest.mark.anyio


def _index_settings(rows: list):
    def build(tmp_path: Path):
        settings = dataclasses.replace(settings_for(tmp_path), mode="http")
        install_baseline(settings, rows)
        return settings

    return build


async def test_an_up_to_date_index_is_not_checked_again_within_the_hour(tmp_path: Path) -> None:
    rows = numbered(120)
    transport = SyntheticIndex(rows)
    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 5)
            second = await update_index_shared(shared.services, 5)
        assert first.status == "up_to_date"
        assert second.status == "cooldown"
        assert second.requests_made == 0
        assert "refreshed at most once an hour" in second.message
        assert len(transport.requests) == 1


async def test_a_partial_update_can_be_continued_at_once(tmp_path: Path) -> None:
    remote = numbered(300)
    transport = SyntheticIndex(remote)
    settings = _index_settings(remote[:100])
    async with shared_services(tmp_path, transport, settings=settings) as (shared, _):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 3)
            second = await update_index_shared(shared.services, 3)
            third = await update_index_shared(shared.services, 3)
        assert (first.status, second.status, third.status) == ("partial", "updated", "cooldown")


class YieldingIndex(SyntheticIndex):
    """Yields to the event loop on every request, as a real network call would."""

    async def handle_async_request(self, request):
        await asyncio.sleep(0)
        return await super().handle_async_request(request)


async def test_concurrent_callers_share_one_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    transport = YieldingIndex(rows)
    runs: list[int] = []
    real_update = vehicles.update_index

    async def counted(services, max_pages: int):
        runs.append(max_pages)
        return await real_update(services, max_pages)

    monkeypatch.setattr(vehicles, "update_index", counted)

    async def update_as(subject: str):
        with signed_in(subject):
            return await update_index_shared(shared.services, 5)

    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        first, second = await asyncio.gather(update_as("github:1"), update_as("github:2"))
        assert runs == [5]  # one update ran; the second caller waited for it
        assert first.status == second.status == "up_to_date"
        assert (first.requests_made, second.requests_made) == (1, 0)
        assert len(transport.requests) == 1
        assert shared.quota.status("github:1").used_today == 1  # charged to who ran it
        assert shared.quota.status("github:2").used_today == 0


async def test_waiting_for_an_update_stops_at_the_call_deadline(tmp_path: Path) -> None:
    rows = numbered(120)
    clock = FakeClock()
    transport = SyntheticIndex(rows)
    settings = _index_settings(rows)
    async with shared_services(tmp_path, transport, settings=settings, clock=clock) as (shared, _):
        state = shared.services.extras[UPDATE_STATE_KEY] = _UpdateState()
        await state.lock.acquire()  # an update is running
        try:
            for seconds_left in (0.05, -1.0):  # a short wait that times out, then none at all
                deadline = call_started_at.set(clock.now - (50.0 - seconds_left))
                try:
                    async with asyncio.timeout(5):  # a broken deadline fails, never hangs
                        with signed_in("github:2"), pytest.raises(CallDeadline):
                            await update_index_shared(shared.services, 5)
                finally:
                    call_started_at.reset(deadline)
            assert state.checked_at is None  # a deadline error starts no cooldown
            assert transport.requests == []
            deadline = call_started_at.set(clock.now - 10.0)  # 40 s left: it waits its turn
            try:
                with signed_in("github:2"):
                    waiting = asyncio.create_task(update_index_shared(shared.services, 5))
                await asyncio.sleep(0.01)
                assert not waiting.done()
            finally:
                call_started_at.reset(deadline)
        finally:
            state.lock.release()
        assert (await waiting).status == "up_to_date"


async def test_a_deadline_error_starts_no_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    real_update = vehicles.update_index
    calls: list[int] = []

    async def out_of_time_once(services, max_pages: int):
        calls.append(max_pages)
        if len(calls) == 1:
            raise CallDeadline()
        return await real_update(services, max_pages)

    monkeypatch.setattr(vehicles, "update_index", out_of_time_once)
    async with shared_services(tmp_path, SyntheticIndex(rows), settings=_index_settings(rows)) as (
        shared,
        _,
    ):
        with signed_in("github:1"):
            with pytest.raises(CallDeadline):
                await update_index_shared(shared.services, 5)
            again = await update_index_shared(shared.services, 5)
        assert again.status == "up_to_date"  # checked for real, not "cooldown"


async def test_the_cooldown_ends_after_an_hour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    now = [start]
    monkeypatch.setattr(vehicles, "_now", lambda: now[0])
    real_update = vehicles.update_index
    runs: list[datetime] = []

    async def counted(services, max_pages: int):
        runs.append(now[0])
        return await real_update(services, max_pages)

    monkeypatch.setattr(vehicles, "update_index", counted)
    async with shared_services(tmp_path, SyntheticIndex(rows), settings=_index_settings(rows)) as (
        shared,
        _,
    ):
        state = shared.services.extras.setdefault(UPDATE_STATE_KEY, _UpdateState())
        with signed_in("github:1"):
            assert (await update_index_shared(shared.services, 5)).status == "up_to_date"
            now[0] = start + timedelta(minutes=59)
            assert (await update_index_shared(shared.services, 5)).status == "cooldown"
            now[0] = start + timedelta(minutes=61)
            assert (await update_index_shared(shared.services, 5)).status == "up_to_date"
            assert runs == [start, start + timedelta(minutes=61)]  # a real check, not cooldown
            assert state.checked_at == start + timedelta(minutes=61)  # a new hour starts
            now[0] = start + timedelta(minutes=62)
            assert (await update_index_shared(shared.services, 5)).status == "cooldown"


async def test_drift_starts_no_cooldown(tmp_path: Path) -> None:
    local = numbered(120)
    transport = SyntheticIndex(local[:60])  # RealOEM now lists fewer vehicles than the index
    async with shared_services(tmp_path, transport, settings=_index_settings(local)) as (
        shared,
        _,
    ):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 5)
            second = await update_index_shared(shared.services, 5)
        assert first.status == second.status == "drift"


async def test_the_tool_uses_the_shared_update_on_the_hosted_server(tmp_path: Path) -> None:
    rows = numbered(120)
    transport = SyntheticIndex(rows)
    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        async with Client(build_server(shared.services)) as client:
            with signed_in("github:1"):
                first = await client.call_tool("update_vehicle_index", {})
                again = await client.call_tool("update_vehicle_index", {})
        assert first.is_error is False, first.content
        assert again.structured_content["status"] == "cooldown"
