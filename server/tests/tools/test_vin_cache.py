"""VIN hits stay cached 180 days, misses only 1 day (ARD section 5.4)."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import url

pytestmark = pytest.mark.anyio

HIT = url("select", vin="PX22770")
MISS = url("select", vin="ZZZZZZZ")
ROUTES = {HIT: "select/vin_bmw_e93_px22770.html", MISS: "select/vin_miss_zzzzzzz.html"}


def cache_lifetime(services: Services, page_url: str) -> timedelta:
    """expires_at - fetched_at of a cached page, read straight from the SQLite cache file."""
    with closing(sqlite3.connect(services.cache.path)) as conn:
        fetched_at, expires_at = conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (page_url,)
        ).fetchone()
    return datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at)


async def _call(client: Client, **arguments: object) -> dict:
    result = await client.call_tool("decode_vin", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def test_hit_is_cached_for_180_days(make_services) -> None:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="PX22770")
    assert cache_lifetime(services, HIT) == timedelta(days=180)


async def test_miss_is_cached_for_1_day(make_services) -> None:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="ZZZZZZZ")
    assert cache_lifetime(services, MISS) == timedelta(days=1)


async def test_repeat_and_full_vin_are_answered_from_the_cache(make_services) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        first = await _call(client, vin="PX22770")
        again = await _call(client, vin="WBA0000000PX22770")
        miss_first = await _call(client, vin="ZZZZZZZ")
        miss_again = await _call(client, vin="zzzzzzz")
    assert (first["from_cache"], first["requests_made"]) == (False, 1)
    assert (again["from_cache"], again["requests_made"]) == (True, 0)
    assert again["vehicle"] == first["vehicle"]
    assert (miss_first["requests_made"], miss_again["requests_made"]) == (1, 0)
    assert miss_again["status"] == "not_found"
    assert [str(request.url) for request in transport.requests] == [HIT, MISS]


async def test_refresh_fetches_again(make_services) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="PX22770")
        refreshed = await _call(client, vin="PX22770", refresh=True)
    assert (refreshed["from_cache"], refreshed["requests_made"]) == (False, 1)
    assert len(transport.requests) == 2
    assert cache_lifetime(services, HIT) == timedelta(days=180)
