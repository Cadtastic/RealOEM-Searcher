"""The hosted server's sign-in database, auth.sqlite3 (hosted design 4.4).

Stdlib sqlite3 in WAL mode, migrated forward only (never dropped and recreated: bans, consents
and usage survive upgrades). Tokens and codes are stored as keyed hashes (auth/keys.py). Every
statement runs through the Runner, so on the hosted server a full disk frees the page cache and
retries once, and a damaged database ends the process (storage_guard.py).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from realoem_mcp.auth.records import (
    AWAITING_CONSENT,
    CONSENTED,
    DENIED,
    GITHUB_RETURNED,
    ClientRecord,
    CodeRecord,
    PendingRequest,
    TokenRecord,
    UserRecord,
)
from realoem_mcp.storage_guard import AUTH, Runner, run_directly

T = TypeVar("T")

JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024
BUSY_TIMEOUT_MS = 5_000  # the admin script may hold the write lock for a moment
UNUSED_CLIENT_AGE = timedelta(hours=24)  # a client that never completed a sign-in
IDLE_CLIENT_AGE = timedelta(days=90)  # a client with no token issued for this long
RETENTION = timedelta(days=90)  # usage rows and the consent audit

# Forward-only migrations: MIGRATIONS[n] takes the database from user_version n to n + 1.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE clients (
          client_id TEXT PRIMARY KEY, client_secret TEXT, metadata TEXT NOT NULL,
          created_at INTEGER NOT NULL, last_issued_at INTEGER)""",
        """CREATE TABLE pending (
          id TEXT PRIMARY KEY, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
          redirect_uri_explicit INTEGER NOT NULL, client_state TEXT, code_challenge TEXT NOT NULL,
          resource TEXT NOT NULL, scopes TEXT NOT NULL, status TEXT NOT NULL,
          gh_state_hash TEXT UNIQUE, subject TEXT, expires_at INTEGER NOT NULL)""",
        "CREATE INDEX pending_expires_at ON pending (expires_at)",
        """CREATE TABLE authorization_codes (
          hash TEXT PRIMARY KEY, family TEXT NOT NULL, client_id TEXT NOT NULL,
          redirect_uri TEXT NOT NULL, redirect_uri_explicit INTEGER NOT NULL,
          code_challenge TEXT NOT NULL, resource TEXT NOT NULL, scopes TEXT NOT NULL,
          subject TEXT NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER)""",
        """CREATE TABLE families (
          id TEXT PRIMARY KEY, subject TEXT NOT NULL, client_id TEXT NOT NULL,
          created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
          revoked INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX families_subject ON families (subject)",
        """CREATE TABLE tokens (
          hash TEXT PRIMARY KEY, kind TEXT NOT NULL, family TEXT NOT NULL, subject TEXT NOT NULL,
          client_id TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT NOT NULL,
          expires_at INTEGER NOT NULL, rotated_at INTEGER)""",
        "CREATE INDEX tokens_family ON tokens (family)",
        """CREATE TABLE users (
          subject TEXT PRIMARY KEY, github_login TEXT NOT NULL, github_created_at TEXT,
          first_seen INTEGER NOT NULL, banned_at INTEGER, banned_reason TEXT)""",
        """CREATE TABLE consents (
          subject TEXT NOT NULL, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
          granted_at INTEGER NOT NULL)""",
        "CREATE INDEX consents_granted_at ON consents (granted_at)",
        # The table Quota counts in (quota.USAGE_SCHEMA); a migration's text never changes.
        """CREATE TABLE IF NOT EXISTS usage (
          subject TEXT NOT NULL, day TEXT NOT NULL, requests INTEGER NOT NULL,
          PRIMARY KEY (subject, day))""",
    ),
)

_PENDING = (
    "id, client_id, redirect_uri, redirect_uri_explicit, client_state, code_challenge, resource, "
    "scopes, status, expires_at, subject"
)
_CODE = (
    "hash, family, client_id, redirect_uri, redirect_uri_explicit, code_challenge, resource, "
    "scopes, subject, expires_at, used_at"
)


def _version(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise RuntimeError(
            f"auth database version {version} is newer than this server ({len(MIGRATIONS)})"
        )
    return version


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the database to the newest version; each migration is one transaction.

    The version is read again under the write lock: another process (the admin script while
    the server restarts) may have applied the same migration in the meantime.
    """
    while _version(conn) < len(MIGRATIONS):
        conn.execute("BEGIN IMMEDIATE")
        try:
            number = _version(conn)
            if number < len(MIGRATIONS):
                for statement in MIGRATIONS[number]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {number + 1}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def _scopes(text: str) -> tuple[str, ...]:
    return tuple(text.split())


