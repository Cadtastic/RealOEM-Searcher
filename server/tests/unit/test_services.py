import sqlite3
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.services import Services, create_services
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio


class Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class AsyncClosable(Closable):
    async def close(self) -> None:  # type: ignore[override]
        self.closed = True


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR)


async def test_create_services_wires_settings_cache_client_and_brands(tmp_path: Path) -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport({target: Route()})
    clock = FakeClock()
    services = create_services(
        _settings(tmp_path), transport=transport, clock=clock, sleep=clock.sleep
    )
    try:
        assert isinstance(services, Services)
        assert services.cache.path.parent == tmp_path / "cache"
        assert len(services.brands) == 4
        assert services.extras == {}
        page = await services.client.fetch(PageType.PARTXREF, "partxref", {"q": "11427953129"})
        assert page.url == target
        assert services.cache.stats().entries == 1
    finally:
        await services.aclose()


async def test_aclose_closes_extras_with_a_close_method(tmp_path: Path) -> None:
    services = create_services(_settings(tmp_path))
    sync_extra, async_extra = Closable(), AsyncClosable()
    services.extras.update({"index": sync_extra, "other": async_extra, "plain": {"a": 1}})
    await services.aclose()
    assert sync_extra.closed
    assert async_extra.closed


class Broken:
    def close(self) -> None:
        raise RuntimeError("boom")


async def test_aclose_closes_everything_even_if_one_close_fails(tmp_path: Path) -> None:
    services = create_services(_settings(tmp_path))
    after = Closable()
    services.extras.update({"broken": Broken(), "after": after})
    with pytest.raises(RuntimeError, match="boom"):
        await services.aclose()
    assert after.closed
    with pytest.raises(sqlite3.ProgrammingError):
        services.cache.stats()  # the cache was closed too


async def test_make_services_fixture_returns_services_and_transport(make_services) -> None:
    params = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
    target = url("partgrp", **params)
    services, transport = make_services({target: "common/partgrp_e90_325i.html"})
    page = await services.client.fetch(PageType.PARTGRP, "partgrp", params)
    assert page.status == 200
    assert [str(r.url) for r in transport.requests] == [target]
    assert services.settings.min_interval_s == 2.0
