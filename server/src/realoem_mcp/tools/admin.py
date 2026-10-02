"""Admin tools: server_status, cache_clear (ARD section 5.11). Exempt from ResultMeta."""

from __future__ import annotations

from datetime import datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from realoem_mcp import __version__
from realoem_mcp.current_user import require_user
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY
from realoem_mcp.services import Services

ADMINS_ONLY = (
    "Only an administrator of this RealOEM Searcher server can clear its shared cache. "
    "Use refresh=true on a single lookup instead (it refetches copies older than an hour)."
)


class QuotaInfo(BaseModel):
    used_today: int  # RealOEM requests made for the caller today (cached answers are free)
    limit: int  # 0 = unlimited
    resets_at: datetime  # the next 00:00 UTC


class ServerStatus(BaseModel):
    version: str
    base_url: str
    user_agent: str
    min_interval_s: float
    cache_path: str | None  # None on the hosted server
    cache_entries: int
    cache_bytes: int
    requests_made: int
    quota: QuotaInfo | None = None  # hosted server: the caller's daily quota
    global_limit: int | None = None  # hosted server: the server-wide daily cap, when one is on


class CacheClearResult(BaseModel):
    removed: int


def register(app: MCPServer, services: Services) -> None:
    hosted = services.settings.mode == "http"

    @app.tool()
    async def server_status() -> ServerStatus:
        """Report this RealOEM server's version, request settings and cache size.

        Use it to troubleshoot (for example before telling the user RealOEM is unreachable) or
        when the user asks how the plugin talks to RealOEM. Makes no request to RealOEM.
        Returns version, base_url, user_agent, min_interval_s (seconds between requests),
        cache_path, cache_entries, cache_bytes and requests_made (HTTP requests sent to
        RealOEM since start, counting retries and redirect hops). On the hosted server
        cache_path is null and quota shows the caller's daily RealOEM lookups (used_today,
        limit, resets_at; cached answers are free); global_limit is the server-wide daily cap
        when one is set.
        """
        stats = services.cache.stats()
        status = ServerStatus(
            version=__version__,
            base_url=services.settings.base_url,
            user_agent=services.settings.user_agent,
            min_interval_s=services.settings.min_interval_s,
            cache_path=str(stats.path),
            cache_entries=stats.entries,
            cache_bytes=stats.bytes,
            requests_made=services.client.requests_made,
        )
        if not hosted:
            return status
        try:
            user = require_user(services.settings)
        except RealOemError as err:
            raise ToolError(err.message) from err
        usage = services.extras[QUOTA_KEY].status(user.subject)
        return status.model_copy(
            update={
                "cache_path": None,
                "quota": QuotaInfo(
                    used_today=usage.used_today, limit=usage.limit, resets_at=usage.resets_at
                ),
                "global_limit": services.settings.global_daily_limit or None,
            }
        )

    @app.tool()
    async def cache_clear(page_type: str | None = None) -> CacheClearResult:
        """Delete cached RealOEM pages so the next lookups fetch fresh copies.

        Prefer refresh=true on a single data tool call; use this only when the user asks to clear
        the cache or many answers look stale. page_type limits the clear to one page type:
        select, production, partgrp, showparts, partxref, partsearch, part or vehicles. Omit it
        to clear everything. Returns removed (the number of cached pages deleted). On the hosted
        server the cache is shared by all users, so only its administrators can clear it.
        """
        try:
            if hosted and not require_user(services.settings).is_admin:
                raise RealOemError(ADMINS_ONLY)
            target = PageType.parse(page_type) if page_type is not None else None
        except RealOemError as err:
            raise ToolError(err.message) from err
        return CacheClearResult(removed=services.cache.clear(target))
