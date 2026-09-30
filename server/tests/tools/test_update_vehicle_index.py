"""update_vehicle_index via the in-memory MCP client (ARD section 5.11 update algorithm)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.parsers.vehicles import parse_vehicles
from realoem_mcp.server import build_server
from realoem_mcp.tools.vehicles import get_index
from tests.harness import BRANDS_DIR, FixtureTransport, Route, load_fixture, url
from tests.vehicle_data import SyntheticIndex, numbered, vehicle
from tests.vehicle_env import vehicle_services

pytestmark = pytest.mark.anyio

P165 = url("vehicles", page="165", sort="year")
P165_ROWS = parse_vehicles(
    load_fixture("vehicles/sort_year_p165.html"), url=P165, brands=BrandRegistry.load(BRANDS_DIR)
).rows
# 8200 undated (unlinked) rows stand in for pages 1-164 of the real index.
FILLER = [vehicle(f"F{i:04d}", start=None) for i in range(8200)]


@dataclass
class Run:
    updates: list[dict[str, Any]]  # structured result of each update_vehicle_index call
    found: dict[str, Any]  # find_vehicle over linked rows afterwards
    resume: tuple[str | None, int] | None  # stored resume point afterwards


def _page_numbers(transport: FixtureTransport | SyntheticIndex) -> list[str]:
    return [request.url.params["page"] for request in transport.requests]


async def _run(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    baseline: Sequence[IndexedVehicle] | None,
    *calls: dict[str, Any],
) -> Run:
    """Call update_vehicle_index once per argument dict (once with {} by default)."""
    async with (
        vehicle_services(tmp_path, transport, baseline=baseline) as services,
        Client(build_server(services)) as client,
    ):
        updates = []
        for arguments in calls or ({},):
            result = await client.call_tool("update_vehicle_index", arguments)
            assert result.is_error is False, result.content
            updates.append(result.structured_content)
        found = await client.call_tool("find_vehicle", {"limit": 100})
        resume = get_index(services).resume_point()
    return Run(updates, found.structured_content, resume)


async def _error(tmp_path: Path, transport: FixtureTransport, arguments: dict) -> CallToolResult:
    async with (
        vehicle_services(tmp_path, transport, baseline=numbered(1)) as services,
        Client(build_server(services)) as client,
    ):
        return await client.call_tool("update_vehicle_index", arguments)


async def test_up_to_date_costs_one_request(tmp_path: Path) -> None:
    transport = FixtureTransport({P165: "vehicles/sort_year_p165.html"})
    (data,) = (await _run(tmp_path, transport, [*FILLER, *P165_ROWS])).updates
    assert {k: data[k] for k in ("status", "added", "remote_total", "local_total")} == {
        "status": "up_to_date",
        "added": [],
        "remote_total": 8218,
        "local_total": 8218,
    }
    assert (data["pages_fetched"], data["requests_made"], data["from_cache"]) == (1, 1, False)
    assert data["source_urls"] == [P165]
    assert data["message"] == "The vehicle index is up to date (8218 vehicles on RealOEM)."
    assert _page_numbers(transport) == ["165"]


async def test_new_vehicles_on_the_last_page_are_added(tmp_path: Path) -> None:
    transport = FixtureTransport({P165: "vehicles/sort_year_p165.html"})
    run = await _run(tmp_path, transport, [*FILLER, *P165_ROWS[:-3]])  # 3 vehicles are new
    (data,) = run.updates
    assert (data["status"], data["remote_total"], data["local_total"]) == ("updated", 8218, 8218)
    assert [v["key"] for v in data["added"]] == [
        "16GG-IDN-03-2025",
        "17GG-IND-03-2025",
        "64GG-THA-03-2025",
    ]
    assert data["added"][2] == P165_ROWS[-1].model_dump(mode="json")
    assert data["message"] == "Added 3 new vehicle(s); the index now has all 8218."
    assert (data["pages_fetched"], data["requests_made"]) == (1, 1)
    local = [v["key"] for v in run.found["vehicles"] if v["source"] == "local"]
    assert sorted(local) == ["16GG-IDN-03-2025", "17GG-IND-03-2025", "64GG-THA-03-2025"]
    assert run.found["index"]["local_rows"] == 3
    assert run.found["index"]["last_update_at"] is not None


async def test_scan_goes_back_until_pages_are_older_than_the_index(tmp_path: Path) -> None:
    remote = numbered(120)  # pages 1-3; the index has the first 95 rows
    transport = SyntheticIndex(remote)
    (data,) = (await _run(tmp_path, transport, remote[:95])).updates
    assert data["status"] == "updated"
    assert [v["key"] for v in data["added"]] == [row.key for row in remote[95:]]
    # probe = page 2 (ceil(95/50)); scan: page 3, then page 2 again from memory, which starts
    # before the index's newest production month, so the scan stops.
    assert _page_numbers(transport) == ["2", "3"]
    assert (data["pages_fetched"], data["requests_made"], data["local_total"]) == (2, 2, 120)
    assert data["source_urls"] == [
        url("vehicles", page="2", sort="year"),
        url("vehicles", page="3", sort="year"),
    ]


async def test_without_a_baseline_nothing_is_requested(tmp_path: Path) -> None:
    transport = SyntheticIndex(numbered(120))
    (data,) = (await _run(tmp_path, transport, None)).updates
    assert (data["status"], data["added"], data["remote_total"], data["local_total"]) == (
        "drift",
        [],
        0,
        0,
    )
    assert (data["requests_made"], data["pages_fetched"], data["source_urls"]) == (0, 0, [])
    assert data["message"] == (
        "No vehicle index baseline is installed; the maintainer must run "
        "scripts/rebuild_vehicle_index.py."
    )
    assert transport.requests == []


async def test_page_limit_gives_a_partial_update_that_resumes(tmp_path: Path) -> None:
    remote = numbered(300)  # 6 pages; the index has the first 100 rows
    transport = SyntheticIndex(remote)
    run = await _run(tmp_path, transport, remote[:100], {"max_pages": 3}, {"max_pages": 3})
    first, second = run.updates
    assert first["status"] == "partial"
    assert [v["key"] for v in first["added"]] == [row.key for row in remote[200:]]
    assert (first["remote_total"], first["local_total"], first["pages_fetched"]) == (300, 200, 3)
    assert first["message"] == (
        "Added 100 of 200 new vehicles before reaching max_pages=3. "
        "Call update_vehicle_index again to continue from page 4."
    )
    # The second call probes page 4 (ceil(200/50)), resumes the scan there with the old
    # newest start month, and stops at page 2, which starts before it.
    assert second["status"] == "updated"
    assert [v["key"] for v in second["added"]] == [row.key for row in remote[100:200]]
    assert _page_numbers(transport) == ["2", "6", "5", "4", "3", "2"]
    assert (second["local_total"], run.resume) == (300, None)


async def test_partial_without_new_vehicles_suggests_more_pages(tmp_path: Path) -> None:
    remote = numbered(300)
    transport = SyntheticIndex(remote)
    run = await _run(tmp_path, transport, remote[:100], {"max_pages": 1})
    (data,) = run.updates
    assert (data["status"], data["added"], data["pages_fetched"]) == ("partial", [], 1)
    assert data["message"] == (
        "No new vehicles in the 1 page(s) allowed by max_pages=1; 200 are still missing. "
        "Call update_vehicle_index again with a larger max_pages (up to 10) to continue from "
        "page 6."
    )
    assert run.resume == (remote[99].production_from, 6)


async def test_a_back_dated_insert_is_reported_as_drift(tmp_path: Path) -> None:
    baseline = numbered(120)
    inserted = vehicle("X001", start="2001-06", end="2030-12")
    transport = SyntheticIndex(sorted([*baseline, inserted], key=lambda v: v.production_from))
    (data,) = (await _run(tmp_path, transport, baseline)).updates
    assert (data["status"], data["added"], data["remote_total"]) == ("drift", [], 121)
    assert _page_numbers(transport) == ["3"]
    assert "The maintainer should rebuild the baseline" in data["message"]


async def test_a_replaced_row_is_drift_and_the_next_probe_stays_in_range(tmp_path: Path) -> None:
    baseline = numbered(150)
    replaced = vehicle("X149", start=baseline[-1].production_from, end="2030-12")
    transport = SyntheticIndex([*baseline[:-1], replaced])  # still exactly 150 rows
    first, second = (await _run(tmp_path, transport, baseline, {}, {})).updates
    assert (first["status"], [v["key"] for v in first["added"]]) == ("drift", [replaced.key])
    assert (first["remote_total"], first["local_total"]) == (150, 151)
    # 151 local rows would probe page 4, past RealOEM's end; the stored remote total keeps the
    # probe on page 3.
    assert (second["status"], second["added"], second["pages_fetched"]) == ("drift", [], 1)
    assert _page_numbers(transport) == ["3", "3"]


EMPTY_TABLE = '<html><body><table id="vi-table"><tbody></tbody></table></body></html>'
# RealOEM's real answer past its end: the last page's rows again under "Showing 8251-8218".
REPEATED_LAST_PAGE = load_fixture("vehicles/sort_year_past_end.html")


@pytest.mark.parametrize(
    "past_end_html",
    [None, EMPTY_TABLE, REPEATED_LAST_PAGE],
    ids=["no-table", "empty-table", "repeated-last-page"],
)
async def test_a_probe_past_the_end_reads_page_one_and_reports_drift(
    tmp_path: Path, past_end_html: str | None
) -> None:
    baseline = numbered(151)
    transport = SyntheticIndex(baseline[:150])  # one vehicle removed on RealOEM
    transport.past_end_html = past_end_html
    (data,) = (await _run(tmp_path, transport, baseline)).updates
    assert (data["status"], data["added"], data["remote_total"], data["local_total"]) == (
        "drift",
        [],
        150,
        151,
    )
    assert _page_numbers(transport) == ["4", "1"]
    assert (data["requests_made"], data["pages_fetched"]) == (2, 2)
    assert data["message"].startswith("RealOEM lists 150 vehicles, fewer than the 151 in the index")


@pytest.mark.parametrize("max_pages", [0, 11])
async def test_max_pages_is_validated_before_any_request(tmp_path: Path, max_pages: int) -> None:
    transport = FixtureTransport({})
    result = await _error(tmp_path, transport, {"max_pages": max_pages})
    assert result.is_error is True
    assert result.content[0].text.endswith(f"max_pages must be between 1 and 10, got {max_pages}.")
    assert transport.requests == []


async def test_an_unparseable_page_is_not_kept_in_the_cache(tmp_path: Path) -> None:
    page_one = url("vehicles", page="1", sort="year")
    transport = FixtureTransport({page_one: Route("common/partgrp_e90_325i.html")})
    async with (
        vehicle_services(tmp_path, transport, baseline=numbered(1)) as services,
        Client(build_server(services)) as client,
    ):
        first = await client.call_tool("update_vehicle_index", {})
        assert services.cache.get(page_one) is None
        second = await client.call_tool("update_vehicle_index", {})
    assert first.is_error is True and second.is_error is True
    assert "vehicles page did not have the expected structure" in first.content[0].text
    assert len(transport.requests) == 2
