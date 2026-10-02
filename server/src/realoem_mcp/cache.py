"""SQLite cache of raw RealOEM pages, keyed by (owner, request URL) (AD5; hosted design 4.8)."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

SCHEMA_VERSION = "2"
# A new file name per schema version: an older server still running (another Claude Code session)
# keeps its own file instead of fighting over one.
DB_FILENAME = "pages.v2.sqlite3"
LEGACY_FILENAMES = ("pages.sqlite3",)  # deleted when possible
SHARED = ""  # owner of the pages every user may read
JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024
EVICT_TO = 0.9  # after crossing the cap, evict down to this share of it
EVICT_BATCH = 200
VACUUM_CHUNK_PAGES = 2048  # pages vacuumed between WAL checkpoints (8 MB with 4 KB pages)

logger = logging.getLogger(__name__)

# html is the LAST column: every other column can then be read without walking a large page's
# overflow chain, so the cap check, eviction, the purge and stats() never read page bodies.
_CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
  owner TEXT NOT NULL, url TEXT NOT NULL, page_type TEXT NOT NULL, final_url TEXT NOT NULL,
  status INTEGER NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  last_used INTEGER NOT NULL, size_bytes INTEGER NOT NULL, html TEXT NOT NULL,
  PRIMARY KEY (owner, url))
"""
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS pages_last_used ON pages (last_used)",
    "CREATE INDEX IF NOT EXISTS pages_expires_at ON pages (expires_at)",
)
_CREATE_META = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _iso(value: datetime) -> str:
    # Fixed-width UTC timestamps compare correctly as strings.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _is_corruption(error: sqlite3.DatabaseError) -> bool:
    """True only for a damaged or non-SQLite file (OperationalError covers locks and I/O)."""
    if isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)


def is_full(error: sqlite3.Error) -> bool:
    """True when SQLite reports that the disk (or the database) is full."""
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) == sqlite3.SQLITE_FULL


def _total(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT value FROM meta WHERE key = 'total_bytes'").fetchone()[0])


def _add_total(conn: sqlite3.Connection, delta: int) -> None:
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) "
        "WHERE key = 'total_bytes'",
        (delta,),
    )


def _schema_complete(conn: sqlite3.Connection) -> bool:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"meta", "pages"} <= tables:
        return False
    keys = {row[0] for row in conn.execute("SELECT key FROM meta")}
    return {"schema_version", "total_bytes"} <= keys


def _rollback(conn: sqlite3.Connection) -> None:
    # SQLite has already rolled back after some errors (a full disk is one); a second ROLLBACK
    # would raise "no transaction is active" and hide the real error.
    if conn.in_transaction:
        conn.execute("ROLLBACK")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int  # total UTF-8 size of the cached HTML
    path: Path


