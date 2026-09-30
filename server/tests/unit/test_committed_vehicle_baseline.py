"""The committed baseline (brands/*/vehicles.csv + vehicles.meta.toml) is well formed.

Skipped until the maintainer has run scripts/rebuild_vehicle_index.py and committed its output.
"""

import csv
import tomllib
from pathlib import Path

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.vehicle_index import CSV_COLUMNS, SOURCE_URL, VehicleIndex
from tests.harness import BRANDS_DIR

META = BRANDS_DIR / "vehicles.meta.toml"

pytestmark = pytest.mark.skipif(not META.exists(), reason="no committed vehicle baseline yet")


def test_committed_baseline_is_sorted_and_loads_completely(tmp_path: Path) -> None:
    meta = tomllib.loads(META.read_text(encoding="utf-8"))
    assert meta["source"] == SOURCE_URL
    registry = BrandRegistry.load(BRANDS_DIR)
    rows = 0
    for brand in registry:
        path = BRANDS_DIR / brand.id / "vehicles.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            records = list(csv.reader(handle))
        assert tuple(records[0]) == CSV_COLUMNS
        order = [(record[8], record[0]) for record in records[1:]]
        assert order == sorted(order), f"{path} must be sorted by prod_start, then key"
        rows += len(records) - 1
    assert rows == meta["total"]
    settings = Settings(cache_dir=tmp_path / "cache", data_dir=tmp_path / "data")
    index = VehicleIndex.open(settings, registry)
    try:
        assert index.count() == meta["total"]
        assert index.meta().built_at == meta["built_at"]
    finally:
        index.close()
