"""build_http_app and the realoem-mcp-http entry point (hosted design 4.2, 4.9)."""

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest
from starlette.applications import Starlette

from realoem_mcp import http_app
from realoem_mcp.auth.records import AWAITING_CONSENT, PendingRequest
from realoem_mcp.config import Settings
from realoem_mcp.http_app import build_http_app, purge_once
from tests.fake_github import FakeGitHub
from tests.harness import url
from tests.hosted_config import BASE, SECRET_KEY, hosted_settings
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
COMPARE_ROUTES = {
    url("partgrp", id=E90, mg="11"): "partgrp/e90_325i_mg11.html",
    url("partgrp", id=R56, mg="11"): "partgrp/r56_cooper_s_mg11.html",
    url("showparts", id=E90, diagId="11_3733"): "showparts/e90_325i_11_3733.html",
}
COMPARE = {
    "vehicle_a": E90,
    "vehicle_b": R56,
    "main_group": "11",
    "diag_ids": ["11_3733", "11_3910"],
}


def _expired_pending(request_id: str) -> PendingRequest:
    return PendingRequest(
        request_id, "c", "https://r", True, None, "c" * 43, "r", ("realoem",), AWAITING_CONSENT, 0
    )


def test_stdio_settings_and_missing_values_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode='http'"):
        build_http_app(Settings(cache_dir=tmp_path, data_dir=tmp_path))
    with pytest.raises(ValueError, match="REALOEM_GITHUB_CLIENT_ID is required"):
        build_http_app(hosted_settings(tmp_path, github_client_id=None))


async def test_shutdown_closes_the_databases(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        store = env.app.state.store
        assert store.live_pending_count(0) == 0
    with pytest.raises(sqlite3.ProgrammingError):  # closed
        store.conn.execute("SELECT 1")


async def test_the_purge_runs_on_its_interval(tmp_path: Path) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub(), purge_interval_s=0.01)
    async with app.router.lifespan_context(app):
        # The purge at startup takes the first row; only a repeat on the interval takes the second.
        for request_id in ("first", "second"):
            app.state.store.add_pending(_expired_pending(request_id))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if app.state.store.conn.execute("SELECT COUNT(*) FROM pending").fetchone() == (0,):
                    break
            else:
                pytest.fail(f"the purge never removed {request_id}")


async def test_the_purge_also_runs_at_startup(tmp_path: Path) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub())
    app.state.store.add_pending(_expired_pending("stale"))  # before the server starts
    async with app.router.lifespan_context(app):
        for _ in range(100):
            await asyncio.sleep(0.01)
            if app.state.store.conn.execute("SELECT COUNT(*) FROM pending").fetchone() == (0,):
                break
        else:
            pytest.fail("no purge at startup")


def test_purge_once_reports_what_it_removed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub())
    store, cache = app.state.store, app.state.services.cache
    try:
        store.add_pending(_expired_pending("a"))
        store.add_pending(_expired_pending("b"))
        with caplog.at_level(logging.INFO, logger="realoem_mcp.http_app"):
            purge_once(store, cache, 1_800_000_000)
        assert "purge: 2 pending; 0 expired pages" in caplog.text
    finally:
        store.close()
        cache.close()


async def test_the_call_deadline_applies_over_http(tmp_path: Path) -> None:
    """CallClock runs on the gate's clock: three requests take 4 s of the fake clock."""
    async with hosted_app(tmp_path, COMPARE_ROUTES, call_deadline_s=3.0) as env:
        tokens = await env.sign_in(1)
        async with env.mcp(tokens.access_token) as client:
            result = await client.call_tool("compare_vehicles", COMPARE)
        data = result.structured_content
        assert (data["complete"], data["unfetched_b"]) == (False, ["11_3910"])


def test_main_reports_a_bad_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(http_app, "install_vin_filter", lambda: None)  # keep pytest's handlers
    for name in ("REALOEM_PUBLIC_URL", "REALOEM_GITHUB_CLIENT_ID", "REALOEM_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REALOEM_DATA_DIR", str(tmp_path))
    httpx_level = logging.getLogger("httpx").level
    try:
        with pytest.raises(SystemExit) as stopped:
            http_app.main()
    finally:
        logging.getLogger("httpx").setLevel(httpx_level)  # main() changes it
    assert stopped.value.code == 2
    assert "The hosted server cannot start" in capsys.readouterr().err


def test_main_serves_on_port_8080(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[bool] = []
    served: list[tuple[object, dict]] = []
    monkeypatch.setattr(http_app, "install_vin_filter", lambda: installed.append(True))
    monkeypatch.setattr(http_app.uvicorn, "run", lambda app, **kw: served.append((app, kw)))
    environment = {
        "REALOEM_PUBLIC_URL": BASE,
        "REALOEM_GITHUB_CLIENT_ID": "id",
        "REALOEM_GITHUB_CLIENT_SECRET": "secret",
        "REALOEM_SECRET_KEY": SECRET_KEY,
        "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
        "REALOEM_DATA_DIR": str(tmp_path / "data"),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    httpx_level = logging.getLogger("httpx").level
    try:
        http_app.main()
    finally:
        logging.getLogger("httpx").setLevel(httpx_level)
    ((app, options),) = served
    assert isinstance(app, Starlette) and installed == [True]
    assert options == {"host": "0.0.0.0", "port": 8080, "access_log": False, "log_config": None}
    app.state.store.close()
    app.state.services.cache.close()
