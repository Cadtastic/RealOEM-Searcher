"""decode_vin on the hosted server: a missed VIN is shortened in its owner's cache entry."""

import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from tests.auth_helpers import signed_in
from tests.harness import url
from tests.shared_env import OWNER_KEY, call_tool, shared_services

pytestmark = pytest.mark.anyio

MISS = url("select", vin="ZZZZZZZ")
MISS_PARAMS = {"vin": "ZZZZZZZ"}
SELECT = url("select", vin="PX22770")
PRODUCTION = url("production", vin="PX22770")
DECODE_WITH_PRODUCTION = {"vin": "PX22770", "include_production": True}


def _owner_of(subject: str) -> str:
    """The cache owner of a user's VIN pages: a keyed hash, so the cache holds no user ids."""
    return hmac.new(OWNER_KEY, subject.encode("utf-8"), hashlib.sha256).hexdigest()


def _lifetime(fetched_at: str, expires_at: str) -> timedelta:
    return datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at)


async def test_a_missed_vin_is_cached_for_one_day_for_its_owner_only(tmp_path: Path) -> None:
    async with shared_services(tmp_path, {MISS: "select/vin_miss_zzzzzzz.html"}) as (shared, _):
        services = shared.services
        result = await call_tool(services, "github:1", "decode_vin", MISS_PARAMS)
        assert result.structured_content["status"] == "not_found"
        ((owner, fetched_at, expires_at),) = services.cache._conn.execute(
            "SELECT owner, fetched_at, expires_at FROM pages WHERE url = ?", (MISS,)
        ).fetchall()
        assert owner == _owner_of("github:1")  # a per-user entry, not a shared one
        assert _lifetime(fetched_at, expires_at) == timedelta(days=1)  # shortened for the owner
        with signed_in("github:1"):
            assert services.client.cached(PageType.SELECT, "select", MISS_PARAMS) is not None
        with signed_in("github:2"):
            assert services.client.cached(PageType.SELECT, "select", MISS_PARAMS) is None
        with pytest.raises(RealOemError, match="not signed in"):  # no caller: fail closed
            services.client.cached(PageType.SELECT, "select", MISS_PARAMS)


async def test_a_production_miss_is_cached_for_one_day_for_its_owner(tmp_path: Path) -> None:
    routes = {
        SELECT: "select/vin_bmw_e93_px22770.html",
        PRODUCTION: "production/vin_miss_zzzzzzz.html",
    }
    async with shared_services(tmp_path, routes) as (shared, _):
        services = shared.services
        result = await call_tool(services, "github:1", "decode_vin", DECODE_WITH_PRODUCTION)
        assert result.is_error is False, result.content
        ((owner, fetched_at, expires_at),) = services.cache._conn.execute(
            "SELECT owner, fetched_at, expires_at FROM pages WHERE url = ?", (PRODUCTION,)
        ).fetchall()
        assert owner == _owner_of("github:1")
        assert _lifetime(fetched_at, expires_at) == timedelta(days=1)


async def test_an_unparseable_production_page_is_not_kept_for_its_owner(tmp_path: Path) -> None:
    routes = {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "select/vin_miss_zzzzzzz.html"}
    async with shared_services(tmp_path, routes) as (shared, transport):
        for _ in range(2):
            result = await call_tool(
                shared.services, "github:1", "decode_vin", DECODE_WITH_PRODUCTION
            )
            assert result.is_error is True
        sent = [str(request.url) for request in transport.requests]
        assert sent == [SELECT, PRODUCTION, PRODUCTION]  # expired at once, so fetched again
