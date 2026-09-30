"""Offline test harness: fixture loading, canned HTTP routes, fake clock (ARD section 8)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.http_client import build_url

if TYPE_CHECKING:
    from realoem_mcp.services import Services  # added in Task 16

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
BRANDS_DIR = REPO_ROOT / "brands"
LANDING_URL = "https://www.realoem.com/bmw/"  # redirect target for invalid vehicle ids
UNMATCHED_STATUS = 404  # not retried by the client, so each stray URL is recorded once

_URL_SETTINGS = Settings()


def load_fixture(rel: str) -> str:
    """Text of fixtures/<rel>, e.g. load_fixture("common/cloudflare_challenge.html")."""
    return (FIXTURES / rel).read_text(encoding="utf-8")


def url(path: str, **params: str) -> str:
    """The URL RealOemClient.build_url produces with default Settings (same encoding/order)."""
    return build_url(_URL_SETTINGS, path, params)


def _normalize(raw: str) -> str:
    # Both sides go through httpx.URL, so the comparison is immune to httpx re-encoding.
    return str(httpx.URL(raw))


@dataclass
class Route:
    """One canned response."""

    fixture: str | None = None  # path under fixtures/, or None for an empty body
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    redirect_to: str | None = None  # emits a 301 to this URL


class FixtureTransport(httpx.AsyncBaseTransport):
    """Serves routes keyed by full URL; records every request and every unmatched URL."""

    def __init__(self, routes: Mapping[str, Route | str]) -> None:
        self.routes: dict[str, Route] = {
            _normalize(key): Route(fixture=value) if isinstance(value, str) else value
            for key, value in routes.items()
        }
        self.redirect_targets = {
            _normalize(route.redirect_to) for route in self.routes.values() if route.redirect_to
        }
        self.requests: list[httpx.Request] = []
        self.unmatched: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = _normalize(str(request.url))
        route = self.routes.get(key)
        if route is None:
            if key in self.redirect_targets:
                return httpx.Response(200, content=b"", request=request)
            self.unmatched.append(key)
            return httpx.Response(
                UNMATCHED_STATUS, text=f"unexpected request: {key}", request=request
            )
        headers = dict(route.headers)
        if route.redirect_to is not None:
            headers["Location"] = route.redirect_to
            return httpx.Response(301, headers=headers, content=b"", request=request)
        body = load_fixture(route.fixture).encode("utf-8") if route.fixture else b""
        headers.setdefault("Content-Type", "text/html;charset=UTF-8")
        return httpx.Response(route.status, headers=headers, content=body, request=request)


class FakeClock:
    """Monotonic clock plus sleep that advances it instantly and records each wait."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# Type of the make_services fixture (tests/conftest.py).
MakeServices = Callable[[Mapping[str, Route | str]], tuple["Services", FixtureTransport]]
