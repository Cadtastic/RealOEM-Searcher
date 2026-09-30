from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import LANDING_URL, MakeServices, Route, url

pytestmark = pytest.mark.anyio

DATED = "VB13-USA-10-2005-E90-BMW-325i"  # E90 325i built 10/2005, as decode_vin returns
UNDATED = "VB13-USA---E90-BMW-325i"  # id the other two captures were requested with
UNKNOWN_VEHICLE = "ZZ99-USA-01-1990-E90-BMW-325i"
CURRENT = url("partsearch", id=DATED, q="11427953129")
PREDECESSOR = url("partsearch", id=UNDATED, q="11427566327")
NOT_ON_VEHICLE = url("partsearch", id=UNDATED, q="11427622446")
ROUTES = {
    CURRENT: "partsearch/e90_325i_200510_oil_filter_11427953129.html",
    PREDECESSOR: "partsearch/e90_325i_predecessor_11427566327.html",
    NOT_ON_VEHICLE: "partsearch/e90_325i_not_on_vehicle_11427622446.html",
}


def _diagrams(vehicle_id: str) -> list[dict[str, str]]:
    return [
        {
            "vehicle_id": vehicle_id,
            "diag_id": diag_id,
            "name": name,
            "url": url("showparts", id=vehicle_id, diagId=diag_id),
        }
        for diag_id, name in [
            ("02_0092", "Engine oil / maintenance service"),
            ("11_3867", "Lubrication system-Oil filter"),
        ]
    ]


async def _call(services: Services, **arguments: Any) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("check_fitment", arguments)


