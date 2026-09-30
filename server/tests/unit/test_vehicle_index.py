"""VehicleIndex on small synthetic baselines in tmp folders (ARD section 5.11, AD16)."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.vehicle_index import DB_FILENAME, SCHEMA_VERSION, VehicleIndex, write_baseline
from tests.vehicle_data import vehicle
from tests.vehicle_env import BUILT_AT, install_baseline, settings_for

E90 = vehicle("VB13", "USA", "2005-10", "2008-02", series_label="3 Series E90")
E90_EUR = vehicle("VB11", "EUR", "2005-03", "2008-02", series_label="3 Series E90")
E92 = vehicle(
    "WB33",
    "USA",
    "2006-09",
    "2010-02",
    series_code="E92",
    model_name="335i",
    series_label="3 Series E92",
    body="Coupe",
)
G26 = vehicle(
    "62FR",
    "EUR",
    "2024-03",
    "2025-04",
    series_code="G26N",
    model_name="430dX",
    series_label="4 Series G26 Gran Coup\xe9 LCI",
    body="Gran Coup\xe9",
)
R56 = vehicle(
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
GS = vehicle(
    "0J91",
    "USA",
    "2018-09",
    "2025-03",
    brand="motorrad",
    series_code="K50",
    model_name="R 1250 GS",
    series_label="K50 (R 1200 GS, R 1250 GS)",
    body=None,
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
UNLINKED = vehicle("9884", "USA", None, model_name="A15", series_label="A15", body=None)
ALL = [E90, E90_EUR, E92, G26, R56, GS, GHOST, UNLINKED]


def _baseline(rows: list[IndexedVehicle]) -> list[IndexedVehicle]:
    return [row.model_copy(update={"source": "baseline"}) for row in rows]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return settings_for(tmp_path)


def _open(settings: Settings) -> VehicleIndex:
    return VehicleIndex.open(settings, BrandRegistry.load(settings.brands_dir))


def test_open_without_baseline_is_an_empty_index(settings: Settings) -> None:
    index = _open(settings)
    try:
        assert (settings.data_dir / DB_FILENAME).is_file()
        assert (index.count(), index.keys(), index.max_prod_start()) == (0, set(), None)
        assert index.search(query="E90") == (0, [])
        meta = index.meta()
        assert (meta.built_at, meta.baseline_total, meta.local_rows, meta.last_update_at) == (
            None,
            0,
            0,
            None,
        )
    finally:
        index.close()


def test_write_baseline_writes_sorted_csvs_and_meta(settings: Settings) -> None:
    brand_ids = ["bmw", "mini", "motorrad", "rolls-royce"]
    counts = write_baseline(
        settings.brands_dir, brand_ids, ALL, total=len(ALL), built_at=date(2026, 9, 30)
    )
    assert counts == {"bmw": 5, "mini": 1, "motorrad": 1, "rolls-royce": 1}
    csv_bytes = (settings.brands_dir / "bmw" / "vehicles.csv").read_bytes()
    assert b"\r\n" not in csv_bytes
    assert csv_bytes.decode("utf-8").splitlines() == [
        "key,vehicle_id,series_label,series_code,model_name,type_code,body,market,prod_start,"
        "prod_end",
        "9884-USA--,,A15,,A15,9884,,USA,,",
        "VB11-EUR-03-2005,VB11-EUR-03-2005-E90-BMW-325i,3 Series E90,E90,325i,VB11,Sedan,EUR,"
        "2005-03,2008-02",
        "VB13-USA-10-2005,VB13-USA-10-2005-E90-BMW-325i,3 Series E90,E90,325i,VB13,Sedan,USA,"
        "2005-10,2008-02",
        "WB33-USA-09-2006,WB33-USA-09-2006-E92-BMW-335i,3 Series E92,E92,335i,WB33,Coupe,USA,"
        "2006-09,2010-02",
        "62FR-EUR-03-2024,62FR-EUR-03-2024-G26N-BMW-430dX,4 Series G26 Gran Coup\xe9 LCI,G26N,"
        "430dX,62FR,Gran Coup\xe9,EUR,2024-03,2025-04",
    ]
    assert (settings.brands_dir / "vehicles.meta.toml").read_text(encoding="utf-8") == (
        "built_at = 2026-09-30\ntotal = 8\n"
        'source = "https://www.realoem.com/bmw/enUS/vehicles?sort=year"\n'
    )


def test_open_loads_every_brand_csv(settings: Settings) -> None:
    install_baseline(settings, ALL)
    index = _open(settings)
    try:
        assert index.count() == 8
        assert index.keys() == {row.key for row in ALL}
        assert index.max_prod_start() == "2024-03"
        total, found = index.search(include_unlinked=True, limit=100)
        assert total == 8
        assert sorted(found, key=lambda v: v.key) == sorted(_baseline(ALL), key=lambda v: v.key)
        meta = index.meta()
        assert (meta.built_at, meta.baseline_total, meta.local_rows) == (BUILT_AT, 8, 0)
    finally:
        index.close()


def test_query_tokens_must_all_match_case_insensitively(settings: Settings) -> None:
    install_baseline(settings, ALL)
    index = _open(settings)
    try:
        assert [v.key for v in index.search(query="e90 325I")[1]] == [
            "VB11-EUR-03-2005",
            "VB13-USA-10-2005",
        ]
        assert [v.key for v in index.search(query="3 series coupe")[1]] == []
        assert [v.key for v in index.search(query="COUP\xc9")[1]] == ["62FR-EUR-03-2024"]
        assert [v.key for v in index.search(query="vb13")[1]] == ["VB13-USA-10-2005"]
        assert [v.key for v in index.search(query="1250 gs")[1]] == ["0J91-USA-09-2018"]
        assert [v.key for v in index.search(query="a15")[1]] == []
        assert [v.key for v in index.search(query="a15", include_unlinked=True)[1]] == [
            "9884-USA--"
        ]
    finally:
        index.close()


def test_filters_year_limit_and_order(settings: Settings) -> None:
    install_baseline(settings, ALL)
    index = _open(settings)

    def keys(**filters: object) -> list[str]:
        return [v.key for v in index.search(**filters)[1]]

    try:
        assert keys(brand="MINI") == ["MF31-USA-11-2006"]
        assert keys(series="e92") == ["WB33-USA-09-2006"]
        assert keys(market="eur") == ["VB11-EUR-03-2005", "62FR-EUR-03-2024"]
        assert keys(type_code="0j91") == ["0J91-USA-09-2018"]
        assert keys(year=2005) == ["VB11-EUR-03-2005", "VB13-USA-10-2005"]
        assert keys(year=2008, brand="bmw") == [
            "VB11-EUR-03-2005",
            "VB13-USA-10-2005",
            "WB33-USA-09-2006",
        ]
        assert keys(year=2011) == ["56SA-USA-06-2010"]
        # Order: brand, series code, model name, market, production start.
        assert keys() == [
            "VB11-EUR-03-2005",
            "VB13-USA-10-2005",
            "WB33-USA-09-2006",
            "62FR-EUR-03-2024",
            "MF31-USA-11-2006",
            "0J91-USA-09-2018",
            "56SA-USA-06-2010",
        ]
        total, first_two = index.search(limit=2)
        assert (total, [v.key for v in first_two]) == (7, ["VB11-EUR-03-2005", "VB13-USA-10-2005"])
    finally:
        index.close()


def test_add_local_ignores_known_keys(settings: Settings) -> None:
    install_baseline(settings, [E90])
    index = _open(settings)
    try:
        assert index.add_local([E90, E92]) == 1
        assert index.add_local([]) == 0
        _, found = index.search(query="3 series")
        assert [(v.key, v.source) for v in found] == [
            ("VB13-USA-10-2005", "baseline"),
            ("WB33-USA-09-2006", "local"),
        ]
        assert found[1] == E92
        assert index.meta().local_rows == 1
    finally:
        index.close()


def test_record_check_stores_time_remote_total_and_resume_point(settings: Settings) -> None:
    install_baseline(settings, [E90])
    index = _open(settings)
    try:
        assert (index.last_remote_total(), index.resume_point()) == (None, None)
        assert index.meta().last_update_at is None
        index.record_check(remote_total=8218, resume=("2024-03", 160))
        assert (index.last_remote_total(), index.resume_point()) == (8218, ("2024-03", 160))
        assert index.meta().last_update_at is not None
        index.record_check(remote_total=8220, resume=None)
        assert (index.last_remote_total(), index.resume_point()) == (8220, None)
    finally:
        index.close()


def test_local_rows_survive_reopening_with_the_same_baseline(settings: Settings) -> None:
    install_baseline(settings, [E90])
    index = _open(settings)
    index.add_local([E92])
    index.close()
    index = _open(settings)
    try:
        assert index.keys() == {E90.key, E92.key}
        assert index.meta().local_rows == 1
    finally:
        index.close()


def test_changed_baseline_reloads_and_reconciles_local_rows(settings: Settings) -> None:
    install_baseline(settings, [E90, E90_EUR])
    index = _open(settings)
    index.add_local([E92, R56])
    index.close()
    install_baseline(settings, [E90, E92, GS])  # E90_EUR removed, E92 now in the baseline
    index = _open(settings)
    try:
        _, found = index.search(include_unlinked=True, limit=100)
        assert {(v.key, v.source) for v in found} == {
            (E90.key, "baseline"),
            (E92.key, "baseline"),
            (GS.key, "baseline"),
            (R56.key, "local"),
        }
        meta = index.meta()
        assert (meta.baseline_total, meta.local_rows) == (3, 1)
    finally:
        index.close()


def test_a_csv_with_the_wrong_header_is_rejected(settings: Settings) -> None:
    path = settings.brands_dir / "bmw" / "vehicles.csv"
    path.write_text("key,model\n", encoding="utf-8")
    with pytest.raises(RealOemError) as caught:
        _open(settings)
    assert caught.value.message.startswith(f"The vehicle baseline {path} is invalid")
    assert "header must be key,vehicle_id," in caught.value.message


def test_a_duplicate_key_across_brand_csvs_is_rejected(settings: Settings) -> None:
    install_baseline(settings, [E90, R56])
    bmw_csv = (settings.brands_dir / "bmw" / "vehicles.csv").read_text(encoding="utf-8")
    (settings.brands_dir / "mini" / "vehicles.csv").write_text(bmw_csv, encoding="utf-8")
    with pytest.raises(RealOemError, match="could not be opened: UNIQUE constraint failed"):
        _open(settings)


def test_a_csv_that_is_not_utf8_is_rejected(settings: Settings) -> None:
    install_baseline(settings, [E90])
    path = settings.brands_dir / "bmw" / "vehicles.csv"
    path.write_bytes(path.read_bytes() + b"X\xffX,,A15,,A15,X,,USA,,\n")
    with pytest.raises(RealOemError, match="codec can't decode") as caught:
        _open(settings)
    assert caught.value.message.startswith(f"The vehicle baseline {path} is invalid: ")


def test_a_csv_row_with_a_missing_field_is_rejected(settings: Settings) -> None:
    install_baseline(settings, [E90])
    path = settings.brands_dir / "bmw" / "vehicles.csv"
    path.write_text(path.read_text(encoding="utf-8") + "X-USA--,,A15,,A15,X,,USA\n", "utf-8")
    with pytest.raises(RealOemError) as caught:
        _open(settings)
    assert caught.value.message == (
        f"The vehicle baseline {path} is invalid: line 3 does not have 10 fields."
    )


def test_a_csv_row_with_an_empty_required_field_is_rejected(settings: Settings) -> None:
    install_baseline(settings, [E90])
    path = settings.brands_dir / "bmw" / "vehicles.csv"
    path.write_text(path.read_text(encoding="utf-8") + "X-USA--,,A15,,,X,,USA,,\n", "utf-8")
    with pytest.raises(RealOemError, match="line 3 has an empty model_name"):
        _open(settings)


def test_a_meta_file_with_a_string_date_is_rejected(settings: Settings) -> None:
    install_baseline(settings, [E90])
    path = settings.brands_dir / "vehicles.meta.toml"
    path.write_text('built_at = "2026-09-30"\ntotal = 1\n', encoding="utf-8")
    with pytest.raises(RealOemError) as caught:
        _open(settings)
    assert caught.value.message == (
        f"The vehicle baseline {path} is invalid: built_at must be a TOML date such as 2026-09-30."
    )


def _store_meta(settings: Settings) -> dict[str, str]:
    with closing(sqlite3.connect(settings.data_dir / DB_FILENAME)) as db:
        return dict(db.execute("SELECT key, value FROM meta").fetchall())


def test_schema_upgrade_keeps_compatible_local_rows(settings: Settings) -> None:
    install_baseline(settings, [E90])
    index = _open(settings)
    index.add_local([E92])
    index.close()
    with closing(sqlite3.connect(settings.data_dir / DB_FILENAME)) as db, db:
        db.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    index = _open(settings)
    try:
        assert index.keys() == {E90.key, E92.key}
        assert index.meta().local_rows == 1
    finally:
        index.close()
    meta = _store_meta(settings)
    assert meta["schema_version"] == SCHEMA_VERSION
    assert "warning" not in meta


def test_schema_upgrade_drops_incompatible_local_rows_with_a_warning(settings: Settings) -> None:
    install_baseline(settings, [E90])
    settings.data_dir.mkdir(parents=True)
    with closing(sqlite3.connect(settings.data_dir / DB_FILENAME)) as db, db:  # an older layout
        db.execute("CREATE TABLE vehicles (key TEXT PRIMARY KEY, source TEXT)")
        db.execute("INSERT INTO vehicles VALUES ('X-USA--', 'local')")
    index = _open(settings)
    try:
        assert index.keys() == {E90.key}
    finally:
        index.close()
    assert _store_meta(settings)["warning"].startswith("1 locally added vehicle(s) were dropped")
