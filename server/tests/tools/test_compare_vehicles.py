from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
E90_0806 = "VB13-USA-08-2006-E90-BMW-325i"  # same car built 08/2006
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
LIST_E90 = url("partgrp", id=E90, mg="11")
LIST_0806 = url("partgrp", id=E90_0806, mg="11")
LIST_R56 = url("partgrp", id=R56, mg="11")
PAN_E90 = url("showparts", id=E90, diagId="11_3733")
PAN_0806 = url("showparts", id=E90_0806, diagId="11_3733")
PAN_R56 = url("showparts", id=R56, diagId="11_3910")
ROUTES = {
    LIST_E90: "partgrp/e90_325i_mg11.html",
    # synthetic: only the 10/2005 diagram list was captured; RealOEM lists the same diagrams
    LIST_0806: "partgrp/e90_325i_mg11.html",
    LIST_R56: "partgrp/r56_cooper_s_mg11.html",
    PAN_E90: "showparts/e90_325i_11_3733.html",
    PAN_0806: "showparts/e90_325i_200608_11_3733.html",
    PAN_R56: "showparts/r56_cooper_s_11_3910.html",
}
LOCTITE = "83190404517"
E90_PAN_PARTS = [
    "11137552414",
    LOCTITE,
    "11137535106",
    "07119963151",
    "11137548031",
    "11132210959",
    "11437527133",
    "11427548322",
    "12617607910",
    "12611744292",
    "07119905544",
    "11137543122",
]
R56_PAN_PARTS = [
    "11137550483",
    LOCTITE,
    "11137585928",
    "11137546275",
    "12617546239",
    "11437585970",
    "11437560212",
    "11437586030",
    "11437560211",
    "11317542856",
    "11137578545",
]
SUBGROUP_10 = ["11_3731", "11_3732", "11_3733", "11_3742", "11_3834"]


async def _call(services: Services, **arguments: Any) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("compare_vehicles", arguments)


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


def _sent(transport: Any) -> list[str]:
    return [str(request.url) for request in transport.requests]


