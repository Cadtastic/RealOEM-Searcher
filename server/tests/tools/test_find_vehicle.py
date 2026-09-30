"""find_vehicle via the in-memory MCP client: local search only, never a request."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.server import build_server
from realoem_mcp.tools.vehicles import INDEX_KEY
from realoem_mcp.vehicle_index import VehicleIndex
from tests.harness import FixtureTransport
from tests.vehicle_data import vehicle
from tests.vehicle_env import vehicle_services

pytestmark = pytest.mark.anyio


def _gs(type_code: str, market: str) -> IndexedVehicle:
    return vehicle(
        type_code,
        market,
        "2018-09",
        "2025-03",
        brand="motorrad",
        series_code="K50",
        model_name="R 1250 GS",
        series_label="K50 (R 1200 GS, R 1250 GS)",
        body=None,
        source="baseline",
    )


GS, GS_EUR = _gs("0J91", "USA"), _gs("0J93", "EUR")
E90 = vehicle("VB13", "USA", "2005-10", "2008-02", source="baseline")


async def _find(
    tmp_path: Path, baseline: Sequence[IndexedVehicle] | None, arguments: dict[str, Any]
) -> CallToolResult:
    transport = FixtureTransport({})
    async with (
        vehicle_services(tmp_path, transport, baseline=baseline) as services,
        Client(build_server(services)) as client,
    ):
        result = await client.call_tool("find_vehicle", arguments)
    assert transport.requests == []  # never touches RealOEM
    return result


async def test_find_vehicle_searches_the_local_index(tmp_path: Path) -> None:
    arguments = {"query": "r 1250 gs", "year": 2019, "brand": "motorrad"}
    result = await _find(tmp_path, [GS, E90], arguments)
    assert result.is_error is False
    data = result.structured_content
    assert data["total_matches"] == 1
    (found,) = data["vehicles"]
    assert found == GS.model_dump(mode="json")
    assert found["vehicle"]["vehicle_id"] == "0J91-USA-09-2018-K50-BMW-R_1250_GS"
    assert data["index"] == {
        "built_at": "2026-09-30",
        "baseline_total": 2,
        "local_rows": 0,
        "last_update_at": None,
    }
    assert "source_urls" not in data  # exempt from ResultMeta: no page was used


async def test_the_index_opens_on_first_use_and_closes_with_the_services(tmp_path: Path) -> None:
    async with (
        vehicle_services(tmp_path, FixtureTransport({}), baseline=[E90]) as services,
        Client(build_server(services)) as client,
    ):
        assert INDEX_KEY not in services.extras
        await client.call_tool("find_vehicle", {})
        index = services.extras[INDEX_KEY]
        assert isinstance(index, VehicleIndex)
        await client.call_tool("find_vehicle", {})
        assert services.extras[INDEX_KEY] is index
    with pytest.raises(sqlite3.ProgrammingError):  # Services.aclose() closed it
        index.count()


async def test_find_vehicle_reports_total_matches_beyond_the_limit(tmp_path: Path) -> None:
    result = await _find(tmp_path, [GS, GS_EUR, E90], {"series": "k50", "limit": 1})
    assert result.structured_content["total_matches"] == 2
    assert [v["key"] for v in result.structured_content["vehicles"]] == ["0J93-EUR-09-2018"]


async def test_find_vehicle_without_a_baseline_returns_nothing(tmp_path: Path) -> None:
    result = await _find(tmp_path, None, {"query": "E90"})
    assert result.is_error is False
    assert result.structured_content["total_matches"] == 0
    assert result.structured_content["index"]["built_at"] is None


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"limit": 0}, "limit must be between 1 and 100, got 0."),
        ({"limit": 101}, "limit must be between 1 and 100, got 101."),
        ({"brand": "audi"}, "Unknown brand 'audi'; use one of: bmw, mini, motorrad, rolls-royce."),
    ],
)
async def test_find_vehicle_rejects_bad_arguments(
    tmp_path: Path, arguments: dict[str, Any], message: str
) -> None:
    result = await _find(tmp_path, [E90], arguments)
    assert result.is_error is True
    assert result.content[0].text.endswith(message)
