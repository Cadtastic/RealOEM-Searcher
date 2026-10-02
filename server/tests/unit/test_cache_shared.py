"""PageCache in shared (hosted) mode: owners, size accounting, the cap, disk-space handling."""

import sqlite3
from collections import namedtuple
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp import cache as cache_module
from realoem_mcp.cache import DB_FILENAME, SCHEMA_VERSION, PageCache
from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

XREF = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"
GRP = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"
VIN = "https://www.realoem.com/bmw/enUS/select?vin=PX22770"
WEEK = timedelta(days=7)
Usage = namedtuple("Usage", "total used free")


def _page(url: str, *, owner: str = "", html: str = "<p>ok</p>", age: timedelta = timedelta(0)):
    return Page(
        page_type=PageType.PARTXREF,
        url=url,
        final_url=url,
        status=200,
        html=html,
        fetched_at=datetime.now(UTC) - age,
        from_cache=False,
        owner=owner,
    )


class Ticker:
    """A clock that advances one second per reading, so last_used values are distinct."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _columns(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(pages)")]


def _write_version_1(path: Path) -> None:
    """A cache file in the version 1 layout, without auto_vacuum."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        conn.execute(
            "CREATE TABLE pages (url TEXT PRIMARY KEY, page_type TEXT NOT NULL, final_url TEXT "
            "NOT NULL, status INTEGER NOT NULL, html TEXT NOT NULL, fetched_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL)"
        )
        conn.commit()


def _full_disk(*args: object) -> None:
    error = sqlite3.OperationalError("database or disk is full")
    error.sqlite_errorcode = sqlite3.SQLITE_FULL  # what SQLite sets on a real full disk
    raise error


# --- owners -------------------------------------------------------------------------------


def test_pages_are_kept_per_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(VIN, owner="alice", html="<p>a</p>"), WEEK)
        cache.put(_page(VIN, owner="bob", html="<p>b</p>"), WEEK)
        assert cache.get(VIN) is None  # nothing shared under this URL
        alice, bob = cache.get(VIN, owner="alice"), cache.get(VIN, owner="bob")
        assert (alice.html, alice.owner, alice.url) == ("<p>a</p>", "alice", VIN)
        assert (bob.html, bob.owner) == ("<p>b</p>", "bob")
        assert cache.stats().entries == 2
    finally:
        cache.close()


def test_shared_pages_have_an_empty_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(XREF), WEEK)
        hit = cache.get(XREF)
        assert hit is not None and hit.owner == ""
        assert cache.get(XREF, owner="alice") is None
    finally:
        cache.close()


def test_shorten_only_touches_the_given_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(VIN, owner="alice", age=timedelta(days=2)), timedelta(days=30))
        cache.put(_page(VIN, owner="bob", age=timedelta(days=2)), timedelta(days=30))
        cache.shorten(VIN, timedelta(days=1), owner="alice")
        assert cache.get(VIN, owner="alice") is None
        assert cache.get(VIN, owner="bob") is not None
    finally:
        cache.close()


def test_html_is_the_last_column_and_the_file_can_shrink(tmp_path: Path) -> None:
    PageCache(tmp_path).close()
    path = tmp_path / DB_FILENAME
    assert _columns(path)[-1] == "html"
    assert _columns(path)[:2] == ["owner", "url"]
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)  # INCREMENTAL
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(pages)")}
    assert {"pages_last_used", "pages_expires_at"} <= indexes


def test_an_old_schema_file_is_replaced_by_a_new_file(tmp_path: Path) -> None:
    path = tmp_path / DB_FILENAME
    _write_version_1(path)
    cache = PageCache(tmp_path)
    try:
        assert cache.stats().entries == 0
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert version == (SCHEMA_VERSION,)


def test_the_version_1_cache_is_deleted_unless_it_is_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "pages.sqlite3"
    _write_version_1(legacy)
    (tmp_path / "pages.sqlite3-wal").write_bytes(b"")
    PageCache(tmp_path).close()
    assert not legacy.exists() and not (tmp_path / "pages.sqlite3-wal").exists()
    _write_version_1(legacy)
    real_unlink = Path.unlink

    def in_use(path: Path, missing_ok: bool = False) -> None:  # Windows, while 0.1.0 runs
        if path.name.startswith("pages.sqlite3"):
            raise PermissionError("the file is being used by another process")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", in_use)
    cache = PageCache(tmp_path)  # the new file is separate, so both versions can run
    try:
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
    assert legacy.exists()


# --- size accounting ------------------------------------------------------------------------


def _sum(cache: PageCache) -> int:
    return cache._conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM pages").fetchone()[0]


