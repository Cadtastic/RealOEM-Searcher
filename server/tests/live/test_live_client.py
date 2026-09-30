"""Opt-in live smoke test (1 request): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_honest_user_agent_gets_the_v2_page(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        page = await services.client.fetch(PageType.PARTXREF, "partxref", {"q": "11427953129"})
    finally:
        await services.aclose()
    assert services.client.requests_made <= 5
    assert page.status == 200
    assert not page.redirected_away
    assert "11427953129" in page.html
