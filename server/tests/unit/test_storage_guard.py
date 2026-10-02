"""What the hosted server does when its own databases fail (hosted design 4.10)."""

import sqlite3

import pytest

from realoem_mcp.errors import RealOemError
from realoem_mcp.storage_guard import AUTH, VEHICLES, StorageGuard, run_directly


def _error(
    code: int, message: str = "simulated", kind: type[sqlite3.Error] = sqlite3.OperationalError
) -> sqlite3.Error:
    error = kind(message)
    error.sqlite_errorcode = code  # what SQLite sets on a real failure
    return error


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def free_space(self) -> None:
        self.events.append("cache deleted")

    def exit(self, status: int) -> None:
        self.events.append(f"exit {status}")


def _failing(*errors: BaseException):
    """An operation that raises the given errors in turn, then returns 'done'."""
    remaining = list(errors)

    def operation() -> str:
        if remaining:
            raise remaining.pop(0)
        return "done"

    return operation


def test_a_full_disk_deletes_the_page_cache_and_retries_once() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    assert guard.run(AUTH, _failing(_error(sqlite3.SQLITE_FULL))) == "done"
    assert recorder.events == ["cache deleted"]


def test_a_second_full_disk_ends_the_process() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    full = _error(sqlite3.SQLITE_FULL)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(VEHICLES, _failing(full, _error(sqlite3.SQLITE_FULL)))
    assert recorder.events == ["cache deleted", "exit 1"]


@pytest.mark.parametrize(
    "code", [sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_IOERR | (3 << 8)]
)
def test_a_damaged_auth_database_ends_the_process(code: int) -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(AUTH, _failing(_error(code)))
    assert recorder.events == ["exit 1"]


@pytest.mark.parametrize(
    ("store", "second", "events"),
    [
        (AUTH, _error(sqlite3.SQLITE_BUSY), ["cache deleted"]),
        (VEHICLES, _error(sqlite3.SQLITE_CORRUPT), ["cache deleted"]),
        (
            AUTH,
            _error(sqlite3.SQLITE_CORRUPT, kind=sqlite3.DatabaseError),
            ["cache deleted", "exit 1"],
        ),
    ],
    ids=["busy-after-full", "corrupt-index-after-full", "corrupt-auth-after-full"],
)
def test_only_a_second_full_disk_or_a_damaged_auth_database_is_fatal(
    store: str, second: sqlite3.Error, events: list[str]
) -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.Error):
        guard.run(store, _failing(_error(sqlite3.SQLITE_FULL), second))
    assert recorder.events == events


def test_a_file_that_is_not_a_database_ends_the_process() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.DatabaseError):  # what SQLite raises for NOTADB and CORRUPT
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_NOTADB, kind=sqlite3.DatabaseError)))
    assert recorder.events == ["exit 1"]


def test_other_errors_pass_through() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(VEHICLES, _failing(_error(sqlite3.SQLITE_CORRUPT)))  # not the auth database
    with pytest.raises(sqlite3.OperationalError):
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_BUSY)))
    with pytest.raises(ValueError):
        guard.run(AUTH, _failing(ValueError("not a database error")))
    assert recorder.events == []


def test_a_wrapped_full_disk_is_recognised() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    wrapped = RealOemError("The vehicle index could not be opened")
    wrapped.__cause__ = _error(sqlite3.SQLITE_FULL)
    assert guard.run(VEHICLES, _failing(wrapped)) == "done"
    assert recorder.events == ["cache deleted"]


def test_a_failure_to_free_space_ends_the_process() -> None:
    recorder = Recorder()

    def broken() -> None:
        raise OSError("cannot delete")

    guard = StorageGuard(broken, exit=recorder.exit)
    with pytest.raises(OSError):
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_FULL)))
    assert recorder.events == ["exit 1"]


def test_run_directly_adds_nothing() -> None:
    assert run_directly(AUTH, lambda: 42) == 42
