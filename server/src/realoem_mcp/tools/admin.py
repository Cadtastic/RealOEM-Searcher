"""Admin tools: server_status, cache_clear (ARD section 5.11). Exempt from ResultMeta."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from realoem_mcp import __version__
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.services import Services


class ServerStatus(BaseModel):
    version: str
    base_url: str
    user_agent: str
    min_interval_s: float
    cache_path: str
    cache_entries: int
    cache_bytes: int
    requests_made: int


class CacheClearResult(BaseModel):
    removed: int


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def server_status() -> ServerStatus:
        """Report this RealOEM server's version, request settings and cache size.

        Use it to troubleshoot (for example before telling the user RealOEM is unreachable) or
        when the user asks how the plugin talks to RealOEM. Makes no request to RealOEM.
        Returns version, base_url, user_agent, min_interval_s (seconds between requests),
        cache_path, cache_entries, cache_bytes and requests_made (HTTP requests sent to
        RealOEM since start, counting retries and redirect hops).
        """
        stats = services.cache.stats()
        return ServerStatus(
            version=__version__,
            base_url=services.settings.base_url,
            user_agent=services.settings.user_agent,
            min_interval_s=services.settings.min_interval_s,
            cache_path=str(stats.path),
            cache_entries=stats.entries,
            cache_bytes=stats.bytes,
            requests_made=services.client.requests_made,
        )

    @app.tool()
    async def cache_clear(page_type: str | None = None) -> CacheClearResult:
        """Delete cached RealOEM pages so the next lookups fetch fresh copies.

        Prefer refresh=true on a single data tool call; use this only when the user asks to clear
        the cache or many answers look stale. page_type limits the clear to one page type:
        select, production, partgrp, showparts, partxref, partsearch, part or vehicles. Omit it
        to clear everything. Returns removed (the number of cached pages deleted).
        """
        try:
            target = PageType.parse(page_type) if page_type is not None else None
        except RealOemError as err:
            raise ToolError(err.message) from err
        return CacheClearResult(removed=services.cache.clear(target))
