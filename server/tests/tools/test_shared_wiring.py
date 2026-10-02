"""build_shared: quotas, per-user VIN pages and the cache cap through the MCP tools (design 4.7)."""

import hashlib
import hmac
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.shared import build_shared, vin_page_owner
from tests.auth_helpers import signed_in
from tests.harness import BRANDS_DIR, url
from tests.shared_env import TODAY, call_tool, shared_services

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
VIN = url("select", vin="PX22770")
ROUTES = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    VIN: "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


async def test_users_share_parts_pages_but_pay_for_their_own_vin_pages(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        services = shared.services
        for subject in ("github:1", "github:2"):
            part = await call_tool(services, subject, "lookup_part", PART)
            vin = await call_tool(services, subject, "decode_vin", {"vin": "PX22770"})
            assert part.is_error is False and vin.is_error is False
        sent = [str(request.url) for request in transport.requests]
        assert sent == [OIL_FILTER, VIN, VIN]  # the part page once, the VIN page per user
        assert shared.quota.status("github:1").used_today == 2
        assert shared.quota.status("github:2").used_today == 1  # the part page was free
        assert services.cache.get(VIN) is None  # no shared copy of a VIN page exists


async def test_a_tool_call_without_a_signed_in_user_fetches_nothing(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        result = await call_tool(shared.services, None, "lookup_part", PART)
        assert result.is_error is True
        assert "not signed in" in result.content[0].text
        assert transport.requests == []


async def test_an_anonymous_refresh_of_an_old_copy_fetches_nothing(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        services = shared.services
        await call_tool(services, "github:1", "lookup_part", PART)
        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="microseconds")
        services.cache._conn.execute("UPDATE pages SET fetched_at = ?", (two_hours_ago,))
        result = await call_tool(services, None, "lookup_part", {**PART, "refresh": True})
        assert result.is_error is True
        assert "not signed in" in result.content[0].text
        assert len(transport.requests) == 1


async def test_a_user_over_the_limit_still_gets_cached_answers(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES, user_daily_limit=1) as (shared, transport):
        services = shared.services
        first = await call_tool(services, "github:1", "lookup_part", PART)
        refused = await call_tool(services, "github:1", "decode_vin", {"vin": "PX22770"})
        again = await call_tool(services, "github:1", "lookup_part", PART)
        assert first.is_error is False
        assert refused.is_error is True
        assert refused.content[0].text.endswith(
            "You've used your 1 RealOEM lookups for today; the limit resets at 00:00 UTC. "
            "Cached results remain available."
        )
        assert again.is_error is False and again.structured_content["from_cache"] is True
        assert [str(request.url) for request in transport.requests] == [OIL_FILTER]


async def test_a_young_github_account_gets_the_smaller_limit(tmp_path: Path) -> None:
    created = {"github:new": TODAY - timedelta(days=3)}
    async with shared_services(tmp_path, ROUTES, created=created, new_user_daily_limit=1) as (
        shared,
        _,
    ):
        services = shared.services
        decoded = await call_tool(services, "github:new", "decode_vin", {"vin": "PX22770"})
        assert decoded.is_error is False
        refused = await call_tool(services, "github:new", "lookup_part", PART)
        assert refused.is_error is True
        assert "your 1 RealOEM lookups" in refused.content[0].text


async def test_the_hosted_cache_is_capped(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, _):
        cache = shared.services.cache
        assert cache._max_bytes == 400 * 1024 * 1024
        assert cache._min_free_bytes == 100 * 1024 * 1024


def test_only_pages_that_carry_a_vin_are_owned_by_the_caller() -> None:
    owner = vin_page_owner(Settings(mode="http"), b"key")
    expected = hmac.new(b"key", b"github:1", hashlib.sha256).hexdigest()
    with signed_in("github:1"):
        assert owner(PageType.SELECT, {"vin": "PX22770"}) == expected
        assert owner(PageType.PRODUCTION, {"vin": "PX22770"}) == expected
        assert owner(PageType.SELECT, {"product": "P", "archive": "0"}) == ""  # the model cascade
        assert owner(PageType.PARTXREF, {"q": "11427953129"}) == ""
        assert owner("production", {"vin": "PX22770"}) == expected  # type: ignore[arg-type]
        assert owner("select", {"vin": "PX22770"}) == expected  # type: ignore[arg-type]
    with pytest.raises(RealOemError, match="not signed in"):
        owner(PageType.SELECT, {"vin": "PX22770"})


@pytest.mark.parametrize(
    ("mode", "owner_key", "message"),
    [("stdio", b"k", "mode='http'"), ("http", b"", "secret owner_key")],
)
def test_build_shared_needs_http_mode_and_a_key(
    tmp_path: Path, mode: str, owner_key: bytes, message: str
) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        with pytest.raises(ValueError, match=message):
            build_shared(
                Settings(
                    mode=mode,  # type: ignore[arg-type]
                    cache_dir=tmp_path,
                    data_dir=tmp_path,
                    brands_dir=BRANDS_DIR,
                ),
                conn,
                owner_key=owner_key,
                account_created_at=lambda subject: None,
            )
    finally:
        conn.close()
