from datetime import UTC, date, datetime

from realoem_mcp.models.common import ResultMeta, VehicleRef
from realoem_mcp.models.vehicles import (
    IndexedVehicle,
    IndexMeta,
    VehicleIndexPage,
    VehicleIndexUpdateResult,
    VehicleSearchResult,
)
from realoem_mcp.vehicle_ids import VehicleId

VID = "VB13-USA-10-2005-E90-BMW-325i"


def _vehicle() -> IndexedVehicle:
    return IndexedVehicle(
        key="VB13-USA-10-2005",
        vehicle=VehicleRef.from_id(VehicleId.parse(VID), "bmw"),
        brand="bmw",
        series_label="3 Series E90",
        series_code="E90",
        model_name="325i",
        type_code="VB13",
        body="Sedan",
        market="USA",
        production_from="2005-10",
        production_to="2008-02",
        source="baseline",
    )


def test_models_have_exactly_the_ard_fields() -> None:
    assert list(IndexedVehicle.model_fields) == [
        "key",
        "vehicle",
        "brand",
        "series_label",
        "series_code",
        "model_name",
        "type_code",
        "body",
        "market",
        "production_from",
        "production_to",
        "source",
    ]
    assert list(IndexMeta.model_fields) == [
        "built_at",
        "baseline_total",
        "local_rows",
        "last_update_at",
    ]
    assert list(VehicleSearchResult.model_fields) == ["total_matches", "vehicles", "index"]
    assert issubclass(VehicleIndexUpdateResult, ResultMeta)
    assert list(VehicleIndexUpdateResult.model_fields)[4:] == [
        "status",
        "added",
        "remote_total",
        "local_total",
        "pages_fetched",
        "message",
    ]
    assert not issubclass(VehicleSearchResult, ResultMeta)  # find_vehicle makes no request


def test_search_result_serializes_dates_as_iso_strings() -> None:
    meta = IndexMeta(
        built_at=date(2026, 9, 30),
        baseline_total=8218,
        local_rows=0,
        last_update_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    result = VehicleSearchResult(total_matches=1, vehicles=[_vehicle()], index=meta)
    dumped = result.model_dump(mode="json")
    assert dumped["index"] == {
        "built_at": "2026-09-30",
        "baseline_total": 8218,
        "local_rows": 0,
        "last_update_at": "2026-10-01T12:00:00Z",
    }
    assert dumped["vehicles"][0]["vehicle"]["vehicle_id"] == VID
    assert dumped["vehicles"][0]["vehicle"]["production_month"] == "2005-10"


def test_index_page_holds_the_result_bar_numbers() -> None:
    page = VehicleIndexPage(page=2, last_page=3, first=51, last=51, total=101, rows=[_vehicle()])
    assert (page.page, page.last_page, page.first, page.last, page.total) == (2, 3, 51, 51, 101)
