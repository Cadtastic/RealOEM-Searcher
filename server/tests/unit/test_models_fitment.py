from datetime import UTC, datetime

from realoem_mcp.http_client import Page
from realoem_mcp.models.common import DiagramRef, ResultMeta
from realoem_mcp.models.fitment import (
    CompareScope,
    ComparisonResult,
    FitmentResult,
    PartComparison,
    PartSearch,
    PartSearchHit,
    PartSummary,
)
from realoem_mcp.page_types import PageType
from tests.harness import url

VEHICLE = "VB13-USA---E90-BMW-325i"
SEARCH = url("partsearch", id=VEHICLE, q="11427566327")
LIST = url("partgrp", id=VEHICLE, mg="11")
OIL_FILTER = DiagramRef(
    vehicle_id=VEHICLE,
    diag_id="11_3867",
    name="Lubrication system-Oil filter",
    url=url("showparts", id=VEHICLE, diagId="11_3867"),
)


def _page(page_url: str, page_type: PageType, *, from_cache: bool, day: int) -> Page:
    return Page(
        page_type=page_type,
        url=page_url,
        final_url=page_url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, day, 12, 0, tzinfo=UTC),
        from_cache=from_cache,
    )


def test_fitment_result_has_the_ard_fields_in_order() -> None:
    assert issubclass(FitmentResult, ResultMeta)
    assert list(FitmentResult.model_fields) == [
        "source_urls",
        "fetched_at",
        "from_cache",
        "requests_made",
        "query",
        "vehicle_id",
        "fits",
        "used_part_numbers",
        "description",
        "price_usd",
        "diagrams",
        "superseded_by",
        "supersedes",
    ]


def test_comparison_models_have_the_ard_fields_in_order() -> None:
    assert issubclass(ComparisonResult, ResultMeta)
    assert list(ComparisonResult.model_fields)[4:] == [
        "scope",
        "complete",
        "in_both",
        "only_a",
        "only_b",
        "unfetched_a",
        "unfetched_b",
        "ignored_diag_ids_a",
        "ignored_diag_ids_b",
    ]
    assert list(CompareScope.model_fields) == ["main_group", "subgroup", "diag_ids"]
    assert list(PartComparison.model_fields) == ["part_number", "description", "qty_a", "qty_b"]
    assert list(PartSummary.model_fields) == ["part_number", "description", "qty", "diag_ids"]


def test_parser_output_model() -> None:
    search = PartSearch(
        part_number="11427566327",
        description="Set oil-filter element",
        price_usd=12.25,
        hits=[PartSearchHit(part_number="11427953129", diagram=OIL_FILTER)],
        superseded_by=[],
        supersedes=[],
    )
    assert search.hits[0].diagram.diag_id == "11_3867"
    assert list(PartSearch.model_fields) == [
        "part_number",
        "description",
        "price_usd",
        "hits",
        "superseded_by",
        "supersedes",
    ]


def test_fitment_result_from_one_page() -> None:
    result = FitmentResult.from_pages(
        [_page(SEARCH, PageType.PARTSEARCH, from_cache=False, day=30)],
        query="11427566327",
        vehicle_id=VEHICLE,
        fits=True,
        used_part_numbers=["11427953129"],
        description="Set oil-filter element",
        price_usd=12.25,
        diagrams=[OIL_FILTER],
        superseded_by=[],
        supersedes=[],
    )
    data = result.model_dump(mode="json")
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == ([SEARCH], False, 1)
    assert data["diagrams"][0]["url"] == url("showparts", id=VEHICLE, diagId="11_3867")


def test_comparison_result_counts_network_pages_only() -> None:
    pages = [
        _page(LIST, PageType.PARTGRP, from_cache=True, day=28),
        _page(OIL_FILTER.url, PageType.SHOWPARTS, from_cache=False, day=30),
    ]
    result = ComparisonResult.from_pages(
        pages,
        scope=CompareScope(main_group="11", subgroup="30", diag_ids=None),
        complete=False,
        in_both=[
            PartComparison(
                part_number="11427953129",
                description="Set oil-filter element",
                qty_a=["1"],
                qty_b=["1", "1"],
            )
        ],
        only_a=[
            PartSummary(
                part_number="11428637821", description="Gasket", qty=["1"], diag_ids=["11_3867"]
            )
        ],
        only_b=[],
        unfetched_a=[],
        unfetched_b=["11_3752"],
        ignored_diag_ids_a=[],
        ignored_diag_ids_b=[],
    )
    data = result.model_dump(mode="json")
    assert (data["from_cache"], data["requests_made"]) == (False, 1)
    assert data["fetched_at"] == "2026-09-28T12:00:00Z"
    assert data["scope"] == {"main_group": "11", "subgroup": "30", "diag_ids": None}
    assert data["in_both"][0]["qty_b"] == ["1", "1"]
    assert data["only_a"][0]["diag_ids"] == ["11_3867"]
