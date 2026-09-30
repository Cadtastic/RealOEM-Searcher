"""Full VINs: the manufacturer prefix (WMI) is checked against the decoded brand (PRD F2.3).

The 17-character VINs below are made up: a real prefix, zeros, and a captured last-7 serial.
"""

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from tests.harness import url

pytestmark = pytest.mark.anyio

ROUTES = {
    url("select", vin="PX22770"): "select/vin_bmw_e93_px22770.html",
    url("select", vin="TD86476"): "select/vin_mini_r53_td86476.html",
    url("select", vin="UX52589"): "select/vin_rr_ghost_ux52589.html",
    url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
    url("select", vin="ZZZZZZZ"): "select/vin_miss_zzzzzzz.html",
    url("select", vin="TEST001"): "select/vin_bmw_e93_px22770.html",  # made-up serial
}


async def _decode(make_services, vin: str) -> dict:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin})
    assert result.is_error is False, result.content
    return result.structured_content


@pytest.mark.parametrize(
    ("vin", "brand"),
    [
        ("WBA0000000PX22770", "bmw"),
        ("WBS0000000PX22770", "bmw"),
        ("5UX0000000PX22770", "bmw"),
        ("LBV0000000TEST001", "bmw"),
        ("WBX0000000TEST001", "bmw"),
        ("WMW0000000TD86476", "mini"),
        ("SCA0000000UX52589", "rolls-royce"),
        ("WB10000000Z656595", "motorrad"),
    ],
)
async def test_matching_prefix_is_normal_confidence(make_services, vin: str, brand: str) -> None:
    data = await _decode(make_services, vin)
    assert data["vehicle"]["brand"] == brand
    assert (data["confidence"], data["warnings"]) == ("normal", [])


async def test_prefix_of_another_brand_is_low_confidence(make_services) -> None:
    data = await _decode(make_services, "WMW0000000PX22770")
    assert data["status"] == "found"
    assert data["vehicle"]["brand"] == "bmw"
    assert data["confidence"] == "low"
    assert data["warnings"] == [
        "The VIN's manufacturer prefix WMW belongs to MINI, but RealOEM matched serial PX22770 "
        "to a BMW vehicle; it is probably a different vehicle with the same last 7 characters."
    ]


async def test_car_prefix_on_a_motorcycle_serial_is_low_confidence(make_services) -> None:
    data = await _decode(make_services, "WBA0000000Z656595")
    assert data["vehicle"]["brand"] == "motorrad"
    assert data["confidence"] == "low"
    (warning,) = data["warnings"]
    assert "belongs to BMW, but RealOEM matched serial Z656595 to a BMW Motorrad vehicle" in warning


async def test_unrecognized_prefix_keeps_normal_confidence_with_a_warning(make_services) -> None:
    data = await _decode(make_services, "JHM0000000PX22770")
    assert data["vehicle"]["brand"] == "bmw"
    assert data["confidence"] == "normal"
    assert data["warnings"] == [
        "Unrecognized manufacturer prefix JHM: it is not a known BMW, MINI, Rolls-Royce or "
        "BMW Motorrad prefix."
    ]


async def test_unrecognized_prefix_is_reported_even_when_not_found(make_services) -> None:
    data = await _decode(make_services, "JHM0000000ZZZZZZZ")
    assert (data["status"], data["confidence"]) == ("not_found", "normal")
    assert data["warnings"][0].startswith("Unrecognized manufacturer prefix JHM")


async def test_seven_characters_skip_the_prefix_check(make_services) -> None:
    data = await _decode(make_services, "TD86476")
    assert (data["confidence"], data["warnings"]) == ("normal", [])