def test_running_total_follows_put_replace_shorten_clear_and_purge(tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "cache")
    cache.put(_page(XREF, html="ä"), WEEK)  # 2 bytes
    cache.put(_page(GRP, html="abc"), WEEK)  # 3 bytes
    cache.put(_page(VIN, owner="alice", html="12345", age=timedelta(days=10)), WEEK)  # expired
    assert cache.stats().bytes == 10 == _sum(cache)
    cache.put(_page(XREF, html="abcdefg"), WEEK)  # replace: 2 -> 7
    cache.shorten(GRP, timedelta(days=1))  # only the lifetime changes
    assert cache.stats().bytes == 15 == _sum(cache)
    assert cache.clear(PageType.PARTXREF) == 3  # every row here is a partxref page
    assert cache.stats().bytes == 0 == _sum(cache)
    cache.put(_page(XREF, html="abc"), WEEK)
    cache.put(_page(GRP, html="12345", age=timedelta(days=10)), WEEK)
    assert cache.purge_expired() == 1
    assert cache.stats().bytes == 3 == _sum(cache)
    cache.close()
    reopened = PageCache(tmp_path / "cache")
    try:
        assert reopened.stats().bytes == 3
        assert reopened.clear() == 1
        assert reopened.stats().bytes == 0 == _sum(reopened)
    finally:
        reopened.close()


def test_expired_rows_purged_on_open_leave_the_total_right(tmp_path: Path) -> None:
    first = PageCache(tmp_path)
    first.put(_page(XREF, html="abc", age=timedelta(days=10)), WEEK)
    first.put(_page(GRP, html="12345"), WEEK)
    first.close()
    second = PageCache(tmp_path)
    try:
        assert (second.stats().entries, second.stats().bytes) == (1, 5)
    finally:
        second.close()


def test_stats_cap_check_eviction_and_purge_never_read_html(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, max_bytes=1_000, clock=Ticker())
    try:
        for i in range(5):
            cache.put(_page(f"{XREF}{i}", html="x" * 300), WEEK)
        statements: list[str] = []
        cache._conn.set_trace_callback(statements.append)
        cache.stats()
        cache._enforce_cap()
        cache._evict_to(300)
        cache.purge_expired()
        cache._conn.set_trace_callback(None)
        assert statements
        assert not [s for s in statements if "html" in s.lower()]
        assert not [s for s in statements if "*" in s.upper().replace("COUNT(*)", "")]
    finally:
        cache.close()


# --- the cap --------------------------------------------------------------------------------


def test_cap_evicts_least_recently_used_down_to_ninety_percent(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, max_bytes=1_000, clock=Ticker())
    try:
        for name in "abc":
            cache.put(_page(XREF + name, html="x" * 300), WEEK)  # 900 bytes: under the cap
        assert cache.get(XREF + "a") is not None  # a is now the most recently used
        cache.put(_page(XREF + "d", html="x" * 300), WEEK)  # 1200 > 1000: evict to <= 900
        assert cache.get(XREF + "b") is None  # the least recently used went first
        assert [cache.get(XREF + n) is not None for n in "acd"] == [True, True, True]
        assert cache.stats().bytes == 900 == _sum(cache)
    finally:
        cache.close()


def test_no_cap_means_no_eviction_and_no_use_tracking(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, clock=Ticker())
    try:
        for i in range(5):
            cache.put(_page(f"{XREF}{i}", html="x" * 300), WEEK)
        before = cache._conn.execute("SELECT last_used FROM pages WHERE url = ?", (XREF + "0",))
        first = before.fetchone()[0]
        cache.get(XREF + "0")
        after = cache._conn.execute("SELECT last_used FROM pages WHERE url = ?", (XREF + "0",))
        assert after.fetchone()[0] == first
        assert cache.stats().entries == 5
    finally:
        cache.close()


def _on_disk(cache: PageCache) -> int:
    """The cache file and its WAL together: what the filesystem actually holds."""
    files = (cache.path, Path(f"{cache.path}-wal"))
    return sum(path.stat().st_size for path in files if path.exists())


@pytest.mark.parametrize("chunk_pages", [cache_module.VACUUM_CHUNK_PAGES, 50])
def test_eviction_returns_disk_space_to_the_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_pages: int
) -> None:
    monkeypatch.setattr(cache_module, "VACUUM_CHUNK_PAGES", chunk_pages)
    cache = PageCache(tmp_path, max_bytes=8_000_000, clock=Ticker())
    try:
        for i in range(70):  # 70 x 50 KB = 3.5 MB, under the cap
            cache.put(_page(f"{XREF}{i}", html="x" * 50_000), WEEK)
        cache._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = _on_disk(cache)
        assert cache._evict_to(1_750_000) == 35  # half: many live pages have to move
        assert _on_disk(cache) < before - 1_500_000  # freed, not parked in the -wal
        assert cache._conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
    finally:
        cache.close()


