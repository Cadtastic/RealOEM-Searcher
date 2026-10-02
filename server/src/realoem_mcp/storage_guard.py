"""What the hosted server does when one of its own databases fails (hosted design 4.10).

The page cache is disposable; the auth database and the vehicle index are not. When either finds
the disk full, deleting the cache files is the one action that frees space without needing any,
so the guard does that and retries the operation once. A second full disk, or a damaged auth
database, ends the process so that Fly restarts it: /healthz never heals anything by itself.
Any other error (a busy database, say) is raised as usual.

Every operation passed to a Runner must be safe to run again: one whole transaction.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from typing import NoReturn, Protocol, TypeVar

from realoem_mcp.cache import is_full

T = TypeVar("T")

AUTH = "auth"
VEHICLES = "vehicle index"
_BROKEN = (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_NOTADB)

log = logging.getLogger(__name__)


class Runner(Protocol):
    def __call__(self, store: str, operation: Callable[[], T], /) -> T: ...


def run_directly(store: str, operation: Callable[[], T]) -> T:
    """The Runner that adds nothing: stdio, tests and the admin script."""
    return operation()


def sqlite_error(error: BaseException) -> sqlite3.Error | None:
    """The SQLite error behind error: itself, or the cause a wrapper (RealOemError) kept."""
    for candidate in (error, error.__cause__):
        if isinstance(candidate, sqlite3.Error):
            return candidate
    return None


def _is_broken(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) in _BROKEN


def hard_exit(status: int) -> NoReturn:
    """End the process at once, even from inside a request handler (where SystemExit may be
    swallowed), after flushing the logs that os._exit would skip."""
    logging.shutdown()
    os._exit(status)


class StorageGuard:
    """A Runner for the hosted server. free_space deletes the page cache files; the HTTP app
    points it at PageCache.reset once the cache is open."""

    def __init__(
        self, free_space: Callable[[], None], *, exit: Callable[[int], object] = hard_exit
    ) -> None:
        self.free_space = free_space
        self._exit = exit

    def run(self, store: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except Exception as error:
            cause = sqlite_error(error)
            if cause is None:
                raise
            if not is_full(cause):
                if store == AUTH and _is_broken(cause):
                    self._fatal(store, cause)
                raise
        log.error("the %s database found the disk full; deleting the page cache, retrying", store)
        try:
            self.free_space()
        except Exception as error:
            self._fatal("page cache", error)
            raise
        try:
            return operation()
        except Exception as error:
            cause = sqlite_error(error)
            if cause is not None and (is_full(cause) or (store == AUTH and _is_broken(cause))):
                self._fatal(store, cause)
            raise

    def _fatal(self, store: str, error: BaseException) -> None:
        log.critical("the %s database failed (%s); exiting so the server restarts", store, error)
        self._exit(1)  # never returns, except for a test double
