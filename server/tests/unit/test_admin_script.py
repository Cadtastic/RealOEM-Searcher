"""scripts/admin.py against a temporary auth database."""

import io
from pathlib import Path

import pytest

from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings
from scripts import admin

NOW = 1_800_000_000.0  # 2027-01-15


def _run(tmp_path: Path, *argv: str) -> str:
    """The command's output, after the line that names the database."""
    out = io.StringIO()
    settings = Settings(data_dir=tmp_path)
    assert admin.main(list(argv), settings=settings, now=lambda: NOW, out=out) == 0
    first, _, rest = out.getvalue().partition("\n")
    assert first == f"Auth database: {settings.auth_path}"
    return rest


def _store(tmp_path: Path) -> AuthStore:
    return AuthStore.open(Settings(data_dir=tmp_path).auth_path)


def test_usage_lists_the_day_busiest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_user("github:1", "octocat", None, 0)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-15', 7)")
    store.conn.execute("INSERT INTO usage VALUES ('github:3', '2027-01-15', 5)")
    store.conn.execute("INSERT INTO usage VALUES ('*', '2027-01-15', 12)")
    store.conn.execute("INSERT INTO usage VALUES ('github:2', '2027-01-14', 3)")
    store.close()
    today = _run(tmp_path, "usage")
    assert today.splitlines() == [
        "Requests on 2027-01-15 (UTC):",
        "      12  everyone",
        "       7  github:1 (octocat)",
        "       5  github:3 (?)",
    ]
    assert "github:2 (?)" in _run(tmp_path, "usage", "--day", "2027-01-14")
    assert "none" in _run(tmp_path, "usage", "--day", "2020-01-01")


def test_ban_unban_and_revoke(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_family("fam", "github:5", "client", int(NOW), int(NOW) + 3600)
    store.close()
    assert "Banned github:5" in _run(tmp_path, "ban", "5", "--reason", "abuse")
    store = _store(tmp_path)
    assert store.is_banned("github:5")
    assert store.user("github:5").banned_reason == "abuse"
    assert store.active_families("github:5", int(NOW)) == []
    store.add_family("fam2", "github:5", "client", int(NOW), int(NOW) + 3600)
    store.close()
    assert "Unbanned github:5." in _run(tmp_path, "unban", "5")
    assert "was not banned" in _run(tmp_path, "unban", "5")
    assert "Revoked 1 sign-in(s) of github:5." in _run(tmp_path, "revoke", "5")


def test_prune_runs_the_purge(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2026-01-01', 1)")
    store.close()
    assert _run(tmp_path, "prune") == "Pruned: 1 usage.\n"
    assert _run(tmp_path, "prune") == "Pruned: nothing.\n"


def test_a_missing_database_is_never_created(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "missing")
    assert admin.main(["ban", "5", "--reason", "x"], settings=settings) == 2
    assert not (tmp_path / "missing").exists()


def test_it_refuses_to_run_as_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(tmp_path).close()
    monkeypatch.setattr(admin.os, "geteuid", lambda: 0, raising=False)
    assert admin.main(["usage"], settings=Settings(data_dir=tmp_path)) == 2


def test_a_github_id_must_be_a_number(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        admin.main(["ban", "octocat", "--reason", "x"], settings=Settings(data_dir=tmp_path))
