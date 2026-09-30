"""The only way the server talks to RealOEM: rate limited, cached, honest (AD6, AD8, AD13, AD14)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import UpstreamError
from realoem_mcp.page_types import PageType

if TYPE_CHECKING:
    from realoem_mcp.cache import PageCache

log = logging.getLogger(__name__)

COOKIE = "ro_ui=v2"
MAX_REDIRECTS = 3
_PATH_RE = re.compile(r"[a-z]+")
_PAGE_TYPE = "realoem_page_type"  # request extension keys (httpx keeps them across redirects)
_STARTED = "realoem_started"


@dataclass(frozen=True)
class Page:
    page_type: PageType
    url: str  # canonical request URL (cache key)
    final_url: str  # after redirects
    status: int
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool

    @property
    def redirected_away(self) -> bool:
        """True when RealOEM redirected to another page (e.g. /bmw/ for an invalid id)."""
        requested = urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1]
        return not urlsplit(self.final_url).path.rstrip("/").endswith("/" + requested)


def build_url(settings: Settings, path: str, params: Mapping[str, str]) -> str:
    """`{base_url}/bmw/{lang}/{path}?{params}`, params in the order given, spaces as %20."""
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"invalid RealOEM path {path!r}")
    if any(key.lower() == "dmode" for key in params):
        raise ValueError("dmode is never sent to RealOEM (AD7)")
    url = f"{settings.base_url}/bmw/{settings.lang}/{path}"
    if params:
        url += "?" + urlencode(list(params.items()), quote_via=quote)
    return url


class _RejectAllCookies(DefaultCookiePolicy):
    """AD14: cookies the server sets are never stored, so they are never sent back."""

    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False


class _OffsiteRedirect(Exception):
    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.target = target


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


class RealOemClient:
    def __init__(
        self,
        settings: Settings,
        cache: PageCache,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_start: float | None = None
        self.requests_made = 0  # every request sent: retries, redirect hops and failures included
        self._origin = _origin(httpx.URL(settings.base_url))
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=settings.timeout_s,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            cookies=CookieJar(policy=_RejectAllCookies()),
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html",
                "Accept-Language": "en-US",
            },
            event_hooks={"request": [self._on_request], "response": [self._on_response]},
        )

    def build_url(self, path: str, params: Mapping[str, str]) -> str:
        return build_url(self._settings, path, params)

    def cached(self, page_type: PageType, path: str, params: Mapping[str, str]) -> Page | None:
        """Cache-only lookup: an unexpired hit or None. Never touches the network."""
        page = self._cache.get(self.build_url(path, params))
        return page if page is not None and page.page_type == page_type else None

    async def fetch(
        self,
        page_type: PageType,
        path: str,
        params: Mapping[str, str],
        *,
        refresh: bool = False,
        ttl: timedelta | None = None,
    ) -> Page:
        url = self.build_url(path, params)
        if not refresh and (hit := self._cache.get(url)) is not None:
            log.info("%s %s cache hit", page_type.value, url)
            return hit
        async with self._lock:
            if not refresh and (hit := self._cache.get(url)) is not None:
                log.info("%s %s cache hit", page_type.value, url)
                return hit
            response = await self._get_with_retries(page_type, url)
            page = Page(
                page_type=page_type,
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                html=response.text,
                fetched_at=datetime.now(UTC),
                from_cache=False,
            )
            if page.redirected_away:
                return page
            if page.status != 200:
                raise UpstreamError(page.status, url)
            self._cache.put(page, ttl if ttl is not None else page_type.ttl)
            return page

    async def _get_with_retries(self, page_type: PageType, url: str) -> httpx.Response:
        # Task 11 adds challenge detection, retries and the X-RO-UI check here.
        try:
            return await self._send(page_type, url)
        except _OffsiteRedirect as exc:
            raise UpstreamError(None, url, f"redirected off-site to {exc.target}") from None
        except httpx.RequestError as exc:  # network, decoding, too many redirects
            raise UpstreamError(None, url, type(exc).__name__) from None

    async def _send(self, page_type: PageType, url: str) -> httpx.Response:
        try:
            return await self._http.get(url, extensions={_PAGE_TYPE: page_type.value})
        except httpx.RequestError as exc:
            log.info("%s %s failed: %s (cache miss)", page_type.value, url, type(exc).__name__)
            raise

    async def _on_request(self, request: httpx.Request) -> None:
        # Runs for every hop, redirects included, so each one is checked, spaced and counted.
        if _origin(request.url) != self._origin:
            raise _OffsiteRedirect(str(request.url))
        request.headers["Cookie"] = COOKIE  # httpx drops Cookie when it follows a redirect
        if self._last_start is not None:
            wait = self._settings.min_interval_s - (self._clock() - self._last_start)
            if wait > 0:
                await self._sleep(wait)
        self._last_start = self._clock()
        self.requests_made += 1
        request.extensions[_STARTED] = time.perf_counter()

    async def _on_response(self, response: httpx.Response) -> None:
        request = response.request
        elapsed_ms = (time.perf_counter() - request.extensions[_STARTED]) * 1000
        log.info(
            "%s %s -> %d in %.0f ms (cache miss)",
            request.extensions.get(_PAGE_TYPE, "?"),
            request.url,
            response.status_code,
            elapsed_ms,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
