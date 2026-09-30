"""scripts/rebuild_vehicle_index.py against a tiny synthetic 3-page index (never the network)."""

from datetime import date
from pathlib import Path

import httpx
import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.vehicle_index import VehicleIndex
from scripts import rebuild_vehicle_index as script
from scripts.rebuild_vehicle_index import RebuildError, RebuildSummary, rebuild
from tests.harness import FakeClock, FixtureTransport, url
from tests.vehicle_data import SyntheticIndex, numbered, vehicle
from tests.vehicle_env import settings_for

pytestmark = pytest.mark.anyio

BUILT_AT = date(2026, 10, 1)
UNLINKED = [
    vehicle("9884", "USA", None, model_name="A15", series_label="A15", body=None),
    vehicle("RC31", "EUR", None, brand="mini", model_name="Cooper", series_label="MINI R50"),
    vehicle("0B74", "BRA", None, brand="motorrad", model_name="F 800 R", body=None),
]
MINI = vehicle(
    "MF31",
    "USA",
    "2006-11",
    "2010-02",
    brand="mini",
    series_code="R56",
    model_name="Cooper S",
    series_label="MINI R56",
    body="Hatchback",
)
GHOST = vehicle(
    "56SA",
    "USA",
    "2010-06",
    "2014-03",
    brand="rolls-royce",
    series_code="RR4",
    model_name="Ghost",
    series_label="Ghost RR4",
)
REMOTE = [*UNLINKED, *numbered(115), MINI, GHOST]  # 120 rows = pages 1-3


async def _rebuild(settings: Settings, transport: httpx.AsyncBaseTransport) -> RebuildSummary:
    clock = FakeClock()
    return await rebuild(
        settings, built_at=BUILT_AT, transport=transport, clock=clock, sleep=clock.sleep
    )


def _pages(transport: SyntheticIndex) -> list[str]:
    return [request.url.params["page"] for request in transport.requests]


