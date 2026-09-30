import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import USER_AGENT, Settings
from realoem_mcp.errors import UpstreamError
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.page_types import PageType
from tests.harness import LANDING_URL, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
GRP_PARAMS = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
GRP = url("partgrp", **GRP_PARAMS)
BAD_PARAMS = {"id": "VB13"}
BAD_ID = url("partgrp", **BAD_PARAMS)


@pytest.fixture
async def make_client(tmp_path: Path):
    made: list[tuple[RealOemClient, PageCache, FixtureTransport]] = []

    def factory(routes):
        transport = FixtureTransport(routes)
        clock = FakeClock()
        cache = PageCache(tmp_path / f"cache{len(made)}")
        client = RealOemClient(
            Settings(cache_dir=tmp_path), cache, transport=transport, clock=clock, sleep=clock.sleep
        )
        made.append((client, cache, transport))
        return client, transport, clock

    yield factory
    for client, cache, transport in made:
        await client.aclose()
        cache.close()
        assert transport.unmatched == []


async def test_sends_honest_headers_and_only_the_ro_ui_cookie(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    (request,) = transport.requests
    assert request.method == "GET"
    assert request.headers["User-Agent"] == USER_AGENT
    assert request.headers["Accept"] == "text/html"
    assert request.headers["Accept-Language"] == "en-US"
    assert request.headers["Cookie"] == "ro_ui=v2"


async def test_server_cookies_are_never_sent_back(make_client) -> None:
    set_cookies = {"Set-Cookie": "ro_ui=v1; Path=/", "X-Other": "1"}
    client, transport, _ = make_client({XREF: Route(headers=set_cookies), GRP: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]


async def test_fetch_returns_page_and_caches_it(make_client) -> None:
    client, transport, _ = make_client({XREF: "common/partgrp_e90_325i.html"})
    first = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    second = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (first.url, first.final_url, first.status) == (XREF, XREF, 200)
    assert first.page_type is PageType.PARTXREF
    assert first.from_cache is False
    assert first.fetched_at.tzinfo is not None
    assert 'rel="canonical"' in first.html
    assert second.from_cache is True
    assert second.html == first.html
    assert len(transport.requests) == 1
    assert client.requests_made == 1


async def test_refresh_bypasses_cache(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert page.from_cache is False
    assert len(transport.requests) == 2


async def test_ttl_override_is_used_when_writing(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, ttl=timedelta(0))
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert len(transport.requests) == 2


async def test_cached_never_touches_the_network(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    hit = client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert hit is not None
    assert hit.from_cache is True
    assert client.cached(PageType.PARTGRP, "partgrp", GRP_PARAMS) is None
    assert len(transport.requests) == 1


async def test_requests_are_spaced_by_min_interval(make_client) -> None:
    client, _, clock = make_client({XREF: Route(), GRP: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    clock.now += 0.5  # half a second of "work" between the two calls
    await client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    assert clock.sleeps == [1.5]


async def test_cache_hits_are_not_rate_limited(make_client) -> None:
    client, _, clock = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert clock.sleeps == []


async def test_concurrent_calls_for_one_url_make_one_request(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    pages = await asyncio.gather(
        *(client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS) for _ in range(3))
    )
    assert len(transport.requests) == 1
    assert sorted(p.from_cache for p in pages) == [False, True, True]


async def test_redirect_to_landing_is_returned_uncached(make_client) -> None:
    client, transport, clock = make_client({BAD_ID: Route(redirect_to=LANDING_URL)})
    page = await client.fetch(PageType.PARTGRP, "partgrp", BAD_PARAMS)
    assert page.redirected_away
    assert (page.url, page.final_url, page.status) == (BAD_ID, LANDING_URL, 200)
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]
    assert clock.sleeps == [2.0]  # the redirect hop is rate limited like any request
    assert client.requests_made == 2
    assert client.cached(PageType.PARTGRP, "partgrp", BAD_PARAMS) is None


async def test_same_host_redirect_loop_is_bounded(make_client) -> None:
    client, transport, clock = make_client({XREF: Route(redirect_to=XREF)})
    with pytest.raises(UpstreamError, match="TooManyRedirects"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert len(transport.requests) == 4  # the request plus MAX_REDIRECTS (3) hops
    assert clock.sleeps == [2.0, 2.0, 2.0]


async def test_https_to_http_downgrade_is_refused(make_client) -> None:
    downgrade = XREF.replace("https://", "http://")
    client, transport, _ = make_client({XREF: Route(redirect_to=downgrade)})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert f"redirected off-site to {downgrade}" in info.value.message
    assert len(transport.requests) == 1
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_undecodable_body_raises_upstream_error(make_client) -> None:
    # Plain HTML labelled as gzip cannot be decoded.
    broken = Route("common/partgrp_e90_325i.html", headers={"Content-Encoding": "gzip"})
    client, _, _ = make_client({XREF: broken})
    with pytest.raises(UpstreamError, match="DecodingError"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)


async def test_redirect_to_another_host_is_refused(make_client) -> None:
    client, transport, _ = make_client({XREF: Route(redirect_to="https://tracker.example/x")})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert "redirected off-site to https://tracker.example/x" in info.value.message
    assert [str(r.url) for r in transport.requests] == [XREF]  # the off-site hop is never sent
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_non_200_raises_upstream_error_and_is_not_cached(make_client) -> None:
    client, _, _ = make_client({XREF: Route(status=404)})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert info.value.status == 404
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_logs_one_info_line_per_network_request(make_client, caplog) -> None:
    client, _, _ = make_client({XREF: Route()})
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    messages = [r.getMessage() for r in caplog.records]
    assert messages[0].startswith(f"partxref {XREF} -> 200 in ")
    assert messages[0].endswith("(cache miss)")
    assert messages[1] == f"partxref {XREF} cache hit"