def _pending(row: Sequence[Any]) -> PendingRequest:
    return PendingRequest(
        id=row[0],
        client_id=row[1],
        redirect_uri=row[2],
        redirect_uri_explicit=bool(row[3]),
        client_state=row[4],
        code_challenge=row[5],
        resource=row[6],
        scopes=_scopes(row[7]),
        status=row[8],
        expires_at=row[9],
        subject=row[10],
    )


def _code(row: Sequence[Any]) -> CodeRecord:
    return CodeRecord(
        hash=row[0],
        family=row[1],
        client_id=row[2],
        redirect_uri=row[3],
        redirect_uri_explicit=bool(row[4]),
        code_challenge=row[5],
        resource=row[6],
        scopes=_scopes(row[7]),
        subject=row[8],
        expires_at=row[9],
        used_at=row[10],
    )


def _datetime(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class AuthStore:
    def __init__(self, conn: sqlite3.Connection, *, run: Runner = run_directly) -> None:
        self._conn = conn
        self._run = run

    @classmethod
    def open(cls, path: Path, *, run: Runner = run_directly) -> AuthStore:
        def connect() -> sqlite3.Connection:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit; one connection, used only from the event-loop thread.
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")
                conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
                migrate(conn)
            except BaseException:
                conn.close()
                raise
            return conn

        return cls(run(AUTH, connect), run=run)

    @property
    def conn(self) -> sqlite3.Connection:
        """The connection, for Quota: the usage table lives in this database."""
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # --- plumbing -----------------------------------------------------------------------------

    def atomic(self, work: Callable[[], T]) -> T:
        """Run work as one write transaction; inside another one it simply joins it."""
        if self._conn.in_transaction:
            return work()

        def transaction() -> T:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                result = work()
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            return result

        return self._run(AUTH, transaction)

    def _guarded(self, operation: Callable[[], T]) -> T:
        return operation() if self._conn.in_transaction else self._run(AUTH, operation)

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._guarded(lambda: self._conn.execute(sql, params).fetchone())

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        return self._guarded(lambda: self._conn.execute(sql, params).fetchall())

    def _write(self, sql: str, params: Sequence[Any] = ()) -> int:
        return self._guarded(lambda: self._conn.execute(sql, params).rowcount)

    # --- clients ------------------------------------------------------------------------------

    def add_client(self, record: ClientRecord) -> None:
        self._write(
            "INSERT INTO clients (client_id, client_secret, metadata, created_at, last_issued_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.client_id,
                record.client_secret,
                json.dumps(record.metadata, sort_keys=True),
                record.created_at,
                record.last_issued_at,
            ),
        )

    def client(self, client_id: str) -> ClientRecord | None:
        row = self._one(
            "SELECT client_id, client_secret, metadata, created_at, last_issued_at FROM clients "
            "WHERE client_id = ?",
            (client_id,),
        )
        if row is None:
            return None
        return ClientRecord(row[0], row[1], json.loads(row[2]), row[3], row[4])

    def touch_client(self, client_id: str, now: int) -> None:
        self._write("UPDATE clients SET last_issued_at = ? WHERE client_id = ?", (now, client_id))

    # --- pending sign-ins ---------------------------------------------------------------------

    def add_pending(self, request: PendingRequest) -> None:
        self._write(
            f"INSERT INTO pending ({_PENDING}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.client_id,
                request.redirect_uri,
                int(request.redirect_uri_explicit),
                request.client_state,
                request.code_challenge,
                request.resource,
                " ".join(request.scopes),
                request.status,
                request.expires_at,
                request.subject,
            ),
        )

    def pending(self, request_id: str, now: int) -> PendingRequest | None:
        """The request, if it is still waiting for consent."""
        row = self._one(
            f"SELECT {_PENDING} FROM pending WHERE id = ? AND status = ? AND expires_at > ?",
            (request_id, AWAITING_CONSENT, now),
        )
        return _pending(row) if row else None

    def _advance(self, sql: str, params: Sequence[Any]) -> PendingRequest | None:
        rows = self._all(f"{sql} RETURNING {_PENDING}", params)
        return _pending(rows[0]) if rows else None

    def consent(self, request_id: str, gh_state_hash: str, now: int) -> PendingRequest | None:
        """awaiting_consent -> consented, once; None when stale, used or unknown."""
        return self._advance(
            "UPDATE pending SET status = ?, gh_state_hash = ? "
            "WHERE id = ? AND status = ? AND expires_at > ?",
            (CONSENTED, gh_state_hash, request_id, AWAITING_CONSENT, now),
        )

    def deny(self, request_id: str, now: int) -> PendingRequest | None:
        return self._advance(
            "UPDATE pending SET status = ? WHERE id = ? AND status = ? AND expires_at > ?",
            (DENIED, request_id, AWAITING_CONSENT, now),
        )

    def return_from_github(self, gh_state_hash: str, now: int) -> PendingRequest | None:
        """consented -> github_returned for the request with this GitHub state, once."""
        return self._advance(
            "UPDATE pending SET status = ?, gh_state_hash = NULL "
            "WHERE gh_state_hash = ? AND status = ? AND expires_at > ?",
            (GITHUB_RETURNED, gh_state_hash, CONSENTED, now),
        )

    def record_subject(self, request_id: str, subject: str) -> None:
        """Note who signed in for this request, once GitHub has said so."""
        self._write("UPDATE pending SET subject = ? WHERE id = ?", (subject, request_id))

    def live_pending_count(self, now: int) -> int:
        return self._one("SELECT COUNT(*) FROM pending WHERE expires_at > ?", (now,))[0]

    # --- authorization codes ------------------------------------------------------------------

    def add_code(self, code: CodeRecord) -> None:
        self._write(
            f"INSERT INTO authorization_codes ({_CODE}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code.hash,
                code.family,
                code.client_id,
                code.redirect_uri,
                int(code.redirect_uri_explicit),
                code.code_challenge,
                code.resource,
                " ".join(code.scopes),
                code.subject,
                code.expires_at,
                code.used_at,
            ),
        )

    def code(self, code_hash: str) -> CodeRecord | None:
        row = self._one(f"SELECT {_CODE} FROM authorization_codes WHERE hash = ?", (code_hash,))
        return _code(row) if row else None

    def use_code(self, code_hash: str, now: int) -> bool:
        """Mark the code used; False when it already was (or does not exist)."""
        return (
            self._write(
                "UPDATE authorization_codes SET used_at = ? WHERE hash = ? AND used_at IS NULL",
                (now, code_hash),
            )
            == 1
        )

    # --- token families and tokens ------------------------------------------------------------

    def add_family(
        self, family: str, subject: str, client_id: str, now: int, expires_at: int
    ) -> None:
        self._write(
            "INSERT INTO families (id, subject, client_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (family, subject, client_id, now, expires_at),
        )

    def active_families(self, subject: str, now: int) -> list[str]:
        """The subject's live families, oldest first."""
        rows = self._all(
            "SELECT id FROM families WHERE subject = ? AND revoked = 0 AND expires_at > ? "
            "ORDER BY created_at, rowid",
            (subject, now),
        )
        return [row[0] for row in rows]

    def revoke_family(self, family: str) -> None:
        self._write("UPDATE families SET revoked = 1 WHERE id = ?", (family,))

    def revoke_subject(self, subject: str) -> int:
        """Revoke every family of the subject; returns how many were live."""
        return self._write(
            "UPDATE families SET revoked = 1 WHERE subject = ? AND revoked = 0", (subject,)
        )

    def add_token(
        self,
        token_hash: str,
        kind: str,
        family: str,
        subject: str,
        client_id: str,
        scopes: Sequence[str],
        resource: str,
        expires_at: int,
    ) -> None:
        self._write(
            "INSERT INTO tokens (hash, kind, family, subject, client_id, scopes, resource, "
            "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token_hash, kind, family, subject, client_id, " ".join(scopes), resource, expires_at),
        )

    def token(self, token_hash: str, kind: str) -> TokenRecord | None:
        """The token of this kind with this hash, whatever its state; None if there is none."""
        row = self._one(
            "SELECT t.hash, t.kind, t.family, t.subject, t.client_id, t.scopes, t.resource, "
            "t.expires_at, t.rotated_at, f.revoked, f.expires_at, u.banned_at IS NOT NULL "
            "FROM tokens t JOIN families f ON f.id = t.family "
            "LEFT JOIN users u ON u.subject = t.subject "
            "WHERE t.hash = ? AND t.kind = ?",
            (token_hash, kind),
        )
        if row is None:
            return None
        return TokenRecord(
            hash=row[0],
            kind=row[1],
            family=row[2],
            subject=row[3],
            client_id=row[4],
            scopes=_scopes(row[5]),
            resource=row[6],
            expires_at=row[7],
            rotated_at=row[8],
            family_revoked=bool(row[9]),
            family_expires_at=row[10],
            banned=bool(row[11]),
        )

    def rotate(self, token_hash: str, now: int) -> bool:
        """Mark a live refresh token rotated; False when it already was, or is revoked."""
        return (
            self._write(
                "UPDATE tokens SET rotated_at = ? WHERE hash = ? AND kind = 'refresh' "
                "AND rotated_at IS NULL "
                "AND NOT EXISTS "
                "(SELECT 1 FROM families f WHERE f.id = tokens.family AND f.revoked = 1)",
                (now, token_hash),
            )
            == 1
        )

    # --- users and consents -------------------------------------------------------------------

    def upsert_user(
        self, subject: str, github_login: str, github_created_at: datetime | None, now: int
    ) -> None:
        created = github_created_at.isoformat() if github_created_at else None
        self._write(
            "INSERT INTO users (subject, github_login, github_created_at, first_seen) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (subject) DO UPDATE SET "
            "github_login = excluded.github_login, "
            "github_created_at = COALESCE(excluded.github_created_at, github_created_at)",
            (subject, github_login, created, now),
        )

    def user(self, subject: str) -> UserRecord | None:
        row = self._one(
            "SELECT subject, github_login, github_created_at, first_seen, banned_at, "
            "banned_reason FROM users WHERE subject = ?",
            (subject,),
        )
        if row is None:
            return None
        return UserRecord(row[0], row[1], _datetime(row[2]), row[3], row[4], row[5])

    def github_created_at(self, subject: str) -> datetime | None:
        """For Quota: when the subject's GitHub account was created (None when unknown)."""
        user = self.user(subject)
        return user.github_created_at if user else None

    def is_banned(self, subject: str) -> bool:
        user = self.user(subject)
        return user is not None and user.banned_at is not None

    def ban(self, subject: str, reason: str, now: int) -> None:
        """Ban the subject (known or not yet seen) and revoke all of its tokens."""

        def work() -> None:
            self._conn.execute(
                "INSERT INTO users (subject, github_login, first_seen, banned_at, banned_reason) "
                "VALUES (?, '', ?, ?, ?) ON CONFLICT (subject) DO UPDATE SET "
                "banned_at = excluded.banned_at, banned_reason = excluded.banned_reason",
                (subject, now, now, reason),
            )
            self.revoke_subject(subject)

        self.atomic(work)

    def unban(self, subject: str) -> bool:
        return (
            self._write(
                "UPDATE users SET banned_at = NULL, banned_reason = NULL "
                "WHERE subject = ? AND banned_at IS NOT NULL",
                (subject,),
            )
            == 1
        )

    def add_consent(self, subject: str, client_id: str, redirect_uri: str, now: int) -> None:
        self._write(
            "INSERT INTO consents (subject, client_id, redirect_uri, granted_at) "
            "VALUES (?, ?, ?, ?)",
            (subject, client_id, redirect_uri, now),
        )

    def usage(self, day: str) -> list[tuple[str, str | None, int]]:
        """(subject, GitHub login, requests) for one UTC day, busiest first; "*" is everyone."""
        rows = self._all(
            "SELECT u.subject, users.github_login, u.requests FROM usage u "
            "LEFT JOIN users ON users.subject = u.subject WHERE u.day = ? "
            "ORDER BY u.requests DESC, u.subject",
            (day,),
        )
        return [(row[0], row[1], row[2]) for row in rows]

    # --- housekeeping -------------------------------------------------------------------------

    def purge(self, now: int) -> dict[str, int]:
        """Delete what is no longer needed (hosted design 4.9); returns the rows removed per
        table. Rotated refresh tokens stay until their family expires: they detect replays."""
        retention_cutoff = now - int(RETENTION.total_seconds())
        oldest_day = datetime.fromtimestamp(retention_cutoff, UTC).date().isoformat()
        statements = {
            "pending": ("DELETE FROM pending WHERE expires_at <= ?", (now,)),
            "authorization_codes": (
                "DELETE FROM authorization_codes WHERE expires_at <= ?",
                (now,),
            ),
            "tokens": (
                "DELETE FROM tokens WHERE (expires_at <= ? AND rotated_at IS NULL) "
                "OR family IN (SELECT id FROM families WHERE expires_at <= ?)",
                (now, now),
            ),
            "families": ("DELETE FROM families WHERE expires_at <= ?", (now,)),
            "clients": (
                "DELETE FROM clients WHERE (last_issued_at IS NULL AND created_at <= ?) "
                "OR last_issued_at <= ?",
                (
                    now - int(UNUSED_CLIENT_AGE.total_seconds()),
                    now - int(IDLE_CLIENT_AGE.total_seconds()),
                ),
            ),
            "usage": ("DELETE FROM usage WHERE day < ?", (oldest_day,)),
            "consents": ("DELETE FROM consents WHERE granted_at <= ?", (retention_cutoff,)),
        }

        def work() -> dict[str, int]:
            return {
                table: self._conn.execute(sql, params).rowcount
                for table, (sql, params) in statements.items()
            }

        return self.atomic(work)
