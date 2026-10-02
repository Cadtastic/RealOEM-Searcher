"""Services container handed to every tool (ARD section 5.2a)."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Admit, Charge, Owner, RealOemClient


@dataclass
class Services:
    settings: Settings
    cache: PageCache
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)  # branch-owned singletons

    async def aclose(self) -> None:
        """Close every extra, then the client, then the cache; re-raise the first error.

        Extras go first because they may still use the client or the cache while closing.
        """
        closers: list[Callable[[], Any]] = []
        for extra in self.extras.values():
            close = getattr(extra, "close", None)
            if callable(close):
                closers.append(close)
        closers += [self.client.aclose, self.cache.close]
        errors: list[Exception] = []
        for close in closers:
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


def create_services(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    admit: Admit | None = None,
    charge: Charge | None = None,
    owner: Owner | None = None,
) -> Services:
    """admit, charge and owner are the hosted server's client hooks (see shared.build_shared)."""
    brands = BrandRegistry.load(settings.brands_dir)
    # Only non-zero limits are passed, so a PageCache stand-in that takes just cache_dir (as in
    # tests/unit/test_services.py) keeps working; stdio has no limits unless REALOEM_CACHE_MAX_MB.
    limits: dict[str, int] = {}
    if settings.cache_max_bytes:
        limits["max_bytes"] = settings.cache_max_bytes
    if settings.cache_min_free_bytes:
        limits["min_free_bytes"] = settings.cache_min_free_bytes
    cache = PageCache(settings.cache_dir, **limits)
    try:
        client = RealOemClient(
            settings,
            cache,
            transport=transport,
            clock=clock or time.monotonic,
            sleep=sleep or asyncio.sleep,
            admit=admit,
            charge=charge,
            owner=owner,
        )
    except BaseException:
        cache.close()
        raise
    return Services(settings=settings, cache=cache, client=client, brands=brands)
