"""The sign-in database (hosted design 4.4, 4.9)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from realoem_mcp.auth.records import (
    AWAITING_CONSENT,
    CONSENTED,
    GITHUB_RETURNED,
    ClientRecord,
    CodeRecord,
    PendingRequest,
)
from realoem_mcp.auth.store import MIGRATIONS, AuthStore, migrate

NOW = 1_800_000_000  # 2027-01-15
HOUR, DAY = 3_600, 86_400


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AuthStore]:
    opened = AuthStore.open(tmp_path / "auth.sqlite3")
    yield opened
    opened.close()


def _pending(request_id: str = "req1", expires_at: int = NOW + 600) -> PendingRequest:
    return PendingRequest(
        id=request_id,
        client_id="client1",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_explicit=True,
        client_state="s",
        code_challenge="c" * 43,
        resource="https://x/mcp",
        scopes=("realoem",),
        status=AWAITING_CONSENT,
        expires_at=expires_at,
    )


def test_a_new_database_is_migrated_and_reopening_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    AuthStore.open(path).close()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    expected = {"clients", "pending", "authorization_codes", "families", "tokens", "users"}
    assert expected | {"consents", "usage"} <= tables
    AuthStore.open(path).close()  # already migrated: nothing to do


def test_a_migration_another_process_applied_meanwhile_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    AuthStore.open(path).close()  # the other process migrated first
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        real_execute = conn.execute
        reads = iter([0])  # what this process read before it took the lock

        class StaleFirstRead:
            def execute(self, sql: str, *args: object):
                if sql == "PRAGMA user_version" and (stale := next(reads, None)) is not None:
                    return real_execute("SELECT ?", (stale,))
                return real_execute(sql, *args)

            def __getattr__(self, name: str) -> object:
                return getattr(conn, name)

        migrate(StaleFirstRead())  # type: ignore[arg-type]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_a_database_from_a_newer_server_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer than this server"):
        AuthStore.open(path)


def test_atomic_rolls_back_everything_on_error(store: AuthStore) -> None:
    def work() -> None:
        store.add_pending(_pending())
        raise ValueError("boom")

    with pytest.raises(ValueError):
        store.atomic(work)
    assert store.pending("req1", NOW) is None
    assert store.conn.in_transaction is False


def test_a_pending_request_moves_forward_once(store: AuthStore) -> None:
    store.add_pending(_pending())
    assert store.pending("req1", NOW) is not None
    consented = store.consent("req1", "statehash", NOW)
    assert consented is not None and consented.status == CONSENTED
    assert store.consent("req1", "statehash", NOW) is None  # a second answer
    assert store.deny("req1", NOW) is None
    assert store.pending("req1", NOW) is None  # no longer waiting for consent
    returned = store.return_from_github("statehash", NOW)
    assert returned is not None and returned.status == GITHUB_RETURNED
    assert store.return_from_github("statehash", NOW) is None  # the state works once


def test_an_expired_request_cannot_be_answered(store: AuthStore) -> None:
    store.add_pending(_pending(expires_at=NOW))
    assert store.pending("req1", NOW) is None
    assert store.consent("req1", "h", NOW) is None
    assert store.deny("req1", NOW) is None


def test_a_code_can_be_used_once(store: AuthStore) -> None:
    store.add_code(
        CodeRecord(
            "codehash",
            "fam",
            "client1",
            "https://r",
            True,
            "c" * 43,
            "https://x/mcp",
            ("realoem",),
            "github:1",
            NOW + 600,
            None,
        )
    )
    assert store.use_code("codehash", NOW) is True
    assert store.use_code("codehash", NOW) is False
    assert store.code("codehash").used_at == NOW


def _family_with_tokens(store: AuthStore, family: str = "fam", subject: str = "github:1") -> None:
    store.add_family(family, subject, "client1", NOW, NOW + 90 * DAY)
    store.add_token(
        f"{family}-a", "access", family, subject, "client1", ["realoem"], "r", NOW + HOUR
    )
    store.add_token(
        f"{family}-r", "refresh", family, subject, "client1", ["realoem"], "r", NOW + 30 * DAY
    )


def test_tokens_are_found_only_with_their_own_kind(store: AuthStore) -> None:
    _family_with_tokens(store)
    access = store.token("fam-a", "access")
    assert access is not None and (access.subject, access.family_revoked) == ("github:1", False)
    assert store.token("fam-a", "refresh") is None
    assert store.token("fam-r", "access") is None


def test_rotation_happens_once_and_never_on_a_revoked_family(store: AuthStore) -> None:
    _family_with_tokens(store)
    assert store.rotate("fam-a", NOW) is False  # only a refresh token rotates
    assert store.rotate("fam-r", NOW) is True
    assert store.rotate("fam-r", NOW) is False
    _family_with_tokens(store, "fam2")
    store.revoke_family("fam2")
    assert store.rotate("fam2-r", NOW) is False
    assert store.token("fam2-a", "access").family_revoked is True


def test_active_families_are_listed_oldest_first(store: AuthStore) -> None:
    for number in range(3):
        store.add_family(f"f{number}", "github:1", "c", NOW + number, NOW + DAY)
    store.add_family("other", "github:2", "c", NOW, NOW + DAY)
    store.add_family("ended", "github:1", "c", NOW, NOW)
    store.revoke_family("f1")
    assert store.active_families("github:1", NOW) == ["f0", "f2"]


def test_a_ban_revokes_every_token_and_shows_on_lookup(store: AuthStore) -> None:
    store.upsert_user("github:1", "octocat", datetime(2011, 1, 25, tzinfo=UTC), NOW)
    _family_with_tokens(store)
    store.ban("github:1", "abuse", NOW)
    assert store.is_banned("github:1")
    assert store.token("fam-a", "access").banned is True
    assert store.token("fam-a", "access").family_revoked is True
    assert store.unban("github:1") is True
    assert not store.is_banned("github:1")
    store.ban("github:9", "never seen", NOW)  # an id that never signed in can be banned too
    assert store.is_banned("github:9")


def test_users_keep_their_account_age(store: AuthStore) -> None:
    created = datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC)
    store.upsert_user("github:1", "octocat", created, NOW)
    store.upsert_user("github:1", "octocat-renamed", None, NOW + DAY)
    user = store.user("github:1")
    assert (user.github_login, user.github_created_at, user.first_seen) == (
        "octocat-renamed",
        created,
        NOW,
    )
    assert store.github_created_at("github:1") == created
    assert store.github_created_at("github:2") is None


def _code_record(code_hash: str, expires_at: int) -> CodeRecord:
    return CodeRecord(
        code_hash,
        "fam",
        "client1",
        "https://r",
        True,
        "c" * 43,
        "r",
        ("realoem",),
        "github:1",
        expires_at,
        None,
    )


def test_purge_removes_what_is_no_longer_needed(store: AuthStore) -> None:
    store.add_pending(_pending("stale", expires_at=NOW - 1))
    store.add_pending(_pending("live"))
    assert store.live_pending_count(NOW) == 1
    store.add_code(_code_record("old-code", NOW - 1))
    store.add_code(_code_record("live-code", NOW + 600))
    store.add_client(ClientRecord("unused", None, {}, NOW - 25 * HOUR, None))
    store.add_client(ClientRecord("new", None, {}, NOW - HOUR, None))
    store.add_client(ClientRecord("idle", None, {}, NOW - 200 * DAY, NOW - 91 * DAY))
    store.add_client(ClientRecord("active", None, {}, NOW - 200 * DAY, NOW - DAY))
    _family_with_tokens(store)
    store.add_token("old-a", "access", "fam", "github:1", "client1", ["realoem"], "r", NOW - 1)
    store.add_token("rotated", "refresh", "fam", "github:1", "client1", ["realoem"], "r", NOW - 1)
    store.rotate("rotated", NOW - 2)
    store.add_family("ended", "github:1", "client1", NOW - 91 * DAY, NOW - 1)
    store.add_token("ended-r", "refresh", "ended", "github:1", "client1", ["realoem"], "r", NOW + 1)
    store.add_consent("github:1", "client1", "https://r", NOW - 91 * DAY)
    store.add_consent("github:1", "client1", "https://r", NOW - DAY)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2026-10-01', 5)")
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-14', 5)")
    removed = store.purge(NOW)
    assert removed == {
        "pending": 1,
        "authorization_codes": 1,
        "tokens": 2,  # the expired access token and the ended family's token
        "families": 1,
        "clients": 2,
        "usage": 1,
        "consents": 1,
    }
    assert store.token("rotated", "refresh") is not None  # kept: it detects a replay
    # Everything still needed survives: a purge that deleted the wrong rows reports the same counts.
    assert store.pending("live", NOW) is not None
    assert store.code("live-code") is not None
    assert store.token("fam-r", "refresh") is not None  # the live family's tokens
    assert store.client("new") is not None and store.client("active") is not None
    assert store.usage("2027-01-14") == [("github:1", None, 5)]
    assert store.conn.execute("SELECT COUNT(*) FROM consents").fetchone() == (1,)


def test_usage_report_names_users(store: AuthStore) -> None:
    store.upsert_user("github:1", "octocat", None, NOW)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-15', 7)")
    store.conn.execute("INSERT INTO usage VALUES ('*', '2027-01-15', 9)")
    store.conn.execute("INSERT INTO usage VALUES ('github:2', '2027-01-15', 2)")
    assert store.usage("2027-01-15") == [
        ("*", None, 9),
        ("github:1", "octocat", 7),
        ("github:2", None, 2),
    ]
