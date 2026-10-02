"""A full disk in the auth database, the quota or the vehicle index (hosted design 4.10).

SQLite's max_page_count makes a database report SQLITE_FULL with the same error a full disk
gives, when a page is allocated. A real full disk in WAL mode usually fails at COMMIT instead (the
WAL append), which is why every transaction here runs COMMIT inside its try. The guard's
free_space (deleting the page cache in production) lifts the limit.
"""

import dataclasses
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest

from realoem_mcp.auth.records import ClientRecord
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import Quota
from realoem_mcp.shared import build_shared
from realoem_mcp.storage_guard import AUTH, VEHICLES, StorageGuard
from realoem_mcp.tools.vehicles import get_index
from realoem_mcp.vehicle_index import VehicleIndex
from tests.auth_helpers import signed_in
from tests.harness import FakeClock, FixtureTransport, url
from tests.vehicle_data import numbered
from tests.vehicle_env import install_baseline, settings_for

T = TypeVar("T")


class FullDisk:
    """Fills a connection's database to its current size, and frees it on demand."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.conn: sqlite3.Connection | None = None
        self.refill = False  # fill the disk again right after freeing it

    def fill(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count = {pages}")

    def free_space(self) -> None:
        self.events.append("cache deleted")
        assert self.conn is not None
        if not self.refill:
            self.conn.execute("PRAGMA max_page_count = 1000000")

    def exit(self, status: int) -> None:
        self.events.append(f"exit {status}")


def _clients(count: int) -> list[ClientRecord]:
    return [ClientRecord(f"client-{n}", "x" * 500, {"n": n}, 0, None) for n in range(count)]


def test_a_full_auth_database_frees_the_cache_and_retries(tmp_path: Path) -> None:
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        disk.fill(store.conn)
        store.atomic(lambda: [store.add_client(client) for client in _clients(50)])
        assert disk.events == ["cache deleted"]
        assert store.client("client-49") is not None
    finally:
        store.close()


def test_a_second_full_disk_ends_the_process(tmp_path: Path) -> None:
    disk = FullDisk()
    disk.refill = True
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        disk.fill(store.conn)
        with pytest.raises(sqlite3.OperationalError):  # raised after the (recorded) exit
            store.atomic(lambda: [store.add_client(client) for client in _clients(50)])
        assert disk.events == ["cache deleted", "exit 1"]
        assert store.conn.in_transaction is False
    finally:
        store.close()


def test_the_quota_is_counted_through_the_guard(tmp_path: Path) -> None:
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        quota = Quota(
            store.conn,
            Settings(mode="http"),
            account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),
            now=lambda: datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
            run=guard.run,
        )
        disk.fill(store.conn)
        for n in range(200):  # enough new usage rows to need another page
            quota.charge(f"github:{n}")
        assert disk.events == ["cache deleted"]
        assert quota.used_by_everyone_today() == 200  # the retried charge counted once
    finally:
        store.close()


def test_a_full_vehicle_index_frees_the_cache_and_retries(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    rows = numbered(400)
    install_baseline(settings, rows[:10])
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    index = VehicleIndex.open(settings, BrandRegistry.load(settings.brands_dir), run=guard.run)
    try:
        disk.fill(index._conn)
        assert index.add_local(rows[10:]) == 390
        assert disk.events == ["cache deleted"]
        assert index.count() == 400
    finally:
        index.close()


def test_the_vehicle_index_limits_its_wal_file(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    install_baseline(settings, numbered(3))
    index = VehicleIndex.open(settings, BrandRegistry.load(settings.brands_dir))
    try:
        limit = index._conn.execute("PRAGMA journal_size_limit").fetchone()[0]
        assert limit == 64 * 1024 * 1024  # as on the cache and the auth database
    finally:
        index.close()


@pytest.mark.anyio
async def test_build_shared_runs_the_quota_and_the_index_through_its_guard(
    tmp_path: Path,
) -> None:
    stores: list[str] = []

    def recorder(store: str, operation: Callable[[], T]) -> T:
        stores.append(store)
        return operation()

    settings = dataclasses.replace(settings_for(tmp_path), mode="http")
    install_baseline(settings, numbered(3))
    part = url("partxref", q="11427953129")
    clock = FakeClock()
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        shared = build_shared(
            settings,
            conn,
            owner_key=b"key",
            account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),
            transport=FixtureTransport({part: "partxref/oil_filter_11427953129.html"}),
            clock=clock,
            sleep=clock.sleep,
            run=recorder,
        )
        try:
            with signed_in("github:1"):
                await shared.services.client.fetch(
                    PageType.PARTXREF,
                    "partxref",
                    {"q": "11427953129"},
                )
            get_index(shared.services)
        finally:
            await shared.services.aclose()
    assert AUTH in stores and VEHICLES in stores
