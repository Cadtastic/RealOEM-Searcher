import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import LANDING_URL, Route, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
K50 = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
GARBAGE = "VB13-USA-03-2006-XXX-YYY-ZZZ"
UNKNOWN = "VB13-USA-01-1990-E90-BMW-325i"  # well-formed; see the redirect routes below
GROUPS_E90 = url("partgrp", id=E90)
DIAGRAMS_E90 = url("partgrp", id=E90, mg="11")
ROUTES = {
    GROUPS_E90: "common/partgrp_e90_325i.html",
    url("partgrp", id=GARBAGE): "partgrp/e90_325i_garbage_suffix.html",
    url("partgrp", id=K50): "partgrp/k50_r1250gs.html",
    DIAGRAMS_E90: "partgrp/e90_325i_mg11.html",
    url("partgrp", id=K50, mg="11"): "partgrp/k50_r1250gs_mg11.html",
    # RealOEM answers with a redirect to the landing page for ids it doesn't know.
    url("partgrp", id=UNKNOWN): Route(redirect_to=LANDING_URL),
    url("partgrp", id=UNKNOWN, mg="11"): Route(redirect_to=LANDING_URL),
}


async def _call(services: Services, tool: str, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def _error(services: Services, tool: str, **arguments: Any) -> str:
    async with Client(build_server(services)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error is True
    return result.content[0].text


async def test_list_part_groups_returns_specs_and_main_groups(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=E90)
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == (
        [GROUPS_E90],
        False,
        1,
    )
    assert data["specs"] == {
        "vehicle": {
            "vehicle_id": E90,
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "model_name": "3 Series E90 325i",
        "body": "Sedan",
        "engine": "N52",
        "steering": "Left-hand drive",
        "transmission": None,
    }
    assert len(data["main_groups"]) == 39
    assert data["main_groups"][4] == {"mg": "11", "name": "ENGINE"}
    assert [str(r.url) for r in transport.requests] == [GROUPS_E90]


async def test_list_part_groups_reports_the_canonical_vehicle_id(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=GARBAGE)
    assert data["source_urls"] == [url("partgrp", id=GARBAGE)]
    assert data["specs"]["vehicle"]["vehicle_id"] == "VB13-USA-03-2006-E90-BMW-325i"


async def test_list_part_groups_for_a_motorcycle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=K50)
    assert data["specs"]["vehicle"]["brand"] == "motorrad"
    assert data["specs"]["body"] is None
    assert data["main_groups"][-1] == {
        "mg": "77",
        "name": "OPTIONAL EQUIPMENT+ACCESSORIES, MOTORRAD",
    }


async def test_list_diagrams_returns_subgroups_with_diagram_refs(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_diagrams", vehicle_id=E90, main_group="11")
    assert (data["vehicle_id"], data["main_group"], data["source_urls"]) == (
        E90,
        "11",
        [DIAGRAMS_E90],
    )
    assert [subgroup["code"] for subgroup in data["subgroups"]] == [
        "05",
        "10",
        "15",
        "18",
        "20",
        "25",
        "30",
        "35",
        "40",
        "45",
        "88",
    ]
    assert data["subgroups"][6]["diagrams"][2] == {
        "diagram": {
            "vehicle_id": E90,
            "diag_id": "11_3867",
            "name": "LUBRICATION SYSTEM-OIL FILTER",
            "url": url("showparts", id=E90, diagId="11_3867"),
        },
        "thumbnail_url": "https://www.realoem.com/bmw/images/thumb_4ipx.jpg",
    }


async def test_list_diagrams_dedupes_motorrad_names(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_diagrams", vehicle_id=K50, main_group="11")
    first = data["subgroups"][0]
    assert first["name"] == "Engine / Running Gear"
    assert first["diagrams"][1]["diagram"]["name"] == "SHORT ENGINE / CYLINDER WITH PISTONS"


@pytest.mark.parametrize(
    ("tool", "arguments", "requested"),
    [
        ("list_part_groups", {}, url("partgrp", id=UNKNOWN)),
        ("list_diagrams", {"main_group": "11"}, url("partgrp", id=UNKNOWN, mg="11")),
    ],
)
async def test_unknown_vehicle_is_not_found_and_not_cached(
    make_services, tool: str, arguments: dict[str, str], requested: str
) -> None:
    services, transport = make_services(ROUTES)
    for _ in range(2):
        message = await _error(services, tool, vehicle_id=UNKNOWN, **arguments)
        assert message.endswith(
            f"RealOEM has no vehicle {UNKNOWN}. Use a vehicle id from decode_vin or select_vehicle."
        )
    assert [str(r.url) for r in transport.requests] == [requested, LANDING_URL] * 2


async def test_missing_main_group_is_not_found_and_cached_for_a_day(make_services) -> None:
    target = url("partgrp", id=E90, mg="99")
    services, transport = make_services({target: "partgrp/e90_325i_mg99.html"})
    for _ in range(2):
        message = await _error(services, "list_diagrams", vehicle_id=E90, main_group="99")
        assert message.endswith(
            f"vehicle {E90} has no main group 99; list_part_groups shows the ones it has."
        )
    assert [str(r.url) for r in transport.requests] == [target]  # the second call hit the cache
    with closing(sqlite3.connect(services.cache.path)) as conn:
        fetched_at, expires_at = conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (target,)
        ).fetchone()
    assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at) == timedelta(
        days=1
    )


async def test_diagram_list_without_diagrams_is_not_found(make_services, tmp_path: Path) -> None:
    empty = re.sub(
        r'(<div class="diagThumbs">).*?(<div class="blk gad-tall-right">)',
        r"\1</div></div>\2",
        load_fixture("partgrp/e90_325i_mg11.html"),
        flags=re.DOTALL,
    )
    page = tmp_path / "partgrp_mg11_empty.html"
    page.write_text(empty, encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    services, _ = make_services({DIAGRAMS_E90: str(page)})
    message = await _error(services, "list_diagrams", vehicle_id=E90, main_group="11")
    assert message.endswith(
        f"vehicle {E90} has no main group 11; list_part_groups shows the ones it has."
    )


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("list_part_groups", {"vehicle_id": ""}, "The vehicle id is empty."),
        ("list_part_groups", {"vehicle_id": "VB13"}, "'VB13' is not a RealOEM vehicle id"),
        ("list_diagrams", {"vehicle_id": E90, "main_group": "1"}, "main_group must be a two-digit"),
        ("list_diagrams", {"vehicle_id": E90, "main_group": "ENGINE"}, "main_group must be"),
        ("list_diagrams", {"vehicle_id": "E90 325i", "main_group": "11"}, "not a RealOEM vehicle"),
    ],
    ids=["empty-id", "id-without-market", "short-mg", "named-mg", "bad-id"],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services, tool: str, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services(ROUTES)
    assert message in await _error(services, tool, **arguments)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("tool", "arguments", "target", "fixture"),
    [
        ("list_part_groups", {}, GROUPS_E90, "partgrp/e90_325i_mg11.html"),
        (
            "list_diagrams",
            {"main_group": "11"},
            DIAGRAMS_E90,
            "partgrp/e90_325i_mg11_textmode.html",
        ),
    ],
)
async def test_unparseable_page_is_an_error_and_not_kept_in_the_cache(
    make_services, tool: str, arguments: dict[str, str], target: str, fixture: str
) -> None:
    services, transport = make_services({target: fixture})
    for _ in range(2):
        message = await _error(services, tool, vehicle_id=E90, **arguments)
        assert "RealOEM's partgrp page did not have the expected structure" in message
    assert [str(r.url) for r in transport.requests] == [target, target]
