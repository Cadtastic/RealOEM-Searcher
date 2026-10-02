"""The per-call deadline, the busy queue and the daily limit on the hosted server (design 4.7)."""

from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
import pytest
from mcp import Client

from realoem_mcp import gate
from realoem_mcp.current_user import CallClock
from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded
from realoem_mcp.page_types import PageType
from realoem_mcp.server import build_server
from tests.auth_helpers import signed_in
from tests.harness import FakeClock, FixtureTransport, Route, url
from tests.shared_env import call_tool, shared_services

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
COMPARE_ROUTES = {
    url("partgrp", id=E90, mg="11"): "partgrp/e90_325i_mg11.html",
    url("partgrp", id=R56, mg="11"): "partgrp/r56_cooper_s_mg11.html",
    url("showparts", id=E90, diagId="11_3733"): "showparts/e90_325i_11_3733.html",
    url("showparts", id=R56, diagId="11_3910"): "showparts/r56_cooper_s_11_3910.html",
}
COMPARE = {
    "vehicle_a": E90,
    "vehicle_b": R56,
    "main_group": "11",
    "diag_ids": ["11_3733", "11_3910"],
}


class AfterRequests(FixtureTransport):
    """Runs then() once `count` requests have been answered."""

    def __init__(
        self, routes: Mapping[str, Route | str], count: int, then: Callable[[], None]
    ) -> None:
        super().__init__(routes)
        self._count = count
        self._then = then

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if len(self.requests) == self._count:
            self._then()
        return response


async def test_compare_vehicles_keeps_its_partial_result_at_the_deadline(tmp_path: Path) -> None:
    clock = FakeClock()  # each request after the first waits 2 s, which advances this clock
    async with shared_services(tmp_path, COMPARE_ROUTES, clock=clock, call_deadline_s=3.0) as (
        shared,
        transport,
    ):
        app = build_server(shared.services, middleware=[CallClock(clock)])
        async with Client(app) as client:
            with signed_in("github:1"):
                result = await client.call_tool("compare_vehicles", COMPARE)
                again = await client.call_tool("compare_vehicles", COMPARE)  # a new call
        assert result.is_error is False, result.content
        data = result.structured_content
        # Fetches are admitted at t=0, 0 and 2 s (the 2-second spacing is waited inside the
        # lock); the fourth is refused at admission at t=4, after the 3-second deadline.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            [],
            ["11_3910"],
        )
        assert data["stopped_reason"] == CallDeadline().message
        assert again.structured_content["complete"] is True  # resumed from the cache
        assert len(transport.requests) == 4  # the second call fetched only the missing diagram
        assert shared.quota.status("github:1").used_today == 4  # refused fetches cost nothing


async def test_after_a_full_queue_compare_vehicles_reads_only_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with shared_services(tmp_path, COMPARE_ROUTES) as (shared, transport):
        real_admit = shared.gate.admit
        refused: list[str] = []

        def full_once(subject: str):
            if len(transport.requests) == 2 and not refused:  # A's diagram, after both lists
                refused.append(subject)
                raise Busy()
            return real_admit(subject)

        monkeypatch.setattr(shared.gate, "admit", full_once)
        result = await call_tool(shared.services, "github:1", "compare_vehicles", COMPARE)
        assert result.is_error is False, result.content
        data = result.structured_content
        # B's diagram was not even tried: after Busy the call reads only the cache.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            ["11_3733"],
            ["11_3910"],
        )
        assert data["stopped_reason"] == Busy().message
        assert len(transport.requests) == 2


async def test_compare_vehicles_treats_a_full_queue_like_a_spent_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After the B diagram and both diagram lists are fetched, the queue refuses everything.
    transport = AfterRequests(
        COMPARE_ROUTES, 3, lambda: monkeypatch.setattr(gate, "MAX_PER_SUBJECT", 0)
    )
    async with shared_services(tmp_path, transport) as (shared, _):
        services = shared.services
        with signed_in("github:1"):
            await services.client.fetch(
                PageType.SHOWPARTS, "showparts", {"id": R56, "diagId": "11_3910"}
            )
        result = await call_tool(services, "github:1", "compare_vehicles", COMPARE)
        assert result.is_error is False, result.content
        data = result.structured_content
        # A's diagram hit Busy; B's, after it, was still read from the cache.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            ["11_3733"],
            [],
        )
        assert data["stopped_reason"] == Busy().message
        assert len(transport.requests) == 3


async def test_compare_vehicles_at_the_daily_limit_still_returns_the_cached_diagrams(
    tmp_path: Path,
) -> None:
    async with shared_services(tmp_path, COMPARE_ROUTES, user_daily_limit=3) as (
        shared,
        transport,
    ):
        services = shared.services
        with signed_in("github:1"):  # both lists and A's diagram: the day's 3 requests
            await services.client.fetch(PageType.PARTGRP, "partgrp", {"id": E90, "mg": "11"})
            await services.client.fetch(PageType.PARTGRP, "partgrp", {"id": R56, "mg": "11"})
            await services.client.fetch(
                PageType.SHOWPARTS, "showparts", {"id": E90, "diagId": "11_3733"}
            )
        result = await call_tool(services, "github:1", "compare_vehicles", COMPARE)
        assert result.is_error is False, result.content
        data = result.structured_content
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            [],
            ["11_3910"],
        )
        assert data["only_a"]  # A's cached diagram was compared
        assert data["stopped_reason"] == QuotaExceeded(3).message
        assert len(transport.requests) == 3
        assert shared.quota.status("github:1").used_today == 3


async def test_other_tools_report_the_deadline_as_an_error(tmp_path: Path) -> None:
    clock = FakeClock()
    async with shared_services(tmp_path, {}, clock=clock, call_deadline_s=3.0) as (shared, _):
        started_long_ago = CallClock(lambda: clock.now - 10.0)  # the call began 10 s ago
        app = build_server(shared.services, middleware=[started_long_ago])
        async with Client(app) as client:
            with signed_in("github:1"):
                result = await client.call_tool(
                    "trace_supersession", {"part_number": "11427953129"}
                )
        assert result.is_error is True
        assert result.content[0].text.endswith(
            "This call took too long; call again to continue (pages already fetched are cached)."
        )
