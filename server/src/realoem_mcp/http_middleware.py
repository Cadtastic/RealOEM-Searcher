"""ASGI middleware of the hosted server (hosted design 4.2, 4.6, 4.9), outermost first:
security headers, the request log, and the limits on the sign-in routes."""

from __future__ import annotations

import ipaddress
import logging
import math
import time
from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from realoem_mcp.auth.html import error_page
from realoem_mcp.config import Settings
from realoem_mcp.rate_limit import SlidingWindow

HSTS = "max-age=31536000"
HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
MAX_REGISTER_BODY = 8 * 1024  # the SDK alone accepts 4 MiB
REGISTER_PER_ADDRESS = (30, 3_600.0)  # per hour, per address outside the hosted range
REGISTER_HOSTED_RANGE = (600, 3_600.0)  # per hour, for the whole hosted range
REGISTER_OUTSIDE_TOTAL = (2_000, 86_400.0)  # per day, all addresses outside the range together
AUTHORIZE_PER_ADDRESS = (60, 600.0)  # per 10 minutes
MAX_PENDING = 100_000  # live pending sign-ins (about 50 MB)
CLIENT_IP_HEADER = "fly-client-ip"  # set by Fly's proxy; the socket peer is the proxy

log = logging.getLogger("realoem_mcp.requests")


class SecurityHeaders:
    """HSTS on every response; CSP and friends on every HTML response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Strict-Transport-Security"] = HSTS
                if headers.get("content-type", "").startswith("text/html"):
                    for name, value in HTML_HEADERS.items():
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestLog:
    """One line per request: method, path (never the query string), status, duration, and the
    signed-in user when there is one. Never headers, bodies, tokens or codes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            token = getattr(scope.get("user"), "access_token", None)  # set by the SDK's auth
            subject = getattr(token, "subject", None)
            log.info(
                "%s %s %d %.0f ms%s",
                scope["method"],
                # Decoded by the server: escape it, so a path cannot forge another log line.
                scope["path"].encode("unicode_escape").decode("ascii"),
                status,
                (time.perf_counter() - started) * 1000,
                f" {subject}" if subject else "",
            )


async def _send_simple(
    send: Send, status: int, body: bytes, content_type: str, retry_after: float | None = None
) -> None:
    headers = [
        (b"content-type", content_type.encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    if retry_after is not None:
        headers.append((b"retry-after", str(max(1, math.ceil(retry_after))).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class SignInLimits:
    """Rate limits and a size limit on /register, rate limits and the pending cap on
    /authorize. Keyed on the address Fly's proxy reports."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        pending_count: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self._hosted = ipaddress.ip_network(settings.hosted_client_range)
        self._pending_count = pending_count
        self._register_each = SlidingWindow(*REGISTER_PER_ADDRESS, clock=clock)
        self._register_hosted = SlidingWindow(*REGISTER_HOSTED_RANGE, clock=clock)
        self._register_outside = SlidingWindow(*REGISTER_OUTSIDE_TOTAL, clock=clock)
        self._authorize_each = SlidingWindow(*AUTHORIZE_PER_ADDRESS, clock=clock)

    def _client(self, scope: Scope) -> tuple[str, bool]:
        """The client's rate-limit key, and whether it is in Anthropic's range. An IPv6 client
        counts by its /64, because one host controls a whole /64."""
        client = scope.get("client")
        raw = (Headers(scope=scope).get(CLIENT_IP_HEADER) or (client[0] if client else "")).strip()
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return raw or "unknown", False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        hosted = address in self._hosted
        if isinstance(address, ipaddress.IPv6Address):
            return str(ipaddress.ip_network(f"{address}/64", strict=False)), hosted
        return str(address), hosted

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in ("/register", "/authorize"):
            await self.app(scope, receive, send)
            return
        address, hosted = self._client(scope)
        if scope["path"] == "/authorize":
            if (wait := self._authorize_each.retry_after(address)) is not None:
                await _send_simple(send, 429, b"Too many sign-in attempts.", "text/plain", wait)
                return
            self._authorize_each.record(address)
            if self._pending_count() >= MAX_PENDING:
                status, page = error_page("busy")
                await _send_simple(send, status, page.encode(), "text/html; charset=utf-8", 60)
                return
            await self.app(scope, receive, send)
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        buckets = (
            [(self._register_hosted, "hosted")]
            if hosted
            else [(self._register_each, address), (self._register_outside, "outside")]
        )
        waits = [wait for bucket, key in buckets if (wait := bucket.retry_after(key)) is not None]
        if waits:
            await _send_simple(send, 429, b"Too many registrations.", "text/plain", max(waits))
            return
        for bucket, key in buckets:
            bucket.record(key)
        body = await self._read_body(scope, receive)
        if body is None:
            await _send_simple(send, 413, b"Registration body too large.", "text/plain")
            return
        await self.app(scope, _replay(body, receive), send)

    @staticmethod
    async def _read_body(scope: Scope, receive: Receive) -> bytes | None:
        """The whole request body, or None once it passes MAX_REGISTER_BODY."""
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REGISTER_BODY:
            return None
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return b"".join(chunks)  # the client went away; the handler will see that
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_REGISTER_BODY:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replayed() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replayed
