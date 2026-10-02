"""RealOemClient in hosted mode: cache owners, the admit/charge hooks, refresh throttle, logs."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded, UpstreamError
from realoem_mcp.http_client import Admission, RealOemClient, masked
from realoem_mcp.page_types import PageType
from tests.harness import LANDING_URL, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
VIN_PARAMS = {"vin": "PX22770"}
VIN = url("select", **VIN_PARAMS)
PRODUCTION = url("production", **VIN_PARAMS)
CASCADE_PARAMS = {"product": "P"}
CASCADE = url("select", **CASCADE_PARAMS)


class Hooks:
    """Records what the client asks of the hosted server's gate, quota and owner hooks."""

    def __init__(self) -> None:
        self.user = "alice"
        self.admission = Admission(wait_s=60.0, deadline_bound=False)
        self.admit_error: Exception | None = None
        self.charge_error: Exception | None = None
        self.entered = 0
        self.exited = 0
        self.charged: list[str] = []

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[Admission]:
        if self.admit_error is not None:
            raise self.admit_error
        self.entered += 1
        try:
            yield self.admission
        finally:
            self.exited += 1

    def charge(self) -> None:
        if self.charge_error is not None:
            raise self.charge_error
        self.charged.append(self.user)

    def owner(self, page_type: PageType, params: Mapping[str, str]) -> str:
        private = page_type is PageType.PRODUCTION or (
            page_type is PageType.SELECT and "vin" in params
        )
        return f"owner-{self.user}" if private else ""


class RecordingTransport(FixtureTransport):
    """Also records how many admissions were open while each request was being sent."""

    def __init__(self, routes: Mapping[str, Route | str], hooks: Hooks) -> None:
        super().__init__(routes)
        self.hooks = hooks
        self.admissions_open: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.admissions_open.append(self.hooks.entered - self.hooks.exited)
        return await super().handle_async_request(request)


