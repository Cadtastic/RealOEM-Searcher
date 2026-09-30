"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]

VEHICLE = "VB13-USA-10-2005-E90-BMW-325i"  # dated id, as decode_vin returns


async def test_check_fitment_against_realoem(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            current = await client.call_tool(
                "check_fitment", {"part_number": "11427953129", "vehicle_id": VEHICLE}
            )
            other = await client.call_tool(
                "check_fitment", {"part_number": "11427622446", "vehicle_id": VEHICLE}
            )
    finally:
        await services.aclose()
    assert current.is_error is False, current.content
    data = current.structured_content
    assert (data["fits"], data["used_part_numbers"]) == (True, ["11427953129"])
    assert "11_3867" in [diagram["diag_id"] for diagram in data["diagrams"]]
    assert {diagram["vehicle_id"] for diagram in data["diagrams"]} == {VEHICLE}
    assert data["requests_made"] == 1
    assert other.is_error is False, other.content
    assert (other.structured_content["fits"], other.structured_content["requests_made"]) == (
        False,
        1,
    )
