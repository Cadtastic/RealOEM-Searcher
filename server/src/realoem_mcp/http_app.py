"""The hosted server: the MCP tools over streamable HTTP behind GitHub sign-in (hosted design 4.2).

build_http_app() assembles everything and is what tests use; main() is the realoem-mcp-http
entry point. The stdio server (server.py) is unchanged and shares build_server().
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from realoem_mcp.auth.github import GitHubLogin, GitHubOAuthApp
from realoem_mcp.auth.keys import Keys
from realoem_mcp.auth.pages import SignInPages
from realoem_mcp.auth.provider import SCOPE, RealOemAuthProvider
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.cache import DB_FILENAME, PageCache
from realoem_mcp.config import Settings
from realoem_mcp.current_user import CallClock
from realoem_mcp.http_middleware import RequestLog, SecurityHeaders, SignInLimits
from realoem_mcp.log_privacy import install_vin_filter
from realoem_mcp.server import build_server
from realoem_mcp.shared import build_shared
from realoem_mcp.storage_guard import StorageGuard, hard_exit

PORT = 8080
PURGE_INTERVAL_S = 3600.0

log = logging.getLogger(__name__)


def _cache_file_deleter(cache_dir: Path) -> Callable[[], None]:
    """Frees disk space before the page cache is open (a full disk found at startup)."""

    def delete() -> None:
        for suffix in ("", "-wal", "-shm"):
            (cache_dir / f"{DB_FILENAME}{suffix}").unlink(missing_ok=True)

    return delete


def _auth_settings(settings: Settings) -> AuthSettings:
    return AuthSettings(
        issuer_url=settings.public_url,  # type: ignore[arg-type]
        resource_server_url=f"{settings.public_url}/mcp",  # type: ignore[arg-type]
        validate_token_resource=True,
        required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    if settings.is_local:  # a development run: only loopback Host headers (a port is required)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*", "127.0.0.1:*"],
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
        )
    # Bearer tokens make DNS rebinding useless, and the SDK would answer any request with an
    # Origin header with a 403 that Claude treats as final.
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def purge_once(store: AuthStore, cache: PageCache, now: float) -> None:
    """The hourly housekeeping (hosted design 4.9)."""
    removed = store.purge(int(now))
    expired_pages = cache.purge_expired()
    log.info(
        "purge: %s; %d expired pages",
        ", ".join(f"{count} {table}" for table, count in removed.items() if count) or "nothing",
        expired_pages,
    )


async def _purge_hourly(store: AuthStore, cache: PageCache, interval_s: float) -> None:
    """Purge at startup, then every interval: a server restarted often still purges."""
    while True:
        try:
            purge_once(store, cache, time.time())
        except Exception:
            log.exception("the hourly purge failed")
        await asyncio.sleep(interval_s)


async def _healthz(request: Request) -> PlainTextResponse:
    """Liveness only: a constant answer, no database access."""
    return PlainTextResponse("ok")


def build_http_app(
    settings: Settings,
    *,
    github: GitHubLogin | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], datetime] | None = None,
    exit: Callable[[int], object] = hard_exit,
    purge_interval_s: float = PURGE_INTERVAL_S,
) -> Starlette:
    """The ASGI app of the hosted server. Refuses stdio settings and missing HTTP-only values.

    github, transport, clock, sleep, now and exit are for tests (a fake GitHub, canned RealOEM
    pages, a fake clock, a recorded exit).
    """
    if settings.mode != "http":
        raise ValueError("build_http_app needs Settings(mode='http'); run realoem-mcp-http")
    settings.validate_http()
    keys = Keys(settings.secret_key_bytes)
    guard = StorageGuard(free_space=_cache_file_deleter(settings.cache_dir), exit=exit)
    store = AuthStore.open(settings.auth_path, run=guard.run)
    shared = build_shared(
        settings,
        store.conn,
        owner_key=keys.key("cache-owner"),
        account_created_at=store.github_created_at,
        transport=transport,
        clock=clock,
        sleep=sleep,
        now=now,
        run=guard.run,
    )
    services = shared.services
    guard.free_space = services.cache.reset
    github = github or GitHubOAuthApp(
        settings.github_client_id or "",
        settings.github_client_secret or "",
        f"{settings.public_url}/oauth/github/callback",
    )
    provider = RealOemAuthProvider(settings, store, github, keys)
    server = build_server(
        services,
        auth_server_provider=provider,
        auth=_auth_settings(settings),
        middleware=[CallClock(clock or time.monotonic)],  # the clock the gate reads
    )
    pages = SignInPages(provider, keys, settings)
    server.custom_route("/consent", methods=["GET"])(pages.show_consent)
    server.custom_route("/consent", methods=["POST"])(pages.submit_consent)
    server.custom_route("/oauth/github/callback", methods=["GET"])(pages.github_callback)
    server.custom_route("/healthz", methods=["GET"])(_healthz)
    # After the custom routes, so the SDK's app stays the root and its lifespan runs.
    app = server.streamable_http_app(
        stateless_http=True, json_response=True, transport_security=_transport_security(settings)
    )
    sdk_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with sdk_lifespan(app):
            purge = asyncio.create_task(_purge_hourly(store, services.cache, purge_interval_s))
            try:
                yield
            finally:
                purge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await purge
                await services.aclose()
                await github.aclose()
                store.close()

    app.router.lifespan_context = lifespan
    app.state.store = store  # for tests and the admin's debugging; nothing else reads these
    app.state.services = services
    # add_middleware puts each one outside the previous: the last added runs first.
    app.add_middleware(
        SignInLimits,
        settings=settings,
        pending_count=lambda: store.live_pending_count(int(time.time())),
    )
    app.add_middleware(RequestLog)
    app.add_middleware(SecurityHeaders)
    return app


def main() -> None:
    # Configure logging before the SDK does (it only configures an unconfigured root logger).
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    install_vin_filter()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the client logs each request itself
    try:
        app = build_http_app(dataclasses.replace(Settings.from_env(), mode="http"))
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(2)
    uvicorn.run(app, host="0.0.0.0", port=PORT, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