# --- disk space -----------------------------------------------------------------------------


def test_low_disk_space_evicts_then_serves_uncached(tmp_path: Path) -> None:
    free = {"bytes": 500}

    def disk_usage(path: Path) -> Usage:
        return Usage(10_000, 10_000 - free["bytes"], free["bytes"])

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=100, disk_usage=disk_usage, clock=Ticker()
    )
    try:
        assert cache.put(_page(XREF + "a", html="x" * 400), WEEK) is True
        assert cache.put(_page(XREF + "b", html="x" * 400), WEEK) is True
        free["bytes"] = 50  # below the floor, and eviction does not help in this fake
        assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is False
        assert cache.get(XREF + "c") is None
        assert cache.stats().bytes <= 500  # it evicted to half the cap before giving up
    finally:
        cache.close()


def test_low_disk_space_evicts_and_caches_when_that_frees_enough(tmp_path: Path) -> None:
    caches: list[PageCache] = []

    def disk_usage(path: Path) -> Usage:  # a 1,000-byte disk that holds only the cache
        used = caches[0].stats().bytes
        return Usage(1_000, used, 1_000 - used)

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=300, disk_usage=disk_usage, clock=Ticker()
    )
    caches.append(cache)
    try:
        assert cache.put(_page(XREF + "a", html="x" * 400), WEEK) is True
        assert cache.put(_page(XREF + "b", html="x" * 400), WEEK) is True  # 200 bytes free now
        assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is True  # a evicted first
        assert cache.get(XREF + "a") is None
        assert cache.get(XREF + "b") is not None and cache.get(XREF + "c") is not None
    finally:
        cache.close()


def test_a_full_disk_during_eviction_never_fails_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    free = {"bytes": 500}

    def disk_usage(path: Path) -> Usage:
        return Usage(10_000, 10_000 - free["bytes"], free["bytes"])

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=100, disk_usage=disk_usage, clock=Ticker()
    )
    try:
        cache.put(_page(XREF + "a", html="x" * 400), WEEK)
        cache.put(_page(XREF + "b", html="x" * 400), WEEK)
        monkeypatch.setattr(PageCache, "_evict_to", _full_disk)
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            free["bytes"] = 50  # low: put evicts before storing, and the eviction fails
            assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is False
            free["bytes"] = 500  # enough room, but over the cap: the eviction after it fails
            assert cache.put(_page(XREF + "d", html="x" * 400), WEEK) is True
        assert cache.get(XREF + "c") is None
        assert cache.get(XREF + "d") is not None
        assert "disk is full" in caplog.text
    finally:
        cache.close()


def test_a_full_disk_during_put_serves_the_page_uncached(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = PageCache(tmp_path)
    try:
        cache._conn.execute("PRAGMA max_page_count = 20")  # makes SQLite report SQLITE_FULL
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            assert cache.put(_page(XREF, html="x" * 500_000), WEEK) is False
        assert "disk is full" in caplog.text
        assert cache.get(XREF) is None
        assert cache.stats().bytes == 0 == _sum(cache)
    finally:
        cache.close()


class FullOnUpdate:
    """A connection whose UPDATE statements fail as on a full disk."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
        if sql.lstrip().upper().startswith("UPDATE"):
            _full_disk()
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


def test_a_full_disk_during_shorten_never_fails_the_caller(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = PageCache(tmp_path)
    real = cache._conn
    try:
        cache.put(_page(VIN, owner="alice", age=timedelta(days=2)), timedelta(days=30))
        cache._conn = FullOnUpdate(real)  # type: ignore[assignment]
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            cache.shorten(VIN, timedelta(days=1), owner="alice")  # does not raise
        assert "could not shorten" in caplog.text and "PX22770" not in caplog.text
    finally:
        cache._conn = real
        cache.close()


def test_reset_closes_before_deleting_and_reopens_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF), WEEK)
    order: list[str] = []
    old_conn = cache._conn
    real_delete = PageCache._delete_database_files

    def delete(self: PageCache) -> None:
        try:
            old_conn.execute("SELECT 1")
            order.append("deleted while open")
        except sqlite3.ProgrammingError:  # "Cannot operate on a closed database."
            order.append("deleted after close")
        real_delete(self)

    monkeypatch.setattr(PageCache, "_delete_database_files", delete)
    cache.reset()
    try:
        assert order == ["deleted after close"]
        assert (cache.stats().entries, cache.stats().bytes) == (0, 0)
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
