from typing import Any

import pytest
from mcp import Client

from realoem_mcp.errors import InvalidInput, NotFound
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.tools.catalog import fetch_diagram_list, fetch_diagram_parts
from tests.harness import LANDING_URL, Route, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
XREF_ID = "VB13-USA-02_2004_E90_BMW_325i"  # form used by lookup_part model rows
UNKNOWN = "VB13-USA-01-1990-E90-BMW-325i"  # well-formed; see the redirect route below
OIL_PAN = url("showparts", id=E90, diagId="11_3733")
ENGINE = url("partgrp", id=E90, mg="11")
ROUTES = {
    OIL_PAN: "showparts/e90_325i_11_3733.html",
    url("showparts", id=XREF_ID, diagId="11_3867"): "showparts/e90_325i_xref_id_11_3867.html",
    # RealOEM answers with a redirect to the landing page for ids it doesn't know.
    url("showparts", id=UNKNOWN, diagId="11_3733"): Route(redirect_to=LANDING_URL),
    ENGINE: "partgrp/e90_325i_mg11.html",
}


async def _call(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("get_diagram_parts", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def _error(services: Services, **arguments: Any) -> str:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("get_diagram_parts", arguments)
    assert result.is_error is True
    return result.content[0].text


async def test_get_diagram_parts_returns_image_hotspots_rows_and_legend(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, vehicle_id=E90, diag_id="11_3733")
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == ([OIL_PAN], False, 1)
    assert data["diagram"] == {
        "vehicle_id": E90,
        "diag_id": "11_3733",
        "name": "Oil Pan",
        "url": OIL_PAN,
    }
    assert (data["image_url"], data["image_width"], data["image_height"]) == (
        "https://www.realoem.com/bmw/images/diag_2zas.jpg",
        640,
        448,
    )
    assert data["hotspots"][0] == {"position": "01", "x1": 78, "y1": 255, "x2": 87, "y2": 271}
    assert len(data["hotspots"]) == 13
    assert len(data["rows"]) == 13
    assert data["rows"][0] == {
        "position": "01",
        "description": "Oil Pan",
        "supplement": None,
        "qty": "1",
        "valid_from": None,
        "valid_to": None,
        "part_number": "11137552414",
        "price_usd": 551.84,
        "notes": "+core",
        "has_photo": False,
        "indent": 2,
        "conditions": [
            {
                "text": "For vehicles with Automatic transmission",
                "option_codes": [{"code": "S205A", "value": "Yes"}],
            }
        ],
    }
    assert data["notes_legend"] == {
        "+core": "plus core charge (possibility of a return of the old part)"
    }
    assert [str(r.url) for r in transport.requests] == [OIL_PAN]


async def test_vehicle_ids_from_part_lookups_are_accepted(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, vehicle_id=XREF_ID, diag_id="11_3867")
    assert data["diagram"]["vehicle_id"] == XREF_ID
    assert data["rows"][2]["part_number"] == "11427953129"
    assert [str(r.url) for r in transport.requests] == [
        url("showparts", id=XREF_ID, diagId="11_3867")
    ]


async def test_unknown_vehicle_is_not_found_and_not_cached(make_services) -> None:
    services, transport = make_services(ROUTES)
    for _ in range(2):
        message = await _error(services, vehicle_id=UNKNOWN, diag_id="11_3733")
        assert message.endswith(
            f"RealOEM has no vehicle {UNKNOWN}. Use a vehicle id from decode_vin or select_vehicle."
        )
    requested = url("showparts", id=UNKNOWN, diagId="11_3733")
    assert [str(r.url) for r in transport.requests] == [requested, LANDING_URL] * 2


@pytest.mark.parametrize("diag_id", ["11-3733", "3733", "11_", "ab_3733", "11_3733#x"])
async def test_bad_diag_id_is_rejected_before_any_request(make_services, diag_id: str) -> None:
    services, transport = make_services(ROUTES)
    message = await _error(services, vehicle_id=E90, diag_id=diag_id)
    assert "diag_id looks like 11_3733" in message
    assert transport.requests == []


async def test_unparseable_parts_page_is_an_error_and_not_kept_in_the_cache(
    make_services,
) -> None:
    services, transport = make_services({OIL_PAN: "partgrp/e90_325i_mg11.html"})
    for _ in range(2):
        message = await _error(services, vehicle_id=E90, diag_id="11_3733")
        assert "RealOEM's showparts page did not have the expected structure" in message
    assert [str(r.url) for r in transport.requests] == [OIL_PAN, OIL_PAN]


async def test_fetch_diagram_parts_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await fetch_diagram_parts(services, E90, "11_3733", cache_only=True) is None
    assert transport.requests == []
    fetched = await fetch_diagram_parts(services, E90, "11_3733")
    assert fetched is not None
    assert (fetched[0].requests_made, fetched[1].from_cache) == (1, False)
    cached = await fetch_diagram_parts(services, E90, "11_3733", cache_only=True)
    assert cached is not None
    result, page = cached
    assert (result.from_cache, result.requests_made, page.url) == (True, 0, OIL_PAN)
    assert result.rows == fetched[0].rows
    assert len(transport.requests) == 1


async def test_fetch_diagram_list_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await fetch_diagram_list(services, E90, "11", cache_only=True) is None
    assert transport.requests == []
    async with Client(build_server(services)) as client:
        await client.call_tool("list_diagrams", {"vehicle_id": E90, "main_group": "11"})
    cached = await fetch_diagram_list(services, E90, "11", cache_only=True)
    assert cached is not None
    result, page = cached
    assert (result.from_cache, result.requests_made, page.url) == (True, 0, ENGINE)
    assert (result.vehicle_id, result.main_group, len(result.subgroups)) == (E90, "11", 11)
    assert len(transport.requests) == 1


async def test_fetch_helpers_validate_input_even_when_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    with pytest.raises(InvalidInput):
        await fetch_diagram_list(services, E90, "ENGINE", cache_only=True)
    with pytest.raises(InvalidInput):
        await fetch_diagram_parts(services, "VB13", "11_3733", cache_only=True)
    with pytest.raises(NotFound):
        await fetch_diagram_parts(services, UNKNOWN, "11_3733")
    assert [str(r.url) for r in transport.requests] == [
        url("showparts", id=UNKNOWN, diagId="11_3733"),
        LANDING_URL,
    ]
