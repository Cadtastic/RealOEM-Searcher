"""Offline F6 test environment: private brands folder, committed-baseline files, Services."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import httpx

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.services import Services, create_services
from realoem_mcp.vehicle_index import write_baseline
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport

BUILT_AT = date(2026, 9, 30)


def copy_brands(dest: Path) -> Path:
    """A brands/ folder with the repository's brand.toml files and no vehicle baseline."""
    for toml in sorted(BRANDS_DIR.glob("*/brand.toml")):
        (dest / toml.parent.name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(toml, dest / toml.parent.name / "brand.toml")
    return dest


def settings_for(tmp_path: Path) -> Settings:
    """Settings whose cache, data and brands folders all live under tmp_path."""
    return Settings(
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        brands_dir=copy_brands(tmp_path / "brands"),
    )


def install_baseline(settings: Settings, rows: Sequence[IndexedVehicle]) -> None:
    """Write rows as the committed baseline (CSV per brand + meta) into settings.brands_dir."""
    brand_ids = [brand.id for brand in BrandRegistry.load(settings.brands_dir)]
    write_baseline(settings.brands_dir, brand_ids, rows, total=len(rows), built_at=BUILT_AT)


@asynccontextmanager
async def vehicle_services(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    baseline: Sequence[IndexedVehicle] | None = None,
) -> AsyncIterator[Services]:
    """Offline Services on a private brands folder (optionally with a baseline) and fake clock."""
    settings = settings_for(tmp_path)
    if baseline is not None:
        install_baseline(settings, baseline)
    clock = FakeClock()
    services = create_services(settings, transport=transport, clock=clock, sleep=clock.sleep)
    try:
        yield services
    finally:
        await services.aclose()
    if isinstance(transport, FixtureTransport):
        assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"
