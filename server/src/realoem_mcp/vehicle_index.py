"""Local vehicle index (AD16, F6): committed CSV baseline -> {data_dir}/vehicles.sqlite3."""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle, IndexMeta
from realoem_mcp.vehicle_ids import VehicleId

DB_FILENAME = "vehicles.sqlite3"
CSV_FILENAME = "vehicles.csv"
META_FILENAME = "vehicles.meta.toml"
SOURCE_URL = "https://www.realoem.com/bmw/enUS/vehicles?sort=year"
SCHEMA_VERSION = "1"
CSV_COLUMNS = (
    "key",
    "vehicle_id",
    "series_label",
    "series_code",
    "model_name",
    "type_code",
    "body",
    "market",
    "prod_start",
    "prod_end",
)
# Stored columns in order; "brand" comes from the CSV's folder, "source" from how a row arrived.
_DB_COLUMNS = (*CSV_COLUMNS[:2], "brand", *CSV_COLUMNS[2:], "source")
_NULLABLE = frozenset({"vehicle_id", "series_code", "body", "prod_start", "prod_end"})
_VALUES = f"({', '.join(_DB_COLUMNS)}, added_at) VALUES ({', '.join('?' * (len(_DB_COLUMNS) + 1))})"
_INSERT = f"INSERT INTO vehicles {_VALUES}"  # a duplicate key is an error
_INSERT_NEW = f"INSERT OR IGNORE INTO vehicles {_VALUES}"  # existing keys are kept
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS vehicles (
  key TEXT PRIMARY KEY, vehicle_id TEXT, brand TEXT NOT NULL, series_label TEXT NOT NULL,
  series_code TEXT, model_name TEXT NOT NULL, type_code TEXT NOT NULL, body TEXT,
  market TEXT NOT NULL, prod_start TEXT, prod_end TEXT,
  source TEXT NOT NULL CHECK (source IN ('baseline', 'local')), added_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS vehicles_brand ON vehicles (brand)",
    "CREATE INDEX IF NOT EXISTS vehicles_series_code ON vehicles (series_code)",
    "CREATE INDEX IF NOT EXISTS vehicles_type_code ON vehicles (type_code)",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
_ORDER = "brand, series_code, model_name, market, prod_start, key"


def sort_key(vehicle: IndexedVehicle) -> tuple[str, str]:
    """Baseline CSV order: production start (empty first), then key."""
    return vehicle.production_from or "", vehicle.key


def csv_record(vehicle: IndexedVehicle) -> dict[str, str]:
    return {
        "key": vehicle.key,
        "vehicle_id": vehicle.vehicle.vehicle_id if vehicle.vehicle else "",
        "series_label": vehicle.series_label,
        "series_code": vehicle.series_code or "",
        "model_name": vehicle.model_name,
        "type_code": vehicle.type_code,
        "body": vehicle.body or "",
        "market": vehicle.market,
        "prod_start": vehicle.production_from or "",
        "prod_end": vehicle.production_to or "",
    }


def write_baseline(
    brands_dir: Path,
    brand_ids: Iterable[str],
    rows: Iterable[IndexedVehicle],
    *,
    total: int,
    built_at: date,
) -> dict[str, int]:
    """Write brands/<brand>/vehicles.csv for every brand id plus brands/vehicles.meta.toml.

    Returns the number of rows written per brand. UTF-8, "\\n" line ends, header row, rows sorted
    by production start (empty first) and then key.
    """
    by_brand: dict[str, list[IndexedVehicle]] = {brand_id: [] for brand_id in brand_ids}
    for row in rows:
        by_brand[row.brand].append(row)
    for brand_id, brand_rows in by_brand.items():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(csv_record(row) for row in sorted(brand_rows, key=sort_key))
        path = brands_dir / brand_id / CSV_FILENAME
        path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    meta = f'built_at = {built_at.isoformat()}\ntotal = {total}\nsource = "{SOURCE_URL}"\n'
    (brands_dir / META_FILENAME).write_text(meta, encoding="utf-8", newline="")
    return {brand_id: len(brand_rows) for brand_id, brand_rows in by_brand.items()}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _casefold(value: str | None) -> str:
    return (value or "").casefold()


class VehicleIndex:
    def __init__(self, conn: sqlite3.Connection, brands: BrandRegistry) -> None:
        self._conn = conn
        self._segments = brands.brand_segments()

    @classmethod
    def open(cls, settings: Settings, brands: BrandRegistry) -> VehicleIndex:
        """Open the store, (re)loading the baseline when the committed files changed.

        Missing baseline files count as an empty baseline, so the index works (empty) before the
        maintainer has built one. Unreadable files raise RealOemError naming the file.
        """
        db_path = settings.data_dir / DB_FILENAME
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        except (OSError, sqlite3.Error) as err:
            raise RealOemError(f"The vehicle index {db_path} could not be opened: {err}") from err
        index = cls(conn, brands)
        try:
            conn.create_function("fold", 1, _casefold, deterministic=True)
            conn.execute("PRAGMA journal_mode=WAL")  # several server processes may share it
            index._ensure_schema()
            brand_ids = sorted(brand.id for brand in brands)
            files = [settings.brands_dir / brand_id / CSV_FILENAME for brand_id in brand_ids]
            meta_path = settings.brands_dir / META_FILENAME
            digest = _baseline_hash([*files, meta_path])
            if index._get_meta("baseline_hash") != digest:
                index._load_baseline(files, meta_path, digest)
        except RealOemError:
            conn.close()
            raise
        except (OSError, sqlite3.Error) as err:
            conn.close()
            raise RealOemError(f"The vehicle index {db_path} could not be opened: {err}") from err
        return index

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")  # take the write lock up front
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _ensure_schema(self) -> None:
        """Create the tables; on a schema-version change rebuild them, keeping local rows if the
        old table has every column (otherwise they are dropped and meta "warning" says so)."""
        tables = {
            n for (n,) in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "meta" in tables and self._get_meta("schema_version") == SCHEMA_VERSION:
            return
        kept: list[tuple[Any, ...]] = []
        dropped = 0
        if "vehicles" in tables:
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(vehicles)")}
            if {*_DB_COLUMNS, "added_at"} <= columns:
                kept = self._conn.execute(
                    f"SELECT {', '.join(_DB_COLUMNS)}, added_at FROM vehicles "
                    "WHERE source = 'local'"
                ).fetchall()
            else:
                where = " WHERE source = 'local'" if "source" in columns else ""
                (dropped,) = self._conn.execute(f"SELECT COUNT(*) FROM vehicles{where}").fetchone()
        with self._transaction():
            self._conn.execute("DROP TABLE IF EXISTS vehicles")
            self._conn.execute("DROP TABLE IF EXISTS meta")
            for statement in _SCHEMA:
                self._conn.execute(statement)
            self._conn.executemany(_INSERT, kept)
            self._set_meta("schema_version", SCHEMA_VERSION)
            if dropped:
                self._set_meta(
                    "warning",
                    f"{dropped} locally added vehicle(s) were dropped when the index store was "
                    "upgraded; run update_vehicle_index to add them again.",
                )

    def _load_baseline(self, files: Sequence[Path], meta_path: Path, digest: str) -> None:
        rows: list[tuple[Any, ...]] = []
        added_at = _now()
        for path in files:
            if path.exists():
                rows.extend(
                    (*_db_values(record, path.parent.name, "baseline"), added_at)
                    for record in _read_csv(path)
                )
        built_at, total = _read_meta(meta_path)
        with self._transaction():
            self._conn.execute("DELETE FROM vehicles WHERE source = 'baseline'")
            self._conn.executemany(
                "DELETE FROM vehicles WHERE source = 'local' AND key = ?", [(r[0],) for r in rows]
            )
            self._conn.executemany(_INSERT, rows)
            self._set_meta("built_at", built_at.isoformat() if built_at else "")
            self._set_meta("baseline_total", str(total))
            self._set_meta("baseline_hash", digest)

    def search(
        self,
        *,
        query: str | None = None,
        brand: str | None = None,
        series: str | None = None,
        year: int | None = None,
        market: str | None = None,
        type_code: str | None = None,
        include_unlinked: bool = False,
        limit: int = 25,
    ) -> tuple[int, list[IndexedVehicle]]:
        """(total matches, first `limit` matches ordered by brand, series, model, market, start)."""
        where: list[str] = []
        args: list[Any] = []
        for token in (query or "").split():
            where.append(
                "(instr(fold(series_label), ?) OR instr(fold(series_code), ?) "
                "OR instr(fold(model_name), ?) OR instr(fold(type_code), ?))"
            )
            args += [token.casefold()] * 4
        for column, value in (
            ("brand", brand),
            ("series_code", series),
            ("market", market),
            ("type_code", type_code),
        ):
            if value is not None:
                where.append(f"fold({column}) = ?")
                args.append(value.casefold())
        if year is not None:
            where.append(
                "CAST(substr(prod_start, 1, 4) AS INTEGER) <= ? "
                "AND (prod_end IS NULL OR CAST(substr(prod_end, 1, 4) AS INTEGER) >= ?)"
            )
            args += [year, year]
        if not include_unlinked:
            where.append("vehicle_id IS NOT NULL")
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        (total,) = self._conn.execute(f"SELECT COUNT(*) FROM vehicles{clause}", args).fetchone()
        cursor = self._conn.execute(
            f"SELECT {', '.join(_DB_COLUMNS)} FROM vehicles{clause} ORDER BY {_ORDER} LIMIT ?",
            [*args, limit],
        )
        return total, [self._vehicle(row) for row in cursor]

    def keys(self) -> set[str]:
        return {key for (key,) in self._conn.execute("SELECT key FROM vehicles")}

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]

    def max_prod_start(self) -> str | None:
        return self._conn.execute("SELECT MAX(prod_start) FROM vehicles").fetchone()[0]

    def add_local(self, rows: Sequence[IndexedVehicle]) -> int:
        """Insert rows found by an update; existing keys are ignored. Returns rows inserted."""
        added_at = _now()
        inserted = 0
        with self._transaction():
            for row in rows:
                values = _db_values(csv_record(row), row.brand, "local")
                inserted += self._conn.execute(_INSERT_NEW, (*values, added_at)).rowcount
        return inserted

    def last_remote_total(self) -> int | None:
        """RealOEM's vehicle count seen by the last update check, if any."""
        value = self._get_meta("last_remote_total")
        return int(value) if value else None

    def resume_point(self) -> tuple[str | None, int] | None:
        """(max_prod_start the interrupted scan started from, next page to read) after `partial`."""
        page = self._get_meta("resume_page")
        if not page:
            return None
        return self._get_meta("resume_start") or None, int(page)

    def record_check(self, *, remote_total: int, resume: tuple[str | None, int] | None) -> None:
        """Store the outcome of an update check: time, RealOEM's total, and where to resume."""
        with self._transaction():
            self._set_meta("last_update_at", _now())
            self._set_meta("last_remote_total", str(remote_total))
            if resume is None:
                self._conn.execute("DELETE FROM meta WHERE key IN ('resume_start', 'resume_page')")
            else:
                self._set_meta("resume_start", resume[0] or "")
                self._set_meta("resume_page", str(resume[1]))

    def meta(self) -> IndexMeta:
        built_at = self._get_meta("built_at")
        last_update = self._get_meta("last_update_at")
        (local_rows,) = self._conn.execute(
            "SELECT COUNT(*) FROM vehicles WHERE source = 'local'"
        ).fetchone()
        return IndexMeta(
            built_at=date.fromisoformat(built_at) if built_at else None,
            baseline_total=int(self._get_meta("baseline_total") or 0),
            local_rows=local_rows,
            last_update_at=datetime.fromisoformat(last_update) if last_update else None,
        )

    def close(self) -> None:
        self._conn.close()

    def _vehicle(self, row: Sequence[Any]) -> IndexedVehicle:
        values = dict(zip(_DB_COLUMNS, row, strict=True))
        vehicle = None
        if values["vehicle_id"]:
            vid = VehicleId.parse(values["vehicle_id"], brand_segments=self._segments)
            vehicle = VehicleRef.from_id(vid, values["brand"])
        return IndexedVehicle(
            key=values["key"],
            vehicle=vehicle,
            brand=values["brand"],
            series_label=values["series_label"],
            series_code=values["series_code"],
            model_name=values["model_name"],
            type_code=values["type_code"],
            body=values["body"],
            market=values["market"],
            production_from=values["prod_start"],
            production_to=values["prod_end"],
            source=values["source"],
        )

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def _baseline_hash(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(f"{path.parent.name}/{path.name}\0".encode())
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def _invalid(path: Path, detail: object) -> RealOemError:
    return RealOemError(f"The vehicle baseline {path} is invalid: {detail}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Every record of one brand's vehicles.csv; RealOemError naming the file if it is bad."""
    records: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise _invalid(path, f"its header must be {','.join(CSV_COLUMNS)}.")
            for record in reader:
                # DictReader fills missing fields with None and puts extra ones under None.
                if None in record or None in record.values():
                    raise _invalid(path, f"line {reader.line_num} does not have 10 fields.")
                empty = [c for c in CSV_COLUMNS if c not in _NULLABLE and not record[c]]
                if empty:
                    raise _invalid(path, f"line {reader.line_num} has an empty {empty[0]}.")
                records.append(record)
    except (OSError, UnicodeError, csv.Error) as err:
        raise _invalid(path, err) from err
    return records


def _read_meta(path: Path) -> tuple[date | None, int]:
    """(built_at, total) from vehicles.meta.toml; (None, 0) when there is no baseline."""
    if not path.exists():
        return None, 0
    try:
        meta = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as err:
        raise _invalid(path, err) from err
    built_at, total = meta.get("built_at"), meta.get("total")
    if not isinstance(built_at, date) or isinstance(built_at, datetime):
        raise _invalid(path, "built_at must be a TOML date such as 2026-09-30.")
    if not isinstance(total, int) or isinstance(total, bool):
        raise _invalid(path, "total must be a whole number.")
    return built_at, total


def _db_values(record: dict[str, str], brand: str, source: str) -> tuple[str | None, ...]:
    """CSV record -> values in _DB_COLUMNS order; empty optional fields become NULL."""
    merged = {**record, "brand": brand, "source": source}
    return tuple(
        (merged[column] or None) if column in _NULLABLE else merged[column]
        for column in _DB_COLUMNS
    )