async def test_complete_comparison_across_different_diagrams(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    data = await _data(
        services, vehicle_a=E90, vehicle_b=R56, main_group="11", diag_ids=["11_3733", "11_3910"]
    )
    assert data["scope"] == {
        "main_group": "11",
        "subgroup": None,
        "diag_ids": ["11_3733", "11_3910"],
    }
    assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (True, [], [])
    assert (data["ignored_diag_ids_a"], data["ignored_diag_ids_b"]) == (["11_3910"], ["11_3733"])
    assert data["in_both"] == [
        {
            "part_number": LOCTITE,
            "description": "Loctite 5970 liquid sealant",
            "qty_a": ["1"],
            "qty_b": ["1", "1"],  # listed twice on the R56 diagram
        }
    ]
    assert _numbers(data["only_a"]) == [n for n in E90_PAN_PARTS if n != LOCTITE]
    assert _numbers(data["only_b"]) == [n for n in R56_PAN_PARTS if n != LOCTITE]
    assert data["only_a"][4] == {
        "part_number": "11132210959",
        "description": "Set of aluminium screws oil pan",
        "qty": ["1", "1"],
        "diag_ids": ["11_3733"],
    }
    assert data["only_b"][-1] == {
        "part_number": "11137578545",
        "description": "Hex bolt with washer",
        "qty": ["16"],
        "diag_ids": ["11_3910"],
    }
    assert data["source_urls"] == [LIST_E90, LIST_R56, PAN_E90, PAN_R56]
    assert (data["from_cache"], data["requests_made"]) == (False, 4)
    assert _sent(transport) == [LIST_E90, LIST_R56, PAN_E90, PAN_R56]


async def test_production_month_difference(make_services: MakeServices) -> None:
    services, _ = make_services(ROUTES)
    data = await _data(
        services, vehicle_a=E90, vehicle_b=E90_0806, main_group="11", diag_ids=["11_3733"]
    )
    assert data["complete"] is True
    # position 10 is "Up To 04/2006", so the 08/2006 car does not list it
    assert data["only_a"] == [
        {
            "part_number": "07119905544",
            "description": "Hex nut with plate",
            "qty": ["3"],
            "diag_ids": ["11_3733"],
        }
    ]
    assert data["only_b"] == []
    assert _numbers(data["in_both"]) == [n for n in E90_PAN_PARTS if n != "07119905544"]
    assert data["in_both"][5] == {
        "part_number": "11132210959",
        "description": "Set of aluminium screws oil pan",
        "qty_a": ["1", "1"],
        "qty_b": ["1", "1"],
    }


async def test_subgroup_and_diag_ids_intersect(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    data = await _data(
        services,
        vehicle_a=E90,
        vehicle_b=E90_0806,
        main_group="11",
        subgroup="10",
        diag_ids=["11_3733", "11_3867", "11_3733"],
    )
    assert data["scope"] == {
        "main_group": "11",
        "subgroup": "10",
        "diag_ids": ["11_3733", "11_3867"],
    }
    # 11_3867 (oil filter) is in subgroup 30, so it is outside the scope on both vehicles
    assert (data["ignored_diag_ids_a"], data["ignored_diag_ids_b"]) == (["11_3867"], ["11_3867"])
    assert data["complete"] is True
    assert _sent(transport) == [LIST_E90, LIST_0806, PAN_E90, PAN_0806]


async def test_rows_without_part_numbers_are_excluded(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: the 08/2006 oil pan with two part numbers blanked, one changed, one renamed
    html = load_fixture(ROUTES[PAN_0806])
    for old, new in [
        ("<td>11137543122</td>", "<td>--</td>"),
        ("<td>11427548322</td>", "<td></td>"),
        ("<td>12611744292</td>", "<td>12611744293</td>"),
        ('<td class="edge2">Oil Pan</td>', '<td class="edge2">Oil sump</td>'),
    ]:
        assert html.count(old) == 1, old
        html = html.replace(old, new)
    page = tmp_path / "pan_0806.html"
    page.write_text(html, encoding="utf-8")
    services, _ = make_services({**ROUTES, PAN_0806: str(page)})
    data = await _data(
        services, vehicle_a=E90, vehicle_b=E90_0806, main_group="11", diag_ids=["11_3733"]
    )
    assert "--" not in _numbers(data["only_b"])
    assert _numbers(data["only_a"]) == [
        "11427548322",
        "12611744292",
        "07119905544",
        "11137543122",
    ]
    assert data["only_b"] == [
        {
            "part_number": "12611744293",
            "description": "Gasket ring",
            "qty": ["1"],
            "diag_ids": ["11_3733"],
        }
    ]
    assert data["in_both"][0] == {
        "part_number": "11137552414",
        "description": "Oil Pan",  # vehicle A's description wins
        "qty_a": ["1"],
        "qty_b": ["1"],
    }


async def test_subgroup_on_neither_vehicle_is_not_found(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    message = await _error(services, vehicle_a=E90, vehicle_b=R56, main_group="11", subgroup="99")
    assert message.endswith(
        "neither vehicle has subgroup 99 in main group 11; list_diagrams shows the subgroups of "
        "each vehicle."
    )
    assert _sent(transport) == [LIST_E90, LIST_R56]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"vehicle_b": "VB13"}, "'VB13' is not a RealOEM vehicle id"),
        ({"main_group": "ENGINE"}, "main_group must be a two-digit RealOEM main group"),
        ({"subgroup": "Engine Housing"}, "subgroup must be a two-digit subgroup code"),
        ({"diag_ids": ["11-3733"]}, "diag_ids must be diagrams of main group 11"),
        ({"diag_ids": ["34_1234"]}, "diag_ids must be diagrams of main group 11"),
        ({"max_requests": 1}, "max_requests must be between 2 and 60, not 1."),
        ({"max_requests": 61}, "max_requests must be between 2 and 60, not 61."),
    ],
    ids=[
        "vehicle",
        "main-group",
        "subgroup",
        "diag-id",
        "diag-id-other-group",
        "budget-low",
        "budget-high",
    ],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, Any], expected: str
) -> None:
    services, transport = make_services(ROUTES)
    defaults = {"vehicle_a": E90, "vehicle_b": R56, "main_group": "11"}
    assert expected in await _error(services, **{**defaults, **arguments})
    assert transport.requests == []


