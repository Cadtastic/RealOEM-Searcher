from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import load_fixture, url

pytestmark = pytest.mark.anyio

SELECT_PX22770 = url("select", vin="PX22770")
ROUTES = {
    SELECT_PX22770: "select/vin_bmw_e93_px22770.html",
    url("select", vin="TD86476"): "select/vin_mini_r53_td86476.html",
    url("select", vin="UX52589"): "select/vin_rr_ghost_ux52589.html",
    url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
    url("select", vin="1234567"): "select/vin_e30_classic_1234567.html",
    url("select", vin="ZZZZZZZ"): "select/vin_miss_zzzzzzz.html",
}


async def _decode(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", arguments)
    assert result.is_error is False, result.content
    data = dict(result.structured_content)
    data.pop("fetched_at")
    return data


async def test_decode_vin_is_listed_with_a_required_vin(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools["decode_vin"].input_schema
    assert schema["required"] == ["vin"]
    assert schema["properties"]["refresh"]["default"] is False
    assert "RealOEM's best match" in tools["decode_vin"].description


async def test_bmw_serial_decodes_every_field(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await _decode(services, vin="px22770") == {
        "source_urls": [SELECT_PX22770],
        "from_cache": False,
        "requests_made": 1,
        "serial": "PX22770",
        "status": "found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": {
            "vehicle_id": "WL13-USA-07-2008-E93-BMW-328i",
            "type_code": "WL13",
            "market": "USA",
            "production_month": "2008-07",
            "series": "E93",
            "brand": "bmw",
            "model": "328i",
        },
        "product": "car",
        "catalog": "current",
        "series_name": "3' E93 (2005 — 2010)",
        "body": "Convertible",
        "engine": "N52N",
        "steering": None,
        "transmission": None,
        "production": None,
    }
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770]


@pytest.mark.parametrize(
    ("vin", "vehicle_id", "brand", "expected"),
    [
        (
            "TD86476",
            "RE33-USA-04-2004-R53-Mini-Cooper_S",
            "mini",
            {
                "product": "car",
                "catalog": "classic",
                "series_name": "MINI R53",
                "body": "3 doors",
                "engine": "W11",
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "UX52589",
            "FK43-USA-12-2013-RR4-Rolls_Royce-Ghost",
            "rolls-royce",
            {
                "product": "car",
                "catalog": "current",
                "series_name": "Rolls-Royce Ghost RR4",
                "body": "Sedan",
                "engine": "N74R",
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "Z656595",
            "0A61-USA-09-2017-K50-BMW-R_1200_GS_17_0A51,_0A61_",
            "motorrad",
            {
                "product": "motorcycle",
                "catalog": "current",
                "series_name": "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)",
                "body": None,
                "engine": None,
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "1234567",
            "1251-EUR-11-1986-E30-BMW-325e",
            "bmw",
            {
                "product": "car",
                "catalog": "classic",
                "series_name": "3' E30 (1981 — 1994)",
                "body": "Coupe",
                "engine": "M20",
                "steering": "Left hand drive",
                "transmission": "Manual",
            },
        ),
    ],
    ids=["mini-classic", "rolls-royce", "motorrad", "bmw-classic-e30"],
)
async def test_other_brands_and_catalogs(
    make_services, vin: str, vehicle_id: str, brand: str, expected: dict[str, Any]
) -> None:
    services, _ = make_services(ROUTES)
    data = await _decode(services, vin=vin)
    assert (data["status"], data["confidence"], data["warnings"]) == ("found", "normal", [])
    assert (data["vehicle"]["vehicle_id"], data["vehicle"]["brand"]) == (vehicle_id, brand)
    assert {key: data[key] for key in expected} == expected


async def test_unknown_serial_is_not_found(make_services) -> None:
    services, _ = make_services(ROUTES)
    assert await _decode(services, vin="ZZZZZZZ") == {
        "source_urls": [url("select", vin="ZZZZZZZ")],
        "from_cache": False,
        "requests_made": 1,
        "serial": "ZZZZZZZ",
        "status": "not_found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": None,
        "product": None,
        "catalog": None,
        "series_name": None,
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
        "production": None,
    }


async def test_full_vin_sends_only_the_last_seven(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _decode(services, vin="WBA-0000000-PX22770")
    assert data["serial"] == "PX22770"
    assert data["vehicle"]["vehicle_id"] == "WL13-USA-07-2008-E93-BMW-328i"
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770]


@pytest.mark.parametrize(
    ("vin", "message"),
    [
        ("PX2277", "give all 17 or just the last 7 (got 6)"),
        ("WBA0000000PX2277", "give all 17 or just the last 7 (got 16)"),
        ("PX22770#", "a VIN has only letters and digits"),
        ("PX2277O", "VINs never contain the letters I, O or Q (found O)"),
    ],
)
async def test_malformed_vin_is_rejected_before_any_request(
    make_services, vin: str, message: str
) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin})
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unparseable_page_is_an_error_and_not_kept_in_the_cache(make_services) -> None:
    services, transport = make_services({SELECT_PX22770: "select/vin_bmw_e93_px22770_v1.html"})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("decode_vin", {"vin": "PX22770"})
        second = await client.call_tool("decode_vin", {"vin": "PX22770"})
    for result in (first, second):
        assert result.is_error is True
        assert "RealOEM's select page did not have the expected structure" in result.content[0].text
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770] * 2


async def test_hit_without_a_selected_product_is_a_layout_error(make_services, tmp_path) -> None:
    html = load_fixture("select/vin_bmw_e93_px22770.html").replace(
        '<a class="ro-lb-row is-selected" href="/bmw/enUS/select?archive=0&amp;product=P"',
        '<a class="ro-lb-row" href="/bmw/enUS/select?archive=0&amp;product=P"',
    )
    broken = Path(tmp_path) / "select_without_product.html"
    broken.write_text(html, encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    services, transport = make_services({SELECT_PX22770: str(broken)})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("decode_vin", {"vin": "PX22770"})
        second = await client.call_tool("decode_vin", {"vin": "PX22770"})
    for result in (first, second):
        assert result.is_error is True
        assert "VIN result has no known product selected" in result.content[0].text
    assert len(transport.requests) == 2