class Unreachable(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("RealOEM is unreachable", request=request)


@pytest.fixture
async def hosted(tmp_path: Path):
    """factory(routes, mode=, transport=) -> (client, transport, hooks, cache).

    In http mode the client gets the recording hooks; in stdio mode it gets none, as in stdio.
    """
    made: list[tuple[RealOemClient, PageCache, httpx.AsyncBaseTransport]] = []

    def factory(routes=None, *, mode: str = "http", transport=None):
        clock = FakeClock()
        hooks = Hooks()
        transport = transport or RecordingTransport(routes or {}, hooks)
        cache = PageCache(tmp_path / f"cache{len(made)}")
        hook_args = (
            {"admit": hooks.admit, "charge": hooks.charge, "owner": hooks.owner}
            if mode == "http"
            else {}
        )
        client = RealOemClient(
            Settings(cache_dir=tmp_path, mode=mode),  # type: ignore[arg-type]
            cache,
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
            **hook_args,
        )
        made.append((client, cache, transport))
        return client, transport, hooks, cache

    yield factory
    for client, cache, transport in made:
        await client.aclose()
        cache.close()
        if isinstance(transport, FixtureTransport):
            assert transport.unmatched == []


# --- cache owners ---------------------------------------------------------------------------


async def test_vin_pages_are_cached_per_user_and_other_pages_are_shared(hosted) -> None:
    client, transport, hooks, _ = hosted({VIN: Route(), XREF: Route(), PRODUCTION: Route()})
    first = await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    await client.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (first.owner, first.url) == ("owner-alice", VIN)  # the URL stays the RealOEM URL
    hooks.user = "bob"
    again = await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    shared = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (again.from_cache, again.owner) == (False, "owner-bob")  # bob pays for his own copy
    assert (shared.from_cache, shared.owner) == (True, "")
    assert [str(r.url) for r in transport.requests] == [VIN, PRODUCTION, XREF, VIN]
    assert client.cached(PageType.SELECT, "select", VIN_PARAMS).owner == "owner-bob"
    hooks.user = "carol"
    assert client.cached(PageType.SELECT, "select", VIN_PARAMS) is None
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is not None


async def test_the_model_cascade_on_the_select_page_is_shared(hosted) -> None:
    client, transport, hooks, _ = hosted({CASCADE: Route()})
    await client.fetch(PageType.SELECT, "select", CASCADE_PARAMS)
    hooks.user = "bob"
    page = await client.fetch(PageType.SELECT, "select", CASCADE_PARAMS)
    assert (page.from_cache, page.owner) == (True, "")
    assert len(transport.requests) == 1


async def test_a_users_own_pages_expire_after_30_days_at_most(hosted) -> None:
    other_vin = url("select", vin="AB12345")
    client, _, _, cache = hosted({VIN: Route(), other_vin: Route(), XREF: Route()})
    await client.fetch(PageType.SELECT, "select", VIN_PARAMS, ttl=timedelta(days=180))
    await client.fetch(PageType.SELECT, "select", {"vin": "AB12345"}, ttl=timedelta(days=1))
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    rows = dict(cache._conn.execute("SELECT url, fetched_at || '|' || expires_at FROM pages"))

    def lifetime(page_url: str) -> timedelta:
        fetched, expires = (datetime.fromisoformat(part) for part in rows[page_url].split("|"))
        return expires - fetched

    assert lifetime(VIN) == timedelta(days=30)  # capped
    assert lifetime(other_vin) == timedelta(days=1)  # shorter is kept
    assert lifetime(XREF) == timedelta(days=7)  # shared pages keep their own lifetime


# --- refresh --------------------------------------------------------------------------------


async def test_hosted_refresh_is_ignored_for_a_copy_younger_than_an_hour(hosted) -> None:
    client, transport, _, cache = hosted({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    young = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert young.from_cache is True
    assert len(transport.requests) == 1
    two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="microseconds")
    cache._conn.execute("UPDATE pages SET fetched_at = ?", (two_hours_ago,))
    old = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert old.from_cache is False
    assert len(transport.requests) == 2


async def test_stdio_refresh_always_fetches(hosted) -> None:
    client, transport, _, _ = hosted({XREF: Route()}, mode="stdio")
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert page.from_cache is False
    assert len(transport.requests) == 2


# --- charge ---------------------------------------------------------------------------------


async def test_only_a_network_fetch_is_charged_and_only_once(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route(), VIN: Route(status=503)})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # cache hit: free
    assert hooks.charged == ["alice"]
    with pytest.raises(UpstreamError):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # 503: two retries
    assert len(transport.requests) == 4  # 1 + 3 attempts
    assert hooks.charged == ["alice", "alice"]  # retries are free; the failed fetch still counts


async def test_a_page_fetched_while_waiting_for_the_lock_is_free(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    await client._lock.acquire()  # another fetch is in flight: both calls below wait
    calls = [
        asyncio.create_task(client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS))
        for _ in range(2)
    ]
    for _ in range(3):
        await asyncio.sleep(0)  # both pass the first cache check and queue for the lock
    client._lock.release()
    pages = await asyncio.gather(*calls)
    assert [page.from_cache for page in pages] == [False, True]  # found at the second check
    assert len(transport.requests) == 1
    assert hooks.charged == ["alice"]


async def test_redirect_hops_are_free(hosted) -> None:
    group_params = {"id": "NOT-A-GROUP"}
    group = url("partgrp", **group_params)
    client, transport, hooks, _ = hosted({group: Route(redirect_to=LANDING_URL)})
    page = await client.fetch(PageType.PARTGRP, "partgrp", group_params)
    assert page.redirected_away is True
    assert len(transport.requests) == 2  # the request and the redirect hop
    assert hooks.charged == ["alice"]


async def test_a_refused_charge_sends_nothing_and_releases_the_lock(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    hooks.charge_error = QuotaExceeded(300)
    with pytest.raises(QuotaExceeded):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert transport.requests == []
    assert (hooks.entered, hooks.exited) == (1, 1)
    hooks.charge_error = None
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # lock was released
    assert page.from_cache is False


# --- admit ----------------------------------------------------------------------------------


async def test_the_admission_is_held_until_the_response_arrives(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route(), VIN: Route(status=503)})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    with pytest.raises(UpstreamError):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # 503: retried twice
    assert transport.admissions_open == [1, 1, 1, 1]  # open while every attempt was sent
    assert (hooks.entered, hooks.exited) == (2, 2)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (hooks.entered, hooks.exited) == (2, 2)  # cache hits never queue


async def test_a_refused_admission_sends_nothing(hosted) -> None:
    client, transport, hooks, _ = hosted({})
    hooks.admit_error = QuotaExceeded(300)
    with pytest.raises(QuotaExceeded):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert transport.requests == []
    assert hooks.charged == []


@pytest.mark.parametrize(
    ("deadline_bound", "error"), [(False, Busy), (True, CallDeadline)], ids=["queue", "deadline"]
)
async def test_waiting_too_long_for_a_turn_fails_without_a_charge(
    hosted, deadline_bound: bool, error: type[Exception]
) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    hooks.admission = Admission(wait_s=0.01, deadline_bound=deadline_bound)
    await client._lock.acquire()  # someone else's fetch is in flight
    try:
        async with asyncio.timeout(5):  # a broken time limit fails the test, never hangs it
            with pytest.raises(error):
                await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    finally:
        client._lock.release()
    assert transport.requests == []
    assert hooks.charged == []
    assert (hooks.entered, hooks.exited) == (1, 1)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # the lock is usable
    assert page.from_cache is False


async def test_a_free_lock_is_taken_even_with_no_time_to_wait(hosted) -> None:
    client, _, hooks, _ = hosted({XREF: Route()})
    hooks.admission = Admission(wait_s=0.0, deadline_bound=True)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert page.from_cache is False


# --- logs -----------------------------------------------------------------------------------


def test_masked_hides_every_query_value() -> None:
    assert masked(VIN) == "https://www.realoem.com/bmw/enUS/select?vin=***"
    assert masked("https://x/y?a=1&b=&c=3") == "https://x/y?a=***&b=***&c=***"
    assert masked("https://x/y") == "https://x/y"


async def test_hosted_logs_never_carry_a_vin(hosted, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _, _ = hosted({VIN: Route(), PRODUCTION: Route(), XREF: Route()})
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # the cache-hit line
        await client.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert "PX22770" not in caplog.text
    assert "select?vin=***" in caplog.text
    assert "production?vin=***" in caplog.text
    assert XREF in caplog.text  # other page types are logged in full


async def test_hosted_failure_logs_never_carry_a_vin(
    hosted, caplog: pytest.LogCaptureFixture
) -> None:
    offsite = "https://elsewhere.example/select?vin=PX22770"
    client, _, _, _ = hosted({VIN: Route(redirect_to=offsite)})
    unreachable, _, _, _ = hosted(transport=Unreachable())
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        with pytest.raises(UpstreamError):
            await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # refused off-site hop
        with pytest.raises(UpstreamError):
            await unreachable.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
    assert "PX22770" not in caplog.text
    assert "elsewhere.example/select?vin=***" in caplog.text
    assert "production?vin=*** failed: ConnectError" in caplog.text


async def test_stdio_logs_keep_the_full_url(hosted, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _, _ = hosted({VIN: Route()}, mode="stdio")
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    assert VIN in caplog.text
