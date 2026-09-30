"""parse_vehicles brand rules and LayoutChanged cases on synthetic pages (tests/vehicle_data.py)."""

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vehicles import VehicleIndexPage
from realoem_mcp.parsers.vehicles import (
    is_past_end,
    parse_vehicles,
    product_for_type,
    row_key,
)
from tests.harness import BRANDS_DIR, load_fixture
from tests.vehicle_data import numbered, render_page, vehicle

BRANDS = BrandRegistry.load(BRANDS_DIR)
URL = "https://www.realoem.com/bmw/enUS/vehicles?page=2&sort=year"
REAL_P2 = load_fixture("vehicles/sort_year_p2.html")
REAL_P165 = load_fixture("vehicles/sort_year_p165.html")
REAL_PAST_END = load_fixture("vehicles/sort_year_past_end.html")
EMPTY_TABLE = '<html><body><table id="vi-table"><tbody></tbody></table></body></html>'
LAST_LINK = '/bmw/enUS/vehicles?page=165&amp;sort=year" title="Last page"'


def _parse(html: str) -> VehicleIndexPage:
    return parse_vehicles(html, url=URL, brands=BRANDS)


def test_rendered_pages_round_trip() -> None:
    rows = numbered(120)
    pages = [_parse(render_page(rows, number)) for number in (1, 2, 3)]
    assert [(p.page, p.last_page, p.first, p.last, p.total) for p in pages] == [
        (1, 3, 1, 50, 120),
        (2, 3, 51, 100, 120),
        (3, 3, 101, 120, 120),
    ]
    assert [row for page in pages for row in page.rows] == rows


def test_unlinked_rows_take_the_brand_from_the_model_prefix() -> None:
    rows = [
        vehicle("RC31", "EUR", None, brand="mini", model_name="Cooper"),
        vehicle("13HE", "USA", None, brand="rolls-royce", model_name="Phantom"),
        vehicle("0B74", "BRA", None, brand="motorrad", model_name="F 800 R", body=None),
        vehicle("9884", "USA", None, brand="bmw", model_name="A15", body=None),
    ]
    parsed = _parse(render_page(rows, 1)).rows
    assert [(row.key, row.brand, row.vehicle) for row in parsed] == [
        ("RC31-EUR--", "mini", None),
        ("13HE-USA--", "rolls-royce", None),
        ("0B74-BRA--", "motorrad", None),
        ("9884-USA--", "bmw", None),
    ]


def test_type_code_starting_with_zero_means_motorcycle() -> None:
    # A motorcycle whose series code matches no motorrad pattern still resolves by product.
    bike = vehicle("0X99", "EUR", "1960-01", "1965-12", brand="motorrad", series_code="E1")
    # A car whose series code looks like a motorcycle series stays a car.
    car = vehicle("AB12", "EUR", "1960-01", "1965-12", brand="bmw", series_code="R8")
    parsed = _parse(render_page([bike, car], 1)).rows
    assert [(row.type_code, row.brand) for row in parsed] == [("0X99", "motorrad"), ("AB12", "bmw")]
    assert (product_for_type("0X99"), product_for_type("AB12")) == ("M", "P")


def test_a_page_past_the_end_is_recognised() -> None:
    assert not is_past_end(REAL_P2)
    assert not is_past_end(REAL_P165)  # the real last page ("Showing 8201-8218")
    assert not is_past_end(load_fixture("vehicles/series_m.html"))  # third <strong> "Series: M"
    assert not is_past_end(render_page(numbered(120), 3))
    assert is_past_end(render_page(numbered(120), 4))  # no table at all
    assert is_past_end(EMPTY_TABLE)
    # RealOEM's real answer past its end repeats the last page's rows under "Showing 8251-8218".
    assert is_past_end(REAL_PAST_END)
    commas = REAL_PAST_END.replace("8251–8218", "8,251–8,218")
    assert commas != REAL_PAST_END
    assert is_past_end(commas)
    with pytest.raises(LayoutChanged, match="18 rows but 'Showing 8251-8218'"):
        _parse(REAL_PAST_END)


def test_row_key() -> None:
    assert row_key("VB13", "USA", "2005-10") == "VB13-USA-10-2005"
    assert row_key("VB13", "USA", None) == "VB13-USA--"


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        ('id="vi-result-bar"', 'id="other-bar"', "#vi-result-bar > span"),
        ('id="vi-table"', 'id="other-table"', "table#vi-table > tbody"),
        ("<strong>51\N{EN DASH}100</strong>", "<strong>51\N{EN DASH}99</strong>", "50 rows but"),
        ("<strong>8218</strong>", "<strong>many</strong>", "unreadable result bar"),
        ('<td class="vi-col-market">IND</td>', "", "td.vi-col-market"),
        ("BMW&nbsp;X5 25d", "BMW X5 25d", "no brand prefix"),
        ("BMW&nbsp;X5 25d", "BMW&nbsp; ", "row without series, model"),
        (
            '<td class="vi-col-series">X5 F15</td>',
            '<td class="vi-col-series"> </td>',
            "row without",
        ),
        ("01/1928\N{EN DASH}09/1932", "01/1928", "unreadable production range"),
        ('<span class="vi-pg-current">2</span>', "", "span.vi-pg-current"),
        (LAST_LINK, LAST_LINK.replace("page=165&amp;", ""), "no page number"),
        (LAST_LINK, LAST_LINK.replace("page=165", "page=166"), "expected 50 rows per page"),
        (
            '<span class="vi-pg-current">2</span>',
            '<span class="vi-pg-current">3</span>',
            "page 3 of 165 shows rows 51-100 of 8218",
        ),
    ],
)
def test_unexpected_structure_raises_layout_changed(old: str, new: str, detail: str) -> None:
    assert old in REAL_P2
    with pytest.raises(LayoutChanged, match=detail) as caught:
        _parse(REAL_P2.replace(old, new, 1))
    assert caught.value.page_type == "vehicles"
    assert caught.value.url == URL
