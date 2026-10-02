"""server_status and cache_clear on the hosted server (design 4.7, 4.8)."""

from pathlib import Path

import pytest

from tests.harness import url
from tests.shared_env import call_tool, shared_services

pytestmark = pytest.mark.anyio

ROUTES = {
    url("partxref", q="11427953129"): "partxref/oil_filter_11427953129.html",
    url("select", vin="PX22770"): "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


async def test_server_status_shows_the_callers_quota_and_no_path(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES, global_daily_limit=2000) as (shared, _):
        services = shared.services
        await call_tool(services, "github:2", "decode_vin", {"vin": "PX22770"})  # someone else
        await call_tool(services, "github:1", "lookup_part", PART)
        status = (await call_tool(services, "github:1", "server_status", {})).structured_content
        assert status["cache_path"] is None
        assert (status["quota"]["used_today"], status["quota"]["limit"]) == (1, 300)  # own count
        assert status["quota"]["resets_at"].startswith("2026-10-03T00:00:00")
        assert status["global_limit"] == 2000
        anonymous = await call_tool(services, None, "server_status", {})
        assert anonymous.is_error is True


async def test_only_admins_may_clear_the_shared_cache(tmp_path: Path) -> None:
    admins = frozenset({"github:1"})
    async with shared_services(tmp_path, ROUTES, admins=admins) as (shared, _):
        services = shared.services
        await call_tool(services, "github:2", "lookup_part", PART)
        refused = await call_tool(services, "github:2", "cache_clear", {})
        assert refused.is_error is True
        assert "Only an administrator" in refused.content[0].text
        assert (await call_tool(services, None, "cache_clear", {})).is_error is True
        assert services.cache.stats().entries == 1
        cleared = await call_tool(services, "github:1", "cache_clear", {})
        assert cleared.structured_content == {"removed": 1}
        status = (await call_tool(services, "github:1", "server_status", {})).structured_content
        assert status["global_limit"] is None  # the server-wide cap is off by default
