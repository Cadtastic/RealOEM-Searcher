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
from realoem_mcp.http_client import RealOemClient


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
) -> Services:
    brands = BrandRegistry.load(settings.brands_dir)
    cache = PageCache(settings.cache_dir)
    try:
        client = RealOemClient(
            settings,
            cache,
            transport=transport,
            clock=clock or time.monotonic,
            sleep=sleep or asyncio.sleep,
        )
    except BaseException:
        cache.close()
        raise
    return Services(settings=settings, cache=cache, client=client, brands=brands)
