import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.errors import InvalidInput
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.tools.parts import fetch_part_xref
from tests.harness import MakeServices, Route, url

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
OIL_FILTER_E90 = url("partxref", q="11427953129", series="E90")


async def _lookup(services: Services, **arguments: object) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("lookup_part", arguments)


async def test_current_part_lists_series_by_brand(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    result = await _lookup(services, part_number="11-42-7-953-129")
    assert result.is_error is False
    data = result.structured_content
    assert (data["query"], data["status"]) == ("11427953129", "current")
    assert data["source_urls"] == [OIL_FILTER]
    assert (data["from_cache"], data["requests_made"]) == (False, 1)
    part = data["part"]
    assert part["part_number"] == "11427953129"
    assert part["description"] == "Set oil-filter element"
    assert part["valid_from"] == "2017-06-01"
    assert len(part["supersedes"]) == 3
    assert len(part["series"]) == 66
    assert part["series"][0] == {
        "code": "E81",
        "name": "1 Series E81",
        "brand": "bmw",
        "production_from": "2006-02",
        "production_to": "2011-12",
    }
    assert part["models"] == []
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_repeat_lookup_uses_the_cache_until_refresh(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    await _lookup(services, part_number="11427953129")
    cached = await _lookup(services, part_number="11 42 7 953 129")
    assert cached.structured_content["from_cache"] is True
    assert cached.structured_content["requests_made"] == 0
    assert len(transport.requests) == 1
    refreshed = await _lookup(services, part_number="11427953129", refresh=True)
    assert refreshed.structured_content["requests_made"] == 1
    assert len(transport.requests) == 2


async def test_series_narrowing_returns_vehicles_and_diagrams(make_services: MakeServices) -> None:
    services, transport = make_services(
        {OIL_FILTER_E90: "partxref/oil_filter_11427953129_e90.html"}
    )
    result = await _lookup(services, part_number="11427953129", series=" e90 ")
    data = result.structured_content
    assert data["status"] == "current"
    assert data["source_urls"] == [OIL_FILTER_E90]  # q first, then series
    models = data["part"]["models"]
    assert len(models) == 114
    assert models[0]["vehicle"]["vehicle_id"] == "VB51-EUR-08_2004_E90_BMW_323i"
    assert models[0]["diagram"]["url"] == (
        "https://www.realoem.com/bmw/enUS/showparts?id=VB51-EUR-08_2004_E90_BMW_323i&diagId=02_0092"
    )
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("q", "fixture", "successor"),
    [
        ("11427541827", "partxref/superseded_11427541827.html", "11427953129"),
        ("11427566327", "partxref/intermediate_11427566327.html", "11427953129"),
    ],
)
async def test_ended_part_points_to_its_successors(
    make_services: MakeServices, q: str, fixture: str, successor: str
) -> None:
    services, _ = make_services({url("partxref", q=q): fixture})
    data = (await _lookup(services, part_number=q)).structured_content
    assert data["status"] == "ended"
    assert data["part"]["ended"] is True
    assert data["part"]["superseded_by"][-1]["part_number"] == successor
    assert data["part"]["superseded_by"][-1]["valid_to"] is None


async def test_status_never_comes_from_the_title(make_services: MakeServices) -> None:
    e30 = url("partxref", q="11427953129", series="E30")
    services, _ = make_services({e30: "partxref/oil_filter_11427953129_e30_no_vehicles.html"})
    data = (await _lookup(services, part_number="11427953129", series="E30")).structured_content
    assert data["status"] == "current"  # the page title says "Discontinued BMW Part"
    assert (data["part"]["series"], data["part"]["models"]) == ([], [])


async def test_seven_digit_short_form(make_services: MakeServices) -> None:
    services, _ = make_services({url("partxref", q="7953129"): "partxref/short_7953129.html"})
    data = (await _lookup(services, part_number="795 3129")).structured_content
    assert (data["query"], data["status"]) == ("7953129", "current")
    assert data["part"]["part_number"] == "11427953129"


@pytest.mark.parametrize(
    ("q", "fixture"),
    [
        ("11426666661", "partxref/not_found_11426666661.html"),  # error div
        ("99999999999", "partxref/false_match_99999999999.html"),  # returns 00009999999
        ("00000000000", "partxref/junk_abc.html"),  # junk part
        ("0000000", "partxref/junk_abc.html"),  # junk part, short form
    ],
)
async def test_not_found(make_services: MakeServices, q: str, fixture: str) -> None:
    services, transport = make_services({url("partxref", q=q): fixture})
    data = (await _lookup(services, part_number=q)).structured_content
    assert (data["query"], data["status"], data["part"]) == (q, "not_found", None)
    assert data["source_urls"] == [url("partxref", q=q)]
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"part_number": "abc"}, "is not a BMW part number"),
        ({"part_number": ""}, "is not a BMW part number"),
        ({"part_number": "1142795312"}, "is not a BMW part number"),
        ({"part_number": "114279531290"}, "is not a BMW part number"),
        ({"part_number": "11427953129", "series": "E9 0"}, "is not a RealOEM series code"),
    ],
)
async def test_malformed_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services({})
    result = await _lookup(services, **arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_blank_series_means_no_series(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    data = (await _lookup(services, part_number="11427953129", series=" ")).structured_content
    assert len(data["part"]["series"]) == 66
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_series_list_on_a_narrowed_page_is_a_layout_change(
    make_services: MakeServices,
) -> None:
    services, _ = make_services({OIL_FILTER_E90: "partxref/oil_filter_11427953129.html"})
    result = await _lookup(services, part_number="11427953129", series="E90")
    assert result.is_error is True
    assert "series list on a page narrowed to one series" in result.content[0].text


async def test_vehicle_rows_on_a_plain_lookup_are_a_layout_change(
    make_services: MakeServices,
) -> None:
    services, _ = make_services({OIL_FILTER: "partxref/oil_filter_11427953129_e90.html"})
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "vehicle rows on a page without a series" in result.content[0].text


async def test_unexpected_page_structure_is_reported(make_services: MakeServices) -> None:
    services, _ = make_services({OIL_FILTER: Route(fixture=None)})  # empty 200 page
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "did not have the expected structure" in result.content[0].text


async def test_unparseable_page_is_not_kept_in_the_cache(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: Route(fixture=None)})  # empty 200 page
    first = await _lookup(services, part_number="11427953129")
    second = await _lookup(services, part_number="11427953129")
    assert (first.is_error, second.is_error) == (True, True)
    assert len(transport.requests) == 2  # the broken page was not served from the cache


async def test_bot_challenge_is_reported(make_services: MakeServices) -> None:
    challenge = Route(
        fixture="common/cloudflare_challenge.html",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    services, transport = make_services({OIL_FILTER: challenge})
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "bot challenge" in result.content[0].text
    assert len(transport.requests) == 1  # never retried


async def test_fetch_part_xref_for_other_features(make_services: MakeServices) -> None:
    missing = url("partxref", q="11426666661")
    services, transport = make_services(
        {
            OIL_FILTER: "partxref/oil_filter_11427953129.html",
            missing: "partxref/not_found_11426666661.html",
        }
    )
    xref, page = await fetch_part_xref(services, "11427953129")
    assert xref is not None and xref.part_number == "11427953129"
    assert (page.url, page.from_cache) == (OIL_FILTER, False)
    none, page = await fetch_part_xref(services, "11426666661")
    assert (none, page.url) == (None, missing)
    with pytest.raises(InvalidInput):
        await fetch_part_xref(services, "abc")
    assert len(transport.requests) == 2
