from datetime import UTC, datetime
from pathlib import Path

import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Page, RealOemClient
from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.vehicle_ids import VehicleId

pytestmark = pytest.mark.anyio


class LookupResult(ResultMeta):
    query: str


def _page(url: str, day: int, *, from_cache: bool) -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=url,
        final_url=url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, day, tzinfo=UTC),
        from_cache=from_cache,
    )


def test_from_pages_fills_the_four_meta_fields() -> None:
    pages = [
        _page("https://x/a", 20, from_cache=True),
        _page("https://x/b", 10, from_cache=False),
        _page("https://x/a", 25, from_cache=False),
    ]
    result = LookupResult.from_pages(pages, query="11427953129")
    assert result.source_urls == ["https://x/a", "https://x/b"]
    assert result.fetched_at == datetime(2026, 9, 10, tzinfo=UTC)
    assert result.from_cache is False
    assert result.requests_made == 2
    assert result.query == "11427953129"


def test_from_pages_all_cached() -> None:
    result = LookupResult.from_pages([_page("https://x/a", 1, from_cache=True)], query="q")
    assert (result.from_cache, result.requests_made) == (True, 0)


def test_from_pages_needs_a_page() -> None:
    with pytest.raises(ValueError, match="at least one page"):
        LookupResult.from_pages([], query="q")


def test_vehicle_ref_from_id_copies_id_fields() -> None:
    vid = VehicleId.parse("MF73-USA-02-2008-R56-Mini-Cooper_S")
    assert VehicleRef.from_id(vid, "mini") == VehicleRef(
        vehicle_id="MF73-USA-02-2008-R56-Mini-Cooper_S",
        type_code="MF73",
        market="USA",
        production_month="2008-02",
        series="R56",
        brand="mini",
        model="Cooper_S",
    )


def test_vehicle_ref_from_undated_id() -> None:
    ref = VehicleRef.from_id(VehicleId.parse("VB13-USA---E90-BMW-325i"), "bmw")
    assert (ref.vehicle_id, ref.production_month) == ("VB13-USA---E90-BMW-325i", None)


async def test_diagram_ref_build_uses_client_build_url(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    client = RealOemClient(Settings(cache_dir=tmp_path), cache)
    try:
        ref = DiagramRef.build(
            client, "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", "11_5146", "Oil filter"
        )
    finally:
        await client.aclose()
        cache.close()
    assert ref.vehicle_id == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert (ref.diag_id, ref.name) == ("11_5146", "Oil filter")
    assert ref.url == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_&diagId=11_5146"
    )
    assert "#" not in ref.url