class PageCache:
    """The page cache. One connection, used only from the event-loop thread: the hosted server's
    hourly purge and its full-disk reset() must run there too, never in a worker thread."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        max_bytes: int = 0,
        min_free_bytes: int = 0,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
        clock: Callable[[], float] = time.time,
    ) -> None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / DB_FILENAME
        self._max_bytes = max_bytes  # 0 = no cap
        self._min_free_bytes = min_free_bytes  # 0 = no free-space floor
        self._disk_usage = disk_usage
        self._clock = clock
        try:
            self._conn = self._open()
        except sqlite3.DatabaseError as error:
            if not _is_corruption(error):
                raise  # locked, read-only, disk I/O...: the file is fine, so never delete it
            logger.warning("page cache %s is unusable (%s); recreating it", self.path, error)
            try:
                self._delete_database_files()
            except OSError as os_error:
                error.add_note(f"the corrupt cache {self.path} could not be deleted: {os_error}")
                raise error from os_error
            self._conn = self._open()
        self._remove_legacy_files()

    def _connect(self) -> sqlite3.Connection:
        # Autocommit; one connection used only from the event-loop thread.
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            if conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0:
                # Only possible before the first table exists; lets evictions shrink the file.
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # the cache is disposable; safe in WAL mode
            conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")
        except BaseException:
            conn.close()
            raise
        return conn

    def _open(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            if self._is_outdated(conn):
                # A new schema needs a new file: auto_vacuum cannot be turned on once tables exist.
                conn.close()
                self._delete_database_files()
                conn = self._connect()
            self._ensure_schema(conn)
            self._purge_expired(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _delete_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def _remove_legacy_files(self) -> None:
        """Delete the files of older cache versions. On Windows they stay while another process
        has them open; elsewhere that process keeps its now-unlinked file until it exits."""
        for name in LEGACY_FILENAMES:
            for suffix in ("", "-wal", "-shm"):
                try:
                    (self.path.parent / f"{name}{suffix}").unlink(missing_ok=True)
                except OSError as error:
                    logger.info("left the old page cache %s in place: %s", name, error)
                    break

    @staticmethod
    def _is_outdated(conn: sqlite3.Connection) -> bool:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not tables:
            return False
        if "meta" not in tables:
            return True
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return row is None or row[0] != SCHEMA_VERSION

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        """Create what is missing in one transaction, so a process starting at the same moment
        sees either no table or all of them. An existing cache opens without the write lock."""
        if _schema_complete(conn):
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_CREATE_META)
            conn.execute(_CREATE_PAGES)
            for statement in _CREATE_INDEXES:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) "
                "SELECT 'total_bytes', CAST(COALESCE(SUM(size_bytes), 0) AS TEXT) FROM pages"
            )
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise

    @staticmethod
    def _purge_expired(conn: sqlite3.Connection) -> int:
        now = _iso(datetime.now(UTC))
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                freed, removed = conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0), COUNT(*) FROM pages "
                    "WHERE expires_at <= ?",
                    (now,),
                ).fetchone()
                conn.execute("DELETE FROM pages WHERE expires_at <= ?", (now,))
                _add_total(conn, -freed)
                conn.execute("COMMIT")
            except BaseException:
                _rollback(conn)
                raise
        except sqlite3.OperationalError as error:
            # Housekeeping only: get() ignores expired rows, so a busy or full disk must never
            # stop startup or the hourly purge.
            logger.warning("skipping expired-page purge: %s", error)
            return 0
        return removed

    @contextmanager
    def _tx(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            _rollback(self._conn)
            raise

    def get(self, url: str, *, owner: str = SHARED) -> Page | None:
        row = self._conn.execute(
            "SELECT page_type, final_url, status, fetched_at, html FROM pages "
            "WHERE owner = ? AND url = ? AND expires_at > ?",
            (owner, url, _iso(datetime.now(UTC))),
        ).fetchone()
        if row is None:
            return None
        if self._max_bytes:
            self._touch(owner, url)
        page_type, final_url, status, fetched_at, html = row
        return Page(
            page_type=PageType(page_type),
            url=url,
            final_url=final_url,
            status=status,
            html=html,
            fetched_at=datetime.fromisoformat(fetched_at),
            from_cache=True,
            owner=owner,
        )

    def _touch(self, owner: str, url: str) -> None:
        try:
            self._conn.execute(
                "UPDATE pages SET last_used = ? WHERE owner = ? AND url = ?",
                (int(self._clock()), owner, url),
            )
        except sqlite3.OperationalError as error:  # never fail a read over bookkeeping
            logger.debug("could not record a cache hit: %s", error)  # no URL: it may hold a VIN

    def put(self, page: Page, ttl: timedelta) -> bool:
        """Store the page under (page.owner, page.url). False when it was served uncached.

        A full or nearly full disk never fails the caller: the page is then served uncached.
        """
        size = len(page.html.encode("utf-8"))
        try:
            if not self._has_room():
                logger.warning(
                    "disk space is low; serving %s without caching it", page.page_type.value
                )
                return False
            with self._tx():
                old = self._conn.execute(
                    "SELECT size_bytes FROM pages WHERE owner = ? AND url = ?",
                    (page.owner, page.url),
                ).fetchone()
                self._conn.execute(
                    "INSERT OR REPLACE INTO pages (owner, url, page_type, final_url, status, "
                    "fetched_at, expires_at, last_used, size_bytes, html) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        page.owner,
                        page.url,
                        page.page_type.value,
                        page.final_url,
                        page.status,
                        _iso(page.fetched_at),
                        _iso(page.fetched_at + ttl),
                        int(self._clock()),
                        size,
                        page.html,
                    ),
                )
                _add_total(self._conn, size - (old[0] if old else 0))
        except sqlite3.OperationalError as error:
            if not is_full(error):
                raise
            logger.warning("the disk is full; serving %s without caching it", page.page_type.value)
            return False
        try:
            self._enforce_cap()
        except sqlite3.OperationalError as error:
            if not is_full(error):
                raise
            logger.warning("the disk is full; could not evict cached pages")  # the page is stored
        return True

    def shorten(self, url: str, ttl: timedelta, *, owner: str = SHARED) -> None:
        """Cap an entry's lifetime at fetched_at + ttl (used for negative results)."""
        row = self._conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE owner = ? AND url = ?", (owner, url)
        ).fetchone()
        if row is None:
            return
        capped = _iso(datetime.fromisoformat(row[0]) + ttl)
        if capped < row[1]:
            try:
                self._conn.execute(
                    "UPDATE pages SET expires_at = ? WHERE owner = ? AND url = ?",
                    (capped, owner, url),
                )
            except sqlite3.OperationalError as error:
                if not is_full(error):
                    raise
                # No URL in the log: it may hold a VIN. The tool call itself carries on.
                logger.warning("the disk is full; could not shorten a cached page's lifetime")

    def clear(self, page_type: PageType | None = None) -> int:
        """Delete every owner's pages (of one page type, or all). Returns the rows removed."""
        with self._tx():
            if page_type is None:
                removed = self._conn.execute("DELETE FROM pages").rowcount
                self._conn.execute("UPDATE meta SET value = '0' WHERE key = 'total_bytes'")
            else:
                value = PageType(page_type).value
                freed = self._conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0) FROM pages WHERE page_type = ?", (value,)
                ).fetchone()[0]
                removed = self._conn.execute(
                    "DELETE FROM pages WHERE page_type = ?", (value,)
                ).rowcount
                _add_total(self._conn, -freed)
        self._release_free_pages()
        return removed

    def purge_expired(self) -> int:
        """Delete expired rows (the hourly housekeeping of the hosted server)."""
        removed = self._purge_expired(self._conn)
        if removed:
            self._release_free_pages()
        return removed

    def stats(self) -> CacheStats:
        entries = self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        return CacheStats(entries=entries, bytes=_total(self._conn), path=self.path)

    def _enforce_cap(self) -> None:
        if self._max_bytes and _total(self._conn) > self._max_bytes:
            self._evict_to(int(self._max_bytes * EVICT_TO))

    def _evict_to(self, target: int) -> int:
        """Delete least-recently-used rows until the total is at most target bytes."""
        if _total(self._conn) <= target:
            return 0  # take no write lock for nothing (on a full disk even that could fail)
        evicted = 0
        with self._tx():
            total = _total(self._conn)
            while total > target:
                victims = self._conn.execute(
                    "SELECT owner, url, size_bytes FROM pages "
                    "ORDER BY last_used, fetched_at LIMIT ?",
                    (EVICT_BATCH,),
                ).fetchall()
                if not victims:
                    break
                doomed = []
                for owner, url, size in victims:
                    if total <= target:
                        break
                    doomed.append((owner, url))
                    total -= size
                self._conn.executemany("DELETE FROM pages WHERE owner = ? AND url = ?", doomed)
                evicted += len(doomed)
            self._conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'total_bytes'", (str(max(total, 0)),)
            )
        if evicted:
            logger.info("evicted %d cached pages (cache is over its size cap)", evicted)
            self._release_free_pages()
        return evicted

    def _release_free_pages(self) -> None:
        """Hand freed pages back to the filesystem.

        incremental_vacuum moves pages from the end of the file into the free slots, and in WAL
        mode every moved page is first written to the -wal file. So the vacuum runs in chunks
        with a checkpoint after each. With a cap or a free-space floor (the hosted server, which
        has one connection, or a stdio cache given REALOEM_CACHE_MAX_MB) that is a TRUNCATE
        checkpoint, which empties the -wal, so the vacuum needs at most one chunk of extra disk
        space; it may wait a moment for another process's reader. Otherwise (stdio) it is a
        PASSIVE checkpoint, which never waits. executescript, not execute: Python's execute()
        steps the pragma once, which frees a single page.
        """
        mode = "TRUNCATE" if self._max_bytes or self._min_free_bytes else "PASSIVE"
        try:
            remaining = self._free_pages()
            while remaining:
                self._conn.executescript(f"PRAGMA incremental_vacuum({VACUUM_CHUNK_PAGES});")
                self._conn.execute(f"PRAGMA wal_checkpoint({mode})")
                left = self._free_pages()
                if left >= remaining:
                    break  # no progress (another process is busy): the next eviction retries
                remaining = left
        except sqlite3.OperationalError as error:
            logger.warning("could not release free cache pages: %s", error)

    def _free_pages(self) -> int:
        return self._conn.execute("PRAGMA freelist_count").fetchone()[0]

    def _has_room(self) -> bool:
        if not self._min_free_bytes:
            return True
        if self._disk_usage(self.path.parent).free >= self._min_free_bytes:
            return True
        if self._max_bytes:
            self._evict_to(self._max_bytes // 2)
        return self._disk_usage(self.path.parent).free >= self._min_free_bytes

    def reset(self) -> None:
        """Close, delete the cache files and reopen empty: the one way to free disk space at once.

        The connection is closed first: on Linux a deleted file frees nothing while it is open.
        If reopening fails, the cache is unusable; the hosted server then exits and restarts.
        """
        self._conn.close()
        try:
            self._delete_database_files()
        finally:
            self._conn = self._open()

    def close(self) -> None:
        self._conn.close()
