"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_lookup_part_against_realoem(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            plain = await client.call_tool("lookup_part", {"part_number": "11427541827"})
            narrowed = await client.call_tool(
                "lookup_part", {"part_number": "11427953129", "series": "E90"}
            )
    finally:
        await services.aclose()
    assert plain.is_error is False, plain.content
    assert plain.structured_content["status"] == "ended"
    successors = plain.structured_content["part"]["superseded_by"]
    assert "11427953129" in [entry["part_number"] for entry in successors]
    assert narrowed.is_error is False, narrowed.content
    assert narrowed.structured_content["status"] == "current"
    assert narrowed.structured_content["part"]["models"], "expected E90 vehicles"
    assert narrowed.structured_content["requests_made"] == 1
