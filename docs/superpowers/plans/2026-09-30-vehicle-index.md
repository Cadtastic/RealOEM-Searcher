# Vehicle Index Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/vehicle-index` (PRD F6.1–F6.6): a local index of every vehicle in RealOEM's vehicles index, shipped as committed per-brand CSV baselines, loaded into a durable SQLite store in the user's data directory, searchable with the no-network `find_vehicle` tool, incrementally refreshed with `update_vehicle_index`, rebuilt only by a maintainer script, and explained by the `vehicle-index` skill.

**Architecture:** `parsers/vehicles.py` turns one `vehicles?page=N&sort=year` page into a `VehicleIndexPage` (rows, "Showing a–b of n", current and last page), assigning each row's brand with the ARD rule (`for_vehicle_id` with `product="M"` for type codes starting with `0`; unlinked rows by their model-cell brand prefix). `vehicle_index.py` owns the CSV format (writer and reader) and `VehicleIndex`, which loads `brands/<brand>/vehicles.csv` into `{data_dir}/vehicles.sqlite3` whenever the sha256 of the baseline files changes, keeps rows added by updates, remembers the last update check (RealOEM's total, a resume point after a `partial` update) and answers searches. `tools/vehicles.py` (auto-discovered) opens the index lazily into `services.extras["vehicle_index"]` and exposes `find_vehicle` (local only) and `update_vehicle_index` (ARD update algorithm, always `refresh=True`); `scripts/rebuild_vehicle_index.py` reuses the same page fetcher to crawl all pages for the maintainer.

**Tech Stack:** Python ≥ 3.11, uv, mcp 2.x (`MCPServer`), httpx, selectolax (lexbor), pydantic 2, stdlib `sqlite3`/`csv`/`tomllib`/`hashlib` (all from the foundation); pytest + AnyIO plugin, ruff.

---

## Before you start

- `main` already contains the foundation and, very likely, the part-lookup, VIN-decode and
  diagram-browse branches. This plan uses **only foundation APIs**: `Settings` (incl. `data_dir`,
  `brands_dir`), `Services` / `Services.extras` / `create_services`, `RealOemClient.fetch(page_type,
  path, params, *, refresh)`, `PageCache.shorten` / `get`, `PageType.VEHICLES`, `LayoutChanged` /
  `InvalidInput` / `RealOemError`, `parsers.common` (`tree`, `text`, `require`, `parse_my`, `Node`),
  `BrandRegistry` (`load`, `for_vehicle_id`, `for_series`, `brand_segments`), `VehicleId.parse`,
  `VehicleRef.from_id`, `ResultMeta.from_pages`, and the test harness (`tests/harness.py`:
  `load_fixture`, `url`, `Route`, `FixtureTransport`, `FakeClock`, `BRANDS_DIR`, `REPO_ROOT`).
- Read `docs/ARD.md` AD16, §5.2, §5.2a, §5.4, §5.7, §5.8, §5.10 and the "F6: vehicle index" part
  of §5.11 once, plus `docs/research/realoem-site-notes.md` §5.5.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.**
  Python commands use `uv run --directory server …`; paths after it (like
  `tests/unit/test_vehicle_index.py`) are relative to `server/`. `git` paths are relative to the
  repository root.
