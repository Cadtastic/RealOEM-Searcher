import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.cache import DB_FILENAME, SCHEMA_VERSION, PageCache
from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

XREF = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"
GRP = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"


def _page(url: str, page_type: PageType, *, age: timedelta = timedelta(0), html: str = "<p>ok</p>"):
    return Page(
        page_type=page_type,
        url=url,
        final_url=url,
        status=200,
        html=html,
        fetched_at=datetime.now(UTC) - age,
        from_cache=False,
    )


@pytest.fixture
def cache(tmp_path: Path):
    cache = PageCache(tmp_path / "cache")
    yield cache
    cache.close()


def test_creates_database_in_cache_dir(tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "nested" / "cache")
    try:
        assert cache.path == tmp_path / "nested" / "cache" / DB_FILENAME
        assert cache.path.exists()
    finally:
        cache.close()


def test_put_then_get_round_trips_as_cached(cache: PageCache) -> None:
    page = _page(XREF, PageType.PARTXREF)
    cache.put(page, timedelta(days=7))
    hit = cache.get(XREF)
    assert hit is not None
    assert hit.from_cache is True
    assert (hit.page_type, hit.url, hit.final_url, hit.status, hit.html) == (
        PageType.PARTXREF,
        XREF,
        XREF,
        200,
        "<p>ok</p>",
    )
    assert hit.fetched_at == page.fetched_at
    assert hit.fetched_at.tzinfo is not None


def test_miss_returns_none(cache: PageCache) -> None:
    assert cache.get(XREF) is None


def test_expired_entry_is_not_returned(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=8)), timedelta(days=7))
    assert cache.get(XREF) is None


def test_shorten_caps_lifetime(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=2)), timedelta(days=180))
    cache.shorten(XREF, timedelta(days=1))
    assert cache.get(XREF) is None


def test_shorten_never_extends_lifetime(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=2)), timedelta(days=1))
    cache.shorten(XREF, timedelta(days=30))
    assert cache.get(XREF) is None


def test_shorten_unknown_url_is_a_no_op(cache: PageCache) -> None:
    cache.shorten(XREF, timedelta(days=1))
    assert cache.stats().entries == 0


def test_clear_all_and_by_page_type(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.put(_page(GRP, PageType.PARTGRP), timedelta(days=30))
    assert cache.clear(PageType.PARTGRP) == 1
    assert cache.get(GRP) is None
    assert cache.get(XREF) is not None
    assert cache.clear() == 1
    assert cache.stats().entries == 0


def test_stats_counts_entries_and_utf8_bytes(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, html="ä"), timedelta(days=7))
    cache.put(_page(GRP, PageType.PARTGRP, html="abc"), timedelta(days=7))
    stats = cache.stats()
    assert (stats.entries, stats.bytes, stats.path) == (2, 5, cache.path)


def test_schema_version_mismatch_resets_tables(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.close()
    with closing(sqlite3.connect(tmp_path / DB_FILENAME)) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
        conn.commit()
    reopened = PageCache(tmp_path)
    try:
        assert reopened.stats().entries == 0
        with closing(sqlite3.connect(tmp_path / DB_FILENAME)) as conn:
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert version == (SCHEMA_VERSION,)
    finally:
        reopened.close()


def test_matching_schema_keeps_data(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.close()
    reopened = PageCache(tmp_path)
    try:
        assert reopened.get(XREF) is not None
    finally:
        reopened.close()


def test_corrupt_database_is_replaced_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / DB_FILENAME).write_bytes(b"this is definitely not a sqlite database" * 50)
    with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
        cache = PageCache(cache_dir)
    try:
        warnings = [r for r in caplog.records if r.name == "realoem_mcp.cache"]
        assert [r.levelname for r in warnings] == ["WARNING"]
        assert "recreating" in warnings[0].getMessage()
        assert cache.stats().entries == 0
        cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
        assert cache.get(XREF) is not None
    finally:
        cache.close()


def test_expired_rows_are_purged_on_open(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    first = PageCache(cache_dir)
    first.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=10)), timedelta(days=7))
    first.put(_page(GRP, PageType.PARTGRP), timedelta(days=30))
    assert first.stats().entries == 2  # expired row still physically present
    first.close()
    second = PageCache(cache_dir)
    try:
        assert second.stats().entries == 1
        assert second.get(GRP) is not None
    finally:
        second.close()


def test_locked_database_is_not_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "cache"
    PageCache(cache_dir).close()  # create a valid database
    path = cache_dir / DB_FILENAME

    def locked(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as patch:
        patch.setattr(PageCache, "_ensure_schema", staticmethod(locked))
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            PageCache(cache_dir)
    assert path.exists()
    PageCache(cache_dir).close()  # still a usable database once the lock is released


def test_corrupt_database_that_cannot_be_deleted_raises_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / DB_FILENAME).write_bytes(b"this is definitely not a sqlite database" * 50)

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(sqlite3.DatabaseError) as info:
        PageCache(cache_dir)
    assert any("could not be deleted" in note for note in info.value.__notes__)


def test_busy_database_skips_the_expired_page_purge_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cache_dir = tmp_path / "cache"
    seed = PageCache(cache_dir)  # valid WAL database
    seed.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=10)), timedelta(days=7))
    seed.close()
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        "realoem_mcp.cache.sqlite3.connect",
        lambda *args, **kwargs: real_connect(*args, **{**kwargs, "timeout": 0.05}),
    )
    # A writer holding the WAL write lock blocks only the purge; reads and schema checks still work.
    holder = real_connect(cache_dir / DB_FILENAME, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            cache = PageCache(cache_dir)
    finally:
        holder.close()
    try:
        warnings = [r for r in caplog.records if r.name == "realoem_mcp.cache"]
        assert [r.levelname for r in warnings] == ["WARNING"]
        assert "skipping expired-page purge" in warnings[0].getMessage()
        assert cache.get(XREF) is None  # expired rows stay invisible even if not purged
    finally:
        cache.close()
