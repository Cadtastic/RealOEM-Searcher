"""MCP server entry point: build_server(services) and main() (stdio)."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import sys

from mcp.server.mcpserver import MCPServer

import realoem_mcp.tools
from realoem_mcp import __version__
from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services

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


async def _serve(settings: Settings) -> None:
    services = create_services(settings)
    try:
        await build_server(services).run_stdio_async()
    finally:
        await services.aclose()


def main() -> None:
    # stdout carries the MCP protocol; all logging goes to stderr.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the client logs each request itself
    asyncio.run(_serve(Settings.from_env()))


if __name__ == "__main__":
    main()
