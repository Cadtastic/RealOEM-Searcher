"""parse_vehicles on trimmed real vehicles-index pages (site notes section 5.5)."""

from collections import Counter

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.models.vehicles import VehicleIndexPage
from realoem_mcp.parsers.vehicles import parse_vehicles
from tests.harness import BRANDS_DIR, load_fixture, url

BRANDS = BrandRegistry.load(BRANDS_DIR)


def _parse(slug: str, page: int) -> VehicleIndexPage:
    return parse_vehicles(
        load_fixture(f"vehicles/{slug}.html"),
        url=url("vehicles", page=str(page), sort="year"),
        brands=BRANDS,
    )


@pytest.mark.parametrize(
    ("slug", "number", "expected"),
    [
        ("sort_year_p1", 1, (1, 165, 1, 50, 8218, 50)),
        ("sort_year_p2", 2, (2, 165, 51, 100, 8218, 50)),
        ("sort_year_p83", 83, (83, 165, 4101, 4150, 8218, 50)),
        ("sort_year_p165", 165, (165, 165, 8201, 8218, 8218, 18)),
        ("series_m", 1, (1, 1, 1, 10, 10, 10)),  # one page: no #vi-pagination at all
    ],
)
def test_result_bar_and_pagination(slug: str, number: int, expected: tuple[int, ...]) -> None:
    p = _parse(slug, number)
    assert (p.page, p.last_page, p.first, p.last, p.total, len(p.rows)) == expected


def test_page_one_is_the_blank_start_rows() -> None:
    page = _parse("sort_year_p1", 1)
    assert all(row.vehicle is None and row.production_from is None for row in page.rows)
    assert all(row.key.endswith("--") for row in page.rows)
    assert Counter(row.brand for row in page.rows) == {"bmw": 48, "motorrad": 2}
    first = page.rows[0]
    assert first.model_dump() == {
        "key": "1A10-BRA--",
        "vehicle": None,
        "brand": "bmw",
        "series_label": "1 Series F20",
        "series_code": None,
        "model_name": "116i",
        "type_code": "1A10",
        "body": "5 doors",
        "market": "BRA",
        "production_from": None,
        "production_to": None,
        "source": "local",
    }


def test_unlinked_motorcycle_and_a_code_rows() -> None:
    rows = {row.type_code: row for row in _parse("sort_year_p1", 1).rows}
    assert (rows["0B74"].brand, rows["0B74"].model_name, rows["0B74"].body) == (
        "motorrad",
        "F 800 R 16 (0B74)",
        None,
    )
    assert rows["0P10"].brand == "motorrad"
    a15 = rows["9884"]
    assert (a15.brand, a15.series_label, a15.body) == ("bmw", "A15", None)


def test_page_two_mixes_the_last_blank_row_with_linked_classics() -> None:
    rows = _parse("sort_year_p2", 2).rows
    assert (rows[0].key, rows[0].vehicle) == ("KS07-IND--", None)
    assert rows[1].model_dump() == {
        "key": "ST01-EUR-01-1928",
        "vehicle": {
            "vehicle_id": "ST01-EUR-01-1928-CMSP-BMW-E30_M3_GrN",
            "type_code": "ST01",
            "market": "EUR",
            "production_month": "1928-01",
            "series": "CMSP",
            "brand": "bmw",
            "model": "E30_M3_GrN",
        },
        "brand": "bmw",
        "series_label": "BMW Classic Motorsport",
        "series_code": "CMSP",
        "model_name": "E30 M3 Gr.N",
        "type_code": "ST01",
        "body": "Coupe",
        "market": "EUR",
        "production_from": "1928-01",
        "production_to": "1932-09",
        "source": "local",
    }


def test_classic_motorcycles_keep_the_series_label_verbatim() -> None:
    row = next(r for r in _parse("sort_year_p2", 2).rows if r.type_code == "0T16")
    assert row.series_label == "R 51         -54"  # verbatim, inner spaces kept
    assert (row.brand, row.series_code, row.model_name) == ("motorrad", "T51", "R51/2")
    assert row.vehicle is not None and row.vehicle.vehicle_id == "0T16-EUR-01-1950-T51-BMW-R51_2"
    assert (row.production_from, row.production_to, row.body) == ("1950-01", "1950-12", None)


def test_mini_rows_split_the_brand_prefix() -> None:
    rows = _parse("sort_year_p83", 83).rows
    assert Counter(row.brand for row in rows) == {"bmw": 38, "mini": 12}
    clubman = rows[2]
    assert (clubman.key, clubman.brand, clubman.series_label, clubman.series_code) == (
        "MH92-EUR-01-2012",
        "mini",
        "MINI Clubman R55 LCI",
        "R55N",
    )
    assert clubman.model_name == "Coop.S JCW"
    assert clubman.vehicle is not None
    assert (clubman.vehicle.brand, clubman.vehicle.model) == ("mini", "CoopS_JCW")


def test_last_page_rolls_royce_and_motorcycles() -> None:
    rows = _parse("sort_year_p165", 165).rows
    assert Counter(row.brand for row in rows) == {"bmw": 13, "rolls-royce": 3, "motorrad": 2}
    phantom, r18 = rows[0], rows[1]
    assert (phantom.key, phantom.brand, phantom.series_code, phantom.model_name) == (
        "13HE-USA-11-2024",
        "rolls-royce",
        "R11N",
        "Phantom",
    )
    assert phantom.vehicle is not None
    assert phantom.vehicle.vehicle_id == "13HE-USA-11-2024-R11N-Rolls_Royce-Phantom"
    assert (r18.brand, r18.type_code, r18.model_name, r18.body) == (
        "motorrad",
        "0N74",
        "R 18 25 (0N74)",
        None,
    )
    assert [row.production_from for row in rows[-3:]] == ["2025-03"] * 3


def test_zinoro_rows_belong_to_bmw() -> None:
    rows = {row.type_code: row for row in _parse("series_m", 1).rows}
    zinoro_bmw_id, zinoro_own_id = rows["CZ31"], rows["CZ11"]
    assert (zinoro_bmw_id.brand, zinoro_bmw_id.model_name) == ("bmw", "Zinoro 1E")
    assert (zinoro_own_id.brand, zinoro_own_id.model_name) == ("bmw", "Zinoro 60H/100H")
    assert zinoro_own_id.vehicle is not None
    assert zinoro_own_id.vehicle.vehicle_id == "CZ11-CHN-06-2015-M13-Zinoro-Zinoro_60H_100H"
    assert zinoro_own_id.series_code == "M13"
    assert (zinoro_own_id.vehicle.brand, zinoro_own_id.vehicle.model) == ("bmw", "Zinoro_60H_100H")
    assert sum(row.vehicle is None for row in rows.values()) == 5
