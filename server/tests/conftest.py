"""Shared pytest fixtures. Helpers to import live in tests/harness.py (ARD section 8)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.live tests unless REALOEM_LIVE=1."""
    if os.environ.get("REALOEM_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set REALOEM_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