async def test_rebuild_writes_sorted_csvs_and_meta(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    transport = SyntheticIndex(REMOTE)
    summary = await _rebuild(settings, transport)
    assert summary == RebuildSummary(
        total=120,
        pages=3,
        requests=4,  # pages 1-3, then page 3 again to check nothing shifted
        attempts=1,
        per_brand={"mini": 2, "rolls-royce": 1, "motorrad": 1, "bmw": 116},
        unlinked=3,
        built_at=BUILT_AT,
    )
    assert _pages(transport) == ["1", "2", "3", "3"]
    brands = settings.brands_dir
    assert (brands / "mini" / "vehicles.csv").read_bytes().decode("utf-8") == (
        "key,vehicle_id,series_label,series_code,model_name,type_code,body,market,prod_start,"
        "prod_end\n"
        "RC31-EUR--,,MINI R50,,Cooper,RC31,Sedan,EUR,,\n"
        "MF31-USA-11-2006,MF31-USA-11-2006-R56-Mini-Cooper_S,MINI R56,R56,Cooper S,MF31,"
        "Hatchback,USA,2006-11,2010-02\n"
    )
    bmw = (brands / "bmw" / "vehicles.csv").read_text(encoding="utf-8").splitlines()
    assert len(bmw) == 117
    assert bmw[1] == "9884-USA--,,A15,,A15,9884,,USA,,"
    starts = [line.split(",")[8] for line in bmw[1:]]
    assert starts == sorted(starts)  # production start ascending, empty first
    assert (brands / "vehicles.meta.toml").read_text(encoding="utf-8") == (
        "built_at = 2026-10-01\ntotal = 120\n"
        'source = "https://www.realoem.com/bmw/enUS/vehicles?sort=year"\n'
    )
    index = VehicleIndex.open(settings, BrandRegistry.load(brands))
    try:
        assert index.count() == 120
        meta = index.meta()
        assert (meta.built_at, meta.baseline_total, meta.local_rows) == (BUILT_AT, 120, 0)
    finally:
        index.close()


async def test_rebuild_restarts_when_the_total_changes(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    transport = SyntheticIndex(REMOTE)
    added = vehicle("NEW1", start="2025-03", end="2025-04")

    def add_a_vehicle(requests_so_far: int) -> None:
        if requests_so_far == 2:  # page 2 of the first attempt already shows 121 vehicles
            transport.rows.append(added)

    transport.on_request = add_a_vehicle
    summary = await _rebuild(settings, transport)
    assert _pages(transport) == ["1", "2", "1", "2", "3", "3"]
    assert (summary.total, summary.attempts, summary.requests) == (121, 2, 6)
    assert added.key in (settings.brands_dir / "bmw" / "vehicles.csv").read_text(encoding="utf-8")


async def test_rebuild_restarts_when_the_last_page_changes(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    transport = SyntheticIndex(REMOTE)
    replacement = vehicle("NEW1", start="2025-03", end="2025-04")

    def replace_the_last_vehicle(requests_so_far: int) -> None:
        if requests_so_far == 4:  # the re-check of page 3; the total stays 120
            transport.rows[-1] = replacement

    transport.on_request = replace_the_last_vehicle
    summary = await _rebuild(settings, transport)
    assert _pages(transport) == ["1", "2", "3", "3", "1", "2", "3", "3"]
    assert (summary.total, summary.attempts, summary.requests) == (120, 2, 8)
    csv_text = (settings.brands_dir / "bmw" / "vehicles.csv").read_text(encoding="utf-8")
    assert replacement.key in csv_text


async def test_rebuild_gives_up_when_the_total_keeps_changing(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    transport = SyntheticIndex(REMOTE)

    def add_a_vehicle(requests_so_far: int) -> None:
        if requests_so_far % 2 == 0:
            transport.rows.append(vehicle(f"N{requests_so_far:03d}", start="2025-03"))

    transport.on_request = add_a_vehicle
    with pytest.raises(RebuildError, match="kept changing"):
        await _rebuild(settings, transport)
    assert len(transport.requests) == 6  # 3 attempts x 2 pages
    assert list(settings.brands_dir.glob("*/vehicles.csv")) == []


async def test_rebuild_checks_that_each_page_is_the_one_requested(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    # RealOEM answering page 1 with page 2's content must not produce a baseline.
    transport = FixtureTransport(
        {url("vehicles", page="1", sort="year"): "vehicles/sort_year_p2.html"}
    )
    with pytest.raises(RebuildError, match="asked for page 1 but RealOEM returned page 2"):
        await _rebuild(settings, transport)
    assert not (settings.brands_dir / "vehicles.meta.toml").exists()


async def test_rebuild_lists_every_duplicate_key(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    transport = SyntheticIndex([*REMOTE[:-2], REMOTE[5], REMOTE[40]])
    expected = sorted([REMOTE[5].key, REMOTE[40].key])
    with pytest.raises(RebuildError, match=f"2 duplicate row keys: {', '.join(expected)}$"):
        await _rebuild(settings, transport)
    assert not (settings.brands_dir / "vehicles.meta.toml").exists()


def test_main_prints_the_summary(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    summary = RebuildSummary(
        total=3,
        pages=1,
        requests=1,
        attempts=1,
        per_brand={"bmw": 2, "mini": 1},
        unlinked=1,
        built_at=BUILT_AT,
    )

    async def fake_rebuild(settings: Settings, *, built_at: date) -> RebuildSummary:
        return summary

    monkeypatch.setenv("REALOEM_BRANDS_DIR", str(tmp_path))
    monkeypatch.delenv("REALOEM_MIN_INTERVAL", raising=False)
    monkeypatch.setattr(script, "rebuild", fake_rebuild)
    assert script.main([]) == 0
    err = capsys.readouterr().err
    assert f"Fetching RealOEM's vehicles index into {tmp_path} (2 s between requests)" in err
    assert "vehicles: 3 (1 without a vehicle id)\n" in err
    assert "per brand: bmw 2, mini 1\n" in err


def test_main_reports_failures_without_writing(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    async def failing_rebuild(settings: Settings, *, built_at: date) -> RebuildSummary:
        raise RebuildError("read 49 rows but RealOEM reports 50 vehicles")

    monkeypatch.setattr(script, "rebuild", failing_rebuild)
    assert script.main([]) == 1
    assert "rebuild failed, nothing written: read 49 rows" in capsys.readouterr().err
