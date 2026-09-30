import importlib
import logging

import pytest
from mcp import Client

from realoem_mcp import server as server_module
from realoem_mcp.server import build_server

pytestmark = pytest.mark.anyio

ADMIN_TOOLS = {"server_status", "cache_clear"}


async def test_build_server_discovers_tool_modules(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services)
    assert app.name == "realoem"
    async with Client(app) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools.tools}
    assert names >= ADMIN_TOOLS
    for tool in tools.tools:
        assert tool.description, f"{tool.name} needs a docstring for the model"


async def test_broken_tools_module_is_logged_and_reraised(
    make_services, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    services, _ = make_services({})
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name.endswith(".broken"):
            raise ImportError("no such dependency")
        return real_import(name, package)

    monkeypatch.setattr(server_module.pkgutil, "iter_modules", lambda path: [_ModuleInfo("broken")])
    monkeypatch.setattr(server_module.importlib, "import_module", fake_import)
    with (
        caplog.at_level(logging.ERROR, logger="realoem_mcp.server"),
        pytest.raises(ImportError, match="no such dependency"),
    ):
        build_server(services)
    assert "failed to load tools module broken" in caplog.text


class _ModuleInfo:
    def __init__(self, name: str) -> None:
        self.name = name
