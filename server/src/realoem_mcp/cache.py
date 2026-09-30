"""SQLite cache of raw RealOEM pages, keyed by request URL (AD5)."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

SCHEMA_VERSION = "1"
DB_FILENAME = "pages.sqlite3"

logger = logging.getLogger(__name__)

_CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, page_type TEXT NOT NULL, final_url TEXT NOT NULL, status INTEGER NOT NULL,
  html TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL)
"""
_CREATE_META = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _iso(value: datetime) -> str:
    # Fixed-width UTC timestamps compare correctly as strings.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int  # total UTF-8 size of the cached HTML
    path: Path


class PageCache:
    def __init__(self, cache_dir: Path) -> None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / DB_FILENAME
        try:
            self._conn = self._open()
        except sqlite3.DatabaseError as error:
            logger.warning("page cache %s is unusable (%s); recreating it", self.path, error)
            self._delete_database_files()
            self._conn = self._open()

    def _open(self) -> sqlite3.Connection:
        # Autocommit; one connection used only from the event-loop thread.
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_schema(conn)
            conn.execute("DELETE FROM pages WHERE expires_at <= ?", (_iso(datetime.now(UTC)),))
        except BaseException:
            conn.close()
            raise
        return conn

    def _delete_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_META)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is not None and row[0] == SCHEMA_VERSION:
            conn.execute(_CREATE_PAGES)
            return
        conn.execute("DROP TABLE IF EXISTS pages")
        conn.execute(_CREATE_PAGES)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )

    def get(self, url: str) -> Page | None:
        row = self._conn.execute(
            "SELECT page_type, url, final_url, status, html, fetched_at FROM pages "
            "WHERE url = ? AND expires_at > ?",
            (url, _iso(datetime.now(UTC))),
        ).fetchone()
        if row is None:
            return None
        page_type, url, final_url, status, html, fetched_at = row
        return Page(
            page_type=PageType(page_type),
            url=url,
            final_url=final_url,
            status=status,
            html=html,
            fetched_at=datetime.fromisoformat(fetched_at),
            from_cache=True,
        )

    def put(self, page: Page, ttl: timedelta) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO pages "
            "(url, page_type, final_url, status, html, fetched_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                page.url,
                page.page_type.value,
                page.final_url,
                page.status,
                page.html,
                _iso(page.fetched_at),
                _iso(page.fetched_at + ttl),
            ),
        )

    def shorten(self, url: str, ttl: timedelta) -> None:
        """Cap an entry's lifetime at fetched_at + ttl (used for negative results)."""
        row = self._conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return
        capped = _iso(datetime.fromisoformat(row[0]) + ttl)
        if capped < row[1]:
            self._conn.execute("UPDATE pages SET expires_at = ? WHERE url = ?", (capped, url))

    def clear(self, page_type: PageType | None = None) -> int:
        if page_type is None:
            cursor = self._conn.execute("DELETE FROM pages")
        else:
            cursor = self._conn.execute(
                "DELETE FROM pages WHERE page_type = ?", (PageType(page_type).value,)
            )
        return cursor.rowcount

    def stats(self) -> CacheStats:
        entries, size = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(html AS BLOB))), 0) FROM pages"
        ).fetchone()
        return CacheStats(entries=entries, bytes=size, path=self.path)

    def close(self) -> None:
        self._conn.close()