async def _data(services: Services, **arguments: Any) -> dict[str, Any]:
    result = await _call(services, **arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def _error(services: Services, **arguments: Any) -> str:
    result = await _call(services, **arguments)
    assert result.is_error is True
    return result.content[0].text


def _numbers(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["part_number"] for entry in entries]


async def test_part_that_fits(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    data = await _data(services, part_number="11 42 7 953 129", vehicle_id=DATED)
    assert (data["query"], data["vehicle_id"], data["fits"]) == ("11427953129", DATED, True)
    assert data["used_part_numbers"] == ["11427953129"]
    assert (data["description"], data["price_usd"]) == ("Set oil-filter element", None)
    assert data["diagrams"] == _diagrams(DATED)
    assert data["superseded_by"] == []
    assert _numbers(data["supersedes"]) == ["11428683196", "11427566327", "11427541827"]
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == (
        [CURRENT],
        False,
        1,
    )
    assert [str(r.url) for r in transport.requests] == [CURRENT]


async def test_predecessor_resolves_to_the_number_the_vehicle_uses(
    make_services: MakeServices,
) -> None:
    services, _ = make_services(ROUTES)
    data = await _data(services, part_number="11427566327", vehicle_id=UNDATED)
    assert (data["query"], data["fits"]) == ("11427566327", True)
    assert data["used_part_numbers"] == ["11427953129"]
    assert data["price_usd"] == 12.25
    assert data["diagrams"] == _diagrams(UNDATED)
    assert _numbers(data["superseded_by"]) == ["11428683196", "11427953129"]
    assert data["superseded_by"][1]["valid_to"] is None


async def test_known_part_not_on_the_vehicle(make_services: MakeServices) -> None:
    services, _ = make_services(ROUTES)
    data = await _data(services, part_number="11427622446", vehicle_id=UNDATED)
    assert (data["fits"], data["used_part_numbers"], data["diagrams"]) == (False, [], [])
    assert data["description"] == "Set oil-filter element"
    assert _numbers(data["supersedes"]) == ["11427557012"]


async def test_seven_digit_short_form(make_services: MakeServices) -> None:
    # synthetic: RealOEM matches the last 7 digits, so it serves 11427953129's page for 7953129
    short = url("partsearch", id=DATED, q="7953129")
    services, _ = make_services({short: ROUTES[CURRENT]})
    data = await _data(services, part_number="795-3129", vehicle_id=DATED)
    assert (data["query"], data["fits"], data["used_part_numbers"]) == (
        "7953129",
        True,
        ["11427953129"],
    )


async def test_last_seven_digit_false_match_is_not_found(make_services: MakeServices) -> None:
    # synthetic: RealOEM matches the last 7 digits, so it serves 11427953129's page for 21427953129
    wrong = url("partsearch", id=DATED, q="21427953129")
    services, transport = make_services({wrong: ROUTES[CURRENT]})
    message = await _error(services, part_number="21427953129", vehicle_id=DATED)
    assert message.endswith(
        "RealOEM does not know part 21427953129. Check the number with lookup_part; enter all "
        "11 digits if you used the 7-digit short form."
    )
    assert [str(r.url) for r in transport.requests] == [wrong]


async def test_unknown_part_is_not_found_and_not_cached(make_services: MakeServices) -> None:
    # site notes 3.8: RealOEM redirects an unknown part to the vehicle's page with nfpn=<part>
    unknown = url("partsearch", id=DATED, q="11426666661")
    target = url("partgrp", id=DATED, nfpn="11426666661")
    services, transport = make_services({unknown: Route(redirect_to=target)})
    for _ in range(2):
        message = await _error(services, part_number="11426666661", vehicle_id=DATED)
        assert message.endswith(
            "RealOEM does not know part 11426666661. Check the number with lookup_part; enter all "
            "11 digits if you used the 7-digit short form."
        )
    assert [str(r.url) for r in transport.requests] == [unknown, target] * 2


@pytest.mark.parametrize(
    "target",
    [url("select"), LANDING_URL],  # site notes 3.8 observed select; landing page as for partgrp
    ids=["select-page", "landing-page"],
)
async def test_unknown_vehicle_is_not_found_and_not_cached(
    make_services: MakeServices, target: str
) -> None:
    missing = url("partsearch", id=UNKNOWN_VEHICLE, q="11427953129")
    services, transport = make_services({missing: Route(redirect_to=target)})
    for _ in range(2):
        message = await _error(services, part_number="11427953129", vehicle_id=UNKNOWN_VEHICLE)
        assert message.endswith(
            f"RealOEM has no vehicle {UNKNOWN_VEHICLE}. Use a vehicle id from decode_vin or "
            "select_vehicle."
        )
    assert [str(r.url) for r in transport.requests] == [missing, target] * 2


async def test_unparseable_page_is_an_error_and_not_kept_in_the_cache(
    make_services: MakeServices,
) -> None:
    services, transport = make_services({CURRENT: "partgrp/e90_325i_mg11.html"})
    for _ in range(2):
        message = await _error(services, part_number="11427953129", vehicle_id=DATED)
        assert "RealOEM's partsearch page did not have the expected structure" in message
        assert "missing 'div.content > h1'" in message
    assert [str(r.url) for r in transport.requests] == [CURRENT, CURRENT]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"part_number": "1142795312", "vehicle_id": DATED}, "is not a BMW part number"),
        ({"part_number": "abc", "vehicle_id": DATED}, "is not a BMW part number"),
        ({"part_number": "11427953129", "vehicle_id": "VB13"}, "is not a RealOEM vehicle id"),
        ({"part_number": "11427953129", "vehicle_id": " "}, "The vehicle id is empty."),
    ],
    ids=["ten-digits", "letters", "type-code-only", "empty-vehicle"],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, str], expected: str
) -> None:
    services, transport = make_services(ROUTES)
    assert expected in await _error(services, **arguments)
    assert transport.requests == []


async def test_repeat_check_uses_the_cache_until_refresh(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    await _data(services, part_number="11427566327", vehicle_id=UNDATED)
    cached = await _data(services, part_number="11427566327", vehicle_id=UNDATED)
    assert (cached["from_cache"], cached["requests_made"]) == (True, 0)
    fresh = await _data(services, part_number="11427566327", vehicle_id=UNDATED, refresh=True)
    assert (fresh["from_cache"], fresh["requests_made"]) == (False, 1)
    assert [str(r.url) for r in transport.requests] == [PREDECESSOR, PREDECESSOR]
