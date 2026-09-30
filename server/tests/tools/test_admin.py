import pytest
from mcp import Client

from realoem_mcp import __version__
from realoem_mcp.config import USER_AGENT
from realoem_mcp.page_types import PageType
from realoem_mcp.server import build_server
from tests.harness import url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
GRP_PARAMS = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
GRP = url("partgrp", **GRP_PARAMS)
PAGE = "common/partgrp_e90_325i.html"


async def test_server_status_reports_settings_and_cache(make_services) -> None:
    services, transport = make_services({XREF: PAGE})
    await services.client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("server_status", {})
    assert result.is_error is False
    status = result.structured_content
    assert status["version"] == __version__
    assert status["base_url"] == "https://www.realoem.com"
    assert status["user_agent"] == USER_AGENT
    assert status["min_interval_s"] == 2.0
    assert status["cache_path"] == str(services.cache.path)
    assert status["cache_entries"] == 1
    assert status["cache_bytes"] > 1000
    assert status["requests_made"] == 1
    assert len(transport.requests) == 1  # server_status itself makes no request


async def test_cache_clear_by_page_type_then_all(make_services) -> None:
    services, _ = make_services({XREF: PAGE, GRP: PAGE})
    await services.client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await services.client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    async with Client(build_server(services)) as client:
        by_type = await client.call_tool("cache_clear", {"page_type": "partgrp"})
        everything = await client.call_tool("cache_clear", {})
    assert by_type.structured_content == {"removed": 1}
    assert everything.structured_content == {"removed": 1}
    assert services.cache.stats().entries == 0


async def test_cache_clear_rejects_unknown_page_type(make_services) -> None:
    services, transport = make_services({})
    async with Client(build_server(services)) as client:
        result = await client.call_tool("cache_clear", {"page_type": "vin"})
    assert result.is_error is True
    assert "Unknown page type 'vin'" in result.content[0].text
    assert transport.requests == []
