"""Shared pytest fixtures. Helpers to import live in tests/harness.py (ARD section 8)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, MakeServices, Route


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def make_services(tmp_path: Path) -> AsyncIterator[MakeServices]:
    """make_services(routes) -> (services, transport), offline and with a fake clock.

    Async fixture: use it only from tests marked @pytest.mark.anyio. Teardown closes every
    Services it created, then fails the test if any request had no route.
    """
    created: list[tuple[Services, FixtureTransport]] = []

    def factory(routes: Mapping[str, Route | str]) -> tuple[Services, FixtureTransport]:
        n = len(created)
        transport = FixtureTransport(routes)
        clock = FakeClock()
        settings = Settings(
            cache_dir=tmp_path / f"cache{n}", data_dir=tmp_path / f"data{n}", brands_dir=BRANDS_DIR
        )
        services = create_services(settings, transport=transport, clock=clock, sleep=clock.sleep)
        created.append((services, transport))
        return services, transport

    yield factory
    for services, _ in created:
        await services.aclose()
    for _, transport in created:
        assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.live tests unless REALOEM_LIVE=1."""
    if os.environ.get("REALOEM_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set REALOEM_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
