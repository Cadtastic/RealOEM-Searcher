from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from realoem_mcp.http_client import Page
from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.models.parts import (
    ModelUse,
    PartLookupResult,
    PartXref,
    SeriesUse,
    SupersessionEntry,
)
from realoem_mcp.page_types import PageType

URL = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"


def _page() -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=URL,
        final_url=URL,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        from_cache=False,
    )


def _xref() -> PartXref:
    vehicle = VehicleRef(
        vehicle_id="VB53-USA-03_2005_E90_BMW_323i",
        type_code="VB53",
        market="USA",
        production_month="2005-03",
        series="E90",
        brand="bmw",
        model="323i",
    )
    diagram = DiagramRef(
        vehicle_id=vehicle.vehicle_id,
        diag_id="11_3867",
        name="Lubrication system-Oil filter",
        url="https://www.realoem.com/bmw/enUS/showparts?id=VB53-USA-03_2005_E90_BMW_323i&diagId=11_3867",
    )
    return PartXref(
        part_number="11427953129",
        description="Set oil-filter element",
        supplier_ref=None,
        weight_kg=None,
        valid_from=date(2017, 6, 1),
        valid_to=None,
        ended=False,
        superseded_by=[],
        supersedes=[
            SupersessionEntry(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
                in_catalog=False,
            )
        ],
        series=[
            SeriesUse(
                code="E90",
                name="3 Series E90",
                brand="bmw",
                production_from="2004-02",
                production_to="2008-09",
            )
        ],
        models=[ModelUse(vehicle=vehicle, body="Sedan", engine="N52", diagram=diagram)],
    )


def test_part_lookup_result_is_a_result_meta() -> None:
    result = PartLookupResult.from_pages(
        [_page()], query="11427953129", status="current", part=_xref()
    )
    assert isinstance(result, ResultMeta)
    data = result.model_dump(mode="json")
    assert data["source_urls"] == [URL]
    assert data["requests_made"] == 1
    assert data["status"] == "current"
    assert data["part"]["valid_from"] == "2017-06-01"
    assert data["part"]["supersedes"][0]["valid_to"] == "2006-03-17"
    assert data["part"]["series"][0]["brand"] == "bmw"
    assert data["part"]["models"][0]["diagram"]["diag_id"] == "11_3867"


def test_not_found_result_has_no_part() -> None:
    result = PartLookupResult.from_pages(
        [_page()], query="11426666661", status="not_found", part=None
    )
    assert result.part is None


def test_status_values_are_fixed() -> None:
    with pytest.raises(ValidationError):
        PartLookupResult.from_pages(
            [_page()], query="11427541827", status="discontinued", part=None
        )
