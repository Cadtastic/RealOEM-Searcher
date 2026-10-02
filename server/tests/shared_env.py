"""Offline Services in hosted ("http") mode: quota, gate and per-user VIN pages, fake clock."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.shared import Shared, build_shared
from tests.auth_helpers import signed_in
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, Route

OWNER_KEY = b"test-owner-key"
TODAY = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)  # the default GitHub account age: established


@asynccontextmanager
async def shared_services(
    tmp_path: Path,
    routes: Mapping[str, Route | str] | httpx.AsyncBaseTransport,
    *,
    created: Mapping[str, datetime] | None = None,
    settings: Callable[[Path], Settings] | None = None,
    clock: FakeClock | None = None,
    **overrides: object,
) -> AsyncIterator[tuple[Shared, httpx.AsyncBaseTransport]]:
    """build_shared() on temporary folders. created maps subjects to GitHub account dates
    (default: an old account). settings builds the Settings instead of the default; clock
    drives request spacing and the call deadline.

    The hosted cache keeps 100 MB of the temporary drive free: with less free space there,
    pages are served uncached and tests that count requests fail.
    """
    transport = routes if isinstance(routes, httpx.AsyncBaseTransport) else FixtureTransport(routes)
    config = (
        settings(tmp_path)
        if settings is not None
        else Settings(
            mode="http",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
            brands_dir=BRANDS_DIR,
            **overrides,  # type: ignore[arg-type]
        )
    )
    clock = clock or FakeClock()
    accounts = dict(created or {})
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        shared = build_shared(
            config,
            conn,
            owner_key=OWNER_KEY,
            account_created_at=lambda subject: accounts.get(subject, OLD_ACCOUNT),
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
            now=lambda: TODAY,
        )
        try:
            yield shared, transport
        finally:
            await shared.services.aclose()
    if isinstance(transport, FixtureTransport):
        assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"


async def call_tool(
    services: Services, subject: str | None, tool: str, arguments: dict[str, object]
) -> CallToolResult:
    """Call one tool through the in-memory MCP client, signed in as subject (None: anonymous)."""
    async with Client(build_server(services)) as client:
        if subject is None:
            return await client.call_tool(tool, arguments)
        with signed_in(subject):
            return await client.call_tool(tool, arguments)