- **Never send a request to realoem.com** while implementing. Task 11 is the only live step and is
  run by the controller, never by an implementer subagent, after the maintainer's explicit yes in
  chat. The opt-in live test of Task 10 is not run as part of this plan. All other tests are offline.
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`.
- This branch **only adds files**; it edits no foundation file and no file of another feature
  branch (in particular nothing in `skills/diagram-browse/`: the diagram-browse plan,
  `docs/superpowers/plans/2026-09-30-diagram-browse.md`, already has its skill use `find_vehicle`
  "if the `find_vehicle` tool is available", and this branch's skill points to `list_part_groups`).
- Tests never depend on the real baseline CSVs: every test that needs a baseline writes a small
  synthetic one into `tmp_path` (`tests/vehicle_env.py`). The one exception is
  `tests/unit/test_committed_vehicle_baseline.py`, which is skipped until Task 11 commits the CSVs.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that).
- Versions stay `0.1.0` everywhere; feature branches never bump them.
- **Test counts** are "baseline + N": run the suite once in Task 0 and write the numbers down
  (other branches merged before this one add their own tests). Per-file counts below are exact. This
  branch adds **90 passed, 1 skipped and 1 deselected** (the opt-in live test); after Task 11 the
  skipped guard test passes (baseline + 91 passed, + 1 deselected).
- The foundation's `tests/unit/test_fixtures.py` checks every fixture under `server/tests/fixtures/`
  (trimmed, no unmasked 17-character VIN), so the new fixtures are covered without extra tests.
- `ruff format --check` reports one more "file already formatted" per new `.py` file; this branch
  adds 17 (baseline + 17 at the end).

## File Structure

| Path | Responsibility |
|---|---|
| `server/src/realoem_mcp/models/vehicles.py` | `IndexedVehicle`, `IndexMeta`, `VehicleSearchResult`, `VehicleIndexUpdateResult(ResultMeta)` (ARD §5.11) and the parser output `VehicleIndexPage` |
| `server/src/realoem_mcp/parsers/vehicles.py` | `parse_vehicles(html, *, url, brands) -> VehicleIndexPage`, `has_vehicle_rows`, `row_key`, `product_for_type`, `PAGE_SIZE` |
| `server/src/realoem_mcp/vehicle_index.py` | CSV format (`CSV_COLUMNS`, `csv_record`, `sort_key`, `write_baseline`) and `VehicleIndex` (baseline load + hash, reconcile, schema version, search, keys/count/max_prod_start/add_local/meta/close, update-check state) |
| `server/src/realoem_mcp/tools/vehicles.py` | `get_index`, `search_index`, `fetch_vehicles_page`, `update_index`; `register()` → `find_vehicle`, `update_vehicle_index` |
| `server/scripts/rebuild_vehicle_index.py` | Maintainer-only full crawl → `brands/<brand>/vehicles.csv` + `brands/vehicles.meta.toml` |
| `skills/vehicle-index/SKILL.md` | Find first, update then search again, start-month ids, "as of `built_at`" end dates, links, next steps |
| `brands/<brand>/vehicles.csv`, `brands/vehicles.meta.toml` | Committed baseline, produced in Task 11 only |
| `server/tests/fixtures/vehicles/*.html` | 5 trimmed real pages: `sort=year` pages 1, 2, 83, 165 and the one-page `series=M` list |
| `server/tests/vehicle_data.py` | Test helpers: `vehicle()`, `numbered()`, `render_page()` (RealOEM markup), `SyntheticIndex` fake transport |
| `server/tests/vehicle_env.py` | Test helpers: private brands folder, `install_baseline`, `vehicle_services()` |
| `server/tests/unit/test_models_vehicles.py` | Model fields and serialization (3) |
| `server/tests/unit/parsers/test_vehicles.py` | `parse_vehicles` on every real fixture (12) |
| `server/tests/unit/parsers/test_vehicles_rules.py` | Brand rules on synthetic pages, past-the-end pages, `LayoutChanged` cases (18) |
| `server/tests/unit/test_vehicle_index.py` | CSV writer, load, search, add, update-check state, reconcile, schema upgrade, bad files (17) |
| `server/tests/tools/test_find_vehicle.py` | `find_vehicle` via in-memory `mcp.Client`: zero requests, lazy open/close, validation (7) |
| `server/tests/tools/test_update_vehicle_index.py` | `update_vehicle_index`: up_to_date, updated, resumable partial, drift cases, no baseline, validation, unparseable page (13) |
| `server/tests/unit/test_rebuild_vehicle_index.py` | Rebuild over a synthetic 3-page index: output, restarts, page and duplicate checks, `main` (8) |
| `server/tests/unit/test_skill_vehicle_index.py` | Skill frontmatter and required statements (2) |
| `server/tests/unit/test_committed_vehicle_baseline.py` | Committed baseline sorted, complete and loadable (1, skipped until Task 11) |
| `server/tests/live/test_live_vehicles.py` | Opt-in live smoke test of `update_vehicle_index` (2 requests; deselected by default) |

Decisions this plan makes where the ARD leaves room:

- **Models are exactly as in ARD §5.11** (`IndexMeta.built_at: date | None`, `None` until a
  baseline is installed). `models/vehicles.py` also holds the parser output
  `VehicleIndexPage(page, last_page, first, last, total, rows)`; rows parsed from RealOEM carry
  `source="local"`.
- **Parsing (site notes §5.5):** result bar = first and second `<strong>` of
  `#vi-result-bar > span` (a series filter adds a third); rows = `table#vi-table > tbody` `tr.r0,
  tr.r1` with the six `td.vi-col-*` cells; the model cell is split at the first NBSP into brand
  prefix and `model_name`; `series_label` is kept verbatim (only trimmed; `R 51         -54` keeps its
  inner spaces); `body` `N/A` or empty → `None`; production `MM/YYYY–MM/YYYY` → `"YYYY-MM"` pair or
  both `None`; the vehicle id is the link's `href` after `/bmw/enUS/partgrp?id=`, parsed with
  `VehicleId.parse(…, brand_segments=registry.brand_segments())`; `series_code` = the id's series.
  No `#vi-pagination` → page 1 of 1; no "Last page" link → the current page is the last page.
  `LayoutChanged` when the result bar, table, a cell, the NBSP prefix, the series label, the model
  name, the type code, the market, the page number or the date range is missing or unreadable, when
  the number of rows differs from "Showing a–b", or when `last_page != max(1, ceil(total / 50))` or
  `first != (page − 1) × 50 + 1`.
- **Brand per row (ARD):** linked rows → `for_vehicle_id(vid, product="M" if type starts with "0"
  else "P")`; unlinked rows → `Mini` → `mini`, `Rolls-Royce` → `rolls-royce`, anything else →
  `for_series(None, product=…)` (`bmw` for cars, `motorrad` for motorcycles). Zinoro rows resolve to
  `bmw` through the registry (the foundation's `bmw` brand lists the `Zinoro` id segment, so their
  `VehicleRef.model` is filled like any other).
- **Row key** = `{type}-{market}-{MM}-{YYYY}` from the cells, or `{type}-{market}--` without a start.
- **CSV:** header `key,vehicle_id,series_label,series_code,model_name,type_code,body,market,prod_start,prod_end`,
  UTF-8, `\n`, `csv` quoting rules, rows sorted by `(prod_start or "", key)`; every registry brand
  gets a file (header only when empty). `vehicles.meta.toml` holds `built_at` as a TOML date,
  `total` and `source`.
- **Store:** `{data_dir}/vehicles.sqlite3` in WAL mode (several server processes may share it),
  schema per ARD plus an `added_at` timestamp and a `schema_version` in `meta`; writes use
  `BEGIN IMMEDIATE`. Baseline hash = sha256 over each registry brand's `vehicles.csv` (sorted by
  brand id, a marker for missing files) and `vehicles.meta.toml`. On a hash change, in one
  transaction: delete `baseline` rows, delete `local` rows whose key is in the new baseline, insert
  the baseline (a key twice in the baseline is an error), store meta. On a `schema_version` change
  the tables are rebuilt: local rows are kept when the old table has every column, otherwise they
  are dropped and `meta.warning` says so. Unreadable files or stores raise `RealOemError` naming the
  file: a baseline file that is not UTF-8 or not valid CSV/TOML, a CSV row without all 10 fields or
  with an empty required column (`key`, `series_label`, `model_name`, `type_code`, `market`), or a
  `vehicles.meta.toml` whose `built_at` is not a TOML date or whose `total` is not an integer. Empty optional CSV fields (`vehicle_id`, `series_code`, `body`, `prod_start`, `prod_end`)
  become `NULL`. Search uses a Python `casefold` SQL function so non-ASCII text ("Coupé") matches
  case-insensitively; results are ordered by brand, series code, model name, market, production
  start, key.
- **Update-check state** lives in the store's `meta` through three methods beyond the ARD list:
  `last_remote_total()`, `resume_point()` and `record_check(remote_total=…, resume=…)` (which also
  sets `last_update_at`). `add_local` only inserts.
- **`find_vehicle`** validates `limit` (1–100) and `brand` (a registry id) before touching the
  index and raises `InvalidInput`; it never sends a request and returns no `ResultMeta`.
- **`update_vehicle_index`:**
  - `max_pages` 1–10 is validated first. With no baseline installed (`built_at is None` or an
    empty index) it returns `drift` at once, with zero requests and the message "No vehicle index
    baseline is installed; the maintainer must run scripts/rebuild_vehicle_index.py."
  - Requests `vehicles` with params `page`, `sort=year` (in that order), always `refresh=True`.
  - Probe page = `ceil(min(local_total, last_remote_total or local_total) / 50)` (≥ 1), so a local
    index that grew past RealOEM's size (after a `drift`) still probes a real page. If a probe page
    above 1 has no vehicle rows (no `table#vi-table`, or an empty one: past RealOEM's end), page 1
    is fetched to read the total and the result is `drift`.
  - Parsed pages are keyed by the page number the parser reports; a page fetched as the probe is
    not fetched again during the scan; unknown keys from every fetched page are collected; a page
    whose first row has no start date, or starts before the scan's bound, ends the scan.
  - `partial` stores `(bound, next page)` as the resume point; the next call scans from that page
    with that bound. Every other status clears it. Vehicles RealOEM adds between a `partial` call
    and the resuming call land after the resume page, so the resumed scan misses them and reports
    `drift` (the next update after that finds them from the last page). `local_total` in the result is the index size
    **after** adding; `added` is sorted like the CSV. A `LayoutChanged` page is expired from the
    cache before re-raising.
- **Rebuild script:** writes nothing unless the whole crawl is consistent: each page must be the
  requested page (the parser checks its offset), the total must stay constant and a final re-fetch
  of the last page must show the same keys (otherwise restart, at most 3 attempts), the row count
  must equal the total and keys must be unique (all duplicates are listed).

## Chunk 1: Fixtures, models and the vehicles-page parser

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

```bash
git checkout main && git pull && git checkout -b feat/vehicle-index
```

Expected: `Switched to a new branch 'feat/vehicle-index'`.

- [ ] **Step 2: Record the baseline**

```bash
uv run --directory server pytest -q
uv run --directory server ruff format --check
```

Expected: PASS. Write down the `passed`/`deselected` counts and the number of formatted files;
they are "baseline" below (on a `main` with only the foundation: `197 passed, 1 deselected` and
`44 files already formatted`).

### Task 1: Vehicles-index fixtures

Five trimmed real pages cover everything the parser must handle: page 1 of `sort=year` (50 rows
without a vehicle id or dates), page 2 (the last undated row, then linked classic cars and
motorcycles with verbatim series labels such as `R 51         -54`), page 83 (MINI rows), page 165
(the last page: 18 rows, Rolls-Royce and motorcycle `0N74`, no "Last page" link) and `series=M`
(a single page without `#vi-pagination`, containing both Zinoro rows).

**Files:**
- Create: `server/tests/fixtures/vehicles/sort_year_p1.html`, `sort_year_p2.html`,
  `sort_year_p83.html`, `sort_year_p165.html`, `series_m.html`

- [ ] **Step 1: Trim the raw captures into fixtures**

The raw pages are in the main checkout's `.research-raw/` (git-ignored). If you work in a separate
worktree, copy `.research-raw/vehicles/` and `.research-raw/diagrams/41_vehicles_sort_year.html`
into the worktree's `.research-raw/` first (never `git add` them).

```bash
uv run --directory server python scripts/trim_fixture.py ../.research-raw/diagrams/41_vehicles_sort_year.html tests/fixtures/vehicles/sort_year_p1.html
uv run --directory server python scripts/trim_fixture.py ../.research-raw/vehicles/03_sort_year_p2.html tests/fixtures/vehicles/sort_year_p2.html
uv run --directory server python scripts/trim_fixture.py ../.research-raw/vehicles/02_sort_year_p83.html tests/fixtures/vehicles/sort_year_p83.html
uv run --directory server python scripts/trim_fixture.py ../.research-raw/vehicles/01_sort_year_p165.html tests/fixtures/vehicles/sort_year_p165.html
uv run --directory server python scripts/trim_fixture.py ../.research-raw/vehicles/14_series_M.html tests/fixtures/vehicles/series_m.html
```

Expected (stderr, one line per command; paths use `\` on Windows):

```
tests/fixtures/vehicles/sort_year_p1.html: 45794 -> 21398 bytes
tests/fixtures/vehicles/sort_year_p2.html: 50421 -> 25785 bytes
tests/fixtures/vehicles/sort_year_p83.html: 50978 -> 26342 bytes
tests/fixtures/vehicles/sort_year_p165.html: 37697 -> 13594 bytes
tests/fixtures/vehicles/series_m.html: 33026 -> 9031 bytes
```

- [ ] **Step 2: Check the fixtures with the foundation's fixture tests**

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q`
Expected: PASS with 10 more tests than before this task (one "trimmed" and one "no unmasked VIN"
test per fixture).

- [ ] **Step 3: Confirm the fixtures contain the structures the parser relies on**

Run: `grep -c 'vi-pagination' server/tests/fixtures/vehicles/*.html`
Expected: `series_m.html:0` and `1` for each `sort_year_p*.html`.

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/vehicles
git commit -m "test(vehicles): add trimmed vehicles-index fixtures" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Vehicle index models (`models/vehicles.py`)

ARD §5.11 defines the four result models; the parser output `VehicleIndexPage` joins them.

**Files:**
- Create: `server/src/realoem_mcp/models/vehicles.py`
- Test: `server/tests/unit/test_models_vehicles.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_vehicles.py`:

```python
from datetime import UTC, date, datetime

from realoem_mcp.models.common import ResultMeta, VehicleRef
from realoem_mcp.models.vehicles import (
    IndexedVehicle,
    IndexMeta,
    VehicleIndexPage,
    VehicleIndexUpdateResult,
    VehicleSearchResult,
)
from realoem_mcp.vehicle_ids import VehicleId

VID = "VB13-USA-10-2005-E90-BMW-325i"


def _vehicle() -> IndexedVehicle:
    return IndexedVehicle(
        key="VB13-USA-10-2005",
        vehicle=VehicleRef.from_id(VehicleId.parse(VID), "bmw"),
        brand="bmw",
        series_label="3 Series E90",
        series_code="E90",
        model_name="325i",
        type_code="VB13",
        body="Sedan",
        market="USA",
        production_from="2005-10",
        production_to="2008-02",
        source="baseline",
    )


def test_models_have_exactly_the_ard_fields() -> None:
    assert list(IndexedVehicle.model_fields) == [
        "key",
        "vehicle",
        "brand",
        "series_label",
        "series_code",
        "model_name",
        "type_code",
        "body",
        "market",
        "production_from",
        "production_to",
        "source",
    ]
    assert list(IndexMeta.model_fields) == [
        "built_at",
        "baseline_total",
        "local_rows",
        "last_update_at",
    ]
    assert list(VehicleSearchResult.model_fields) == ["total_matches", "vehicles", "index"]
    assert issubclass(VehicleIndexUpdateResult, ResultMeta)
    assert list(VehicleIndexUpdateResult.model_fields)[4:] == [
        "status",
        "added",
        "remote_total",
        "local_total",
        "pages_fetched",
        "message",
    ]
    assert not issubclass(VehicleSearchResult, ResultMeta)  # find_vehicle makes no request


def test_search_result_serializes_dates_as_iso_strings() -> None:
    meta = IndexMeta(
        built_at=date(2026, 9, 30),
        baseline_total=8218,
        local_rows=0,
        last_update_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    result = VehicleSearchResult(total_matches=1, vehicles=[_vehicle()], index=meta)
    dumped = result.model_dump(mode="json")
    assert dumped["index"] == {
        "built_at": "2026-09-30",
        "baseline_total": 8218,
        "local_rows": 0,
        "last_update_at": "2026-10-01T12:00:00Z",
    }
    assert dumped["vehicles"][0]["vehicle"]["vehicle_id"] == VID
    assert dumped["vehicles"][0]["vehicle"]["production_month"] == "2005-10"


def test_index_page_holds_the_result_bar_numbers() -> None:
    page = VehicleIndexPage(page=2, last_page=3, first=51, last=51, total=101, rows=[_vehicle()])
    assert (page.page, page.last_page, page.first, page.last, page.total) == (2, 3, 51, 51, 101)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_vehicles.py -q`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'realoem_mcp.models.vehicles'`
(`1 error`).

- [ ] **Step 3: Write the models**

Create `server/src/realoem_mcp/models/vehicles.py`:

```python
"""Vehicle index models (ARD section 5.11, F6) plus the vehicles-page parser output."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta, VehicleRef


class IndexedVehicle(BaseModel):
    key: str  # "{type}-{market}-{MM}-{YYYY}", or "{type}-{market}--" for unlinked rows
    vehicle: VehicleRef | None  # None for unlinked rows
    brand: str
    series_label: str
    series_code: str | None
    model_name: str
    type_code: str
    body: str | None
    market: str
    production_from: str | None  # "YYYY-MM"
    production_to: str | None  # "YYYY-MM"
    source: Literal["baseline", "local"]


class IndexMeta(BaseModel):
    built_at: date | None  # None when no baseline is installed
    baseline_total: int
    local_rows: int
    last_update_at: datetime | None


class VehicleSearchResult(BaseModel):
    total_matches: int
    vehicles: list[IndexedVehicle]
    index: IndexMeta


class VehicleIndexUpdateResult(ResultMeta):
    status: Literal["up_to_date", "updated", "partial", "drift"]
    added: list[IndexedVehicle]
    remote_total: int
    local_total: int
    pages_fetched: int
    message: str


class VehicleIndexPage(BaseModel):
    """One parsed vehicles-index page (parsers/vehicles.py)."""

    page: int  # current page number
    last_page: int
    first: int  # "Showing <first>-<last> of <total>"
    last: int
    total: int
    rows: list[IndexedVehicle]  # source="local": rows read from RealOEM, not from the baseline
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_vehicles.py -q`
Expected: `3 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/src/realoem_mcp/models/vehicles.py server/tests/unit/test_models_vehicles.py
git commit -m "feat(vehicles): add vehicle index models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

### Task 3: `parse_vehicles` on real pages

**Files:**
- Create: `server/src/realoem_mcp/parsers/vehicles.py`
- Test: `server/tests/unit/parsers/test_vehicles.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_vehicles.py`:

```python
"""parse_vehicles on trimmed real vehicles-index pages (site notes section 5.5)."""

from collections import Counter

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.models.vehicles import VehicleIndexPage
from realoem_mcp.parsers.vehicles import parse_vehicles
from tests.harness import BRANDS_DIR, load_fixture, url

BRANDS = BrandRegistry.load(BRANDS_DIR)


def _parse(slug: str, page: int) -> VehicleIndexPage:
    return parse_vehicles(
        load_fixture(f"vehicles/{slug}.html"),
        url=url("vehicles", page=str(page), sort="year"),
        brands=BRANDS,
    )


@pytest.mark.parametrize(
    ("slug", "number", "expected"),
    [
        ("sort_year_p1", 1, (1, 165, 1, 50, 8218, 50)),
        ("sort_year_p2", 2, (2, 165, 51, 100, 8218, 50)),
        ("sort_year_p83", 83, (83, 165, 4101, 4150, 8218, 50)),
        ("sort_year_p165", 165, (165, 165, 8201, 8218, 8218, 18)),
        ("series_m", 1, (1, 1, 1, 10, 10, 10)),  # one page: no #vi-pagination at all
    ],
)
def test_result_bar_and_pagination(slug: str, number: int, expected: tuple[int, ...]) -> None:
    p = _parse(slug, number)
    assert (p.page, p.last_page, p.first, p.last, p.total, len(p.rows)) == expected


def test_page_one_is_the_blank_start_rows() -> None:
    page = _parse("sort_year_p1", 1)
    assert all(row.vehicle is None and row.production_from is None for row in page.rows)
    assert all(row.key.endswith("--") for row in page.rows)
    assert Counter(row.brand for row in page.rows) == {"bmw": 48, "motorrad": 2}
    first = page.rows[0]
    assert first.model_dump() == {
        "key": "1A10-BRA--",
        "vehicle": None,
        "brand": "bmw",
        "series_label": "1 Series F20",
        "series_code": None,
        "model_name": "116i",
        "type_code": "1A10",
        "body": "5 doors",
        "market": "BRA",
        "production_from": None,
        "production_to": None,
        "source": "local",
    }


def test_unlinked_motorcycle_and_a_code_rows() -> None:
    rows = {row.type_code: row for row in _parse("sort_year_p1", 1).rows}
    assert (rows["0B74"].brand, rows["0B74"].model_name, rows["0B74"].body) == (
        "motorrad",
        "F 800 R 16 (0B74)",
        None,
    )
    assert rows["0P10"].brand == "motorrad"
    a15 = rows["9884"]
    assert (a15.brand, a15.series_label, a15.body) == ("bmw", "A15", None)


def test_page_two_mixes_the_last_blank_row_with_linked_classics() -> None:
    rows = _parse("sort_year_p2", 2).rows
    assert (rows[0].key, rows[0].vehicle) == ("KS07-IND--", None)
    assert rows[1].model_dump() == {
        "key": "ST01-EUR-01-1928",
        "vehicle": {
            "vehicle_id": "ST01-EUR-01-1928-CMSP-BMW-E30_M3_GrN",
            "type_code": "ST01",
            "market": "EUR",
            "production_month": "1928-01",
            "series": "CMSP",
            "brand": "bmw",
            "model": "E30_M3_GrN",
        },
        "brand": "bmw",
        "series_label": "BMW Classic Motorsport",
        "series_code": "CMSP",
        "model_name": "E30 M3 Gr.N",
        "type_code": "ST01",
        "body": "Coupe",
        "market": "EUR",
        "production_from": "1928-01",
        "production_to": "1932-09",
        "source": "local",
    }


def test_classic_motorcycles_keep_the_series_label_verbatim() -> None:
    row = next(r for r in _parse("sort_year_p2", 2).rows if r.type_code == "0T16")
    assert row.series_label == "R 51         -54"  # verbatim, inner spaces kept
    assert (row.brand, row.series_code, row.model_name) == ("motorrad", "T51", "R51/2")
    assert row.vehicle is not None and row.vehicle.vehicle_id == "0T16-EUR-01-1950-T51-BMW-R51_2"
    assert (row.production_from, row.production_to, row.body) == ("1950-01", "1950-12", None)


def test_mini_rows_split_the_brand_prefix() -> None:
    rows = _parse("sort_year_p83", 83).rows
    assert Counter(row.brand for row in rows) == {"bmw": 38, "mini": 12}
    clubman = rows[2]
    assert (clubman.key, clubman.brand, clubman.series_label, clubman.series_code) == (
        "MH92-EUR-01-2012",
        "mini",
        "MINI Clubman R55 LCI",
        "R55N",
    )
    assert clubman.model_name == "Coop.S JCW"
    assert clubman.vehicle is not None
    assert (clubman.vehicle.brand, clubman.vehicle.model) == ("mini", "CoopS_JCW")


def test_last_page_rolls_royce_and_motorcycles() -> None:
    rows = _parse("sort_year_p165", 165).rows
    assert Counter(row.brand for row in rows) == {"bmw": 13, "rolls-royce": 3, "motorrad": 2}
    phantom, r18 = rows[0], rows[1]
    assert (phantom.key, phantom.brand, phantom.series_code, phantom.model_name) == (
        "13HE-USA-11-2024",
        "rolls-royce",
        "R11N",
        "Phantom",
    )
    assert phantom.vehicle is not None
    assert phantom.vehicle.vehicle_id == "13HE-USA-11-2024-R11N-Rolls_Royce-Phantom"
    assert (r18.brand, r18.type_code, r18.model_name, r18.body) == (
        "motorrad",
        "0N74",
        "R 18 25 (0N74)",
        None,
    )
    assert [row.production_from for row in rows[-3:]] == ["2025-03"] * 3


def test_zinoro_rows_belong_to_bmw() -> None:
    rows = {row.type_code: row for row in _parse("series_m", 1).rows}
    zinoro_bmw_id, zinoro_own_id = rows["CZ31"], rows["CZ11"]
    assert (zinoro_bmw_id.brand, zinoro_bmw_id.model_name) == ("bmw", "Zinoro 1E")
    assert (zinoro_own_id.brand, zinoro_own_id.model_name) == ("bmw", "Zinoro 60H/100H")
    assert zinoro_own_id.vehicle is not None
    assert zinoro_own_id.vehicle.vehicle_id == "CZ11-CHN-06-2015-M13-Zinoro-Zinoro_60H_100H"
    assert zinoro_own_id.series_code == "M13"
    assert (zinoro_own_id.vehicle.brand, zinoro_own_id.vehicle.model) == ("bmw", "Zinoro_60H_100H")
    assert sum(row.vehicle is None for row in rows.values()) == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_vehicles.py -q`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'realoem_mcp.parsers.vehicles'`
(`1 error`).

- [ ] **Step 3: Write the parser**

Create `server/src/realoem_mcp/parsers/vehicles.py`:

```python
"""Vehicles index page: /bmw/enUS/vehicles?page=N&sort=year (site notes section 5.5)."""

from __future__ import annotations

import math
import re

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle, VehicleIndexPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_my, require, text, tree
from realoem_mcp.vehicle_ids import VehicleId

PAGE_TYPE = PageType.VEHICLES.value
PAGE_SIZE = 50  # vehicles per index page
LINK_PREFIX = "/bmw/enUS/partgrp?id="
NBSP = "\xa0"
# Brand prefix of the model cell ("Mini&nbsp;Cooper") for rows without a link; others go by type.
UNLINKED_PREFIX_BRANDS = {"Mini": "mini", "Rolls-Royce": "rolls-royce"}
_RANGE = re.compile(r"(\d[\d,]*)\s*[^\d\s,]\s*(\d[\d,]*)")  # "8201&ndash;8218"
_MONTH_YEAR = re.compile(r"\d{2}/\d{4}")
_PAGE_PARAM = re.compile(r"[?&]page=(\d+)")


def product_for_type(type_code: str) -> str:
    """Motorcycle type codes start with "0" (site notes section 5.5)."""
    return "M" if type_code.startswith("0") else "P"


def has_vehicle_rows(html: str) -> bool:
    """False for a page past the end of the index (no table#vi-table, or a table without rows)."""
    return (
        tree(html).css_first("table#vi-table > tbody > tr.r0, table#vi-table > tbody > tr.r1")
        is not None
    )


def parse_vehicles(html: str, *, url: str, brands: BrandRegistry) -> VehicleIndexPage:
    root = tree(html)
    bar = require(root, "#vi-result-bar > span", PAGE_TYPE, url)
    numbers = bar.css("strong")  # a series filter adds a third <strong> ("Series: M")
    if len(numbers) < 2:
        raise LayoutChanged(PAGE_TYPE, "result bar does not show 'Showing a-b of n'", url)
    showing = _RANGE.fullmatch(text(numbers[0]))
    total_text = text(numbers[1]).replace(",", "")
    if showing is None or not total_text.isdigit():
        raise LayoutChanged(PAGE_TYPE, f"unreadable result bar {text(bar)!r}", url)
    first, last = (int(group.replace(",", "")) for group in showing.groups())
    table = require(root, "table#vi-table > tbody", PAGE_TYPE, url)
    rows = [_row(tr, url, brands) for tr in table.css("tr.r0, tr.r1")]
    if len(rows) != last - first + 1:
        raise LayoutChanged(PAGE_TYPE, f"{len(rows)} rows but 'Showing {first}-{last}'", url)
    page, last_page = _pagination(root, url)
    total = int(total_text)
    if last_page != max(1, math.ceil(total / PAGE_SIZE)) or first != (page - 1) * PAGE_SIZE + 1:
        raise LayoutChanged(
            PAGE_TYPE,
            f"page {page} of {last_page} shows rows {first}-{last} of {total}, "
            f"expected {PAGE_SIZE} rows per page",
            url,
        )
    return VehicleIndexPage(
        page=page, last_page=last_page, first=first, last=last, total=total, rows=rows
    )


def _pagination(root: Node, url: str) -> tuple[int, int]:
    nav = root.css_first("#vi-pagination")
    if nav is None:  # everything fits on one page
        return 1, 1
    current = text(require(nav, "span.vi-pg-current", PAGE_TYPE, url))
    if not current.isdigit():
        raise LayoutChanged(PAGE_TYPE, f"current page {current!r} is not a number", url)
    last_link = nav.css_first('a[title="Last page"]')
    if last_link is None:  # on the last page
        return int(current), int(current)
    match = _PAGE_PARAM.search(last_link.attributes.get("href") or "")
    if match is None:
        raise LayoutChanged(PAGE_TYPE, "last-page link has no page number", url)
    return int(current), int(match.group(1))


def _row(tr: Node, url: str, brands: BrandRegistry) -> IndexedVehicle:
    cells = {
        name: require(tr, f"td.vi-col-{name}", PAGE_TYPE, url)
        for name in ("series", "model", "type", "body", "prod", "market")
    }
    prefix, sep, model_name = cells["model"].text(deep=True).partition(NBSP)
    if not sep:
        raise LayoutChanged(PAGE_TYPE, "model cell has no brand prefix", url)
    type_code, market = text(cells["type"]), text(cells["market"])
    series_label = cells["series"].text(deep=True).strip()
    model_name = " ".join(model_name.split())
    if not (type_code and market and series_label and model_name):
        raise LayoutChanged(PAGE_TYPE, "row without series, model, type code or market", url)
    dates = _MONTH_YEAR.findall(text(cells["prod"]))
    if len(dates) not in (0, 2):
        raise LayoutChanged(PAGE_TYPE, f"unreadable production range {text(cells['prod'])!r}", url)
    start, end = (parse_my(dates[0]), parse_my(dates[1])) if dates else (None, None)
    product = product_for_type(type_code)
    link = cells["model"].css_first(f'a[href^="{LINK_PREFIX}"]')
    if link is None:
        brand = (
            UNLINKED_PREFIX_BRANDS.get(prefix.strip())
            or brands.for_series(None, product=product).id
        )
        vehicle = None
    else:
        vid = VehicleId.parse(
            (link.attributes.get("href") or "")[len(LINK_PREFIX) :],
            brand_segments=brands.brand_segments(),
        )
        brand = brands.for_vehicle_id(vid, product=product).id
        vehicle = VehicleRef.from_id(vid, brand)
    body = text(cells["body"])
    return IndexedVehicle(
        key=row_key(type_code, market, start),
        vehicle=vehicle,
        brand=brand,
        series_label=series_label,
        series_code=vehicle.series if vehicle else None,
        model_name=model_name,
        type_code=type_code,
        body=None if body in ("", "N/A") else body,
        market=market,
        production_from=start,
        production_to=end,
        source="local",
    )


def row_key(type_code: str, market: str, production_from: str | None) -> str:
    """{type}-{market}-{MM}-{YYYY}, or {type}-{market}-- without a production start."""
    if production_from is None:
        return f"{type_code}-{market}--"
    year, month = production_from.split("-")
    return f"{type_code}-{market}-{month}-{year}"
```

Notes: the model cell is split at the NBSP **before** any stripping (`str.strip()` would remove a
trailing NBSP, and `text()` collapses it). `_RANGE` accepts any single non-digit separator because
RealOEM writes `&ndash;` between the numbers. `PAGE_SIZE` lives here because the parser checks page
offsets with it and the tool and rebuild script compute page numbers from it.
`has_vehicle_rows` lets the update tool recognise a page past RealOEM's end.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_vehicles.py -q`
Expected: `12 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/src/realoem_mcp/parsers/vehicles.py server/tests/unit/parsers/test_vehicles.py
git commit -m "feat(vehicles): parse vehicles-index pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

### Task 4: Synthetic index pages, brand rules and `LayoutChanged`

The real pages contain no unlinked MINI or Rolls-Royce row and no motorcycle whose series code
matches no motorrad pattern, so these rules are tested on synthetic pages rendered with RealOEM's
markup. The same helper (`tests/vehicle_data.py`) later serves a fake multi-page index to the tool
and rebuild tests. The parser from Task 3 already implements the rules; this task adds the helper
and the tests that pin them down.

**Files:**
- Create: `server/tests/vehicle_data.py`
- Test: `server/tests/unit/parsers/test_vehicles_rules.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_vehicles_rules.py`:

```python
"""parse_vehicles brand rules and LayoutChanged cases on synthetic pages (tests/vehicle_data.py)."""

import pytest

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vehicles import VehicleIndexPage
from realoem_mcp.parsers.vehicles import (
    has_vehicle_rows,
    parse_vehicles,
    product_for_type,
    row_key,
)
from tests.harness import BRANDS_DIR, load_fixture
from tests.vehicle_data import numbered, render_page, vehicle

BRANDS = BrandRegistry.load(BRANDS_DIR)
URL = "https://www.realoem.com/bmw/enUS/vehicles?page=2&sort=year"
REAL_P2 = load_fixture("vehicles/sort_year_p2.html")
EMPTY_TABLE = '<html><body><table id="vi-table"><tbody></tbody></table></body></html>'
LAST_LINK = '/bmw/enUS/vehicles?page=165&amp;sort=year" title="Last page"'


def _parse(html: str) -> VehicleIndexPage:
    return parse_vehicles(html, url=URL, brands=BRANDS)


def test_rendered_pages_round_trip() -> None:
    rows = numbered(120)
    pages = [_parse(render_page(rows, number)) for number in (1, 2, 3)]
    assert [(p.page, p.last_page, p.first, p.last, p.total) for p in pages] == [
        (1, 3, 1, 50, 120),
        (2, 3, 51, 100, 120),
        (3, 3, 101, 120, 120),
    ]
    assert [row for page in pages for row in page.rows] == rows


def test_unlinked_rows_take_the_brand_from_the_model_prefix() -> None:
    rows = [
        vehicle("RC31", "EUR", None, brand="mini", model_name="Cooper"),
        vehicle("13HE", "USA", None, brand="rolls-royce", model_name="Phantom"),
        vehicle("0B74", "BRA", None, brand="motorrad", model_name="F 800 R", body=None),
        vehicle("9884", "USA", None, brand="bmw", model_name="A15", body=None),
    ]
    parsed = _parse(render_page(rows, 1)).rows
    assert [(row.key, row.brand, row.vehicle) for row in parsed] == [
        ("RC31-EUR--", "mini", None),
        ("13HE-USA--", "rolls-royce", None),
        ("0B74-BRA--", "motorrad", None),
        ("9884-USA--", "bmw", None),
    ]


def test_type_code_starting_with_zero_means_motorcycle() -> None:
    # A motorcycle whose series code matches no motorrad pattern still resolves by product.
    bike = vehicle("0X99", "EUR", "1960-01", "1965-12", brand="motorrad", series_code="E1")
    # A car whose series code looks like a motorcycle series stays a car.
    car = vehicle("AB12", "EUR", "1960-01", "1965-12", brand="bmw", series_code="R8")
    parsed = _parse(render_page([bike, car], 1)).rows
    assert [(row.type_code, row.brand) for row in parsed] == [("0X99", "motorrad"), ("AB12", "bmw")]
    assert (product_for_type("0X99"), product_for_type("AB12")) == ("M", "P")


def test_a_page_past_the_end_has_no_vehicle_rows() -> None:
    assert has_vehicle_rows(REAL_P2)
    assert has_vehicle_rows(render_page(numbered(120), 3))
    assert not has_vehicle_rows(render_page(numbered(120), 4))  # no table at all
    assert not has_vehicle_rows(EMPTY_TABLE)


def test_row_key() -> None:
    assert row_key("VB13", "USA", "2005-10") == "VB13-USA-10-2005"
    assert row_key("VB13", "USA", None) == "VB13-USA--"


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        ('id="vi-result-bar"', 'id="other-bar"', "#vi-result-bar > span"),
        ('id="vi-table"', 'id="other-table"', "table#vi-table > tbody"),
        ("<strong>51\N{EN DASH}100</strong>", "<strong>51\N{EN DASH}99</strong>", "50 rows but"),
        ("<strong>8218</strong>", "<strong>many</strong>", "unreadable result bar"),
        ('<td class="vi-col-market">IND</td>', "", "td.vi-col-market"),
        ("BMW&nbsp;X5 25d", "BMW X5 25d", "no brand prefix"),
        ("BMW&nbsp;X5 25d", "BMW&nbsp; ", "row without series, model"),
        (
            '<td class="vi-col-series">X5 F15</td>',
            '<td class="vi-col-series"> </td>',
            "row without",
        ),
        ("01/1928\N{EN DASH}09/1932", "01/1928", "unreadable production range"),
        ('<span class="vi-pg-current">2</span>', "", "span.vi-pg-current"),
        (LAST_LINK, LAST_LINK.replace("page=165&amp;", ""), "no page number"),
        (LAST_LINK, LAST_LINK.replace("page=165", "page=166"), "expected 50 rows per page"),
        (
            '<span class="vi-pg-current">2</span>',
            '<span class="vi-pg-current">3</span>',
            "page 3 of 165 shows rows 51-100 of 8218",
        ),
    ],
)
def test_unexpected_structure_raises_layout_changed(old: str, new: str, detail: str) -> None:
    assert old in REAL_P2
    with pytest.raises(LayoutChanged, match=detail) as caught:
        _parse(REAL_P2.replace(old, new, 1))
    assert caught.value.page_type == "vehicles"
    assert caught.value.url == URL
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_vehicles_rules.py -q`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'tests.vehicle_data'`
(`1 error`).

- [ ] **Step 3: Write the helper**

Create `server/tests/vehicle_data.py`:

```python
"""Synthetic vehicles-index rows, rendered index pages and a fake RealOEM index (F6 tests)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from html import escape
from typing import Literal

import httpx

from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.parsers.vehicles import PAGE_SIZE, row_key
from realoem_mcp.vehicle_ids import VehicleId

Source = Literal["baseline", "local"]
ID_SEGMENTS = {"bmw": "BMW", "motorrad": "BMW", "mini": "Mini", "rolls-royce": "Rolls_Royce"}
MODEL_PREFIXES = {"bmw": "BMW", "motorrad": "BMW", "mini": "Mini", "rolls-royce": "Rolls-Royce"}


def vehicle(
    type_code: str,
    market: str = "USA",
    start: str | None = "2010-01",
    end: str | None = "2015-12",
    *,
    brand: str = "bmw",
    series_code: str = "E90",
    model_name: str = "325i",
    series_label: str | None = None,
    body: str | None = "Sedan",
    source: Source = "local",
) -> IndexedVehicle:
    """One index row. start=None makes an unlinked row (no vehicle id, no dates), like RealOEM."""
    ref = None
    if start is not None:
        year, month = start.split("-")
        segment = ID_SEGMENTS[brand]
        raw = f"{type_code}-{market}-{month}-{year}-{series_code}-{segment}-{model_name}"
        ref = VehicleRef.from_id(VehicleId.parse(raw.replace(" ", "_")), brand)
    return IndexedVehicle(
        key=row_key(type_code, market, start),
        vehicle=ref,
        brand=brand,
        series_label=series_label or f"Series {series_code}",
        series_code=series_code if ref else None,
        model_name=model_name,
        type_code=type_code,
        body=body,
        market=market,
        production_from=start,
        production_to=end if start is not None else None,
        source=source,
    )


def numbered(count: int) -> list[IndexedVehicle]:
    """count rows T000, T001, ... one production month apart from 2000-01 (sort=year order)."""
    return [
        vehicle(f"T{i:03d}", start=f"{2000 + i // 12}-{i % 12 + 1:02d}", end="2030-12")
        for i in range(count)
    ]


def render_page(rows: Sequence[IndexedVehicle], number: int) -> str:
    """vehicles?page=<number>&sort=year for an index holding `rows` (same markup as RealOEM).

    A page past the end renders without the vehicles table (RealOEM's exact markup for that case
    was never captured; the tool only relies on the table being absent).
    """
    total = len(rows)
    last_page = max(1, math.ceil(total / PAGE_SIZE))
    if number > last_page:  # past the end: no result bar, no table
        return '<html><body><div class="vi-empty">No vehicles found.</div></body></html>'
    chunk = rows[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]
    first = (number - 1) * PAGE_SIZE + 1
    body = "\n".join(_render_row(row, i) for i, row in enumerate(chunk))
    nav = ""
    if last_page > 1:
        last = (
            f'<a href="/bmw/enUS/vehicles?page={last_page}&amp;sort=year" title="Last page">'
            "&raquo;</a>"
            if number < last_page
            else '<span class="vi-pg-disabled">&raquo;</span>'
        )
        nav = f'<div id="vi-pagination"><span class="vi-pg-current">{number}</span>{last}</div>'
    return (
        '<html><body><div id="vi-result-bar"><span>Showing '
        f"<strong>{first}&ndash;{first + len(chunk) - 1}</strong> of <strong>{total}</strong> "
        'vehicles</span><span class="vi-sort">Sort: <span class="vi-sort-active">Year</span>'
        '</span></div><table id="vi-table"><thead><tr><th class="vi-col-series">Series</th>'
        f"</tr></thead><tbody>\n{body}\n</tbody></table>{nav}</body></html>"
    )


def _render_row(row: IndexedVehicle, i: int) -> str:
    model = f"{MODEL_PREFIXES[row.brand]}&nbsp;{escape(row.model_name)}"
    if row.vehicle is not None:
        model = f'<a href="/bmw/enUS/partgrp?id={escape(row.vehicle.vehicle_id)}">{model}</a>'
    prod = ""
    if row.production_from and row.production_to:
        prod = f"{_my(row.production_from)}&ndash;{_my(row.production_to)}"
    cells = [
        ("series", escape(row.series_label)),
        ("model", model),
        ("type", row.type_code),
        ("body", escape(row.body or "N/A")),
        ("prod", prod),
        ("market", row.market),
    ]
    tds = "".join(f'<td class="vi-col-{name}">{value}</td>' for name, value in cells)
    return f'<tr class="r{i % 2}">{tds}</tr>'


def _my(year_month: str) -> str:
    year, month = year_month.split("-")
    return f"{month}/{year}"


class SyntheticIndex(httpx.AsyncBaseTransport):
    """Serves vehicles?page=N&sort=year from `rows`, which tests may change between requests."""

    def __init__(self, rows: Sequence[IndexedVehicle]) -> None:
        self.rows = list(rows)
        self.requests: list[httpx.Request] = []
        self.on_request: Callable[[int], None] | None = None  # called with the request count
        self.past_end_html: str | None = None  # replaces the default page past the end

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(len(self.requests))
        params = request.url.params
        if request.url.path != "/bmw/enUS/vehicles" or params.get("sort") != "year":
            return httpx.Response(404, text="not a vehicles index URL", request=request)
        number = int(params["page"])
        past_end = (number - 1) * PAGE_SIZE >= len(self.rows)
        if past_end and self.past_end_html is not None:
            html = self.past_end_html
        else:
            html = render_page(self.rows, number)
        headers = {"Content-Type": "text/html;charset=UTF-8"}
        return httpx.Response(200, text=html, headers=headers, request=request)
```

`vehicle(type_code, market, start, end, …)` builds one `IndexedVehicle` the way the parser would
(with `start=None` it is an unlinked row); `numbered(n)` builds `n` rows one month apart from
2000-01, already in `sort=year` order; `render_page(rows, n)` renders page `n` of an index holding
`rows` (a page past the end has no vehicles table; `SyntheticIndex.past_end_html` replaces that
page when a test needs a different past-the-end answer, such as an empty table); `SyntheticIndex(rows)` is an `httpx` transport
serving those pages, recording requests and calling `on_request(count)` before answering so tests
can change `rows` mid-crawl.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers -q`
Expected: PASS; `tests/unit/parsers/test_vehicles_rules.py` alone gives `18 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/tests/vehicle_data.py server/tests/unit/parsers/test_vehicles_rules.py
git commit -m "test(vehicles): pin brand rules and layout checks on synthetic index pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

## Chunk 2: The local vehicle index store

### Task 5: `VehicleIndex` and the baseline CSV format (`vehicle_index.py`)

**Files:**
- Create: `server/src/realoem_mcp/vehicle_index.py`
- Create: `server/tests/vehicle_env.py`
- Test: `server/tests/unit/test_vehicle_index.py`

- [ ] **Step 1: Write the test environment helper**

Create `server/tests/vehicle_env.py` (a private `brands/` folder with copies of the repository's
`brand.toml` files, so tests never read or write the real baseline):

```python
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
```

- [ ] **Step 2: Write the failing test**

Create `server/tests/unit/test_vehicle_index.py`:

```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_vehicle_index.py -q`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'realoem_mcp.vehicle_index'`
(`1 error`).

- [ ] **Step 4: Write the index**

Create `server/src/realoem_mcp/vehicle_index.py`:

```python
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
```

Notes: the connection is in autocommit mode (`isolation_level=None`); every write goes through
`_transaction()`, which starts with `BEGIN IMMEDIATE` (takes the write lock up front, so two server
processes sharing the file serialize cleanly) and commits or rolls back, so a baseline reload is
all-or-nothing. `fold` is a Python `str.casefold` registered as a deterministic SQL function;
SQLite's own `LIKE`/`lower` only fold ASCII.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_vehicle_index.py -q`
Expected: `17 passed`

- [ ] **Step 6: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/src/realoem_mcp/vehicle_index.py server/tests/vehicle_env.py server/tests/unit/test_vehicle_index.py
git commit -m "feat(vehicles): add the local vehicle index store with CSV baseline" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

## Chunk 3: Tools

### Task 6: `find_vehicle` (no network)

**Files:**
- Create: `server/src/realoem_mcp/tools/vehicles.py`
- Test: `server/tests/tools/test_find_vehicle.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_find_vehicle.py`:

```python
"""find_vehicle via the in-memory MCP client: local search only, never a request."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.server import build_server
from realoem_mcp.tools.vehicles import INDEX_KEY
from realoem_mcp.vehicle_index import VehicleIndex
from tests.harness import FixtureTransport
from tests.vehicle_data import vehicle
from tests.vehicle_env import vehicle_services

pytestmark = pytest.mark.anyio


def _gs(type_code: str, market: str) -> IndexedVehicle:
    return vehicle(
        type_code,
        market,
        "2018-09",
        "2025-03",
        brand="motorrad",
        series_code="K50",
        model_name="R 1250 GS",
        series_label="K50 (R 1200 GS, R 1250 GS)",
        body=None,
        source="baseline",
    )


GS, GS_EUR = _gs("0J91", "USA"), _gs("0J93", "EUR")
E90 = vehicle("VB13", "USA", "2005-10", "2008-02", source="baseline")


async def _find(
    tmp_path: Path, baseline: Sequence[IndexedVehicle] | None, arguments: dict[str, Any]
) -> CallToolResult:
    transport = FixtureTransport({})
    async with (
        vehicle_services(tmp_path, transport, baseline=baseline) as services,
        Client(build_server(services)) as client,
    ):
        result = await client.call_tool("find_vehicle", arguments)
    assert transport.requests == []  # never touches RealOEM
    return result


async def test_find_vehicle_searches_the_local_index(tmp_path: Path) -> None:
    arguments = {"query": "r 1250 gs", "year": 2019, "brand": "motorrad"}
    result = await _find(tmp_path, [GS, E90], arguments)
    assert result.is_error is False
    data = result.structured_content
    assert data["total_matches"] == 1
    (found,) = data["vehicles"]
    assert found == GS.model_dump(mode="json")
    assert found["vehicle"]["vehicle_id"] == "0J91-USA-09-2018-K50-BMW-R_1250_GS"
    assert data["index"] == {
        "built_at": "2026-09-30",
        "baseline_total": 2,
        "local_rows": 0,
        "last_update_at": None,
    }
    assert "source_urls" not in data  # exempt from ResultMeta: no page was used


async def test_the_index_opens_on_first_use_and_closes_with_the_services(tmp_path: Path) -> None:
    async with (
        vehicle_services(tmp_path, FixtureTransport({}), baseline=[E90]) as services,
        Client(build_server(services)) as client,
    ):
        assert INDEX_KEY not in services.extras
        await client.call_tool("find_vehicle", {})
        index = services.extras[INDEX_KEY]
        assert isinstance(index, VehicleIndex)
        await client.call_tool("find_vehicle", {})
        assert services.extras[INDEX_KEY] is index
    with pytest.raises(sqlite3.ProgrammingError):  # Services.aclose() closed it
        index.count()


async def test_find_vehicle_reports_total_matches_beyond_the_limit(tmp_path: Path) -> None:
    result = await _find(tmp_path, [GS, GS_EUR, E90], {"series": "k50", "limit": 1})
    assert result.structured_content["total_matches"] == 2
    assert [v["key"] for v in result.structured_content["vehicles"]] == ["0J93-EUR-09-2018"]


async def test_find_vehicle_without_a_baseline_returns_nothing(tmp_path: Path) -> None:
    result = await _find(tmp_path, None, {"query": "E90"})
    assert result.is_error is False
    assert result.structured_content["total_matches"] == 0
    assert result.structured_content["index"]["built_at"] is None


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"limit": 0}, "limit must be between 1 and 100, got 0."),
        ({"limit": 101}, "limit must be between 1 and 100, got 101."),
        ({"brand": "audi"}, "Unknown brand 'audi'; use one of: bmw, mini, motorrad, rolls-royce."),
    ],
)
async def test_find_vehicle_rejects_bad_arguments(
    tmp_path: Path, arguments: dict[str, Any], message: str
) -> None:
    result = await _find(tmp_path, [E90], arguments)
    assert result.is_error is True
    assert result.content[0].text.endswith(message)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_find_vehicle.py -q`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'realoem_mcp.tools.vehicles'`
(`1 error`).

- [ ] **Step 3: Write the tool module (find only)**

Create `server/src/realoem_mcp/tools/vehicles.py`:

```python
"""F6 vehicle index tools: find_vehicle (local only) and update_vehicle_index (ARD section 5.11)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, RealOemError
from realoem_mcp.models.vehicles import VehicleSearchResult
from realoem_mcp.services import Services
from realoem_mcp.vehicle_index import VehicleIndex

INDEX_KEY = "vehicle_index"  # services.extras key
MAX_LIMIT = 100


def get_index(services: Services) -> VehicleIndex:
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands)
        services.extras[INDEX_KEY] = index
    return index


def search_index(
    services: Services,
    *,
    query: str | None,
    brand: str | None,
    series: str | None,
    year: int | None,
    market: str | None,
    type_code: str | None,
    include_unlinked: bool,
    limit: int,
) -> VehicleSearchResult:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit must be between 1 and {MAX_LIMIT}, got {limit}.")
    brand_ids = sorted(b.id for b in services.brands)
    if brand is not None and brand.lower() not in brand_ids:
        raise InvalidInput(f"Unknown brand {brand!r}; use one of: {', '.join(brand_ids)}.")
    index = get_index(services)
    total, vehicles = index.search(
        query=query,
        brand=brand,
        series=series,
        year=year,
        market=market,
        type_code=type_code,
        include_unlinked=include_unlinked,
        limit=limit,
    )
    return VehicleSearchResult(total_matches=total, vehicles=vehicles, index=index.meta())


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def find_vehicle(
        query: str | None = None,
        brand: str | None = None,
        series: str | None = None,
        year: int | None = None,
        market: str | None = None,
        type_code: str | None = None,
        include_unlinked: bool = False,
        limit: int = 25,
    ) -> VehicleSearchResult:
        """Find BMW, MINI, Rolls-Royce and BMW Motorrad vehicles in the local vehicle index.

        Use this first whenever the user names a vehicle ("2019 R 1250 GS", "E90 325i USA") to get
        vehicle ids for list_part_groups and the other catalog tools. Makes no request to RealOEM.
        query: words that must all appear (case-insensitive substrings) in the series label, series
        code, model name or type code. brand: bmw, mini, rolls-royce or motorrad. series (e.g. E90),
        market (e.g. USA) and type_code (e.g. VB13) match exactly, ignoring case. year: vehicles in
        production that year. include_unlinked: also return the few rows RealOEM lists without a
        vehicle id. limit: 1-100 vehicles (default 25).
        Returns total_matches, vehicles (vehicle id, series, model, type code, body, market,
        production_from/production_to as YYYY-MM) and index (built_at, baseline_total, local_rows,
        last_update_at). Vehicle ids carry the production START month; for a specific car's build
        month use select_vehicle or decode_vin. End dates of vehicles still in production are as
        of built_at. If nothing matches, call update_vehicle_index and search again.
        """
        try:
            return search_index(
                services,
                query=query,
                brand=brand,
                series=series,
                year=year,
                market=market,
                type_code=type_code,
                include_unlinked=include_unlinked,
                limit=limit,
            )
        except RealOemError as err:
            raise ToolError(err.message) from err
```

`build_server` discovers the module by itself (AD15); `server.py` is not edited. The index is
opened on the first call and kept in `services.extras["vehicle_index"]`, so `Services.aclose()`
closes it (the test checks both).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/tools/test_find_vehicle.py tests/tools/test_server.py -q`
Expected: PASS (`test_find_vehicle.py`: `7 passed`; `test_server.py` still passes, now also checking
that `find_vehicle` has a docstring).

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/src/realoem_mcp/tools/vehicles.py server/tests/tools/test_find_vehicle.py
git commit -m "feat(vehicles): add find_vehicle tool over the local index" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

### Task 7: `update_vehicle_index`

ARD §5.11 algorithm (steps 1–4). The tests use the real page 165 for the one-request cases and
`SyntheticIndex` for multi-page scans:

| Test | Index | RealOEM | Pages requested | Status |
|---|---|---|---|---|
| up to date | 8200 filler + all 18 rows of p165 | real p165 | 165 | `up_to_date` |
| last page | 8200 filler + first 15 rows of p165 | real p165 | 165 | `updated` (3) |
| scan back | first 95 of 120 | 120 rows | 2, 3 | `updated` (25) |
| no baseline | nothing installed | 120 rows | none | `drift` |
| page limit, resumed | first 100 of 300; `max_pages=3` twice | 300 rows | 2, 6, 5 / 4, 3, 2 | `partial` (100) then `updated` (100) |
| page limit, nothing found | first 100 of 300; `max_pages=1` | 300 rows | 2 | `partial` (0), resume at page 6 |
| back-dated insert | 120 | 121 rows, new one in 2001 | 3 | `drift` (0 added) |
| one replaced, twice | 150 | 150 rows, last one replaced | 3 / 3 | `drift` (1 added), then `drift` (probe stays on page 3) |
| probe past the end (no table / empty table) | 151 | 150 rows | 4, 1 | `drift` |

**Files:**
- Modify: `server/src/realoem_mcp/tools/vehicles.py` (replaced as a whole below)
- Test: `server/tests/tools/test_update_vehicle_index.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_update_vehicle_index.py`:

```python
"""update_vehicle_index via the in-memory MCP client (ARD section 5.11 update algorithm)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.parsers.vehicles import parse_vehicles
from realoem_mcp.server import build_server
from realoem_mcp.tools.vehicles import get_index
from tests.harness import BRANDS_DIR, FixtureTransport, Route, load_fixture, url
from tests.vehicle_data import SyntheticIndex, numbered, vehicle
from tests.vehicle_env import vehicle_services

pytestmark = pytest.mark.anyio

P165 = url("vehicles", page="165", sort="year")
P165_ROWS = parse_vehicles(
    load_fixture("vehicles/sort_year_p165.html"), url=P165, brands=BrandRegistry.load(BRANDS_DIR)
).rows
# 8200 undated (unlinked) rows stand in for pages 1-164 of the real index.
FILLER = [vehicle(f"F{i:04d}", start=None) for i in range(8200)]


@dataclass
class Run:
    updates: list[dict[str, Any]]  # structured result of each update_vehicle_index call
    found: dict[str, Any]  # find_vehicle over linked rows afterwards
    resume: tuple[str | None, int] | None  # stored resume point afterwards


def _page_numbers(transport: FixtureTransport | SyntheticIndex) -> list[str]:
    return [request.url.params["page"] for request in transport.requests]


async def _run(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    baseline: Sequence[IndexedVehicle] | None,
    *calls: dict[str, Any],
) -> Run:
    """Call update_vehicle_index once per argument dict (once with {} by default)."""
    async with (
        vehicle_services(tmp_path, transport, baseline=baseline) as services,
        Client(build_server(services)) as client,
    ):
        updates = []
        for arguments in calls or ({},):
            result = await client.call_tool("update_vehicle_index", arguments)
            assert result.is_error is False, result.content
            updates.append(result.structured_content)
        found = await client.call_tool("find_vehicle", {"limit": 100})
        resume = get_index(services).resume_point()
    return Run(updates, found.structured_content, resume)


async def _error(tmp_path: Path, transport: FixtureTransport, arguments: dict) -> CallToolResult:
    async with (
        vehicle_services(tmp_path, transport, baseline=numbered(1)) as services,
        Client(build_server(services)) as client,
    ):
        return await client.call_tool("update_vehicle_index", arguments)


async def test_up_to_date_costs_one_request(tmp_path: Path) -> None:
    transport = FixtureTransport({P165: "vehicles/sort_year_p165.html"})
    (data,) = (await _run(tmp_path, transport, [*FILLER, *P165_ROWS])).updates
    assert {k: data[k] for k in ("status", "added", "remote_total", "local_total")} == {
        "status": "up_to_date",
        "added": [],
        "remote_total": 8218,
        "local_total": 8218,
    }
    assert (data["pages_fetched"], data["requests_made"], data["from_cache"]) == (1, 1, False)
    assert data["source_urls"] == [P165]
    assert data["message"] == "The vehicle index is up to date (8218 vehicles on RealOEM)."
    assert _page_numbers(transport) == ["165"]


async def test_new_vehicles_on_the_last_page_are_added(tmp_path: Path) -> None:
    transport = FixtureTransport({P165: "vehicles/sort_year_p165.html"})
    run = await _run(tmp_path, transport, [*FILLER, *P165_ROWS[:-3]])  # 3 vehicles are new
    (data,) = run.updates
    assert (data["status"], data["remote_total"], data["local_total"]) == ("updated", 8218, 8218)
    assert [v["key"] for v in data["added"]] == [
        "16GG-IDN-03-2025",
        "17GG-IND-03-2025",
        "64GG-THA-03-2025",
    ]
    assert data["added"][2] == P165_ROWS[-1].model_dump(mode="json")
    assert data["message"] == "Added 3 new vehicle(s); the index now has all 8218."
    assert (data["pages_fetched"], data["requests_made"]) == (1, 1)
    local = [v["key"] for v in run.found["vehicles"] if v["source"] == "local"]
    assert sorted(local) == ["16GG-IDN-03-2025", "17GG-IND-03-2025", "64GG-THA-03-2025"]
    assert run.found["index"]["local_rows"] == 3
    assert run.found["index"]["last_update_at"] is not None


async def test_scan_goes_back_until_pages_are_older_than_the_index(tmp_path: Path) -> None:
    remote = numbered(120)  # pages 1-3; the index has the first 95 rows
    transport = SyntheticIndex(remote)
    (data,) = (await _run(tmp_path, transport, remote[:95])).updates
    assert data["status"] == "updated"
    assert [v["key"] for v in data["added"]] == [row.key for row in remote[95:]]
    # probe = page 2 (ceil(95/50)); scan: page 3, then page 2 again from memory, which starts
    # before the index's newest production month, so the scan stops.
    assert _page_numbers(transport) == ["2", "3"]
    assert (data["pages_fetched"], data["requests_made"], data["local_total"]) == (2, 2, 120)
    assert data["source_urls"] == [
        url("vehicles", page="2", sort="year"),
        url("vehicles", page="3", sort="year"),
    ]


async def test_without_a_baseline_nothing_is_requested(tmp_path: Path) -> None:
    transport = SyntheticIndex(numbered(120))
    (data,) = (await _run(tmp_path, transport, None)).updates
    assert (data["status"], data["added"], data["remote_total"], data["local_total"]) == (
        "drift",
        [],
        0,
        0,
    )
    assert (data["requests_made"], data["pages_fetched"], data["source_urls"]) == (0, 0, [])
    assert data["message"] == (
        "No vehicle index baseline is installed; the maintainer must run "
        "scripts/rebuild_vehicle_index.py."
    )
    assert transport.requests == []


async def test_page_limit_gives_a_partial_update_that_resumes(tmp_path: Path) -> None:
    remote = numbered(300)  # 6 pages; the index has the first 100 rows
    transport = SyntheticIndex(remote)
    run = await _run(tmp_path, transport, remote[:100], {"max_pages": 3}, {"max_pages": 3})
    first, second = run.updates
    assert first["status"] == "partial"
    assert [v["key"] for v in first["added"]] == [row.key for row in remote[200:]]
    assert (first["remote_total"], first["local_total"], first["pages_fetched"]) == (300, 200, 3)
    assert first["message"] == (
        "Added 100 of 200 new vehicles before reaching max_pages=3. "
        "Call update_vehicle_index again to continue from page 4."
    )
    # The second call probes page 4 (ceil(200/50)), resumes the scan there with the old
    # newest start month, and stops at page 2, which starts before it.
    assert second["status"] == "updated"
    assert [v["key"] for v in second["added"]] == [row.key for row in remote[100:200]]
    assert _page_numbers(transport) == ["2", "6", "5", "4", "3", "2"]
    assert (second["local_total"], run.resume) == (300, None)


async def test_partial_without_new_vehicles_suggests_more_pages(tmp_path: Path) -> None:
    remote = numbered(300)
    transport = SyntheticIndex(remote)
    run = await _run(tmp_path, transport, remote[:100], {"max_pages": 1})
    (data,) = run.updates
    assert (data["status"], data["added"], data["pages_fetched"]) == ("partial", [], 1)
    assert data["message"] == (
        "No new vehicles in the 1 page(s) allowed by max_pages=1; 200 are still missing. "
        "Call update_vehicle_index again with a larger max_pages (up to 10) to continue from "
        "page 6."
    )
    assert run.resume == (remote[99].production_from, 6)


async def test_a_back_dated_insert_is_reported_as_drift(tmp_path: Path) -> None:
    baseline = numbered(120)
    inserted = vehicle("X001", start="2001-06", end="2030-12")
    transport = SyntheticIndex(sorted([*baseline, inserted], key=lambda v: v.production_from))
    (data,) = (await _run(tmp_path, transport, baseline)).updates
    assert (data["status"], data["added"], data["remote_total"]) == ("drift", [], 121)
    assert _page_numbers(transport) == ["3"]
    assert "The maintainer should rebuild the baseline" in data["message"]


async def test_a_replaced_row_is_drift_and_the_next_probe_stays_in_range(tmp_path: Path) -> None:
    baseline = numbered(150)
    replaced = vehicle("X149", start=baseline[-1].production_from, end="2030-12")
    transport = SyntheticIndex([*baseline[:-1], replaced])  # still exactly 150 rows
    first, second = (await _run(tmp_path, transport, baseline, {}, {})).updates
    assert (first["status"], [v["key"] for v in first["added"]]) == ("drift", [replaced.key])
    assert (first["remote_total"], first["local_total"]) == (150, 151)
    # 151 local rows would probe page 4, past RealOEM's end; the stored remote total keeps the
    # probe on page 3.
    assert (second["status"], second["added"], second["pages_fetched"]) == ("drift", [], 1)
    assert _page_numbers(transport) == ["3", "3"]


EMPTY_TABLE = '<html><body><table id="vi-table"><tbody></tbody></table></body></html>'


@pytest.mark.parametrize("past_end_html", [None, EMPTY_TABLE], ids=["no-table", "empty-table"])
async def test_a_probe_past_the_end_reads_page_one_and_reports_drift(
    tmp_path: Path, past_end_html: str | None
) -> None:
    baseline = numbered(151)
    transport = SyntheticIndex(baseline[:150])  # one vehicle removed on RealOEM
    transport.past_end_html = past_end_html
    (data,) = (await _run(tmp_path, transport, baseline)).updates
    assert (data["status"], data["added"], data["remote_total"], data["local_total"]) == (
        "drift",
        [],
        150,
        151,
    )
    assert _page_numbers(transport) == ["4", "1"]
    assert (data["requests_made"], data["pages_fetched"]) == (2, 2)
    assert data["message"].startswith("RealOEM lists 150 vehicles, fewer than the 151 in the index")


@pytest.mark.parametrize("max_pages", [0, 11])
async def test_max_pages_is_validated_before_any_request(tmp_path: Path, max_pages: int) -> None:
    transport = FixtureTransport({})
    result = await _error(tmp_path, transport, {"max_pages": max_pages})
    assert result.is_error is True
    assert result.content[0].text.endswith(f"max_pages must be between 1 and 10, got {max_pages}.")
    assert transport.requests == []


async def test_an_unparseable_page_is_not_kept_in_the_cache(tmp_path: Path) -> None:
    page_one = url("vehicles", page="1", sort="year")
    transport = FixtureTransport({page_one: Route("common/partgrp_e90_325i.html")})
    async with (
        vehicle_services(tmp_path, transport, baseline=numbered(1)) as services,
        Client(build_server(services)) as client,
    ):
        first = await client.call_tool("update_vehicle_index", {})
        assert services.cache.get(page_one) is None
        second = await client.call_tool("update_vehicle_index", {})
    assert first.is_error is True and second.is_error is True
    assert "vehicles page did not have the expected structure" in first.content[0].text
    assert len(transport.requests) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_update_vehicle_index.py -q`
Expected: FAIL — `13 failed`; every test reports `Unknown tool: update_vehicle_index` (the tool
does not exist yet).

- [ ] **Step 3: Add the update tool**

Replace the whole of `server/src/realoem_mcp/tools/vehicles.py` with:

```python
"""F6 vehicle index tools: find_vehicle (local only) and update_vehicle_index (ARD section 5.11)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.vehicles import (
    IndexedVehicle,
    VehicleIndexPage,
    VehicleIndexUpdateResult,
    VehicleSearchResult,
)
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.vehicles import PAGE_SIZE, has_vehicle_rows, parse_vehicles
from realoem_mcp.services import Services
from realoem_mcp.vehicle_index import VehicleIndex, sort_key

INDEX_KEY = "vehicle_index"  # services.extras key
MAX_PAGES_LIMIT = 10
MAX_LIMIT = 100
REBUILD_HINT = "The maintainer should rebuild the baseline with scripts/rebuild_vehicle_index.py."
NO_BASELINE = (
    "No vehicle index baseline is installed; the maintainer must run "
    "scripts/rebuild_vehicle_index.py."
)


def get_index(services: Services) -> VehicleIndex:
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands)
        services.extras[INDEX_KEY] = index
    return index


async def _fetch(services: Services, number: int) -> Page:
    """vehicles?page=<number>&sort=year, always from the network."""
    return await services.client.fetch(
        PageType.VEHICLES, "vehicles", {"page": str(number), "sort": "year"}, refresh=True
    )


def _parse(services: Services, page: Page) -> VehicleIndexPage:
    try:
        return parse_vehicles(page.html, url=page.url, brands=services.brands)
    except LayoutChanged:
        services.cache.shorten(page.url, timedelta(0))  # never keep an unparseable page cached
        raise


async def fetch_vehicles_page(services: Services, number: int) -> tuple[VehicleIndexPage, Page]:
    """Fetch and parse vehicles?page=<number>&sort=year, always from the network."""
    page = await _fetch(services, number)
    return _parse(services, page), page


def search_index(
    services: Services,
    *,
    query: str | None,
    brand: str | None,
    series: str | None,
    year: int | None,
    market: str | None,
    type_code: str | None,
    include_unlinked: bool,
    limit: int,
) -> VehicleSearchResult:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit must be between 1 and {MAX_LIMIT}, got {limit}.")
    brand_ids = sorted(b.id for b in services.brands)
    if brand is not None and brand.lower() not in brand_ids:
        raise InvalidInput(f"Unknown brand {brand!r}; use one of: {', '.join(brand_ids)}.")
    index = get_index(services)
    total, vehicles = index.search(
        query=query,
        brand=brand,
        series=series,
        year=year,
        market=market,
        type_code=type_code,
        include_unlinked=include_unlinked,
        limit=limit,
    )
    return VehicleSearchResult(total_matches=total, vehicles=vehicles, index=index.meta())


def _result(pages: list[Page], **fields: Any) -> VehicleIndexUpdateResult:
    if pages:
        return VehicleIndexUpdateResult.from_pages(pages, pages_fetched=len(pages), **fields)
    return VehicleIndexUpdateResult(  # no request was made
        source_urls=[],
        fetched_at=datetime.now(UTC),
        from_cache=True,
        requests_made=0,
        pages_fetched=0,
        **fields,
    )


async def update_index(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """ARD section 5.11 update algorithm: probe one page, then scan back from the last page
    (or from where an interrupted scan stopped)."""
    if not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise InvalidInput(f"max_pages must be between 1 and {MAX_PAGES_LIMIT}, got {max_pages}.")
    index = get_index(services)
    local_total = index.count()
    if index.meta().built_at is None or local_total == 0:
        return _result(
            [],
            status="drift",
            added=[],
            remote_total=0,
            local_total=local_total,
            message=NO_BASELINE,
        )
    known, resume = index.keys(), index.resume_point()
    max_start = resume[0] if resume else index.max_prod_start()
    parsed: dict[int, VehicleIndexPage] = {}
    pages: list[Page] = []
    new: dict[str, IndexedVehicle] = {}

    def keep(result: VehicleIndexPage, page: Page) -> VehicleIndexPage:
        parsed[result.page] = result  # keyed by the page RealOEM says it served
        pages.append(page)
        new.update((row.key, row) for row in result.rows if row.key not in known)
        return result

    # Probe where the index ends, but never past RealOEM's last known end.
    probe_total = min(local_total, index.last_remote_total() or local_total)
    probe_number = max(1, math.ceil(probe_total / PAGE_SIZE))
    probe_page = await _fetch(services, probe_number)
    if probe_number > 1 and not has_vehicle_rows(probe_page.html):  # past RealOEM's end
        services.cache.shorten(probe_page.url, timedelta(0))
        first, first_page = await fetch_vehicles_page(services, 1)
        index.record_check(remote_total=first.total, resume=None)
        return _result(
            [probe_page, first_page],
            status="drift",
            added=[],
            remote_total=first.total,
            local_total=local_total,
            message=f"RealOEM lists {first.total} vehicles, fewer than the {local_total} in the "
            f"index (vehicles were removed or merged). {REBUILD_HINT}",
        )
    probe = keep(_parse(services, probe_page), probe_page)
    remote_total = probe.total
    stopped_at: int | None = None  # next page to read when max_pages ran out
    if remote_total != local_total or new:
        number = min(resume[1], probe.last_page) if resume else probe.last_page
        while True:
            current = parsed.get(number)
            if current is None:
                if len(pages) >= max_pages:
                    stopped_at = number
                    break
                current = keep(*await fetch_vehicles_page(services, number))
            first_start = current.rows[0].production_from if current.rows else None
            older = first_start is None or (max_start is not None and first_start < max_start)
            if number <= 1 or older:
                break
            number -= 1
    added = sorted(new.values(), key=sort_key)
    index.add_local(added)
    expected = remote_total - local_total
    resume_point = None
    if remote_total == local_total and not added:
        status = "up_to_date"
        message = f"The vehicle index is up to date ({remote_total} vehicles on RealOEM)."
    elif len(added) == expected:
        status = "updated"
        message = f"Added {len(added)} new vehicle(s); the index now has all {remote_total}."
    elif len(added) < expected and stopped_at is not None:
        status = "partial"
        resume_point = (max_start, stopped_at)
        if added:
            message = (
                f"Added {len(added)} of {expected} new vehicles before reaching max_pages="
                f"{max_pages}. Call update_vehicle_index again to continue from page "
                f"{stopped_at}."
            )
        else:
            message = (
                f"No new vehicles in the {len(pages)} page(s) allowed by max_pages={max_pages}; "
                f"{expected} are still missing. Call update_vehicle_index again with a larger "
                f"max_pages (up to {MAX_PAGES_LIMIT}) to continue from page {stopped_at}."
            )
    else:
        status = "drift"
        message = (
            f"RealOEM lists {remote_total} vehicles and the index had {local_total}; "
            f"{len(added)} new vehicle(s) were added, but the difference is not explained by new "
            f"vehicles at the end of the list (vehicles were back-dated, removed or changed). "
            f"{REBUILD_HINT}"
        )
    index.record_check(remote_total=remote_total, resume=resume_point)
    return _result(
        pages,
        status=status,
        added=added,
        remote_total=remote_total,
        local_total=index.count(),
        message=message,
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def find_vehicle(
        query: str | None = None,
        brand: str | None = None,
        series: str | None = None,
        year: int | None = None,
        market: str | None = None,
        type_code: str | None = None,
        include_unlinked: bool = False,
        limit: int = 25,
    ) -> VehicleSearchResult:
        """Find BMW, MINI, Rolls-Royce and BMW Motorrad vehicles in the local vehicle index.

        Use this first whenever the user names a vehicle ("2019 R 1250 GS", "E90 325i USA") to get
        vehicle ids for list_part_groups and the other catalog tools. Makes no request to RealOEM.
        query: words that must all appear (case-insensitive substrings) in the series label, series
        code, model name or type code. brand: bmw, mini, rolls-royce or motorrad. series (e.g. E90),
        market (e.g. USA) and type_code (e.g. VB13) match exactly, ignoring case. year: vehicles in
        production that year. include_unlinked: also return the few rows RealOEM lists without a
        vehicle id. limit: 1-100 vehicles (default 25).
        Returns total_matches, vehicles (vehicle id, series, model, type code, body, market,
        production_from/production_to as YYYY-MM) and index (built_at, baseline_total, local_rows,
        last_update_at). Vehicle ids carry the production START month; for a specific car's build
        month use select_vehicle or decode_vin. End dates of vehicles still in production are as
        of built_at. If nothing matches, call update_vehicle_index and search again.
        """
        try:
            return search_index(
                services,
                query=query,
                brand=brand,
                series=series,
                year=year,
                market=market,
                type_code=type_code,
                include_unlinked=include_unlinked,
                limit=limit,
            )
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def update_vehicle_index(max_pages: int = 5) -> VehicleIndexUpdateResult:
        """Add vehicles RealOEM listed since the local vehicle index was built.

        Use when find_vehicle does not find a vehicle the user named, or when the user asks to
        update the vehicle list. Fetches RealOEM's vehicles index sorted by year: one request when
        nothing is new, otherwise pages from the end backwards: at most max_pages requests
        (1-10, default 5), plus one to read the total when the local index is larger than
        RealOEM's. Returns status (up_to_date; updated; partial = page limit reached, call again
        to continue where it stopped; drift = the maintainer should rebuild the baseline, also
        returned without any request when no baseline is installed), added (the new vehicles),
        remote_total, local_total, pages_fetched and message. Never downloads the whole index.
        """
        try:
            return await update_index(services, max_pages)
        except RealOemError as err:
            raise ToolError(err.message) from err
```

Compared with Task 6 this adds the imports and constants it needs, `_fetch` / `_parse` /
`fetch_vehicles_page` (the last one is also used by the rebuild script), `_result`, `update_index`
and the `update_vehicle_index` tool; `get_index`, `search_index` and `find_vehicle` are unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --directory server pytest tests/tools -q`
Expected: PASS; `tests/tools/test_update_vehicle_index.py` alone gives `13 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/src/realoem_mcp/tools/vehicles.py server/tests/tools/test_update_vehicle_index.py
git commit -m "feat(vehicles): add update_vehicle_index with the incremental update algorithm" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

## Chunk 4: Rebuild script, skill and baseline

### Task 8: Maintainer rebuild script

**Files:**
- Create: `server/scripts/rebuild_vehicle_index.py`
- Test: `server/tests/unit/test_rebuild_vehicle_index.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_rebuild_vehicle_index.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_rebuild_vehicle_index.py -q`
Expected: FAIL — collection error `ImportError: cannot import name 'rebuild_vehicle_index' from
'scripts'` (`1 error`).

- [ ] **Step 3: Write the script**

Create `server/scripts/rebuild_vehicle_index.py`:

```python
"""MAINTAINER ONLY: rebuild the committed vehicle index baseline from RealOEM (PRD F6.1, F6.6).

Fetches every page of /bmw/enUS/vehicles?sort=year (about 165 pages plus one re-check of the last
page, about 6 minutes at the normal 2-second rate limit) through RealOemClient, checks each page,
and writes brands/<brand>/vehicles.csv plus brands/vehicles.meta.toml. Never run this from a tool
or in CI; run it once per catalog release, after the project owner agreed to it.

Usage (from server/):
    uv run python scripts/rebuild_vehicle_index.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.services import Services, create_services
from realoem_mcp.tools.vehicles import fetch_vehicles_page
from realoem_mcp.vehicle_index import write_baseline

MAX_ATTEMPTS = 3


class RebuildError(Exception):
    """The index could not be read consistently; nothing was written."""


class _IndexChanged(Exception):
    """RealOEM's index changed during the crawl (total or last page)."""


@dataclass(frozen=True)
class RebuildSummary:
    total: int
    pages: int
    requests: int
    attempts: int
    per_brand: dict[str, int]
    unlinked: int
    built_at: date

    def lines(self) -> list[str]:
        brands = ", ".join(f"{brand} {count}" for brand, count in sorted(self.per_brand.items()))
        return [
            f"vehicles: {self.total} ({self.unlinked} without a vehicle id)",
            f"pages: {self.pages}, requests: {self.requests}, attempts: {self.attempts}",
            f"per brand: {brands}",
            f"built_at: {self.built_at}",
        ]


async def crawl(services: Services) -> tuple[list[IndexedVehicle], int, int]:
    """All rows in sort=year order, the total and the number of pages; raises _IndexChanged."""
    rows: list[IndexedVehicle] = []
    last_keys: list[str] = []
    number, last_page, total = 1, 1, None
    while number <= last_page:
        page, _ = await fetch_vehicles_page(services, number)
        if page.page != number:
            raise RebuildError(f"asked for page {number} but RealOEM returned page {page.page}")
        if total is None:
            total, last_page = page.total, page.last_page
        elif page.total != total:
            raise _IndexChanged(f"total changed from {total} to {page.total} on page {number}")
        rows.extend(page.rows)
        last_keys = [row.key for row in page.rows]
        number += 1
    # Rows inserted or removed mid-crawl shift later pages; the last page shows it.
    check, _ = await fetch_vehicles_page(services, last_page)
    if check.total != total or [row.key for row in check.rows] != last_keys:
        raise _IndexChanged(f"page {last_page} changed during the crawl")
    if len(rows) != total:
        raise RebuildError(f"read {len(rows)} rows but RealOEM reports {total} vehicles")
    duplicates = sorted(key for key, n in Counter(row.key for row in rows).items() if n > 1)
    if duplicates:
        raise RebuildError(f"{len(duplicates)} duplicate row keys: {', '.join(duplicates)}")
    return rows, total, last_page


async def rebuild(
    settings: Settings,
    *,
    built_at: date,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> RebuildSummary:
    """Crawl, restarting when the index changes, then write the baseline into brands_dir."""
    services = create_services(settings, transport=transport, clock=clock, sleep=sleep)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                rows, total, pages = await crawl(services)
            except _IndexChanged as change:
                print(f"attempt {attempt}: {change}; restarting", file=sys.stderr)
                continue
            brand_ids = [brand.id for brand in services.brands]
            per_brand = write_baseline(
                settings.brands_dir, brand_ids, rows, total=total, built_at=built_at
            )
            return RebuildSummary(
                total=total,
                pages=pages,
                requests=services.client.requests_made,
                attempts=attempt,
                per_brand=per_brand,
                unlinked=sum(1 for row in rows if row.vehicle is None),
                built_at=built_at,
            )
        raise RebuildError(f"RealOEM's vehicles index kept changing ({max_attempts} attempts)")
    finally:
        await services.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MAINTAINER ONLY: rebuild brands/*/vehicles.csv from RealOEM (~166 requests)."
    )
    parser.parse_args(argv)
    settings = Settings.from_env()
    print(
        f"Fetching RealOEM's vehicles index into {settings.brands_dir} "
        f"({settings.min_interval_s:g} s between requests)...",
        file=sys.stderr,
    )
    try:
        summary = asyncio.run(rebuild(settings, built_at=datetime.now(UTC).date()))
    except (RealOemError, RebuildError) as err:
        print(f"rebuild failed, nothing written: {err}", file=sys.stderr)
        return 1
    for line in summary.lines():
        print(line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The script goes through `create_services`, so it uses the normal client: honest user agent,
`ro_ui=v2` cookie, `REALOEM_MIN_INTERVAL` (default 2 s, never below 1 s) and challenge detection.
It writes into `Settings.brands_dir` (the repository's `brands/` unless `REALOEM_BRANDS_DIR` is
set) only after a complete, consistent crawl.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_rebuild_vehicle_index.py -q`
Expected: `8 passed`

- [ ] **Step 5: Lint and commit**

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/scripts/rebuild_vehicle_index.py server/tests/unit/test_rebuild_vehicle_index.py
git commit -m "feat(vehicles): add maintainer-only vehicle index rebuild script" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

### Task 9: `vehicle-index` skill

**Files:**
- Create: `skills/vehicle-index/SKILL.md`
- Test: `server/tests/unit/test_skill_vehicle_index.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_skill_vehicle_index.py`:

```python
"""skills/vehicle-index/SKILL.md: trigger-oriented frontmatter and the facts PRD F6.5 requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "vehicle-index" / "SKILL.md"


def _read() -> tuple[dict[str, str], str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    head, sep, body = text[4:].partition("\n---\n")
    assert sep, "frontmatter is not closed with ---"
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    return meta, body


def test_frontmatter_names_the_skill_and_its_triggers() -> None:
    meta, _ = _read()
    assert set(meta) == {"name", "description"}
    assert meta["name"] == "vehicle-index"
    for trigger in ("2019 R 1250 GS", "E90 325i", "type code", "vehicle id", "update the vehicle"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_the_workflow_and_its_limits() -> None:
    _, body = _read()
    text = " ".join(body.split())  # line breaks in the Markdown do not matter
    for phrase in (
        "Call `find_vehicle` first",
        "call `update_vehicle_index`, then call `find_vehicle` again",
        "It continues where the previous call stopped",
        "no vehicle index baseline is installed",
        "https://www.realoem.com/bmw/enUS/partgrp?id=<url-encoded vehicle_id>",
        "`up_to_date`",
        "`updated`",
        "`partial`",
        "`drift`",
        "production START month",
        '"as of `built_at`"',
        "`select_vehicle`",
        "`decode_vin`",
        "`list_part_groups(vehicle_id)`",
        "Never fetch RealOEM pages directly",
    ):
        assert phrase in text, phrase
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_skill_vehicle_index.py -q`
Expected: FAIL — `FileNotFoundError` for `skills/vehicle-index/SKILL.md` (`2 failed`).

- [ ] **Step 3: Write the skill**

Create `skills/vehicle-index/SKILL.md`:

````markdown
---
name: vehicle-index
description: Find a BMW, MINI, Rolls-Royce or BMW Motorrad vehicle in RealOEM's catalog by name, series, year, market or type code without clicking through the model cascade. Use when the user names a vehicle ("find a 2019 R 1250 GS", "E90 325i USA", "which markets had the MINI R56 Cooper S", "vehicles with type code VB13"), needs a vehicle id for parts diagrams, or asks to update the vehicle list.
---

# Vehicle index

A local list of every vehicle in RealOEM's vehicles index (about 8,200), shipped with the plugin
and stored on this computer. Searching it is free: `find_vehicle` never contacts RealOEM.

## Steps

1. Call `find_vehicle` first. Put the words the user used in `query` (series code, model, type
   code: `"E90 325i"`, `"R 1250 GS"`, `"VB13"`); all words must match. Narrow with `brand`
   (`bmw`, `mini`, `rolls-royce`, `motorrad`), `series` (e.g. `E90`), `year` (in production that
   year), `market` (e.g. `USA`, `EUR`) or `type_code`. Raise `limit` (up to 100) only when the
   user wants a long list; `total_matches` tells how many there are.
2. If nothing matches, retry once with fewer or different words (e.g. only the series code, or
   the model without the body style).
3. Still not found, or the user asks to update the vehicle list: call `update_vehicle_index`, then
   call `find_vehicle` again with the same arguments.
   - `up_to_date`: RealOEM has no vehicles the index lacks; the vehicle is not in RealOEM under
     those words.
   - `updated`: new vehicles were added (`added`); search again.
   - `partial`: the page limit (`max_pages`, default 5) stopped the update; the vehicles found so
     far were added. Search again; if the vehicle is still missing, call `update_vehicle_index`
     again (with a larger `max_pages`, up to 10, when `added` was empty). It continues where the
     previous call stopped.
   - `drift`: RealOEM changed older entries. Report the `message`: the maintainer should rebuild
     the index. The vehicles found so far were still added.
   Call `update_vehicle_index` at most once per conversation unless it returned `partial` or the
   user asks again.
   If `index.built_at` is null, no vehicle index baseline is installed: `update_vehicle_index`
   then returns `drift` without contacting RealOEM. Say the vehicle list is not installed yet and
   find the vehicle with `select_vehicle` (the model cascade) or `decode_vin` instead.
4. Several matches: show a short table (model, series, body, market, production range, vehicle
   id) and ask which one the user means, or pick by the user's market and year.

## Explaining the results

- **Vehicle ids carry the production START month** of that model (`VB13-USA-10-2005-...` means
  production started 10/2005), not the build month of the user's car. RealOEM filters parts lists
  by the month in the id. For a specific car's build month, use `select_vehicle` with `prod`
  (month `YYYYMM00`) or `decode_vin` with the car's VIN.
- **End dates are "as of `built_at`"**: for vehicles still in production RealOEM rewrites the end
  date with each catalog release, so say "production 03/2025 - 04/2025 (as of <index.built_at>)"
  and do not claim the model ended then.
- Link each vehicle to RealOEM as
  `https://www.realoem.com/bmw/enUS/partgrp?id=<url-encoded vehicle_id>` (or use the
  `source_urls` of `list_part_groups` once you have called it).
- `model` in `vehicle` comes from the vehicle id (underscores for spaces); prefer `model_name`
  for display.
- Rows without a vehicle id (only with `include_unlinked=true`) cannot be opened in RealOEM's
  parts catalog; say so if the user asks about one.

## Next steps

`find_vehicle` results feed the diagram tools: pass `vehicle.vehicle_id` to
`list_part_groups(vehicle_id)` to list the vehicle's main groups, then `list_diagrams` and
`get_diagram_parts`, if those tools are available. For fitment questions pass the same id to
`check_fitment`.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Never try to download the whole vehicle list; `update_vehicle_index` only adds new vehicles,
  and a full rebuild is a maintainer task (`scripts/rebuild_vehicle_index.py`).
- Brand notes: `brands/<brand>/README.md`.
````

The skill names the tools of feature C (`select_vehicle`, `list_part_groups`, `list_diagrams`,
`get_diagram_parts`), B (`decode_vin`) and D (`check_fitment`) by their short names only; nothing
in `skills/diagram-browse/` changes.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_skill_vehicle_index.py -q`
Expected: `2 passed`

- [ ] **Step 5: Validate the plugin and commit**

Run: `claude plugin validate . --strict`
Expected: validation passes. If `claude` is not on `PATH` (Windows desktop app installs), use
`"$APPDATA/Claude/claude-code/<version>/claude.exe" plugin validate . --strict`, or skip this check
and say so in the pull request.

```bash
uv run --directory server ruff check
uv run --directory server ruff format --check
git add skills/vehicle-index/SKILL.md server/tests/unit/test_skill_vehicle_index.py
git commit -m "feat(vehicles): add vehicle-index skill" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `All checks passed!` and `… files already formatted`.

### Task 10: Baseline guard test and opt-in live smoke test

The guard test is skipped until Task 11 commits the baseline; afterwards it proves that every CSV
has the right header and order, that the row count equals `total` in `vehicles.meta.toml`, and that
`VehicleIndex` loads all of it. The live test is deselected by default (`-m "not live"` in
`pyproject.toml`) and makes 2 requests when run on purpose: page 1 seeds a tmp index, then
`update_vehicle_index(max_pages=1)` probes page 1 again and stops (`partial`).

**Files:**
- Test: `server/tests/unit/test_committed_vehicle_baseline.py`
- Test: `server/tests/live/test_live_vehicles.py`

- [ ] **Step 1: Write the guard test**

Create `server/tests/unit/test_committed_vehicle_baseline.py`:

```python
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
```

- [ ] **Step 2: Write the live smoke test**

Create `server/tests/live/test_live_vehicles.py`:

```python
"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from realoem_mcp.tools.vehicles import fetch_vehicles_page
from tests.vehicle_env import install_baseline, settings_for

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_update_vehicle_index_live(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    services = create_services(settings)  # real client: honest user agent, 2 s spacing
    try:
        page_one, _ = await fetch_vehicles_page(services, 1)  # request 1: seed the index
        install_baseline(settings, page_one.rows)
        async with Client(build_server(services)) as client:
            # request 2: the probe is page 1 again (50 local rows); max_pages=1 stops the scan
            result = await client.call_tool("update_vehicle_index", {"max_pages": 1})
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert (data["status"], data["added"], data["pages_fetched"]) == ("partial", [], 1)
    assert data["remote_total"] == page_one.total > 8000
    assert data["requests_made"] == 1
```

Do **not** run it now (it would contact realoem.com). It runs only with
`REALOEM_LIVE=1 uv run --directory server pytest -m live tests/live/test_live_vehicles.py`.

- [ ] **Step 3: Run the offline checks**

```bash
uv run --directory server pytest tests/unit/test_committed_vehicle_baseline.py -q -rs
uv run --directory server pytest tests/live/test_live_vehicles.py -q
```

Expected: `1 skipped` with reason `no committed vehicle baseline yet` (there is no failing phase:
this guards data that does not exist yet; Task 11 Step 4 shows it passing), then
`1 deselected` for the live test.

- [ ] **Step 4: Full suite, lint and commit**

```bash
uv run --directory server pytest -q
uv run --directory server ruff check
uv run --directory server ruff format --check
git add server/tests/unit/test_committed_vehicle_baseline.py server/tests/live/test_live_vehicles.py
git commit -m "test(vehicles): guard the committed baseline and add a live smoke test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: baseline + `90 passed, 1 skipped` and deselected + 1; `All checks passed!`; formatted
files = baseline + 17.

### Task 11: Build and commit the baseline (MAINTAINER, LIVE NETWORK)

> **Implementer subagents: do not run anything in this task; stop and report back. The controller
> asks the maintainer and runs Steps 1–5 only after an explicit yes in chat.**
>
> **LIVE NETWORK — requires explicit go-ahead from the maintainer in chat before running.** This is
> the only step in this plan that contacts realoem.com: about 167 requests (165 pages, one re-check
> of the last page, and one capture of the page after it in Step 2), one every 2 seconds (about 6
> minutes), with the honest `RealOEM-Searcher/0.1.0` user
> agent. Without the go-ahead, skip this task and continue with Task 12 (the pull request then says
> the baseline will be added on this branch before merge). Never run it in CI, never loop it, never
> lower `REALOEM_MIN_INTERVAL`, and run it at most twice (one retry after a failure).

**Files:**
- Create (generated): `brands/bmw/vehicles.csv`, `brands/mini/vehicles.csv`,
  `brands/motorrad/vehicles.csv`, `brands/rolls-royce/vehicles.csv`, `brands/vehicles.meta.toml`

- [ ] **Step 1: Run the rebuild (after the go-ahead)**

Run: `uv run --directory server python scripts/rebuild_vehicle_index.py`

Expected (stderr; counts as of 2026-09-30 — RealOEM may have added vehicles since):

```
Fetching RealOEM's vehicles index into <repo>/brands (2 s between requests)...
vehicles: 8218 (51 without a vehicle id)
pages: 165, requests: 166, attempts: 1
per brand: bmw <n>, mini <n>, motorrad <n>, rolls-royce <n>
built_at: <today>
```

`attempts: 2` or `3` means RealOEM's index changed during the crawl and the script restarted; that
is fine. `requests` above `(pages + 1) × attempts` means the client retried (429/5xx). If it prints
`rebuild failed, nothing written: …`, stop: a `BotChallenge` means RealOEM is blocking automated
requests (do not retry; tell the maintainer); a `LayoutChanged` or other message means the page
structure or data changed (for duplicate keys the message lists every one); report it and commit
nothing.

- [ ] **Step 2: Inspect the output**

```bash
git status --short brands
cat brands/vehicles.meta.toml
head -3 brands/mini/vehicles.csv
wc -l brands/*/vehicles.csv
```

Expected: the five new files (no other change); `built_at = <today>`, `total = <n>`,
`source = "https://www.realoem.com/bmw/enUS/vehicles?sort=year"`; each CSV starts with the header
`key,vehicle_id,series_label,series_code,model_name,type_code,body,market,prod_start,prod_end`;
the line counts minus 4 headers add up to `total`; `motorrad` and `mini` are non-empty; the whole set
is about 1 MB.

Then capture, once, the page right after the last one (`pages` from Step 1 plus 1; 166 below), so
the markup RealOEM serves past the end of the index is on record for future parser work (the update
tool only relies on "no vehicle rows"). It is one more request under the same go-ahead, saved to
the git-ignored `.research-raw/vehicles/`; never commit it:

```bash
uv run --directory server python scripts/capture_page.py vehicles sort_year_past_end page=166 sort=year
```

Expected: `wrote …/.research-raw/vehicles/sort_year_past_end.html and ….headers`. Mention in the
pull request whether that page had a `table#vi-table`.

- [ ] **Step 3: Find a vehicle offline (PRD success criterion 5)**

```bash
uv run --directory server python -c "import tempfile, pathlib; from realoem_mcp.brands import BrandRegistry; from realoem_mcp.config import Settings; from realoem_mcp.vehicle_index import VehicleIndex; s = Settings(data_dir=pathlib.Path(tempfile.mkdtemp())); i = VehicleIndex.open(s, BrandRegistry.load(s.brands_dir)); print(i.search(query='R 1250 GS', year=2019, limit=3)); i.close()"
```

Expected: a total above 0 and `IndexedVehicle` rows with `brand='motorrad'`, `series_code='K50'` or
similar, and vehicle ids ending in `R_1250_GS…` (no network is used).

- [ ] **Step 4: Run the whole suite**

```bash
uv run --directory server pytest -q
uv run --directory server pytest tests/unit/test_committed_vehicle_baseline.py -q
```

Expected: baseline + `91 passed` (deselected + 1); the guard test now gives `1 passed`. Every other
test uses private tmp baselines, so the real CSVs change nothing else.

- [ ] **Step 5: Commit the baseline**

```bash
git add brands/bmw/vehicles.csv brands/mini/vehicles.csv brands/motorrad/vehicles.csv brands/rolls-royce/vehicles.csv brands/vehicles.meta.toml
git commit -m "data(vehicles): add vehicle index baseline built from RealOEM" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 5: Delivery

### Task 12: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest -q
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: baseline + `91 passed` if Task 11 ran, otherwise baseline + `90 passed, 1 skipped`;
deselected = baseline + 1; `All checks passed!`; formatted files = baseline + 17.

- [ ] **Step 2: Nothing raw or generated is staged**

```bash
git status --short
git ls-files | grep -E '^\.research-raw/|\.sqlite3$|\.venv/' || echo clean
```

Expected: no status lines, then `clean`.

- [ ] **Step 3: Confirm the branch only adds files**

Run: `git diff --name-status main...HEAD | grep -v '^A' || echo "only additions"`
Expected: `only additions`

- [ ] **Step 4: Push and open the pull request**

Before running it, edit exactly these three lines of the body:

1. The Summary bullet that starts with `- Baseline:` — keep it if Task 11 ran; otherwise replace
   the whole line with
   `- Baseline CSVs: not included yet; the maintainer's one-time live rebuild (plan Task 11) will run on this branch before merge.`
2. The Test plan checkbox that starts with `- [ ] Baseline committed` — change `- [ ]` to `- [x]`
   only if Task 11 ran.
3. The Test plan checkbox that starts with ``- [ ] `claude plugin validate`` — change `- [ ]` to
   `- [x]` only if it ran in Task 9; otherwise append ` (skipped: claude CLI not available)`.

```bash
git push -u origin feat/vehicle-index
gh pr create --base main --head feat/vehicle-index --title "feat: vehicle index (find_vehicle, update_vehicle_index, rebuild script)" --body "$(cat <<'EOF'
## Summary

Implements PRD F6 per ARD AD16 and §5.11:

- `find_vehicle(query, brand, series, year, market, type_code, include_unlinked, limit)`: searches the local vehicle index (all query words must match series label, series code, model name or type code, case-insensitively); returns vehicle ids for the catalog tools. **No network requests.**
- `update_vehicle_index(max_pages=5)`: checks RealOEM's `vehicles?sort=year` for vehicles added since the index was built — one request when nothing is new, otherwise a backwards scan from the last page bounded by `max_pages` (1–10). Statuses `up_to_date`, `updated`, `partial` (resumes on the next call), `drift`; a probe past RealOEM's end and a missing baseline both give `drift` (the latter without any request). Never crawls the whole index.
- `VehicleIndex` (`vehicle_index.py`): committed per-brand CSV baseline loaded into `{data_dir}/vehicles.sqlite3` (WAL, separate from the page cache); reloaded when the baseline's sha256 changes, keeping local rows that are not in the new baseline; schema-versioned.
- `parsers/vehicles.py`: vehicles-index page parser (rows, NBSP brand prefix, unlinked rows, totals, pagination; brand per row by the ARD rule incl. type codes starting with `0` ⇒ motorcycles; Zinoro ⇒ BMW); `LayoutChanged` on unexpected structure, and unparseable pages are expired from the cache.
- `scripts/rebuild_vehicle_index.py`: maintainer-only full rebuild through `RealOemClient` at the normal rate limit; checks every page, restarts when the index changes mid-crawl (total or a final re-check of the last page), writes sorted UTF-8 CSVs and `brands/vehicles.meta.toml`.
- `skills/vehicle-index/SKILL.md`: find first, update and search again, start-month vehicle ids, end dates "as of built_at", RealOEM links, next step `list_part_groups(vehicle_id)`.
- Baseline: `brands/*/vehicles.csv` + `brands/vehicles.meta.toml` built once by the maintainer (~167 requests incl. one past-the-end capture, approved per PRD §4.2).
- 5 trimmed fixtures (`sort=year` pages 1, 2, 83, 165; `series=M`); opt-in live smoke test (2 requests).

Only adds files; no foundation or other feature file changed, no version bump.

## Test plan

- [x] `uv run pytest` (offline) and `uv run ruff check` / `ruff format --check`
- [x] Parser tests on every fixture (linked/unlinked rows, MINI, Rolls-Royce, motorcycles, Zinoro, totals, single page) and `LayoutChanged` cases
- [x] `VehicleIndex` tests on tmp baselines (load, search, add, reconcile on baseline change, schema upgrade, bad files)
- [x] Tool tests via in-memory `mcp.Client`: `find_vehicle` makes zero requests; update up_to_date (1 request), updated, resumable partial, drift cases, probe past the end, no baseline, validation before any request, unparseable page not cached
- [x] Rebuild script tests on a synthetic 3-page index (format, sort order, restarts, page and duplicate checks)
- [ ] Baseline committed and `test_committed_vehicle_baseline.py` passing (plan Task 11, maintainer)
- [ ] `claude plugin validate . --strict`
- [ ] Optional: `REALOEM_LIVE=1 uv run pytest -m live tests/live/test_live_vehicles.py` (2 requests)
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