async def test_budget_spent_on_the_diagram_lists(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    data = await _data(
        services, vehicle_a=E90, vehicle_b=E90_0806, main_group="11", subgroup="10", max_requests=2
    )
    assert data["complete"] is False
    assert (data["unfetched_a"], data["unfetched_b"]) == (SUBGROUP_10, SUBGROUP_10)
    assert (data["in_both"], data["only_a"], data["only_b"]) == ([], [], [])
    assert data["requests_made"] == 2
    assert _sent(transport) == [LIST_E90, LIST_0806]


async def test_diagrams_alternate_between_the_vehicles(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    data = await _data(
        services,
        vehicle_a=E90,
        vehicle_b=E90_0806,
        main_group="11",
        diag_ids=["11_3733", "11_3867"],
        max_requests=4,
    )
    assert _sent(transport) == [LIST_E90, LIST_0806, PAN_E90, PAN_0806]
    assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
        False,
        ["11_3867"],
        ["11_3867"],
    )
    assert len(data["in_both"]) == 11


async def test_rerun_continues_from_the_cache(make_services: MakeServices) -> None:
    services, transport = make_services(ROUTES)
    arguments = {
        "vehicle_a": E90,
        "vehicle_b": R56,
        "main_group": "11",
        "diag_ids": ["11_3733", "11_3910"],
        "max_requests": 3,
    }
    first = await _data(services, **arguments)
    assert (first["complete"], first["unfetched_a"], first["unfetched_b"]) == (
        False,
        [],
        ["11_3910"],
    )
    assert _numbers(first["only_a"]) == E90_PAN_PARTS  # B not read yet: partial result
    assert first["requests_made"] == 3
    second = await _data(services, **arguments)
    assert (second["complete"], second["requests_made"], second["from_cache"]) == (True, 1, False)
    assert _numbers(second["in_both"]) == [LOCTITE]
    third = await _data(services, **arguments)
    assert (third["complete"], third["requests_made"], third["from_cache"]) == (True, 0, True)
    assert third["in_both"] == second["in_both"]
    assert _sent(transport) == [LIST_E90, LIST_R56, PAN_E90, PAN_R56]


async def test_cached_diagrams_are_read_after_the_budget_is_spent(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await client.call_tool("get_diagram_parts", {"vehicle_id": R56, "diag_id": "11_3910"})
    data = await _data(
        services,
        vehicle_a=E90,
        vehicle_b=R56,
        main_group="11",
        diag_ids=["11_3733", "11_3910"],
        max_requests=2,
    )
    assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
        False,
        ["11_3733"],
        [],
    )
    assert _numbers(data["only_b"]) == R56_PAN_PARTS
    assert data["source_urls"] == [LIST_E90, LIST_R56, PAN_R56]
    assert (data["requests_made"], data["from_cache"]) == (2, False)
    assert _sent(transport) == [PAN_R56, LIST_E90, LIST_R56]


async def test_subgroup_on_one_vehicle_only(make_services: MakeServices) -> None:
    services, _ = make_services(ROUTES)
    data = await _data(
        services, vehicle_a=E90, vehicle_b=R56, main_group="11", subgroup="50", max_requests=2
    )
    # the E90 has no subgroup 50 (exhaust manifold) in main group 11; the R56 has three diagrams
    assert (data["unfetched_a"], data["unfetched_b"]) == ([], ["11_3944", "11_3945", "11_6649"])
    assert data["complete"] is False


async def test_refresh_refetches_within_the_budget_and_reads_the_rest_from_cache(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(ROUTES)
    arguments = {
        "vehicle_a": E90,
        "vehicle_b": R56,
        "main_group": "11",
        "diag_ids": ["11_3733", "11_3910"],
    }
    await _data(services, **arguments)  # primes the cache: 4 requests
    data = await _data(services, **arguments, refresh=True, max_requests=3)
    assert (data["complete"], data["requests_made"], data["from_cache"]) == (True, 3, False)
    assert _numbers(data["in_both"]) == [LOCTITE]
    # both lists and A's diagram are refetched; B's diagram comes from the cache
    assert _sent(transport) == [LIST_E90, LIST_R56, PAN_E90, PAN_R56, LIST_E90, LIST_R56, PAN_E90]
