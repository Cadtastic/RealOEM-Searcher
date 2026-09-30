import re
from typing import Any

import pytest

from realoem_mcp.models.fitment import PartSearch
from realoem_mcp.parsers.partsearch import parse_partsearch
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

DATED = "VB13-USA-10-2005-E90-BMW-325i"  # E90 325i built 10/2005, as decode_vin returns
UNDATED = "VB13-USA---E90-BMW-325i"  # id the other two captures were requested with
OIL_FILTER = "Set oil-filter element"
RETRO = "Exchangeable retrospectively"


def _hits(vehicle_id: str) -> list[dict[str, Any]]:
    """The two diagrams showing 11427953129 on the E90 325i, built for vehicle_id."""
    return [
        {
            "part_number": "11427953129",
            "diagram": {
                "vehicle_id": vehicle_id,
                "diag_id": diag_id,
                "name": name,
                "url": url("showparts", id=vehicle_id, diagId=diag_id),
            },
        }
        for diag_id, name in [
            ("02_0092", "Engine oil / maintenance service"),
            ("11_3867", "Lubrication system-Oil filter"),
        ]
    ]


def _entry(
    number: str, start: str, end: str | None, remark: str | None, *, in_catalog: bool
) -> dict[str, Any]:
    return {
        "part_number": number,
        "description": OIL_FILTER,
        "valid_from": start,
        "valid_to": end,
        "remark": remark,
        "in_catalog": in_catalog,
    }


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


def _parse(html: str, q: str, services: Services, vehicle_id: str = UNDATED) -> PartSearch | None:
    return parse_partsearch(
        html,
        url=url("partsearch", id=vehicle_id, q=q),
        client=services.client,
        vehicle_id=vehicle_id,
    )


def _fixture(slug: str, q: str, services: Services, vehicle_id: str = UNDATED) -> dict[str, Any]:
    search = _parse(load_fixture(f"partsearch/{slug}.html"), q, services, vehicle_id)
    assert search is not None
    return search.model_dump(mode="json")


async def test_current_part_found_on_two_diagrams(services: Services) -> None:
    data = _fixture("e90_325i_200510_oil_filter_11427953129", "11427953129", services, DATED)
    assert data == {
        "part_number": "11427953129",
        "description": OIL_FILTER,
        "price_usd": None,
        "hits": _hits(DATED),
        "superseded_by": [],
        "supersedes": [
            _entry("11428683196", "2016-09-01", "2017-09-21", RETRO, in_catalog=True),
            _entry("11427566327", "2006-02-13", "2017-01-30", RETRO, in_catalog=True),
            _entry("11427541827", "2004-09-01", "2006-03-17", None, in_catalog=False),
        ],
    }


async def test_predecessor_hits_name_the_number_the_vehicle_uses(services: Services) -> None:
    data = _fixture("e90_325i_predecessor_11427566327", "11427566327", services)
    assert (data["part_number"], data["description"]) == ("11427566327", OIL_FILTER)
    assert data["price_usd"] == 12.25
    assert data["hits"] == _hits(UNDATED)  # site notes 3.8: supersession resolved to 11427953129
    assert data["superseded_by"] == [
        _entry("11428683196", "2016-09-01", "2017-09-21", RETRO, in_catalog=True),
        _entry("11427953129", "2017-06-01", None, RETRO, in_catalog=True),
    ]
    assert data["supersedes"] == [
        _entry("11427541827", "2004-09-01", "2006-03-17", None, in_catalog=False)
    ]


async def test_part_not_on_the_vehicle_has_no_hits(services: Services) -> None:
    assert _fixture("e90_325i_not_on_vehicle_11427622446", "11427622446", services) == {
        "part_number": "11427622446",
        "description": OIL_FILTER,
        "price_usd": None,
        "hits": [],
        "superseded_by": [],
        "supersedes": [_entry("11427557012", "2006-09-01", "2011-03-16", None, in_catalog=False)],
    }


async def test_no_vehicles_template_has_no_hits(services: Services) -> None:
    # synthetic: partxref's no-vehicles results block (site notes 3.3) in place of the miss text
    html = load_fixture("partsearch/e90_325i_not_on_vehicle_11427622446.html")
    no_vehicles = (
        '<div class="partSearchResults"><h4 class="vs2">Search for another part</h4>'
        '<div class="searchForm"><form name="form3" action="/bmw/enUS/partxref">'
        '<label for="q">PART NR APPLICATION SEARCH:</label>'
        '<input name="q" size="10" maxlength="20" value="11427622446">'
        '<input type="submit" value="Search"></form></div></div>'
    )
    html, count = re.subn(
        r'<div class="partSearchResults">.*?</div>', no_vehicles, html, flags=re.DOTALL
    )
    assert count == 1
    search = _parse(html, "11427622446", services)
    assert search is not None
    assert (search.part_number, search.hits) == ("11427622446", [])


async def test_unknown_part_is_none(services: Services) -> None:
    # synthetic, defensive: RealOEM answers an unknown part with a redirect (site notes 3.8); an
    # error div like partxref's is still read as "not found" should the page ever show one
    html = load_fixture("partsearch/e90_325i_not_on_vehicle_11427622446.html")
    error = '<div class="error vs2">The specified part 11426666661 was not found.</div>'
    html, count = re.subn(r"<h1>.*?</p>", error, html, flags=re.DOTALL)
    assert count == 1
    assert _parse(html, "11426666661", services) is None


async def test_heading_with_description_is_the_fallback_description(services: Services) -> None:
    # synthetic: partxref's no-vehicles heading form "number - description" and an empty h2
    html = load_fixture("partsearch/e90_325i_not_on_vehicle_11427622446.html")
    for old, new in [
        ("11427622446</h1>", "11427622446 - Set oil-filter element (heading)</h1>"),
        (f"{OIL_FILTER}</h2>", "</h2>"),
    ]:
        assert old in html, old
        html = html.replace(old, new)
    search = _parse(html, "11427622446", services)
    assert search is not None
    assert (search.part_number, search.description) == (
        "11427622446",
        "Set oil-filter element (heading)",
    )
