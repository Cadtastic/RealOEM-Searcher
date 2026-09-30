from datetime import UTC, datetime

from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import (
    Condition,
    DiagramParts,
    DiagramPartsResult,
    Hotspot,
    MainGroup,
    OptionCode,
    PartGroups,
    PartGroupsResult,
    PartRow,
    VehicleSelectionResult,
    VehicleSpecs,
)
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.page_types import PageType
from tests.harness import url

VEHICLE = VehicleRef(
    vehicle_id="VB13-USA-10-2005-E90-BMW-325i",
    type_code="VB13",
    market="USA",
    production_month="2005-10",
    series="E90",
    brand="bmw",
    model="325i",
)
META = {
    "fetched_at": datetime(2026, 9, 30, tzinfo=UTC),
    "from_cache": True,
    "requests_made": 0,
}


def _page(page_type: PageType, page_url: str) -> Page:
    return Page(
        page_type=page_type,
        url=page_url,
        final_url=page_url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=True,
    )


def test_part_groups_result_is_the_parser_output_plus_result_meta() -> None:
    page_url = url("partgrp", id=VEHICLE.vehicle_id)
    groups = PartGroups(
        specs=VehicleSpecs(
            vehicle=VEHICLE,
            model_name="3 Series E90 325i",
            body="Sedan",
            engine="N52",
            steering="Left-hand drive",
            transmission=None,
        ),
        main_groups=[MainGroup(mg="11", name="ENGINE")],
    )
    result = PartGroupsResult.from_pages([_page(PageType.PARTGRP, page_url)], **dict(groups))
    assert result.model_dump() == {"source_urls": [page_url], **META, **groups.model_dump()}


def test_diagram_parts_result_is_the_parser_output_plus_result_meta() -> None:
    page_url = url("showparts", id=VEHICLE.vehicle_id, diagId="11_3733")
    row = PartRow(
        position="01",
        description="Oil Pan",
        supplement=None,
        qty="1",
        valid_from=None,
        valid_to="2006-04",
        part_number="11137552414",
        price_usd=551.84,
        notes="+core",
        has_photo=False,
        indent=2,
        conditions=[
            Condition(
                text="For vehicles with Automatic transmission",
                option_codes=[OptionCode(code="S205A", value="Yes")],
            )
        ],
    )
    parts = DiagramParts(
        diagram=DiagramRef(
            vehicle_id=VEHICLE.vehicle_id, diag_id="11_3733", name="Oil Pan", url=page_url
        ),
        image_url="https://www.realoem.com/bmw/images/diag_2zas.jpg",
        image_width=640,
        image_height=448,
        hotspots=[Hotspot(position="01", x1=78, y1=255, x2=87, y2=271)],
        rows=[row],
        notes_legend={"+core": "plus core charge"},
    )
    result = DiagramPartsResult.from_pages([_page(PageType.SHOWPARTS, page_url)], **dict(parts))
    assert result.model_dump() == {"source_urls": [page_url], **META, **parts.model_dump()}


def test_vehicle_selection_result_fields() -> None:
    assert list(VehicleSelectionResult.model_fields) == [
        "source_urls",
        "fetched_at",
        "from_cache",
        "requests_made",
        "selected",
        "next_level",
        "options",
        "complete",
        "vehicle",
        "type_code",
        "summary",
    ]
