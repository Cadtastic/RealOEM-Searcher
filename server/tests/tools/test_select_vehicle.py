from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import LANDING_URL, Route, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = {"product": "P", "archive": "0", "series": "E90"}
E90_325I = E90 | {"body": "Lim", "model": "325i"}
E90_USA = E90_325I | {"market": "USA", "prod": "20051000"}
E90_EUR = E90_325I | {"market": "EUR", "prod": "20051000"}
K50_MODEL = "R 1250 GS 19 (0J91, 0J93)"
K50_USA = {
    "product": "M",
    "archive": "0",
    "series": "K50",
    "model": K50_MODEL,
    "market": "USA",
    "prod": "20190500",
}
ROUTES = {
    url("select", product="M", archive="0"): "catalog/cascade_motorcycles.html",
    url("select", **E90): "select/cascade_e90.html",
    url("select", **E90_325I): "select/cascade_e90_325i.html",
    url("select", **E90_USA): "catalog/cascade_e90_325i_usa_200510.html",
    url("select", **E90_EUR): "select/cascade_e90_325i_eur_200510.html",
    url("select", product="P", archive="1", series="E46"): "select/cascade_classic_e46.html",
    url("select", **K50_USA): "catalog/cascade_k50_r1250gs_usa_201905.html",
}


def _option(value: str, label: str, *, selected: bool = True) -> dict[str, Any]:
    return {"value": value, "label": label, "selected": selected}


async def _select(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def test_select_vehicle_is_listed_with_levels_in_send_order(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    tool = tools["select_vehicle"]
    assert list(tool.input_schema["properties"]) == [
        "product",
        "archive",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
        "steering",
        "trans",
        "refresh",
    ]
    assert tool.input_schema["properties"]["product"]["default"] == "P"
    assert "catalog, whose parameter is archive" in tool.description


async def test_first_step_lists_series_with_product_and_catalog_auto_selected(
    make_services,
) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, product="M", archive="0")
    assert (data["complete"], data["next_level"]) == (False, "series")
    assert data["selected"] == {
        "product": _option("M", "Motorcycle"),
        "catalog": _option("0", "Current"),
    }
    assert len(data["options"]) == 87
    assert data["options"][2] == _option(
        "K50", "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)", selected=False
    )
    assert (data["vehicle"], data["type_code"], data["summary"]) == (None, None, None)
    assert [str(r.url) for r in transport.requests] == [url("select", product="M", archive="0")]


async def test_product_defaults_to_cars_and_auto_selected_body_is_reported(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, archive="0", series="E90")
    assert data["selected"]["series"] == _option("E90", "3' E90 (2004 — 2023)")
    assert data["selected"]["body"] == _option("Lim", "Sedan")  # the only body: auto-selected
    assert data["next_level"] == "model"
    assert [option["value"] for option in data["options"]][:3] == ["316i", "318d", "318i"]
    assert len(data["options"]) == 20
    assert [str(r.url) for r in transport.requests] == [url("select", **E90)]


async def test_usa_market_is_auto_selected(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_325I)
    assert data["selected"]["market"] == _option("USA", "USA")
    assert data["next_level"] == "prod"
    assert data["options"][0] == _option("20040200", "02/2004", selected=False)
    assert len(data["options"]) == 27


async def test_eur_market_asks_for_steering(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_EUR)
    assert data["selected"]["engine"] == _option("N52", "N52")
    assert data["next_level"] == "steering"
    assert data["options"] == [
        _option("L", "Left hand drive", selected=False),
        _option("R", "Right hand drive", selected=False),
    ]


async def test_classic_catalog_is_sent_as_archive(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, archive="1", series="E46")
    assert data["selected"]["catalog"] == _option("1", "Classic")
    assert data["next_level"] == "body"
    assert [option["value"] for option in data["options"]] == ["Lim", "Cab", "Cou", "com", "tou"]
    assert [str(r.url) for r in transport.requests] == [
        url("select", product="P", archive="1", series="E46")
    ]


async def test_complete_car_selection_returns_the_vehicle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_USA)
    data.pop("fetched_at")
    selected = data.pop("selected")
    assert data == {
        "source_urls": [url("select", **E90_USA)],
        "from_cache": False,
        "requests_made": 1,
        "next_level": None,
        "options": [],
        "complete": True,
        "vehicle": {
            "vehicle_id": "VB13-USA-10-2005-E90-BMW-325i",
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "type_code": "VB13",
        "summary": "3 Series E90 BMW 325i",
    }
    assert {level: option["value"] for level, option in selected.items()} == {
        "product": "P",
        "catalog": "0",
        "series": "E90",
        "body": "Lim",
        "model": "325i",
        "market": "USA",
        "prod": "20051000",
        "engine": "N52",
    }


async def test_complete_motorcycle_selection_is_a_motorrad_vehicle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **K50_USA)
    assert data["complete"] is True
    assert data["vehicle"]["vehicle_id"] == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert data["vehicle"]["brand"] == "motorrad"
    assert data["selected"]["model"] == _option(K50_MODEL, K50_MODEL)
    assert "body" not in data["selected"]


async def test_repeat_call_is_answered_from_the_cache(make_services) -> None:
    services, transport = make_services(ROUTES)
    await _select(services, **E90)
    again = await _select(services, **E90)
    assert (again["from_cache"], again["requests_made"]) == (True, 0)
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"product": "X"}, "Input should be 'P' or 'M'"),
        ({"archive": "2"}, "Input should be '0' or '1'"),
        ({"series": " "}, "series must not be empty"),
        ({"series": "E90", "prod": "10/2005"}, "prod is a production month as YYYYMM00"),
        ({"series": "E90", "prod": "20051300"}, "prod is a production month as YYYYMM00"),
    ],
    ids=["product", "archive", "empty-series", "prod-format", "prod-month"],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unparseable_select_page_is_not_kept_in_the_cache(make_services) -> None:
    target = url("select", **E90)
    services, transport = make_services({target: "select/vin_bmw_e93_px22770_v1.html"})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("select_vehicle", E90)
        second = await client.call_tool("select_vehicle", E90)
    for result in (first, second):
        assert result.is_error is True
        assert "RealOEM's select page did not have the expected structure" in (
            result.content[0].text
        )
    assert [str(r.url) for r in transport.requests] == [target, target]


async def test_redirect_to_the_landing_page_is_not_found(make_services) -> None:
    target = url("select", product="P", archive="0", series="XYZ")
    services, transport = make_services({target: Route(redirect_to=LANDING_URL)})
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", {"archive": "0", "series": "XYZ"})
    assert result.is_error is True
    assert "RealOEM did not show a selection page for these values" in result.content[0].text
    assert [str(r.url) for r in transport.requests] == [target, LANDING_URL]


async def test_page_without_open_level_or_vehicle_is_a_layout_error(
    make_services, tmp_path: Path
) -> None:
    html = load_fixture("catalog/cascade_e90_325i_usa_200510.html")
    assert 'name="id"' in html
    page = tmp_path / "select_without_vehicle.html"
    page.write_text(html.replace('name="id"', 'name="vehicle"'), encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    target = url("select", **E90_USA)
    services, transport = make_services({target: str(page)})
    async with Client(build_server(services)) as client:
        for _ in range(2):
            result = await client.call_tool("select_vehicle", E90_USA)
            assert result.is_error is True
            assert "no open level and no vehicle id" in result.content[0].text
    assert len(transport.requests) == 2
