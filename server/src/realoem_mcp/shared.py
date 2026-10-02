"""Wires the hosted ("http") mode pieces together: quota, gate, cache owners, Services.

The HTTP app builds its Services through build_shared(); nothing here imports the HTTP layer,
so the whole shared mode runs in tests through the in-memory MCP client.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.current_user import require_user
from realoem_mcp.gate import GATE_KEY, FetchGate
from realoem_mcp.http_client import Owner
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY, Quota
from realoem_mcp.services import Services, create_services
from realoem_mcp.storage_guard import Runner, run_directly


@dataclass
class Shared:
    services: Services
    quota: Quota
    gate: FetchGate


def vin_page_owner(settings: Settings, owner_key: bytes) -> Owner:
    """Cache owner of a page: the caller for pages that carry a VIN, "" (shared) otherwise.

    A shared VIN page would tell any user, through from_cache and fetched_at, whether and when
    someone else decoded that VIN. The owner is a keyed hash, so the cache holds no user ids.
    """

    def owner(page_type: PageType, params: Mapping[str, str]) -> str:
        carries_vin = page_type is PageType.PRODUCTION or (
            page_type is PageType.SELECT and "vin" in params
        )
        if not carries_vin:
            return ""
        subject = require_user(settings).subject
        return hmac.new(owner_key, subject.encode("utf-8"), hashlib.sha256).hexdigest()

    return owner


def build_shared(
    settings: Settings,
    usage_conn: sqlite3.Connection,
    *,
    owner_key: bytes,
    account_created_at: Callable[[str], datetime | None],
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], datetime] | None = None,
    run: Runner = run_directly,
) -> Shared:
    """Services for the hosted server: every cache-miss fetch is admitted, charged to the
    signed-in caller and, for VIN pages, cached for that caller only.

    usage_conn is an autocommit SQLite connection that holds the `usage` table. run is the
    storage guard the quota and the vehicle index use (the HTTP app passes StorageGuard.run).
    """
    if settings.mode != "http":
        raise ValueError("build_shared needs Settings(mode='http')")
    if not owner_key:  # without a key the owner would be a plain hash of the user id
        raise ValueError("build_shared needs a secret owner_key")
    quota = Quota(
        usage_conn,
        settings,
        account_created_at=account_created_at,
        run=run,
        **({"now": now} if now is not None else {}),
    )
    gate = FetchGate(settings, quota, clock=clock or time.monotonic)
    services = create_services(
        settings,
        transport=transport,
        clock=clock,
        sleep=sleep,
        # require_user: a fetch with no signed-in caller is refused, never charged to nobody.
        admit=lambda: gate.admit(require_user(settings).subject),
        charge=lambda: quota.charge(require_user(settings).subject),
        owner=vin_page_owner(settings, owner_key),
    )
    services.run_storage = run
    services.extras[QUOTA_KEY] = quota
    services.extras[GATE_KEY] = gate
    return Shared(services=services, quota=quota, gate=gate)
