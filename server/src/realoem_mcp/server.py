"""MCP server entry point: build_server(services) and main() (stdio)."""

from __future__ import annotations

import importlib
import pkgutil

from mcp.server.mcpserver import MCPServer

import realoem_mcp.tools
from realoem_mcp import __version__
from realoem_mcp.services import Services

INSTRUCTIONS = (
    "Look up BMW, MINI, Rolls-Royce and BMW Motorrad OEM parts on RealOEM.com. Every RealOEM "
    "request is rate limited and cached, so call tools only for what the user asked, and include "
    "the source_urls from results when answering."
)


def build_server(services: Services) -> MCPServer:
    app = MCPServer("realoem", instructions=INSTRUCTIONS, version=__version__)
    package = realoem_mcp.tools
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(app, services)
    return app
