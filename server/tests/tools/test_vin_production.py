"""include_production=true: one extra production?vin= request (PRD F2.4)."""

from datetime import timedelta

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import url
from tests.tools.test_vin_cache import cache_lifetime

pytestmark = pytest.mark.anyio

SELECT = url("select", vin="PX22770")
PRODUCTION = url("production", vin="PX22770")
SELECT_MISS = url("select", vin="ZZZZZZZ")


async def _decode(services: Services, vin: str) -> dict:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin, "include_production": True})
    assert result.is_error is False, result.content
    return result.structured_content


async def test_include_production_parameter_defaults_to_false(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert tools["decode_vin"].input_schema["properties"]["include_production"]["default"] is False


async def test_production_statistics_are_added(make_services) -> None:
    services, transport = make_services(
        {
            SELECT: "select/vin_bmw_e93_px22770.html",
            PRODUCTION: "production/vin_bmw_e93_px22770.html",
        }
    )
    data = await _decode(services, "PX22770")
    assert data["production"] == {
        "built_month": "2008-07",
        "seq_in_month": 321,
        "total_in_month": 547,
        "seq_in_type": 12557,
        "total_in_type": 17781,
    }
    assert data["source_urls"] == [SELECT, PRODUCTION]
    assert (data["requests_made"], data["warnings"]) == (2, [])
    assert [str(request.url) for request in transport.requests] == [SELECT, PRODUCTION]
    assert cache_lifetime(services, PRODUCTION) == timedelta(days=180)


async def test_production_miss_is_a_warning_cached_for_1_day(make_services) -> None:
    services, _ = make_services(
        {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "production/vin_miss_zzzzzzz.html"}
    )
    data = await _decode(services, "PX22770")
    assert data["status"] == "found"
    assert data["production"] is None
    assert data["warnings"] == ["RealOEM has no production record for serial PX22770."]
    assert cache_lifetime(services, PRODUCTION) == timedelta(days=1)
    assert cache_lifetime(services, SELECT) == timedelta(days=180)


async def test_production_record_for_another_type_is_left_out(make_services) -> None:
    services, _ = make_services(
        {
            SELECT: "select/vin_bmw_e93_px22770.html",
            PRODUCTION: "production/vin_mini_r53_td86476.html",
        }
    )
    data = await _decode(services, "PX22770")
    assert data["production"] is None
    assert data["warnings"] == [
        "RealOEM's production record for serial PX22770 is for type RE33, not the decoded type "
        "WL13; build statistics were left out."
    ]


async def test_motorcycle_production(make_services) -> None:
    services, _ = make_services(
        {
            url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
            url("production", vin="Z656595"): "production/vin_moto_r1200gs_z656595.html",
        }
    )
    data = await _decode(services, "WB10000000Z656595")
    assert data["production"]["built_month"] == "2017-09"
    assert (data["production"]["seq_in_month"], data["production"]["total_in_month"]) == (73, 246)


async def test_unparseable_production_page_fails_and_is_not_kept(make_services) -> None:
    services, transport = make_services(
        {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "select/vin_miss_zzzzzzz.html"}
    )
    async with Client(build_server(services)) as client:
        for _ in range(2):
            result = await client.call_tool(
                "decode_vin", {"vin": "PX22770", "include_production": True}
            )
            assert result.is_error is True
            assert "missing '#ps-vin-result'" in result.content[0].text
    assert [str(request.url) for request in transport.requests] == [SELECT, PRODUCTION, PRODUCTION]


async def test_no_production_request_when_the_vin_is_not_found(make_services) -> None:
    services, transport = make_services({SELECT_MISS: "select/vin_miss_zzzzzzz.html"})
    data = await _decode(services, "ZZZZZZZ")
    assert (data["status"], data["production"], data["requests_made"]) == ("not_found", None, 1)
    assert [str(request.url) for request in transport.requests] == [SELECT_MISS]
