# Diagram Browsing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/diagram-browse` (PRD F3.1–F3.5, feature C): four MCP tools that walk RealOEM's catalog the way its website does — `select_vehicle` (model cascade one level at a time, auto-selected levels included, until a vehicle id), `list_part_groups` (vehicle specs and main groups), `list_diagrams` (a main group's subgroups and diagrams) and `get_diagram_parts` (a diagram's parts list with option-code conditions, image and hotspots) — plus the exported `fetch_diagram_list` / `fetch_diagram_parts` helpers that feature D (fitment) builds on, and the `diagram-browse` skill.

**Architecture:** Pure parsers turn trimmed real RealOEM pages into pydantic models: `parsers/partgrp.py` reads the main-groups page (`.vehicle-specs dl`, `.mg-thumb` links, canonical vehicle id) and a main group's diagram list (`.diagThumbs` walked in order: `a[name]` subgroup headings, `.diag-thumb` diagrams), `parsers/showparts.py` reads the diagram image, the inline `partsimgmap` hotspots and `table#partsList` (11-cell part rows, 4-cell condition rows grouped by their `posNN` class). The model cascade reuses VIN decode's `parse_select` and `models/select.py` unchanged. `tools/catalog.py` (auto-discovered, no `server.py` edit) validates input before any request, fetches through the foundation `RealOemClient` (one request per call, 30-day cache), turns RealOEM's redirect to its landing page into `NotFound`, and expires any page that fails to parse before re-raising (ARD §5.10). Tests run offline against trimmed fixtures through the foundation harness (`make_services`, `FixtureTransport`, `Route`, in-memory `mcp.Client`).

**Tech Stack:** Python ≥ 3.11, uv, mcp 2.x (`MCPServer`), httpx, selectolax (lexbor), pydantic 2, SQLite page cache (all from the foundation); pytest + AnyIO plugin, ruff.

---

## Before you start

- `feat/foundation`, `feat/part-lookup` and `feat/vin-decode` are already merged into `main`. This plan
  uses their APIs exactly as they exist there and **edits none of their files**:
  - foundation: `Services` (`settings`, `cache`, `client`, `brands`), `RealOemClient.fetch(page_type,
    path, params, *, refresh, ttl)` / `.cached(page_type, path, params)` / `.build_url`,
    `Page.redirected_away`, `PageCache.shorten(url, ttl)`, `PageType`, `InvalidInput` / `NotFound` /
    `LayoutChanged` / `RealOemError`, `parsers.common` (`tree`, `text`, `require`, `canonical_url`,
    `parse_my`, `parse_price_usd`, `Node`, `Tree`), `BrandRegistry` (`for_vehicle_id`,
    `brand_segments`, `Brand.dedupe_repeated_names`), `VehicleId.parse`, `ResultMeta.from_pages`,
    `VehicleRef.from_id`, `DiagramRef.build`, and the test harness (`tests/harness.py`:
    `load_fixture`, `url`, `Route`, `LANDING_URL`, `MakeServices`, `REPO_ROOT`; `tests/conftest.py`:
    `make_services`).
  - VIN decode: `models/select.py` (`SelectOption`, `SelectLevel.selected_option`, `SelectPage`) and
    `parsers/select.py` (`parse_select`), plus its committed select fixtures under
    `server/tests/fixtures/select/` (`cascade_e90.html`, `cascade_e90_325i.html`,
    `cascade_e90_325i_eur_200510.html`, `cascade_classic_e46.html`, `vin_bmw_e93_px22770_v1.html`).
  - foundation fixture `server/tests/fixtures/common/partgrp_e90_325i.html` (the E90 325i main-groups
    page, trimmed from the same raw capture this plan would use) is reused, not duplicated.
- Read `docs/ARD.md` §5.5, §5.7–§5.11 (the "C: catalog tools" contract) and §8, and
  `docs/research/realoem-site-notes.md` §1, §2 and §5.1–§5.4 once.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.**
  Python commands use `uv run --directory server …` (so they run inside `server/`); paths after it
  (like `tests/unit/test_models_catalog.py`) are relative to `server/`. `git` paths are relative to
  the repository root.
- Never make requests to realoem.com while implementing.
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`. The
  foundation's `tests/unit/test_fixtures.py` automatically checks every new fixture (trimmed, no
  unmasked 17-character VIN): each new fixture adds 2 tests to the full suite.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that).
- Versions stay `0.1.0` everywhere; feature branches never bump them.
- Test counts: per-file counts below are exact. Full-suite totals are given as **BASELINE + N**,
  where BASELINE is the number of passing tests you record in Task 0 (it includes the part-lookup
  and VIN-decode tests already on `main`).

## File Structure

| Path | Responsibility |
|---|---|
| `server/src/realoem_mcp/models/catalog.py` | `VehicleSelectionResult`, `VehicleSpecs`, `MainGroup`, `PartGroups` (parser output) + `PartGroupsResult`, `DiagramThumb`, `Subgroup`, `DiagramListResult`, `Hotspot`, `OptionCode`, `Condition`, `PartRow`, `DiagramParts` (parser output) + `DiagramPartsResult` |
| `server/src/realoem_mcp/parsers/partgrp.py` | `parse_part_groups(html, *, url, brands) -> PartGroups`, `parse_diagram_list(html, *, url, client, vehicle_id, dedupe_names) -> list[Subgroup]`, `vehicle_brand()`, `dedupe_repeated()`, `MAIN_GROUP` / `DIAG_ID` patterns |
| `server/src/realoem_mcp/parsers/showparts.py` | `parse_showparts(html, *, url, client, vehicle_id, diag_id) -> DiagramParts` |
| `server/src/realoem_mcp/tools/catalog.py` | `register()` → `select_vehicle`, `list_part_groups`, `list_diagrams`, `get_diagram_parts`; exported `fetch_diagram_list`, `fetch_diagram_parts` (for D) |
| `skills/diagram-browse/SKILL.md` | How to reach a vehicle id, main group numbers, reading parts lists (conditions, option codes, date filtering, hotspots), rules |
| `server/tests/fixtures/partgrp/*.html` | 9 trimmed `partgrp` pages: MINI, Rolls-Royce, Motorrad main groups; garbage-suffix id (canonical link); BMW, MINI, Motorrad diagram lists; BMW text drill-down page; RealOEM's answer for a main group the vehicle lacks (`mg=99`) |
| `server/tests/fixtures/showparts/*.html` | 6 trimmed `showparts` pages: E90 oil pan 10/2005, 08/2006 and EUR; MINI oil pan; Motorrad engine housing; E90 oil filter opened with a `lookup_part`-style id |
| `server/tests/fixtures/catalog/*.html` | 3 new select pages for the cascade tests (kept out of VIN decode's `fixtures/select/`): motorcycle root, complete E90 325i USA 10/2005, complete R 1250 GS USA 05/2019 |
| `server/tests/unit/test_models_catalog.py` | Result models = parser output + `ResultMeta` |
| `server/tests/unit/parsers/test_partgrp.py` | Specs and main groups per brand, canonical id, diagram lists, Motorrad name dedupe |
| `server/tests/unit/parsers/test_partgrp_layout.py` | `LayoutChanged` on broken partgrp pages and the text drill-down page; empty diagram list |
| `server/tests/unit/parsers/test_showparts.py` | Every field of the E90 table, date filtering (10/2005 vs 08/2006), EUR, MINI, Motorrad, xref-style id |
| `server/tests/unit/parsers/test_showparts_layout.py` | `LayoutChanged` on broken showparts pages |
| `server/tests/tools/test_select_vehicle.py` | Cascade stepping, auto-selected levels, complete → vehicle, rejected before any request, broken page not cached |
| `server/tests/tools/test_part_groups.py` | `list_part_groups` / `list_diagrams`: results, canonical id, unknown vehicle, missing main group (real answer and empty list), input validation, broken pages not cached |
| `server/tests/tools/test_diagram_parts.py` | `get_diagram_parts`, `fetch_diagram_parts` / `fetch_diagram_list` with `cache_only` |
| `server/tests/unit/test_skill_diagram_browse.py` | Skill frontmatter and required statements |

Decisions this plan makes where the ARD leaves room (feature D may rely on the first four):

- **Exported helpers** (ARD §5.11): `fetch_diagram_list(services, vehicle_id, main_group, *,
  refresh=False, cache_only=False)` and `fetch_diagram_parts(services, vehicle_id, diag_id, *,
  refresh=False, cache_only=False)` return `(result, page)`. Input is validated first (also with
  `cache_only`); with `cache_only=True` they read only `client.cached(...)` (`refresh` is ignored) and
  return `None` on a miss; otherwise they never return `None`. Both raise `NotFound` for an unknown
  vehicle, `fetch_diagram_list` also for a main group without diagrams. The tools are thin wrappers
  around them.
- **Vehicle ids in results.** `list_part_groups` reports RealOEM's canonical id in
  `specs.vehicle` (ARD: garbage suffix `VB13-USA-03-2006-XXX-YYY-ZZZ` → `VB13-USA-03-2006-E90-BMW-325i`).
  `list_diagrams` and `get_diagram_parts` keep the **requested** id (percent-decoded and trimmed by
  `VehicleId.parse`) in `vehicle_id` and every `DiagramRef`, so `DiagramRef.url` is exactly the URL
  (cache key) that `fetch_diagram_parts` fetches for it. Reason: RealOEM canonicalizes the
  `lookup_part`-style id `VB13-USA-02_2004_E90_BMW_325i` to the undated `VB13-USA---E90-BMW-325i`
  (captured), which would silently change the key and drop the date.
- **Vehicle id input** (all three vehicle tools and both helpers): parsed with `VehicleId.parse`
  (empty → `InvalidInput`); the type code and market must be letters/digits, so `VB13` alone (which
  RealOEM answers with a 301 to its landing page) is rejected before any request. The dash, xref
  (`_`) and undated forms are all accepted and sent as given (F3.5).
- **Brand**: `vehicle_brand(brands, vid)` = `brands.for_vehicle_id(vid, product="M" if the type code
  starts with "0" else "P")` (the ARD F6 rule). `select_vehicle` passes the selected `product`
  instead. Motorrad (`dedupe_repeated_names = true`) subgroup and diagram names printed twice
  ("Engine / Running Gear Engine / Running Gear") are collapsed by `dedupe_repeated`.
- **`main_group`** must be two digits (`^\d{2}$`), **`diag_id`** `^\d{2}_\d+$`; anything else is
  `InvalidInput` before any request.
- **Missing main group** (captured: `partgrp?id=VB13-USA-10-2005-E90-BMW-325i&mg=99`): RealOEM answers
  HTTP 200 with the vehicle's main-groups page (`.partgrp-grid`, `.vehicle-specs`, canonical link
  keeps `&mg=99`) and no `.diagThumbs`. `parse_diagram_list` returns `None` for that shape (and `[]`
  for a `.diagThumbs` without diagrams); `fetch_diagram_list` then shortens the cache entry to 1 day
  (`services.cache.shorten(page.url, timedelta(days=1))`) and raises
  `NotFound("vehicle <id> has no main group <mg>; list_part_groups shows the ones it has.")`. A page
  with neither `.diagThumbs` nor `.partgrp-grid` is `LayoutChanged`.
- **`LayoutChanged` rules.** partgrp: no canonical link with `id`, no `.vehicle-specs dl`, no
  `.mg-thumb` main group link, an `mg` that is not two digits, a main group without a name, the text
  drill-down page (`.partgrp-selects`, what `dmode=0` shows), neither `.diagThumbs` nor `.partgrp-grid`, a diagram before the
  first subgroup heading, a subgroup heading without `h3.diag-hdr`, a diagram link whose `diagId` is
  missing or malformed, a diagram without title or thumbnail. showparts: no `#partsimg img` or an
  image without alt/src/numeric width/height, no `table#partsList` or no header row, no
  `partsimgmap` script, `partsimgmap` that is not JSON or has an entry other than
  `[str, int, int, int, int]`, a row without a `posNN` class, a row with neither 11 cells nor 4 cells
  ending in `colspan="8"`, a part row without position or description, an `a.opt-code` not followed
  by `=value`, a notes-legend entry without `=`. select (in `select_vehicle`): whatever
  `parse_select` raises, plus a page with neither an open level nor a vehicle id. Every tool expires
  such a page (`cache.shorten(page.url, timedelta(0))`) before re-raising; tests serve a broken page
  twice and expect two requests. (`_expire_if_unparseable` is a local copy of the private helper in
  `tools/vin.py`; the ARD keeps helpers in the feature's own module.)
- **Parts rows.** Part rows (11 cells): position (`01` or `--`), description (indent 1–3 from the
  `edge1..3` class, else 0), supplement, qty, from / up to (`MM/YYYY` → `"YYYY-MM"`), part number,
  price (`parse_price_usd`; empty → `None`), photo flag (`a[href*="/photos/"]`), notes (e.g.
  `+core`, explained in `notes_legend`); the 11th (affiliate, emptied in fixtures) cell is ignored. Empty cells are
  `None`. Cell text treats `<br>` and element boundaries as spaces.
- **Condition rows** (4 cells: empty, text, option codes, `colspan="8"`) belong to the part rows of
  the same `posNN` class: a run of consecutive condition rows applies to every following part row
  of that position until the next condition row; condition rows after a position's last part row
  (the trailing "Attention! …" notes) are added to that last part row. Condition rows of a position
  with no part row are dropped. `OptionCode(code, value)` comes from each `a.opt-code` and the
  `=Yes` text right after it. Example (E90 oil pan): pos 01 "Oil Pan" gets "For vehicles with
  Automatic transmission" + `S205A=Yes`; the `--` Loctite row gets "Required for repair" and the
  trailing "Attention! …".
- **Hotspots** are the raw `partsimgmap` boxes (display space of the `img` width × height, e.g.
  640 × 448), several per position allowed, and include positions the date filter removed from the
  table (08/2006 still has a box for position 10).
- **Image and thumbnail URLs** are absolute (`urljoin` with the page URL).
- **`select_vehicle`** (ARD §5.11): `product: Literal["P", "M"] = "P"` and `archive: Literal["0",
  "1"] | None` (the SDK rejects other values before the tool runs, with pydantic's message); the
  other levels are strings, stripped, and must not be blank; `prod` must be `YYYYMM00` with month
  01–12. Parameters are sent in the ARD order, only when given. `selected` maps each level with a
  selected row (auto-selected included) to its `SelectOption`; when the page carries a vehicle id,
  `complete=true`, `next_level=None`, `options=[]` and `vehicle`/`type_code`/`summary` are set;
  otherwise `next_level` is the first level without a selection and `options` are its rows. A
  redirect away from `select` is `NotFound`. The tool does not check that levels are given in
  order; if RealOEM ignores a value, `selected` shows it (the skill tells Claude to check).
- **Fixtures.** The E90 main-groups page is the foundation's `common/partgrp_e90_325i.html`. The
  motorcycle root page was captured as `select?archive=0&product=M`; the tool sends the same two
  parameters as `product=M&archive=0`, so the test routes that URL to it. The `lookup_part`-style
  showparts page was captured at `showparts?id=VB13-USA-02_2004_E90_BMW_325i&diagId=11_3867`.
  `trim_fixture.py` keeps the `partsimgmap` script and empties the affiliate cell
  (`td.ecs-tuning-cell`) without removing it, so part rows keep their 11 cells (verified in Task 3).

## Chunk 1: Models and the partgrp parser

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

```bash
git checkout main && git pull && git checkout -b feat/diagram-browse
```

Expected: `Switched to a new branch 'feat/diagram-browse'`.

- [ ] **Step 2: Record the baseline**

Run: `uv run --directory server pytest -q`
Expected: PASS, e.g. `337 passed, 2 deselected` (foundation + VIN decode only; the number is higher
with part-lookup on `main`). **Write the passed count down as BASELINE**; later totals are
BASELINE + N.

- [ ] **Step 3: Confirm the reused modules and the raw captures are there**

```bash
ls server/src/realoem_mcp/models/select.py server/src/realoem_mcp/parsers/select.py server/tests/fixtures/common/partgrp_e90_325i.html server/tests/fixtures/select/cascade_e90.html
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
ls "$RAW/diagrams/07_showparts_E90_325i_11_3733_v2.html" "$RAW/xref/showparts_VB13_11_3867_v2.html" "$RAW/diagrams2/partgrp_mg99.html"
```

Expected: all seven paths are listed (no `No such file or directory`). `RAW` resolves the git-ignored
`.research-raw/` of the main checkout, also from a git worktree.

### Task 1: Catalog models (`models/catalog.py`)

ARD §5.11. The parsers return `PartGroups` and `DiagramParts`; the tool results are those plus the
four `ResultMeta` fields (`class PartGroupsResult(ResultMeta, PartGroups)`), so
`PartGroupsResult.from_pages([page], **dict(groups))` builds a result without repeating fields.
`DiagramListResult` and `VehicleSelectionResult` are built field by field in the tools.

**Files:**
- Create: `server/src/realoem_mcp/models/catalog.py`
- Test: `server/tests/unit/test_models_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_catalog.py`:

```python
from datetime import UTC, datetime

from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import (
    Condition,
    DiagramParts,
    DiagramPartsResult,
    Hotspot,
    MainGroup,
    OptionCode,
    PartGroups,
    PartGroupsResult,
    PartRow,
    VehicleSelectionResult,
    VehicleSpecs,
)
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.page_types import PageType
from tests.harness import url

VEHICLE = VehicleRef(
    vehicle_id="VB13-USA-10-2005-E90-BMW-325i",
    type_code="VB13",
    market="USA",
    production_month="2005-10",
    series="E90",
    brand="bmw",
    model="325i",
)
META = {
    "fetched_at": datetime(2026, 9, 30, tzinfo=UTC),
    "from_cache": True,
    "requests_made": 0,
}


def _page(page_type: PageType, page_url: str) -> Page:
    return Page(
        page_type=page_type,
        url=page_url,
        final_url=page_url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=True,
    )


def test_part_groups_result_is_the_parser_output_plus_result_meta() -> None:
    page_url = url("partgrp", id=VEHICLE.vehicle_id)
    groups = PartGroups(
        specs=VehicleSpecs(
            vehicle=VEHICLE,
            model_name="3 Series E90 325i",
            body="Sedan",
            engine="N52",
            steering="Left-hand drive",
            transmission=None,
        ),
        main_groups=[MainGroup(mg="11", name="ENGINE")],
    )
    result = PartGroupsResult.from_pages([_page(PageType.PARTGRP, page_url)], **dict(groups))
    assert result.model_dump() == {"source_urls": [page_url], **META, **groups.model_dump()}


def test_diagram_parts_result_is_the_parser_output_plus_result_meta() -> None:
    page_url = url("showparts", id=VEHICLE.vehicle_id, diagId="11_3733")
    row = PartRow(
        position="01",
        description="Oil Pan",
        supplement=None,
        qty="1",
        valid_from=None,
        valid_to="2006-04",
        part_number="11137552414",
        price_usd=551.84,
        notes="+core",
        has_photo=False,
        indent=2,
        conditions=[
            Condition(
                text="For vehicles with Automatic transmission",
                option_codes=[OptionCode(code="S205A", value="Yes")],
            )
        ],
    )
    parts = DiagramParts(
        diagram=DiagramRef(
            vehicle_id=VEHICLE.vehicle_id, diag_id="11_3733", name="Oil Pan", url=page_url
        ),
        image_url="https://www.realoem.com/bmw/images/diag_2zas.jpg",
        image_width=640,
        image_height=448,
        hotspots=[Hotspot(position="01", x1=78, y1=255, x2=87, y2=271)],
        rows=[row],
        notes_legend={"+core": "plus core charge"},
    )
    result = DiagramPartsResult.from_pages([_page(PageType.SHOWPARTS, page_url)], **dict(parts))
    assert result.model_dump() == {"source_urls": [page_url], **META, **parts.model_dump()}


def test_vehicle_selection_result_fields() -> None:
    assert list(VehicleSelectionResult.model_fields) == [
        "source_urls",
        "fetched_at",
        "from_cache",
        "requests_made",
        "selected",
        "next_level",
        "options",
        "complete",
        "vehicle",
        "type_code",
        "summary",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_catalog.py -q`
Expected: FAIL (`1 error`: collecting the file fails with `ModuleNotFoundError: No module named 'realoem_mcp.models.catalog'`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/models/catalog.py`:

```python
"""Catalog models (feature C, ARD section 5.11): cascade, main groups, diagrams, parts lists."""

from __future__ import annotations

from pydantic import BaseModel

from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.models.select import SelectOption


class VehicleSelectionResult(ResultMeta):
    selected: dict[str, SelectOption]  # level -> effective choice, auto-selected levels included
    next_level: str | None  # first level without a choice; None once complete
    options: list[SelectOption]  # choices for next_level ([] when complete)
    complete: bool
    vehicle: VehicleRef | None
    type_code: str | None
    summary: str | None  # "You Have Selected:" text, e.g. "3 Series E90 BMW 325i"


class VehicleSpecs(BaseModel):
    vehicle: VehicleRef  # built from the page's canonical vehicle id
    model_name: str | None  # e.g. "3 Series E90 325i"
    body: str | None  # e.g. "Sedan"; None for motorcycles ("N/A")
    engine: str | None
    steering: str | None  # e.g. "Left-hand drive"
    transmission: str | None  # only some vehicles (e.g. Rolls-Royce)


class MainGroup(BaseModel):
    mg: str  # two digits, e.g. "11"
    name: str  # e.g. "ENGINE"


class PartGroups(BaseModel):  # parser output of parsers/partgrp.py (main groups page)
    specs: VehicleSpecs
    main_groups: list[MainGroup]


class PartGroupsResult(ResultMeta, PartGroups):
    pass


class DiagramThumb(BaseModel):
    diagram: DiagramRef
    thumbnail_url: str


class Subgroup(BaseModel):
    code: str  # e.g. "10"
    name: str  # e.g. "Engine Housing"
    diagrams: list[DiagramThumb]


class DiagramListResult(ResultMeta):
    vehicle_id: str
    main_group: str
    subgroups: list[Subgroup]


class Hotspot(BaseModel):
    position: str  # matches PartRow.position, e.g. "01"
    x1: int
    y1: int
    x2: int
    y2: int  # display space: the same pixels as image_width x image_height


class OptionCode(BaseModel):
    code: str  # e.g. "S205A"
    value: str  # e.g. "Yes"


class Condition(BaseModel):
    text: str  # e.g. "For vehicles with Automatic transmission"
    option_codes: list[OptionCode]


class PartRow(BaseModel):
    position: str  # "01", or "--" for accessories without a callout
    description: str
    supplement: str | None
    qty: str | None
    valid_from: str | None  # "YYYY-MM"
    valid_to: str | None  # "YYYY-MM"
    part_number: str | None
    price_usd: float | None
    notes: str | None  # e.g. "+core"; see DiagramParts.notes_legend
    has_photo: bool
    indent: int  # 0-3, from the description cell's edge1..edge3 class
    conditions: list[Condition]


class DiagramParts(BaseModel):  # parser output of parsers/showparts.py
    diagram: DiagramRef
    image_url: str
    image_width: int
    image_height: int
    hotspots: list[Hotspot]
    rows: list[PartRow]
    notes_legend: dict[str, str]  # e.g. {"+core": "plus core charge (...)"}


class DiagramPartsResult(ResultMeta, DiagramParts):
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_catalog.py -q`
Expected: PASS (`3 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, then `… files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models/catalog.py server/tests/unit/test_models_catalog.py
git commit -m "feat(catalog): add catalog result models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: partgrp fixtures and parser (`parsers/partgrp.py`)

Site notes §5.2–§5.3. Main groups come from `.mg-thumb a[href*="mg="]` (mg from the href, name from
the `img` alt, else `.title`); specs from `.vehicle-specs dl` (`N/A` and empty values become `None`);
the vehicle from the canonical link's `id`. The diagram list walks the direct children of
`.diagThumbs` in order: `a[name]` starts a subgroup (code = the name, name = `h3.diag-hdr`), each
`.diag-thumb` is a diagram of the current subgroup (diagId from its link, name from `.title`,
thumbnail from its `img`). The tests cover BMW, MINI, Rolls-Royce and Motorrad main groups, the
canonical id of a garbage-suffix request, BMW / MINI / Motorrad diagram lists, RealOEM's
main-groups answer for a main group the vehicle lacks (`None`), and every
`LayoutChanged` rule (broken pages are edited copies of real fixtures).

**Files:**
- Create: `server/tests/fixtures/partgrp/*.html` (9 files, generated), `server/src/realoem_mcp/parsers/partgrp.py`
- Test: `server/tests/unit/parsers/test_partgrp.py`, `server/tests/unit/parsers/test_partgrp_layout.py`

- [ ] **Step 1: Generate the fixtures and write the failing tests**

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/06_partgrp_E90_325i_mg11_v2.html" tests/fixtures/partgrp/e90_325i_mg11.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/13_partgrp_constructed_garbage_suffix.html" tests/fixtures/partgrp/e90_325i_garbage_suffix.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/17_partgrp_R56_CooperS_v2.html" tests/fixtures/partgrp/r56_cooper_s.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/18_partgrp_R56_CooperS_mg11_v2.html" tests/fixtures/partgrp/r56_cooper_s_mg11.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/24_partgrp_RR4_Ghost_v2.html" tests/fixtures/partgrp/rr4_ghost.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/29_partgrp_M_K50_R1250GS_v2.html" tests/fixtures/partgrp/k50_r1250gs.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/30_partgrp_M_K50_R1250GS_mg11_v2.html" tests/fixtures/partgrp/k50_r1250gs_mg11.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/37_partgrp_E90_325i_mg11_textmode_v2.html" tests/fixtures/partgrp/e90_325i_mg11_textmode.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams2/partgrp_mg99.html" tests/fixtures/partgrp/e90_325i_mg99.html
```

Expected (stderr, one line per file; paths may print with `\` on Windows):
`e90_325i_mg11.html: 49345 -> 28012 bytes`, `e90_325i_garbage_suffix.html: 52798 -> 30322 bytes`,
`r56_cooper_s.html: 51132 -> 28557 bytes`, `r56_cooper_s_mg11.html: 50034 -> 28597 bytes`,
`rr4_ghost.html: 50637 -> 27983 bytes`, `k50_r1250gs.html: 48133 -> 25286 bytes`,
`k50_r1250gs_mg11.html: 49418 -> 27770 bytes`, `e90_325i_mg11_textmode.html: 41839 -> 20049 bytes`,
`e90_325i_mg99.html: 52969 -> 30357 bytes`.

Captured URLs (all `https://www.realoem.com/bmw/enUS/partgrp?…`): `id=VB13-USA-10-2005-E90-BMW-325i&mg=11`,
`id=VB13-USA-03-2006-XXX-YYY-ZZZ`, `id=MF73-USA-02-2008-R56-Mini-Cooper_S` (and `&mg=11`),
`id=FK43-USA-06-2010-RR4-Rolls_Royce-Ghost`, `id=0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_`
(and `&mg=11`), `id=VB13-USA-10-2005-E90-BMW-325i&mg=99`; the text drill-down page is what
`id=VB13-USA-10-2005-E90-BMW-325i&mg=11` returned after a `dmode=0` visit.

Create `server/tests/unit/parsers/test_partgrp.py`:

```python
import pytest

from realoem_mcp.models.catalog import PartGroups, Subgroup
from realoem_mcp.parsers.partgrp import (
    dedupe_repeated,
    parse_diagram_list,
    parse_part_groups,
    vehicle_brand,
)
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
K50 = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    """Offline services: the parsers need its brand registry and client (no requests)."""
    return make_services({})[0]


def _groups(fixture: str, vehicle_id: str, services: Services) -> PartGroups:
    html = load_fixture(fixture)
    return parse_part_groups(html, url=url("partgrp", id=vehicle_id), brands=services.brands)


def _diagrams(
    fixture: str, vehicle_id: str, services: Services, *, dedupe: bool = False
) -> list[Subgroup]:
    return parse_diagram_list(
        load_fixture(fixture),
        url=url("partgrp", id=vehicle_id, mg="11"),
        client=services.client,
        vehicle_id=vehicle_id,
        dedupe_names=dedupe,
    )


async def test_bmw_specs_and_main_groups(services: Services) -> None:
    groups = _groups("common/partgrp_e90_325i.html", E90, services)
    assert groups.specs.model_dump() == {
        "vehicle": {
            "vehicle_id": E90,
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "model_name": "3 Series E90 325i",
        "body": "Sedan",
        "engine": "N52",
        "steering": "Left-hand drive",
        "transmission": None,
    }
    names = {group.mg: group.name for group in groups.main_groups}
    assert len(groups.main_groups) == 39
    assert (groups.main_groups[0].mg, groups.main_groups[-1].mg) == ("01", "91")
    assert {mg: names[mg] for mg in ("11", "12", "13", "17", "18", "21", "23", "24")} == {
        "11": "ENGINE",
        "12": "ENGINE ELECTRICAL SYSTEM",
        "13": "FUEL PREPARATION SYSTEM",
        "17": "RADIATOR",
        "18": "EXHAUST SYSTEM",
        "21": "CLUTCH",
        "23": "MANUAL TRANSMISSION",
        "24": "AUTOMATIC TRANSMISSION",
    }
    assert {mg: names[mg] for mg in ("31", "32", "33", "34", "51", "61", "64")} == {
        "31": "FRONT AXLE",
        "32": "STEERING",
        "33": "REAR AXLE",
        "34": "BRAKES",
        "51": "VEHICLE TRIM",
        "61": "VEHICLE ELECTRICAL SYSTEM",
        "64": "HEATER AND AIR CONDITIONING",
    }
    assert names["88"] == "VALUE PARTS&PACKAGES SERVICE AND REPAIR"


async def test_vehicle_id_comes_from_the_canonical_link(services: Services) -> None:
    garbage = "VB13-USA-03-2006-XXX-YYY-ZZZ"
    groups = _groups("partgrp/e90_325i_garbage_suffix.html", garbage, services)
    vehicle = groups.specs.vehicle
    assert vehicle.vehicle_id == "VB13-USA-03-2006-E90-BMW-325i"
    assert (vehicle.production_month, vehicle.series, vehicle.model) == ("2006-03", "E90", "325i")


async def test_mini_specs(services: Services) -> None:
    groups = _groups("partgrp/r56_cooper_s.html", R56, services)
    assert groups.specs.vehicle.brand == "mini"
    assert groups.specs.vehicle.model == "Cooper_S"
    assert (groups.specs.model_name, groups.specs.body, groups.specs.engine) == (
        "MINI R56 Cooper S",
        "3 doors",
        "N14",
    )
    assert len(groups.main_groups) == 35


async def test_rolls_royce_has_transmission_and_bespoke_group(services: Services) -> None:
    groups = _groups("partgrp/rr4_ghost.html", "FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", services)
    assert groups.specs.vehicle.brand == "rolls-royce"
    assert groups.specs.model_name == "Rolls-Royce Ghost RR4 Ghost"
    assert groups.specs.transmission == "Automatic"
    assert groups.main_groups[-1].model_dump() == {"mg": "92", "name": "BESPOKE"}
    assert len(groups.main_groups) == 33


async def test_motorcycle_has_no_body_engine_or_steering(services: Services) -> None:
    groups = _groups("partgrp/k50_r1250gs.html", K50, services)
    assert groups.specs.model_dump() == {
        "vehicle": {
            "vehicle_id": K50,
            "type_code": "0J93",
            "market": "USA",
            "production_month": "2019-05",
            "series": "K50",
            "brand": "motorrad",
            "model": "R_1250_GS_19_0J91,_0J93_",
        },
        "model_name": "K50 (R 1200 GS, R 1250 GS) R 1250 GS 19 (0J91, 0J93)",
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
    }
    names = {group.mg: group.name for group in groups.main_groups}
    assert (names["13"], names["17"], names["77"]) == (
        "FUEL SYSTEM",
        "COOLING",
        "OPTIONAL EQUIPMENT+ACCESSORIES, MOTORRAD",
    )


async def test_bmw_diagram_list(services: Services) -> None:
    subgroups = _diagrams("partgrp/e90_325i_mg11.html", E90, services)
    assert [(s.code, s.name, len(s.diagrams)) for s in subgroups] == [
        ("05", "Engine", 1),
        ("10", "Engine Housing", 5),
        ("15", "Cylinder Head", 5),
        ("18", "Belt Drive", 2),
        ("20", "Crankshaft Drive", 5),
        ("25", "Valve Train", 4),
        ("30", "Lubrication System", 3),
        ("35", "Engine Cooling", 2),
        ("40", "Intake Manifold", 2),
        ("45", "Vacuum Control", 1),
        ("88", "Inspection Kits", 1),
    ]
    housing = subgroups[1].diagrams
    assert [(d.diagram.diag_id, d.diagram.name) for d in housing] == [
        ("11_3731", "ENGINE BLOCK"),
        ("11_3732", "ENGINE BLOCK MOUNTING PARTS"),
        ("11_3733", "OIL PAN"),
        ("11_3742", "CYLINDER CRANKCASE/HELI-COIL INSERT"),
        ("11_3834", "OIL PAN"),
    ]
    assert housing[2].model_dump() == {
        "diagram": {
            "vehicle_id": E90,
            "diag_id": "11_3733",
            "name": "OIL PAN",
            "url": url("showparts", id=E90, diagId="11_3733"),
        },
        "thumbnail_url": "https://www.realoem.com/bmw/images/thumb_2zas.jpg",
    }


async def test_mini_diagram_list(services: Services) -> None:
    subgroups = _diagrams("partgrp/r56_cooper_s_mg11.html", R56, services)
    assert len(subgroups) == 12
    assert sum(len(s.diagrams) for s in subgroups) == 31
    assert subgroups[1].diagrams[2].diagram.model_dump() == {
        "vehicle_id": R56,
        "diag_id": "11_3910",
        "name": "OIL PAN/OIL LEVEL INDICATOR",
        "url": url("showparts", id=R56, diagId="11_3910"),
    }


async def test_motorcycle_diagram_list_dedupes_doubled_names(services: Services) -> None:
    subgroups = _diagrams("partgrp/k50_r1250gs_mg11.html", K50, services, dedupe=True)
    assert len(subgroups) == 17
    assert (subgroups[0].code, subgroups[0].name) == ("05", "Engine / Running Gear")
    assert [d.diagram.name for d in subgroups[0].diagrams] == [
        "ENGINE",
        "SHORT ENGINE / CYLINDER WITH PISTONS",
        "ENGINE",
    ]
    oil_filter = subgroups[13]
    assert (oil_filter.code, oil_filter.name) == ("42", "Oil Filter And Lines")
    assert oil_filter.diagrams[0].diagram.url == url("showparts", id=K50, diagId="11_3820")


async def test_motorcycle_names_stay_doubled_without_dedupe(services: Services) -> None:
    subgroups = _diagrams("partgrp/k50_r1250gs_mg11.html", K50, services)
    assert subgroups[0].name == "Engine / Running Gear Engine / Running Gear"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Engine / Running Gear Engine / Running Gear", "Engine / Running Gear"),
        ("ENGINE ENGINE", "ENGINE"),
        ("Engine Housing", "Engine Housing"),
        ("OIL PAN", "OIL PAN"),
        ("", ""),
    ],
)
def test_dedupe_repeated(name: str, expected: str) -> None:
    assert dedupe_repeated(name) == expected


@pytest.mark.parametrize(
    ("vehicle_id", "brand"),
    [
        (E90, "bmw"),
        (R56, "mini"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", "rolls-royce"),
        (K50, "motorrad"),
        ("VB13-USA-02_2004_E90_BMW_325i", "bmw"),
    ],
)
async def test_vehicle_brand(services: Services, vehicle_id: str, brand: str) -> None:
    vid = VehicleId.parse(vehicle_id, brand_segments=services.brands.brand_segments())
    assert vehicle_brand(services.brands, vid).id == brand
```

Create `server/tests/unit/parsers/test_partgrp_layout.py`:

```python
import re

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.catalog import Subgroup
from realoem_mcp.parsers.partgrp import parse_diagram_list, parse_part_groups
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
GROUPS = "common/partgrp_e90_325i.html"
DIAGRAMS = "partgrp/e90_325i_mg11.html"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


def _edited(fixture: str, *edits: tuple[str, str]) -> str:
    html = load_fixture(fixture)
    for old, new in edits:
        assert old in html, f"{old!r} not in {fixture}"
        html = html.replace(old, new)
    return html


def _diagrams(html: str, services: Services) -> list[Subgroup] | None:
    return parse_diagram_list(
        html,
        url=url("partgrp", id=E90, mg="11"),
        client=services.client,
        vehicle_id=E90,
        dedupe_names=False,
    )


@pytest.mark.parametrize(
    ("edits", "detail"),
    [
        (
            [('<link rel="canonical"', '<link rel="alternate"')],
            "no vehicle id in the canonical link",
        ),
        ([('class="vehicle-specs"', 'class="specs"')], "missing '.vehicle-specs dl'"),
        ([('class="mg-thumb"', 'class="group"')], "no main groups (.mg-thumb links)"),
        ([("325i&amp;mg=11", "325i&amp;mg=ENGINE")], "main group link with mg='ENGINE'"),
        (
            [('alt="ENGINE">', 'alt="">'), ('<h3 class="title">ENGINE</h3>', "<h3></h3>")],
            "main group 11 has no name",
        ),
    ],
    ids=["no-canonical", "no-specs", "no-main-groups", "bad-mg", "no-name"],
)
async def test_broken_main_groups_page(
    services: Services, edits: list[tuple[str, str]], detail: str
) -> None:
    html = _edited(GROUPS, *edits)
    with pytest.raises(LayoutChanged) as info:
        parse_part_groups(html, url=url("partgrp", id=E90), brands=services.brands)
    assert info.value.detail == detail
    assert info.value.page_type == "partgrp"


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        ('class="diagThumbs"', 'class="thumbs"', "neither .diagThumbs nor .partgrp-grid"),
        ("diagId=11_3733", "diagram=11_3733", "diagram link with diagId=None"),
        ("diagId=11_3733", "diagId=3733", "diagram link with diagId='3733'"),
        ('<h3 class="diag-hdr">Engine Housing</h3>', "", "subgroup anchor without h3.diag-hdr"),
        ('<a name="05"><h3 class="diag-hdr">Engine</h3></a>', "", "diagram before the first"),
        (
            '<div class="title">SHORT ENGINE</div>',
            '<div class="title"></div>',
            "diagram 11_3730 has no title or thumbnail",
        ),
    ],
    ids=[
        "no-container",
        "no-diag-id",
        "bad-diag-id",
        "no-subgroup-name",
        "no-first-subgroup",
        "no-diagram-title",
    ],
)
async def test_broken_diagram_list(services: Services, old: str, new: str, detail: str) -> None:
    with pytest.raises(LayoutChanged, match=re.escape(detail)):
        _diagrams(_edited(DIAGRAMS, (old, new)), services)


async def test_text_drill_down_page_is_a_layout_change(services: Services) -> None:
    html = load_fixture("partgrp/e90_325i_mg11_textmode.html")
    with pytest.raises(LayoutChanged, match="text drill-down page"):
        _diagrams(html, services)


async def test_main_groups_page_means_the_vehicle_has_no_such_main_group(
    services: Services,
) -> None:
    html = load_fixture("partgrp/e90_325i_mg99.html")  # RealOEM's answer to mg=99
    assert _diagrams(html, services) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory server pytest tests/unit/parsers/test_partgrp.py tests/unit/parsers/test_partgrp_layout.py -q`
Expected: FAIL (`2 errors`: collecting both files fails with `ModuleNotFoundError: No module named 'realoem_mcp.parsers.partgrp'`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/partgrp.py`:

```python
"""partgrp pages (site notes 5.2-5.3): main groups and vehicle specs, a main group's diagrams."""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlsplit

from realoem_mcp.brands import Brand, BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.catalog import (
    DiagramThumb,
    MainGroup,
    PartGroups,
    Subgroup,
    VehicleSpecs,
)
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, Tree, canonical_url, require, text, tree
from realoem_mcp.vehicle_ids import VehicleId

PAGE = PageType.PARTGRP
MAIN_GROUP = re.compile(r"\d{2}")
DIAG_ID = re.compile(r"\d{2}_\d+")
_SPEC_FIELDS = {
    "Model": "model_name",
    "Body": "body",
    "Engine": "engine",
    "Steering": "steering",
    "Transmission": "transmission",
}
_NOT_AVAILABLE = {"", "N/A"}


def vehicle_brand(brands: BrandRegistry, vid: VehicleId) -> Brand:
    """Brand of a vehicle id; motorcycle type codes start with "0" (ARD F6 rule)."""
    return brands.for_vehicle_id(vid, product="M" if vid.type_code.startswith("0") else "P")


def dedupe_repeated(name: str) -> str:
    """Collapse a name printed twice ("Engine Engine" -> "Engine"), as on BMW Motorrad pages."""
    half, rest = divmod(len(name), 2)
    if rest and name[half] == " " and name[:half] == name[half + 1 :]:
        return name[:half]
    return name


def parse_part_groups(html: str, *, url: str, brands: BrandRegistry) -> PartGroups:
    root = tree(html)
    vehicle_id = _canonical_id(root, url)
    vid = VehicleId.parse(vehicle_id, brand_segments=brands.brand_segments())
    vehicle = VehicleRef.from_id(vid, vehicle_brand(brands, vid).id)
    specs = _specs(require(root, ".vehicle-specs dl", PAGE, url), vehicle)
    main_groups = [_main_group(link, url) for link in root.css('.mg-thumb a[href*="mg="]')]
    if not main_groups:
        raise LayoutChanged(PAGE, "no main groups (.mg-thumb links)", url)
    return PartGroups(specs=specs, main_groups=main_groups)


def parse_diagram_list(
    html: str, *, url: str, client: RealOemClient, vehicle_id: str, dedupe_names: bool
) -> list[Subgroup] | None:
    """Subgroups in page order; None when the vehicle has no such main group.

    For a main group the vehicle lacks, RealOEM answers with the vehicle's main-groups page
    (.partgrp-grid, no .diagThumbs).
    """
    root = tree(html)
    if root.css_first(".partgrp-selects") is not None:
        raise LayoutChanged(PAGE, "text drill-down page (dmode=0) instead of diagrams", url)
    container = root.css_first(".diagThumbs")
    if container is None:
        if root.css_first(".partgrp-grid") is not None:
            return None
        raise LayoutChanged(PAGE, "neither .diagThumbs nor .partgrp-grid", url)
    subgroups: list[Subgroup] = []
    for child in container.iter():
        classes = (child.attributes.get("class") or "").split()
        if child.tag == "a" and child.attributes.get("name"):
            name = _clean(text(child.css_first("h3.diag-hdr")), dedupe_names)
            if not name:
                raise LayoutChanged(PAGE, "subgroup anchor without h3.diag-hdr", url)
            subgroups.append(Subgroup(code=child.attributes["name"], name=name, diagrams=[]))
        elif "diag-thumb" in classes:
            if not subgroups:
                raise LayoutChanged(PAGE, "diagram before the first subgroup heading", url)
            thumb = _thumb(child, url, client, vehicle_id, dedupe_names)
            subgroups[-1].diagrams.append(thumb)
    return subgroups


def _canonical_id(root: Tree, url: str) -> str:
    canonical = canonical_url(root)
    vehicle_id = _query_param(canonical or "", "id")
    if not vehicle_id:
        raise LayoutChanged(PAGE, "no vehicle id in the canonical link", url)
    return vehicle_id


def _specs(dl: Node, vehicle: VehicleRef) -> VehicleSpecs:
    values: dict[str, str | None] = dict.fromkeys(_SPEC_FIELDS.values())
    for dt in dl.css("dt"):
        field = _SPEC_FIELDS.get(text(dt))
        dd = dt.next
        while dd is not None and dd.tag != "dd":
            dd = dd.next
        if field is not None and dd is not None:
            value = text(dd)
            values[field] = None if value in _NOT_AVAILABLE else value
    return VehicleSpecs(vehicle=vehicle, **values)


def _main_group(link: Node, url: str) -> MainGroup:
    mg = _query_param(link.attributes.get("href") or "", "mg") or ""
    if not MAIN_GROUP.fullmatch(mg):
        raise LayoutChanged(PAGE, f"main group link with mg={mg!r}", url)
    img = link.css_first("img")
    name = (img.attributes.get("alt") or "").strip() if img is not None else ""
    name = name or text(link.css_first(".title"))
    if not name:
        raise LayoutChanged(PAGE, f"main group {mg} has no name", url)
    return MainGroup(mg=mg, name=name)


def _thumb(
    node: Node, url: str, client: RealOemClient, vehicle_id: str, dedupe_names: bool
) -> DiagramThumb:
    link = node.css_first('a[href*="diagId="]')
    diag_id = _query_param(link.attributes.get("href") or "", "diagId") if link else None
    if diag_id is None or not DIAG_ID.fullmatch(diag_id):
        raise LayoutChanged(PAGE, f"diagram link with diagId={diag_id!r}", url)
    name = _clean(text(node.css_first(".title")), dedupe_names)
    img = node.css_first("img")
    src = img.attributes.get("src") if img is not None else None
    if not name or not src:
        raise LayoutChanged(PAGE, f"diagram {diag_id} has no title or thumbnail", url)
    return DiagramThumb(
        diagram=DiagramRef.build(client, vehicle_id, diag_id, name),
        thumbnail_url=urljoin(url, src),
    )


def _clean(name: str, dedupe_names: bool) -> str:
    return dedupe_repeated(name) if dedupe_names else name


def _query_param(href: str, name: str) -> str | None:
    # RealOEM's hrefs are not URL-encoded ("id=...R_1250_GS_19_0J91,_0J93_"), so split by hand.
    for pair in urlsplit(href).query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key == name:
            return unquote(value)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/parsers/test_partgrp.py tests/unit/parsers/test_partgrp_layout.py -q`
Expected: PASS (`32 passed`)

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q -k "partgrp and not common"`
Expected: PASS (`18 passed`, the other fixtures deselected: each new fixture is trimmed and VIN-free)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, then `… files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/partgrp server/src/realoem_mcp/parsers/partgrp.py server/tests/unit/parsers/test_partgrp.py server/tests/unit/parsers/test_partgrp_layout.py
git commit -m "feat(catalog): parse main groups, vehicle specs and diagram lists" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 2: The showparts parser

### Task 3: showparts fixtures and parser (`parsers/showparts.py`)

Site notes §5.4. The E90 325i oil pan (`11_3733`) is captured three times: USA 10/2005, USA 08/2006
(position 10 "Up To 04/2006" is filtered out) and EUR 10/2005 (identical table, different id). MINI
R56 and Motorrad R 1250 GS add rows without `edge` classes, German supplements and missing prices;
the oil-filter page was opened with the `lookup_part`-style id `VB13-USA-02_2004_E90_BMW_325i`
(PRD F3.5). The broken-page tests edit the E90 fixture.

**Files:**
- Create: `server/tests/fixtures/showparts/*.html` (6 files, generated), `server/src/realoem_mcp/parsers/showparts.py`
- Test: `server/tests/unit/parsers/test_showparts.py`, `server/tests/unit/parsers/test_showparts_layout.py`

- [ ] **Step 1: Generate the fixtures and write the failing tests**

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/07_showparts_E90_325i_11_3733_v2.html" tests/fixtures/showparts/e90_325i_11_3733.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/35_showparts_E90_325i_USA_200608_11_3733.html" tests/fixtures/showparts/e90_325i_200608_11_3733.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/34_showparts_E90_325i_EUR_VB11_11_3733.html" tests/fixtures/showparts/e90_325i_eur_11_3733.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/19_showparts_R56_CooperS_11_3910_v2.html" tests/fixtures/showparts/r56_cooper_s_11_3910.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/31_showparts_M_K50_R1250GS_11_5146_v2.html" tests/fixtures/showparts/k50_r1250gs_11_5146.html
uv run --directory server python scripts/trim_fixture.py "$RAW/xref/showparts_VB13_11_3867_v2.html" tests/fixtures/showparts/e90_325i_xref_id_11_3867.html
grep -c "var partsimgmap" server/tests/fixtures/showparts/*.html
```

Expected: `e90_325i_11_3733.html: 55582 -> 28408 bytes`,
`e90_325i_200608_11_3733.html: 54493 -> 27774 bytes`, `e90_325i_eur_11_3733.html: 55582 -> 28408 bytes`,
`r56_cooper_s_11_3910.html: 53016 -> 26293 bytes`, `k50_r1250gs_11_5146.html: 53710 -> 27144 bytes`,
`e90_325i_xref_id_11_3867.html: 49182 -> 23919 bytes`; then every `grep` line ends in `:1` (the
trimmer kept the `partsimgmap` script in all six).

Create `server/tests/unit/parsers/test_showparts.py`:

```python
import pytest

from realoem_mcp.models.catalog import DiagramParts
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
AUTOMATIC = {
    "text": "For vehicles with Automatic transmission",
    "option_codes": [{"code": "S205A", "value": "Yes"}],
}
ATTENTION = {
    "text": "Attention! Aluminum screws may only be used once. "
    "For additional information, refer to the repair manual!",
    "option_codes": [],
}


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


def _parse(fixture: str, vehicle_id: str, diag_id: str, services: Services) -> DiagramParts:
    return parse_showparts(
        load_fixture(f"showparts/{fixture}.html"),
        url=url("showparts", id=vehicle_id, diagId=diag_id),
        client=services.client,
        vehicle_id=vehicle_id,
        diag_id=diag_id,
    )


def _row(position: str, description: str, part_number: str, **fields: object) -> dict:
    """A PartRow dump with the E90 oil pan defaults (qty 1, indent 2, no dates or extras)."""
    row = {
        "position": position,
        "description": description,
        "supplement": None,
        "qty": "1",
        "valid_from": None,
        "valid_to": None,
        "part_number": part_number,
        "price_usd": None,
        "notes": None,
        "has_photo": False,
        "indent": 2,
        "conditions": [],
    }
    return row | fields


E90_OIL_PAN_ROWS = [
    _row("01", "Oil Pan", "11137552414", price_usd=551.84, notes="+core", conditions=[AUTOMATIC]),
    _row(
        "--",
        "Loctite 5970 liquid sealant",
        "83190404517",
        supplement="50ML",
        price_usd=23.4,
        conditions=[{"text": "Required for repair", "option_codes": []}, ATTENTION],
    ),
    _row("02", "Screw plug", "11137535106", supplement="M12X16", price_usd=3.68),
    _row(
        "03",
        "Gasket ring",
        "07119963151",
        supplement="A12X17-CU",
        price_usd=0.57,
        has_photo=True,
    ),
    _row("04", "Profile-gasket", "11137548031", price_usd=47.4),
    _row(
        "--",
        "Set of aluminium screws oil pan",
        "11132210959",
        conditions=[{"text": "only in conjunction with", "option_codes": []}, ATTENTION],
    ),
    _row(
        "05",
        "Set of aluminium screws oil pan",
        "11132210959",
        indent=3,
        conditions=[
            {
                "text": "For vehicles with Automatic transmission " + ATTENTION["text"],
                "option_codes": [{"code": "S205A", "value": "Yes"}],
            }
        ],
    ),
    _row("06", "Oilreturnpipe", "11437527133", price_usd=10.46, conditions=[AUTOMATIC]),
    _row("07", "O-ring", "11427548322", supplement="17X3", price_usd=2.42),
    _row("08", "Oil levelling sensor", "12617607910", has_photo=True),
    _row("09", "Gasket ring", "12611744292", price_usd=6.42, has_photo=True),
    _row(
        "10",
        "Hex nut with plate",
        "07119905544",
        supplement="M6-8-ZNNIV SI",
        qty="3",
        valid_to="2006-04",
        price_usd=0.64,
        has_photo=True,
    ),
    _row("11", "Protection cap", "11137543122", price_usd=2.17, indent=3),
]
OIL_PAN_HOTSPOTS = [
    ("01", 78, 255, 87, 271),
    ("02", 85, 70, 94, 87),
    ("02", 123, 232, 131, 249),
    ("03", 86, 95, 95, 111),
    ("03", 123, 278, 131, 294),
    ("04", 257, 44, 266, 61),
    ("05", 242, 391, 251, 407),
    ("06", 555, 227, 564, 243),
    ("07", 486, 226, 495, 243),
    ("08", 448, 336, 457, 352),
    ("09", 420, 314, 429, 331),
    ("10", 437, 420, 455, 437),
    ("11", 313, 23, 331, 39),
]


def _hotspots(parts: DiagramParts) -> list[tuple[str, int, int, int, int]]:
    return [(h.position, h.x1, h.y1, h.x2, h.y2) for h in parts.hotspots]


async def test_bmw_oil_pan_every_field(services: Services) -> None:
    parts = _parse("e90_325i_11_3733", E90, "11_3733", services)
    assert parts.diagram.model_dump() == {
        "vehicle_id": E90,
        "diag_id": "11_3733",
        "name": "Oil Pan",
        "url": url("showparts", id=E90, diagId="11_3733"),
    }
    assert parts.image_url == "https://www.realoem.com/bmw/images/diag_2zas.jpg"
    assert (parts.image_width, parts.image_height) == (640, 448)
    assert _hotspots(parts) == OIL_PAN_HOTSPOTS
    assert [row.model_dump() for row in parts.rows] == E90_OIL_PAN_ROWS
    assert parts.notes_legend == {
        "+core": "plus core charge (possibility of a return of the old part)"
    }


async def test_later_production_month_drops_rows_that_ended(services: Services) -> None:
    vehicle_id = "VB13-USA-08-2006-E90-BMW-325i"
    parts = _parse("e90_325i_200608_11_3733", vehicle_id, "11_3733", services)
    assert [row.model_dump() for row in parts.rows] == [
        row for row in E90_OIL_PAN_ROWS if row["position"] != "10"
    ]
    assert parts.diagram.vehicle_id == vehicle_id
    assert _hotspots(parts) == OIL_PAN_HOTSPOTS  # the image still marks position 10


async def test_eur_market_vehicle_gets_the_same_table(services: Services) -> None:
    vehicle_id = "VB11-EUR-10-2005-E90-BMW-325i"
    parts = _parse("e90_325i_eur_11_3733", vehicle_id, "11_3733", services)
    assert [row.model_dump() for row in parts.rows] == E90_OIL_PAN_ROWS
    assert parts.diagram.url == url("showparts", id=vehicle_id, diagId="11_3733")
    assert parts.rows[0].price_usd == 551.84  # prices are USD for every market


async def test_mini_rows_without_edge_classes_have_indent_zero(services: Services) -> None:
    vehicle_id = "MF73-USA-02-2008-R56-Mini-Cooper_S"
    parts = _parse("r56_cooper_s_11_3910", vehicle_id, "11_3910", services)
    assert parts.diagram.name == "Oil pan/oil level indicator"
    assert parts.image_url == "https://www.realoem.com/bmw/images/diag_6q63.jpg"
    assert [(r.position, r.part_number, r.indent) for r in parts.rows] == [
        ("01", "11137550483", 1),
        ("--", "83190404517", 3),
        ("02", "11137585928", 0),
        ("03", "11137546275", 0),
        ("03", "12617546239", 0),
        ("04", "11437585970", 0),
        ("05", "11437560212", 0),
        ("06", "11437586030", 0),
        ("07", "11437560211", 0),
        ("08", "11317542856", 0),
        ("09", "11137578545", 0),
        ("10", "83190404517", 3),
    ]
    assert [c.text for c in parts.rows[1].conditions] == ["Required for repair"]
    assert [c.text for c in parts.rows[-1].conditions] == ["See PuMA measure 50752218"]
    assert (parts.rows[3].valid_to, parts.rows[4].valid_to) == ("2023-09", None)
    assert parts.notes_legend == {}


async def test_motorcycle_german_supplements_and_missing_prices(services: Services) -> None:
    vehicle_id = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    parts = _parse("k50_r1250gs_11_5146", vehicle_id, "11_5146", services)
    assert parts.diagram.name == "Screw connection, engine housing"
    assert [(r.description, r.supplement, r.price_usd) for r in parts.rows[:3]] == [
        ("Crankcase", "SILBER", None),
        ("Crankcase", "SCHWARZ", None),
        ("ISA screw", "M6X30-8.8-ZNNIV", None),
    ]
    assert len(parts.rows) == 11
    assert {row.indent for row in parts.rows} == {0}
    assert parts.rows[3].price_usd == 16.92


async def test_xref_style_vehicle_id_is_kept_as_given(services: Services) -> None:
    vehicle_id = "VB13-USA-02_2004_E90_BMW_325i"  # as in lookup_part model rows
    parts = _parse("e90_325i_xref_id_11_3867", vehicle_id, "11_3867", services)
    assert parts.diagram.model_dump() == {
        "vehicle_id": vehicle_id,
        "diag_id": "11_3867",
        "name": "Lubrication system-Oil filter",
        "url": url("showparts", id=vehicle_id, diagId="11_3867"),
    }
    assert parts.rows[2].model_dump() == _row(
        "03", "Set oil-filter element", "11427953129", indent=0
    )
```

Create `server/tests/unit/parsers/test_showparts_layout.py`:

```python
import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


@pytest.mark.parametrize(
    ("edits", "detail"),
    [
        ([('<div id="partsimg">', '<div id="image">')], "missing '#partsimg img'"),
        (
            [('width="640" height="448" alt="Oil Pan"', 'alt="Oil Pan"')],
            "diagram image without alt, src, width or height",
        ),
        ([('<table id="partsList"', '<table id="parts"')], "missing 'table#partsList'"),
        ([("<th ", "<td "), ("</th>", "</td>")], "parts table has no header row"),
        ([("var partsimgmap", "var partsmap")], "no partsimgmap script"),
        (
            [('["01",78,255,87,271]', '["01",78,255,87]')],
            "unexpected partsimgmap entry ['01', 78, 255, 87]",
        ),
        ([('["11",313,23,331,39]]', '["11",313,23,331,39],]')], "partsimgmap is not valid JSON"),
        ([('<tr class="r0 pos02">', '<tr class="r0">')], "parts table row without a pos class"),
        ([('<td colspan="8"></td>', "")], "parts table row with 3 cells"),
        (
            [('<td class="edge2">Oil Pan</td>', '<td class="edge2"></td>')],
            "part row without position or description",
        ),
        ([("S205A</a>=Yes", "S205A</a>")], "option code 'S205A' without =value"),
        (
            [("<li>+core = plus", "<li>+core plus")],
            "notes legend entry '+core plus core charge (possibility of a return of the old "
            "part)' has no '='",
        ),
    ],
    ids=[
        "no-image",
        "no-image-size",
        "no-table",
        "no-header",
        "no-hotspots",
        "bad-hotspot",
        "hotspots-not-json",
        "no-pos-class",
        "bad-cell-count",
        "no-description",
        "option-without-value",
        "legend-without-meaning",
    ],
)
async def test_broken_parts_page(
    services: Services, edits: list[tuple[str, str]], detail: str
) -> None:
    html = load_fixture("showparts/e90_325i_11_3733.html")
    for old, new in edits:
        assert old in html, old
        html = html.replace(old, new)
    with pytest.raises(LayoutChanged) as info:
        parse_showparts(
            html,
            url=url("showparts", id=E90, diagId="11_3733"),
            client=services.client,
            vehicle_id=E90,
            diag_id="11_3733",
        )
    assert info.value.detail == detail
    assert info.value.page_type == "showparts"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory server pytest tests/unit/parsers/test_showparts.py tests/unit/parsers/test_showparts_layout.py -q`
Expected: FAIL (`2 errors`: collecting both files fails with `ModuleNotFoundError: No module named 'realoem_mcp.parsers.showparts'`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/showparts.py`:

```python
"""showparts page (site notes 5.4): diagram image, hotspots, parts table, notes legend."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import groupby
from urllib.parse import urljoin

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.catalog import Condition, DiagramParts, Hotspot, OptionCode, PartRow
from realoem_mcp.models.common import DiagramRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, Tree, parse_my, parse_price_usd, require, text, tree

PAGE = PageType.SHOWPARTS
# Part row cells: pos, description, supplement, qty, from, up to, part number, price, photo,
# notes, ECS link. Condition row cells: empty, text, option codes, colspan=8 filler.
PART_CELLS = 11
CONDITION_CELLS = 4
_HOTSPOTS = re.compile(r"var\s+partsimgmap\s*=\s*(\[.*?\])\s*;", re.DOTALL)
_POS_CLASS = re.compile(r"pos\S+")
_EDGE_CLASS = re.compile(r"edge([1-3])")


@dataclass
class _Part:
    cells: list[Node]
    conditions: list[Condition] = field(default_factory=list)


def parse_showparts(
    html: str, *, url: str, client: RealOemClient, vehicle_id: str, diag_id: str
) -> DiagramParts:
    root = tree(html)
    img = require(root, "#partsimg img", PAGE, url)
    name = (img.attributes.get("alt") or "").strip()
    src = img.attributes.get("src")
    width, height = img.attributes.get("width") or "", img.attributes.get("height") or ""
    if not name or not src or not width.isdigit() or not height.isdigit():
        raise LayoutChanged(PAGE, "diagram image without alt, src, width or height", url)
    table = require(root, "table#partsList", PAGE, url)
    if table.css_first("tr th") is None:
        raise LayoutChanged(PAGE, "parts table has no header row", url)
    return DiagramParts(
        diagram=DiagramRef.build(client, vehicle_id, diag_id, name),
        image_url=urljoin(url, src),
        image_width=int(width),
        image_height=int(height),
        hotspots=_hotspots(root, url),
        rows=[_part_row(part, url) for part in _parts(table, url)],
        notes_legend=_notes_legend(root, url),
    )


def _hotspots(root: Tree, url: str) -> list[Hotspot]:
    """var partsimgmap=[["01",78,255,87,271],...]: [position, x1, y1, x2, y2] per box."""
    for script in root.css("script"):
        match = _HOTSPOTS.search(script.text(deep=True))
        if match is None:
            continue
        try:
            entries = json.loads(match.group(1))
        except ValueError:
            raise LayoutChanged(PAGE, "partsimgmap is not valid JSON", url) from None
        hotspots = []
        for entry in entries:
            if not _is_hotspot(entry):
                raise LayoutChanged(PAGE, f"unexpected partsimgmap entry {entry!r}", url)
            position, x1, y1, x2, y2 = entry
            hotspots.append(Hotspot(position=position, x1=x1, y1=y1, x2=x2, y2=y2))
        return hotspots
    raise LayoutChanged(PAGE, "no partsimgmap script", url)


def _is_hotspot(entry: object) -> bool:
    return (
        isinstance(entry, list)
        and len(entry) == 5
        and isinstance(entry[0], str)
        and all(type(value) is int for value in entry[1:])
    )


def _parts(table: Node, url: str) -> list[_Part]:
    """Part rows with their conditions (the colspan=8 rows of the same position).

    A run of condition rows applies to every following part row of that position until the
    next condition row; condition rows after a position's last part row (e.g. a trailing
    "Attention!" note) belong to that last part row.
    """
    parts: list[_Part] = []
    for _, rows in groupby(_data_rows(table, url), key=lambda row: row[0]):
        run: list[Condition] = []  # the latest run of consecutive condition rows
        in_run = False
        last: _Part | None = None  # the latest part row of this position
        for _, cells in rows:
            if len(cells) == PART_CELLS:
                last = _Part(cells=cells, conditions=list(run))
                parts.append(last)
                in_run = False
            else:
                if not in_run:
                    run = []
                run.append(_condition(cells, url))
                in_run = True
        if in_run and last is not None:
            last.conditions.extend(run)
    return parts


def _data_rows(table: Node, url: str) -> Iterator[tuple[str, list[Node]]]:
    """(posNN class, cells) of every part and condition row; the header row is skipped."""
    for row in table.css("tr"):
        cells = row.css("td")
        if not cells:
            continue  # header row (th cells)
        classes = (row.attributes.get("class") or "").split()
        position = next((name for name in classes if _POS_CLASS.fullmatch(name)), None)
        if position is None:
            raise LayoutChanged(PAGE, "parts table row without a pos class", url)
        condition = len(cells) == CONDITION_CELLS and cells[-1].attributes.get("colspan") == "8"
        if len(cells) != PART_CELLS and not condition:
            raise LayoutChanged(PAGE, f"parts table row with {len(cells)} cells", url)
        yield position, cells


def _condition(cells: list[Node], url: str) -> Condition:
    codes: list[OptionCode] = []
    for link in cells[2].css("a.opt-code"):
        code = text(link)
        after = link.next
        raw = after.text(deep=False).strip() if after is not None and after.is_text_node else ""
        if not code or not raw.startswith("=") or not raw[1:].strip():
            raise LayoutChanged(PAGE, f"option code {code!r} without =value", url)
        codes.append(OptionCode(code=code, value=raw[1:].strip()))
    return Condition(text=_cell_text(cells[1]), option_codes=codes)


def _part_row(part: _Part, url: str) -> PartRow:
    cells = part.cells
    position, description = _cell_text(cells[0]), _cell_text(cells[1])
    if not position or not description:
        raise LayoutChanged(PAGE, "part row without position or description", url)
    edge = _EDGE_CLASS.search(cells[1].attributes.get("class") or "")
    return PartRow(
        position=position,
        description=description,
        supplement=_cell_text(cells[2]) or None,
        qty=_cell_text(cells[3]) or None,
        valid_from=parse_my(_cell_text(cells[4])),
        valid_to=parse_my(_cell_text(cells[5])),
        part_number=_cell_text(cells[6]) or None,
        price_usd=parse_price_usd(_cell_text(cells[7])),
        notes=_cell_text(cells[9]) or None,
        has_photo=cells[8].css_first('a[href*="/photos/"]') is not None,
        indent=int(edge.group(1)) if edge else 0,
        conditions=part.conditions,
    )


def _notes_legend(root: Tree, url: str) -> dict[str, str]:
    legend: dict[str, str] = {}
    for item in root.css("div.notes li"):
        key, sep, meaning = text(item).partition("=")
        if not sep or not key.strip():
            raise LayoutChanged(PAGE, f"notes legend entry {text(item)!r} has no '='", url)
        legend[key.strip()] = meaning.strip()
    return legend


def _cell_text(cell: Node) -> str:
    """Cell text with <br> and element boundaries as spaces, whitespace collapsed."""
    return " ".join(cell.text(deep=True, separator=" ").split())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/parsers/test_showparts.py tests/unit/parsers/test_showparts_layout.py -q`
Expected: PASS (`18 passed`)

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q -k showparts`
Expected: PASS (`12 passed`, the other fixtures deselected)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, then `… files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/showparts server/src/realoem_mcp/parsers/showparts.py server/tests/unit/parsers/test_showparts.py server/tests/unit/parsers/test_showparts_layout.py
git commit -m "feat(catalog): parse parts lists with conditions, hotspots and notes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 3: The model cascade tool

### Task 4: `select_vehicle` (PRD F3.1)

One `select` request per call with the parameters in ARD order (`product`, `archive`, `series`,
`body`, `model`, `market`, `prod`, `engine`, `steering`, `trans`; only those given). VIN decode's
`parse_select` reads every level; the tool reports the effective selection (auto-selected levels
included), the first open level with its options, or the finished vehicle. Three new select pages
(in `fixtures/catalog/`, since `fixtures/select/` belongs to VIN decode) complete the cascade tests;
the other routes reuse VIN decode's fixtures. A redirect away from `select` is `NotFound`, and a page
with neither an open level nor a vehicle id is `LayoutChanged` (expired, so asked for again). This task creates
`tools/catalog.py` with `select_vehicle` only; Task 5 replaces the file with the complete module.

**Files:**
- Create: `server/tests/fixtures/catalog/cascade_motorcycles.html`, `server/tests/fixtures/catalog/cascade_e90_325i_usa_200510.html`, `server/tests/fixtures/catalog/cascade_k50_r1250gs_usa_201905.html` (generated), `server/src/realoem_mcp/tools/catalog.py`
- Test: `server/tests/tools/test_select_vehicle.py`

- [ ] **Step 1: Generate the fixtures and write the failing test**

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/25_select_M_root.html" tests/fixtures/catalog/cascade_motorcycles.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/04_select_P_E90_325i_USA_200510.html" tests/fixtures/catalog/cascade_e90_325i_usa_200510.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/28_select_M_K50_R1250GS_USA_201905.html" tests/fixtures/catalog/cascade_k50_r1250gs_usa_201905.html
```

Expected: `cascade_motorcycles.html: 41711 -> 20226 bytes`,
`cascade_e90_325i_usa_200510.html: 74189 -> 50405 bytes`,
`cascade_k50_r1250gs_usa_201905.html: 52213 -> 29006 bytes`.

Create `server/tests/tools/test_select_vehicle.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import LANDING_URL, Route, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = {"product": "P", "archive": "0", "series": "E90"}
E90_325I = E90 | {"body": "Lim", "model": "325i"}
E90_USA = E90_325I | {"market": "USA", "prod": "20051000"}
E90_EUR = E90_325I | {"market": "EUR", "prod": "20051000"}
K50_MODEL = "R 1250 GS 19 (0J91, 0J93)"
K50_USA = {
    "product": "M",
    "archive": "0",
    "series": "K50",
    "model": K50_MODEL,
    "market": "USA",
    "prod": "20190500",
}
ROUTES = {
    url("select", product="M", archive="0"): "catalog/cascade_motorcycles.html",
    url("select", **E90): "select/cascade_e90.html",
    url("select", **E90_325I): "select/cascade_e90_325i.html",
    url("select", **E90_USA): "catalog/cascade_e90_325i_usa_200510.html",
    url("select", **E90_EUR): "select/cascade_e90_325i_eur_200510.html",
    url("select", product="P", archive="1", series="E46"): "select/cascade_classic_e46.html",
    url("select", **K50_USA): "catalog/cascade_k50_r1250gs_usa_201905.html",
}


def _option(value: str, label: str, *, selected: bool = True) -> dict[str, Any]:
    return {"value": value, "label": label, "selected": selected}


async def _select(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def test_select_vehicle_is_listed_with_levels_in_send_order(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    tool = tools["select_vehicle"]
    assert list(tool.input_schema["properties"]) == [
        "product",
        "archive",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
        "steering",
        "trans",
        "refresh",
    ]
    assert tool.input_schema["properties"]["product"]["default"] == "P"
    assert "catalog, whose parameter is archive" in tool.description


async def test_first_step_lists_series_with_product_and_catalog_auto_selected(
    make_services,
) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, product="M", archive="0")
    assert (data["complete"], data["next_level"]) == (False, "series")
    assert data["selected"] == {
        "product": _option("M", "Motorcycle"),
        "catalog": _option("0", "Current"),
    }
    assert len(data["options"]) == 87
    assert data["options"][2] == _option(
        "K50", "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)", selected=False
    )
    assert (data["vehicle"], data["type_code"], data["summary"]) == (None, None, None)
    assert [str(r.url) for r in transport.requests] == [url("select", product="M", archive="0")]


async def test_product_defaults_to_cars_and_auto_selected_body_is_reported(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, archive="0", series="E90")
    assert data["selected"]["series"] == _option("E90", "3' E90 (2004 — 2023)")
    assert data["selected"]["body"] == _option("Lim", "Sedan")  # the only body: auto-selected
    assert data["next_level"] == "model"
    assert [option["value"] for option in data["options"]][:3] == ["316i", "318d", "318i"]
    assert len(data["options"]) == 20
    assert [str(r.url) for r in transport.requests] == [url("select", **E90)]


async def test_usa_market_is_auto_selected(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_325I)
    assert data["selected"]["market"] == _option("USA", "USA")
    assert data["next_level"] == "prod"
    assert data["options"][0] == _option("20040200", "02/2004", selected=False)
    assert len(data["options"]) == 27


async def test_eur_market_asks_for_steering(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_EUR)
    assert data["selected"]["engine"] == _option("N52", "N52")
    assert data["next_level"] == "steering"
    assert data["options"] == [
        _option("L", "Left hand drive", selected=False),
        _option("R", "Right hand drive", selected=False),
    ]


async def test_classic_catalog_is_sent_as_archive(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _select(services, archive="1", series="E46")
    assert data["selected"]["catalog"] == _option("1", "Classic")
    assert data["next_level"] == "body"
    assert [option["value"] for option in data["options"]] == ["Lim", "Cab", "Cou", "com", "tou"]
    assert [str(r.url) for r in transport.requests] == [
        url("select", product="P", archive="1", series="E46")
    ]


async def test_complete_car_selection_returns_the_vehicle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **E90_USA)
    data.pop("fetched_at")
    selected = data.pop("selected")
    assert data == {
        "source_urls": [url("select", **E90_USA)],
        "from_cache": False,
        "requests_made": 1,
        "next_level": None,
        "options": [],
        "complete": True,
        "vehicle": {
            "vehicle_id": "VB13-USA-10-2005-E90-BMW-325i",
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "type_code": "VB13",
        "summary": "3 Series E90 BMW 325i",
    }
    assert {level: option["value"] for level, option in selected.items()} == {
        "product": "P",
        "catalog": "0",
        "series": "E90",
        "body": "Lim",
        "model": "325i",
        "market": "USA",
        "prod": "20051000",
        "engine": "N52",
    }


async def test_complete_motorcycle_selection_is_a_motorrad_vehicle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _select(services, **K50_USA)
    assert data["complete"] is True
    assert data["vehicle"]["vehicle_id"] == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert data["vehicle"]["brand"] == "motorrad"
    assert data["selected"]["model"] == _option(K50_MODEL, K50_MODEL)
    assert "body" not in data["selected"]


async def test_repeat_call_is_answered_from_the_cache(make_services) -> None:
    services, transport = make_services(ROUTES)
    await _select(services, **E90)
    again = await _select(services, **E90)
    assert (again["from_cache"], again["requests_made"]) == (True, 0)
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"product": "X"}, "Input should be 'P' or 'M'"),
        ({"archive": "2"}, "Input should be '0' or '1'"),
        ({"series": " "}, "series must not be empty"),
        ({"series": "E90", "prod": "10/2005"}, "prod is a production month as YYYYMM00"),
        ({"series": "E90", "prod": "20051300"}, "prod is a production month as YYYYMM00"),
    ],
    ids=["product", "archive", "empty-series", "prod-format", "prod-month"],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unparseable_select_page_is_not_kept_in_the_cache(make_services) -> None:
    target = url("select", **E90)
    services, transport = make_services({target: "select/vin_bmw_e93_px22770_v1.html"})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("select_vehicle", E90)
        second = await client.call_tool("select_vehicle", E90)
    for result in (first, second):
        assert result.is_error is True
        assert "RealOEM's select page did not have the expected structure" in (
            result.content[0].text
        )
    assert [str(r.url) for r in transport.requests] == [target, target]


async def test_redirect_to_the_landing_page_is_not_found(make_services) -> None:
    target = url("select", product="P", archive="0", series="XYZ")
    services, transport = make_services({target: Route(redirect_to=LANDING_URL)})
    async with Client(build_server(services)) as client:
        result = await client.call_tool("select_vehicle", {"archive": "0", "series": "XYZ"})
    assert result.is_error is True
    assert "RealOEM did not show a selection page for these values" in result.content[0].text
    assert [str(r.url) for r in transport.requests] == [target, LANDING_URL]


async def test_page_without_open_level_or_vehicle_is_a_layout_error(
    make_services, tmp_path: Path
) -> None:
    html = load_fixture("catalog/cascade_e90_325i_usa_200510.html")
    assert 'name="id"' in html
    page = tmp_path / "select_without_vehicle.html"
    page.write_text(html.replace('name="id"', 'name="vehicle"'), encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    target = url("select", **E90_USA)
    services, transport = make_services({target: str(page)})
    async with Client(build_server(services)) as client:
        for _ in range(2):
            result = await client.call_tool("select_vehicle", E90_USA)
            assert result.is_error is True
            assert "no open level and no vehicle id" in result.content[0].text
    assert len(transport.requests) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_select_vehicle.py -q`
Expected: FAIL (`17 failed`: the tool does not exist yet, so the listing test raises `KeyError: 'select_vehicle'` and every call returns `Unknown tool: select_vehicle`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/tools/catalog.py`:

```python
"""Catalog tools (feature C, ARD section 5.11): the model cascade (select_vehicle)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import VehicleSelectionResult
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
_PROD = re.compile(r"\d{4}(0[1-9]|1[0-2])00")


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def select_vehicle(
        product: Literal["P", "M"] = "P",
        archive: Literal["0", "1"] | None = None,
        series: str | None = None,
        body: str | None = None,
        model: str | None = None,
        market: str | None = None,
        prod: str | None = None,
        engine: str | None = None,
        steering: str | None = None,
        trans: str | None = None,
        refresh: bool = False,
    ) -> VehicleSelectionResult:
        """Pick a vehicle in RealOEM's catalog one level at a time, when there is no VIN.

        Levels in order: product (P cars incl. MINI and Rolls-Royce, M motorcycles), catalog
        (sent as archive: 0 current, 1 classic for older models such as E30/E36/E46/R53),
        series, body, model, market, prod (production month as YYYYMM00, e.g. 20051000),
        engine, steering, trans (the last two mostly for classic cars). Call it first with
        just product (or nothing), then call again with every value in `selected` plus the
        `value` of your choice from `options` for `next_level`. Levels with a single option
        (and USA under this US catalog) are auto-selected and appear in `selected`. Parameter
        names equal level names except catalog, whose parameter is archive. When complete is
        true, vehicle.vehicle_id is ready for list_part_groups. refresh=true ignores the cache.
        """
        levels = {
            "product": product,
            "archive": archive,
            "series": series,
            "body": body,
            "model": model,
            "market": market,
            "prod": prod,
            "engine": engine,
            "steering": steering,
            "trans": trans,
        }
        try:
            return await _select(services, levels, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err


async def _select(
    services: Services, levels: dict[str, str | None], *, refresh: bool
) -> VehicleSelectionResult:
    params: dict[str, str] = {}
    for name, value in levels.items():
        if value is None:
            continue
        if not value.strip():
            raise InvalidInput(f"{name} must not be empty; leave it out instead.")
        params[name] = value.strip()
    if "prod" in params and not _PROD.fullmatch(params["prod"]):
        raise InvalidInput(
            f"prod is a production month as YYYYMM00 (e.g. 20051000), got {params['prod']!r}."
        )
    page = await services.client.fetch(PageType.SELECT, "select", params, refresh=refresh)
    if page.redirected_away:
        raise NotFound(
            "RealOEM did not show a selection page for these values; start again with only "
            "product and add one level at a time from the options it returns."
        )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        open_level = next((level for level in select.levels if level.selected_option is None), None)
        if select.vehicle_id is None and open_level is None:
            raise LayoutChanged(PageType.SELECT, "no open level and no vehicle id", page.url)
    selected = {
        level.level: level.selected_option
        for level in select.levels
        if level.selected_option is not None
    }
    if select.vehicle_id is None:
        return VehicleSelectionResult.from_pages(
            [page],
            selected=selected,
            next_level=open_level.level,
            options=open_level.options,
            complete=False,
            vehicle=None,
            type_code=None,
            summary=None,
        )
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    product = selected["product"].value if "product" in selected else None
    brand = services.brands.for_vehicle_id(vid, product=product)
    return VehicleSelectionResult.from_pages(
        [page],
        selected=selected,
        next_level=None,
        options=[],
        complete=True,
        vehicle=VehicleRef.from_id(vid, brand.id),
        type_code=select.type_code,
        summary=select.summary,
    )


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/tools/test_select_vehicle.py -q`
Expected: PASS (`17 passed`)

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q -k "cascade_motorcycles or cascade_e90_325i_usa_200510 or cascade_k50_r1250gs_usa_201905"`
Expected: PASS (`6 passed`, the other fixtures deselected)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, then `… files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/catalog/cascade_motorcycles.html server/tests/fixtures/catalog/cascade_e90_325i_usa_200510.html server/tests/fixtures/catalog/cascade_k50_r1250gs_usa_201905.html server/src/realoem_mcp/tools/catalog.py server/tests/tools/test_select_vehicle.py
git commit -m "feat(catalog): add select_vehicle model cascade tool" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 4: Main group, diagram and parts tools

### Task 5: `list_part_groups`, `list_diagrams`, `get_diagram_parts` and the fetch helpers (PRD F3.2–F3.5)

One request each: `partgrp` with `id`; `partgrp` with `id`, `mg`; `showparts` with `id`, `diagId`.
A redirect away from the requested page (RealOEM sends unknown ids to `/bmw/`) is `NotFound` and is
never cached by the client, so each call asks again. `Route(redirect_to=LANDING_URL)` reproduces it
(the harness answers the landing URL with an empty 200, so a redirected call records two requests).
The missing-main-group test serves RealOEM's real answer for `mg=99` twice: the second call is
answered from the cache, whose entry lives exactly 1 day (read from the SQLite cache file).
A second test writes an E90 diagram list with an empty `.diagThumbs` to `tmp_path` and routes to
its absolute path (`FIXTURES / "<absolute path>"` is that absolute path): `[]` is `NotFound` too.
`fetch_diagram_list` and `fetch_diagram_parts` are exported for feature D; their `cache_only` mode is
tested directly.

**Files:**
- Modify: `server/src/realoem_mcp/tools/catalog.py` (replace the whole file)
- Test: `server/tests/tools/test_part_groups.py`, `server/tests/tools/test_diagram_parts.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/tools/test_part_groups.py`:

```python
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import LANDING_URL, Route, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
K50 = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
GARBAGE = "VB13-USA-03-2006-XXX-YYY-ZZZ"
UNKNOWN = "VB13-USA-01-1990-E90-BMW-325i"  # well-formed; see the redirect routes below
GROUPS_E90 = url("partgrp", id=E90)
DIAGRAMS_E90 = url("partgrp", id=E90, mg="11")
ROUTES = {
    GROUPS_E90: "common/partgrp_e90_325i.html",
    url("partgrp", id=GARBAGE): "partgrp/e90_325i_garbage_suffix.html",
    url("partgrp", id=K50): "partgrp/k50_r1250gs.html",
    DIAGRAMS_E90: "partgrp/e90_325i_mg11.html",
    url("partgrp", id=K50, mg="11"): "partgrp/k50_r1250gs_mg11.html",
    # RealOEM answers with a redirect to the landing page for ids it doesn't know.
    url("partgrp", id=UNKNOWN): Route(redirect_to=LANDING_URL),
    url("partgrp", id=UNKNOWN, mg="11"): Route(redirect_to=LANDING_URL),
}


async def _call(services: Services, tool: str, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def _error(services: Services, tool: str, **arguments: Any) -> str:
    async with Client(build_server(services)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error is True
    return result.content[0].text


async def test_list_part_groups_returns_specs_and_main_groups(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=E90)
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == (
        [GROUPS_E90],
        False,
        1,
    )
    assert data["specs"] == {
        "vehicle": {
            "vehicle_id": E90,
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "model_name": "3 Series E90 325i",
        "body": "Sedan",
        "engine": "N52",
        "steering": "Left-hand drive",
        "transmission": None,
    }
    assert len(data["main_groups"]) == 39
    assert data["main_groups"][4] == {"mg": "11", "name": "ENGINE"}
    assert [str(r.url) for r in transport.requests] == [GROUPS_E90]


async def test_list_part_groups_reports_the_canonical_vehicle_id(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=GARBAGE)
    assert data["source_urls"] == [url("partgrp", id=GARBAGE)]
    assert data["specs"]["vehicle"]["vehicle_id"] == "VB13-USA-03-2006-E90-BMW-325i"


async def test_list_part_groups_for_a_motorcycle(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_part_groups", vehicle_id=K50)
    assert data["specs"]["vehicle"]["brand"] == "motorrad"
    assert data["specs"]["body"] is None
    assert data["main_groups"][-1] == {
        "mg": "77",
        "name": "OPTIONAL EQUIPMENT+ACCESSORIES, MOTORRAD",
    }


async def test_list_diagrams_returns_subgroups_with_diagram_refs(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_diagrams", vehicle_id=E90, main_group="11")
    assert (data["vehicle_id"], data["main_group"], data["source_urls"]) == (
        E90,
        "11",
        [DIAGRAMS_E90],
    )
    assert [subgroup["code"] for subgroup in data["subgroups"]] == [
        "05",
        "10",
        "15",
        "18",
        "20",
        "25",
        "30",
        "35",
        "40",
        "45",
        "88",
    ]
    assert data["subgroups"][6]["diagrams"][2] == {
        "diagram": {
            "vehicle_id": E90,
            "diag_id": "11_3867",
            "name": "LUBRICATION SYSTEM-OIL FILTER",
            "url": url("showparts", id=E90, diagId="11_3867"),
        },
        "thumbnail_url": "https://www.realoem.com/bmw/images/thumb_4ipx.jpg",
    }


async def test_list_diagrams_dedupes_motorrad_names(make_services) -> None:
    services, _ = make_services(ROUTES)
    data = await _call(services, "list_diagrams", vehicle_id=K50, main_group="11")
    first = data["subgroups"][0]
    assert first["name"] == "Engine / Running Gear"
    assert first["diagrams"][1]["diagram"]["name"] == "SHORT ENGINE / CYLINDER WITH PISTONS"


@pytest.mark.parametrize(
    ("tool", "arguments", "requested"),
    [
        ("list_part_groups", {}, url("partgrp", id=UNKNOWN)),
        ("list_diagrams", {"main_group": "11"}, url("partgrp", id=UNKNOWN, mg="11")),
    ],
)
async def test_unknown_vehicle_is_not_found_and_not_cached(
    make_services, tool: str, arguments: dict[str, str], requested: str
) -> None:
    services, transport = make_services(ROUTES)
    for _ in range(2):
        message = await _error(services, tool, vehicle_id=UNKNOWN, **arguments)
        assert message.endswith(
            f"RealOEM has no vehicle {UNKNOWN}. Use a vehicle id from decode_vin or select_vehicle."
        )
    assert [str(r.url) for r in transport.requests] == [requested, LANDING_URL] * 2


async def test_missing_main_group_is_not_found_and_cached_for_a_day(make_services) -> None:
    target = url("partgrp", id=E90, mg="99")
    services, transport = make_services({target: "partgrp/e90_325i_mg99.html"})
    for _ in range(2):
        message = await _error(services, "list_diagrams", vehicle_id=E90, main_group="99")
        assert message.endswith(
            f"vehicle {E90} has no main group 99; list_part_groups shows the ones it has."
        )
    assert [str(r.url) for r in transport.requests] == [target]  # the second call hit the cache
    with closing(sqlite3.connect(services.cache.path)) as conn:
        fetched_at, expires_at = conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (target,)
        ).fetchone()
    assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at) == timedelta(
        days=1
    )


async def test_diagram_list_without_diagrams_is_not_found(make_services, tmp_path: Path) -> None:
    empty = re.sub(
        r'(<div class="diagThumbs">).*?(<div class="blk gad-tall-right">)',
        r"\1</div></div>\2",
        load_fixture("partgrp/e90_325i_mg11.html"),
        flags=re.DOTALL,
    )
    page = tmp_path / "partgrp_mg11_empty.html"
    page.write_text(empty, encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    services, _ = make_services({DIAGRAMS_E90: str(page)})
    message = await _error(services, "list_diagrams", vehicle_id=E90, main_group="11")
    assert message.endswith(
        f"vehicle {E90} has no main group 11; list_part_groups shows the ones it has."
    )


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("list_part_groups", {"vehicle_id": ""}, "The vehicle id is empty."),
        ("list_part_groups", {"vehicle_id": "VB13"}, "'VB13' is not a RealOEM vehicle id"),
        ("list_diagrams", {"vehicle_id": E90, "main_group": "1"}, "main_group must be a two-digit"),
        ("list_diagrams", {"vehicle_id": E90, "main_group": "ENGINE"}, "main_group must be"),
        ("list_diagrams", {"vehicle_id": "E90 325i", "main_group": "11"}, "not a RealOEM vehicle"),
    ],
    ids=["empty-id", "id-without-market", "short-mg", "named-mg", "bad-id"],
)
async def test_bad_input_is_rejected_before_any_request(
    make_services, tool: str, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services(ROUTES)
    assert message in await _error(services, tool, **arguments)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("tool", "arguments", "target", "fixture"),
    [
        ("list_part_groups", {}, GROUPS_E90, "partgrp/e90_325i_mg11.html"),
        (
            "list_diagrams",
            {"main_group": "11"},
            DIAGRAMS_E90,
            "partgrp/e90_325i_mg11_textmode.html",
        ),
    ],
)
async def test_unparseable_page_is_an_error_and_not_kept_in_the_cache(
    make_services, tool: str, arguments: dict[str, str], target: str, fixture: str
) -> None:
    services, transport = make_services({target: fixture})
    for _ in range(2):
        message = await _error(services, tool, vehicle_id=E90, **arguments)
        assert "RealOEM's partgrp page did not have the expected structure" in message
    assert [str(r.url) for r in transport.requests] == [target, target]
```

Create `server/tests/tools/test_diagram_parts.py`:

```python
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.errors import InvalidInput, NotFound
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.tools.catalog import fetch_diagram_list, fetch_diagram_parts
from tests.harness import LANDING_URL, Route, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
XREF_ID = "VB13-USA-02_2004_E90_BMW_325i"  # form used by lookup_part model rows
UNKNOWN = "VB13-USA-01-1990-E90-BMW-325i"  # well-formed; see the redirect route below
OIL_PAN = url("showparts", id=E90, diagId="11_3733")
ENGINE = url("partgrp", id=E90, mg="11")
ROUTES = {
    OIL_PAN: "showparts/e90_325i_11_3733.html",
    url("showparts", id=XREF_ID, diagId="11_3867"): "showparts/e90_325i_xref_id_11_3867.html",
    # RealOEM answers with a redirect to the landing page for ids it doesn't know.
    url("showparts", id=UNKNOWN, diagId="11_3733"): Route(redirect_to=LANDING_URL),
    ENGINE: "partgrp/e90_325i_mg11.html",
}


async def _call(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("get_diagram_parts", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def _error(services: Services, **arguments: Any) -> str:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("get_diagram_parts", arguments)
    assert result.is_error is True
    return result.content[0].text


async def test_get_diagram_parts_returns_image_hotspots_rows_and_legend(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, vehicle_id=E90, diag_id="11_3733")
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == ([OIL_PAN], False, 1)
    assert data["diagram"] == {
        "vehicle_id": E90,
        "diag_id": "11_3733",
        "name": "Oil Pan",
        "url": OIL_PAN,
    }
    assert (data["image_url"], data["image_width"], data["image_height"]) == (
        "https://www.realoem.com/bmw/images/diag_2zas.jpg",
        640,
        448,
    )
    assert data["hotspots"][0] == {"position": "01", "x1": 78, "y1": 255, "x2": 87, "y2": 271}
    assert len(data["hotspots"]) == 13
    assert len(data["rows"]) == 13
    assert data["rows"][0] == {
        "position": "01",
        "description": "Oil Pan",
        "supplement": None,
        "qty": "1",
        "valid_from": None,
        "valid_to": None,
        "part_number": "11137552414",
        "price_usd": 551.84,
        "notes": "+core",
        "has_photo": False,
        "indent": 2,
        "conditions": [
            {
                "text": "For vehicles with Automatic transmission",
                "option_codes": [{"code": "S205A", "value": "Yes"}],
            }
        ],
    }
    assert data["notes_legend"] == {
        "+core": "plus core charge (possibility of a return of the old part)"
    }
    assert [str(r.url) for r in transport.requests] == [OIL_PAN]


async def test_vehicle_ids_from_part_lookups_are_accepted(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _call(services, vehicle_id=XREF_ID, diag_id="11_3867")
    assert data["diagram"]["vehicle_id"] == XREF_ID
    assert data["rows"][2]["part_number"] == "11427953129"
    assert [str(r.url) for r in transport.requests] == [
        url("showparts", id=XREF_ID, diagId="11_3867")
    ]


async def test_unknown_vehicle_is_not_found_and_not_cached(make_services) -> None:
    services, transport = make_services(ROUTES)
    for _ in range(2):
        message = await _error(services, vehicle_id=UNKNOWN, diag_id="11_3733")
        assert message.endswith(
            f"RealOEM has no vehicle {UNKNOWN}. Use a vehicle id from decode_vin or select_vehicle."
        )
    requested = url("showparts", id=UNKNOWN, diagId="11_3733")
    assert [str(r.url) for r in transport.requests] == [requested, LANDING_URL] * 2


@pytest.mark.parametrize("diag_id", ["11-3733", "3733", "11_", "ab_3733", "11_3733#x"])
async def test_bad_diag_id_is_rejected_before_any_request(make_services, diag_id: str) -> None:
    services, transport = make_services(ROUTES)
    message = await _error(services, vehicle_id=E90, diag_id=diag_id)
    assert "diag_id looks like 11_3733" in message
    assert transport.requests == []


async def test_unparseable_parts_page_is_an_error_and_not_kept_in_the_cache(
    make_services,
) -> None:
    services, transport = make_services({OIL_PAN: "partgrp/e90_325i_mg11.html"})
    for _ in range(2):
        message = await _error(services, vehicle_id=E90, diag_id="11_3733")
        assert "RealOEM's showparts page did not have the expected structure" in message
    assert [str(r.url) for r in transport.requests] == [OIL_PAN, OIL_PAN]


async def test_fetch_diagram_parts_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await fetch_diagram_parts(services, E90, "11_3733", cache_only=True) is None
    assert transport.requests == []
    fetched = await fetch_diagram_parts(services, E90, "11_3733")
    assert fetched is not None
    assert (fetched[0].requests_made, fetched[1].from_cache) == (1, False)
    cached = await fetch_diagram_parts(services, E90, "11_3733", cache_only=True)
    assert cached is not None
    result, page = cached
    assert (result.from_cache, result.requests_made, page.url) == (True, 0, OIL_PAN)
    assert result.rows == fetched[0].rows
    assert len(transport.requests) == 1


async def test_fetch_diagram_list_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await fetch_diagram_list(services, E90, "11", cache_only=True) is None
    assert transport.requests == []
    async with Client(build_server(services)) as client:
        await client.call_tool("list_diagrams", {"vehicle_id": E90, "main_group": "11"})
    cached = await fetch_diagram_list(services, E90, "11", cache_only=True)
    assert cached is not None
    result, page = cached
    assert (result.from_cache, result.requests_made, page.url) == (True, 0, ENGINE)
    assert (result.vehicle_id, result.main_group, len(result.subgroups)) == (E90, "11", 11)
    assert len(transport.requests) == 1


async def test_fetch_helpers_validate_input_even_when_cache_only(make_services) -> None:
    services, transport = make_services(ROUTES)
    with pytest.raises(InvalidInput):
        await fetch_diagram_list(services, E90, "ENGINE", cache_only=True)
    with pytest.raises(InvalidInput):
        await fetch_diagram_parts(services, "VB13", "11_3733", cache_only=True)
    with pytest.raises(NotFound):
        await fetch_diagram_parts(services, UNKNOWN, "11_3733")
    assert [str(r.url) for r in transport.requests] == [
        url("showparts", id=UNKNOWN, diagId="11_3733"),
        LANDING_URL,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory server pytest tests/tools/test_part_groups.py tests/tools/test_diagram_parts.py -q`
Expected: FAIL (`1 error`: collecting `test_diagram_parts.py` fails with `ImportError: cannot import name 'fetch_diagram_list' from 'realoem_mcp.tools.catalog'`, which interrupts the run)

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/tools/catalog.py` with:

```python
"""Catalog tools (feature C, ARD section 5.11): model cascade, main groups, diagrams, parts lists.

fetch_diagram_list and fetch_diagram_parts are exported for feature D (fitment).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import (
    DiagramListResult,
    DiagramPartsResult,
    PartGroupsResult,
    VehicleSelectionResult,
)
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.partgrp import (
    DIAG_ID,
    MAIN_GROUP,
    parse_diagram_list,
    parse_part_groups,
    vehicle_brand,
)
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
MISSING_GROUP_TTL = timedelta(days=1)
_PROD = re.compile(r"\d{4}(0[1-9]|1[0-2])00")
_CODE = re.compile(r"[A-Za-z0-9]+")


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def select_vehicle(
        product: Literal["P", "M"] = "P",
        archive: Literal["0", "1"] | None = None,
        series: str | None = None,
        body: str | None = None,
        model: str | None = None,
        market: str | None = None,
        prod: str | None = None,
        engine: str | None = None,
        steering: str | None = None,
        trans: str | None = None,
        refresh: bool = False,
    ) -> VehicleSelectionResult:
        """Pick a vehicle in RealOEM's catalog one level at a time, when there is no VIN.

        Levels in order: product (P cars incl. MINI and Rolls-Royce, M motorcycles), catalog
        (sent as archive: 0 current, 1 classic for older models such as E30/E36/E46/R53),
        series, body, model, market, prod (production month as YYYYMM00, e.g. 20051000),
        engine, steering, trans (the last two mostly for classic cars). Call it first with
        just product (or nothing), then call again with every value in `selected` plus the
        `value` of your choice from `options` for `next_level`. Levels with a single option
        (and USA under this US catalog) are auto-selected and appear in `selected`. Parameter
        names equal level names except catalog, whose parameter is archive. When complete is
        true, vehicle.vehicle_id is ready for list_part_groups. refresh=true ignores the cache.
        """
        levels = {
            "product": product,
            "archive": archive,
            "series": series,
            "body": body,
            "model": model,
            "market": market,
            "prod": prod,
            "engine": engine,
            "steering": steering,
            "trans": trans,
        }
        try:
            return await _select(services, levels, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def list_part_groups(vehicle_id: str, refresh: bool = False) -> PartGroupsResult:
        """List a vehicle's specifications and its main parts groups (one request).

        vehicle_id comes from decode_vin, select_vehicle or another RealOEM result. Returns
        specs (vehicle with RealOEM's canonical vehicle id, model_name, body, engine, steering,
        transmission) and main_groups (mg number such as "11" and name such as "ENGINE"); pass
        an mg to list_diagrams. refresh=true ignores the cache.
        """
        try:
            vid = _vehicle_id(services, vehicle_id)
            page = await _fetch(services, PageType.PARTGRP, {"id": str(vid)}, vid, refresh=refresh)
            with _expire_if_unparseable(services, page):
                groups = parse_part_groups(page.html, url=page.url, brands=services.brands)
            return PartGroupsResult.from_pages([page], **dict(groups))
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def list_diagrams(
        vehicle_id: str, main_group: str, refresh: bool = False
    ) -> DiagramListResult:
        """List the subgroups and diagrams of one main group of a vehicle (one request).

        main_group is the two-digit mg from list_part_groups (e.g. "11" engine, "34" brakes).
        Returns subgroups (code, name) with their diagrams (diagram.diag_id, diagram.name,
        diagram.url, thumbnail_url); pass a diag_id to get_diagram_parts. Titles can repeat
        (two "OIL PAN" diagrams), so always refer to diagrams by diag_id. refresh=true
        ignores the cache.
        """
        try:
            result, _ = await fetch_diagram_list(  # never None without cache_only
                services, vehicle_id, main_group, refresh=refresh
            )
            return result
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def get_diagram_parts(
        vehicle_id: str, diag_id: str, refresh: bool = False
    ) -> DiagramPartsResult:
        """Return one diagram's parts list, image and hotspots for a vehicle (one request).

        diag_id comes from list_diagrams (or from a lookup_part result). RealOEM filters the
        list by the vehicle id's production month. Each row has position, description,
        supplement, qty, valid_from/valid_to ("YYYY-MM"), part_number, price_usd, notes (see
        notes_legend), has_photo, indent and conditions (text plus option_codes such as
        S205A=Yes, meaning "only for vehicles with that option"). hotspots are boxes per
        position in the same pixel space as image_width x image_height. refresh=true ignores
        the cache.
        """
        try:
            result, _ = await fetch_diagram_parts(  # never None without cache_only
                services, vehicle_id, diag_id, refresh=refresh
            )
            return result
        except RealOemError as err:
            raise ToolError(err.message) from err


async def fetch_diagram_list(
    services: Services,
    vehicle_id: str,
    main_group: str,
    *,
    refresh: bool = False,
    cache_only: bool = False,
) -> tuple[DiagramListResult, Page] | None:
    """A main group's diagram list. cache_only=True never touches the network: None on a miss."""
    vid = _vehicle_id(services, vehicle_id)
    if not MAIN_GROUP.fullmatch(main_group):
        raise InvalidInput(
            f"main_group must be a two-digit RealOEM main group such as 11, got {main_group!r}."
        )
    params = {"id": str(vid), "mg": main_group}
    page = await _load(
        services, PageType.PARTGRP, params, vid, refresh=refresh, cache_only=cache_only
    )
    if page is None:
        return None
    brand = vehicle_brand(services.brands, vid)
    with _expire_if_unparseable(services, page):
        subgroups = parse_diagram_list(
            page.html,
            url=page.url,
            client=services.client,
            vehicle_id=str(vid),
            dedupe_names=brand.dedupe_repeated_names,
        )
    if not subgroups:
        services.cache.shorten(page.url, MISSING_GROUP_TTL)
        raise NotFound(
            f"vehicle {vid} has no main group {main_group}; list_part_groups shows the ones it has."
        )
    result = DiagramListResult.from_pages(
        [page], vehicle_id=str(vid), main_group=main_group, subgroups=subgroups
    )
    return result, page


async def fetch_diagram_parts(
    services: Services,
    vehicle_id: str,
    diag_id: str,
    *,
    refresh: bool = False,
    cache_only: bool = False,
) -> tuple[DiagramPartsResult, Page] | None:
    """A diagram's parts list. cache_only=True never touches the network: None on a miss."""
    vid = _vehicle_id(services, vehicle_id)
    if not DIAG_ID.fullmatch(diag_id):
        raise InvalidInput(
            f"diag_id looks like 11_3733 (main group, underscore, number), got {diag_id!r}."
        )
    params = {"id": str(vid), "diagId": diag_id}
    page = await _load(
        services, PageType.SHOWPARTS, params, vid, refresh=refresh, cache_only=cache_only
    )
    if page is None:
        return None
    with _expire_if_unparseable(services, page):
        parts = parse_showparts(
            page.html, url=page.url, client=services.client, vehicle_id=str(vid), diag_id=diag_id
        )
    return DiagramPartsResult.from_pages([page], **dict(parts)), page


async def _select(
    services: Services, levels: dict[str, str | None], *, refresh: bool
) -> VehicleSelectionResult:
    params: dict[str, str] = {}
    for name, value in levels.items():
        if value is None:
            continue
        if not value.strip():
            raise InvalidInput(f"{name} must not be empty; leave it out instead.")
        params[name] = value.strip()
    if "prod" in params and not _PROD.fullmatch(params["prod"]):
        raise InvalidInput(
            f"prod is a production month as YYYYMM00 (e.g. 20051000), got {params['prod']!r}."
        )
    page = await services.client.fetch(PageType.SELECT, "select", params, refresh=refresh)
    if page.redirected_away:
        raise NotFound(
            "RealOEM did not show a selection page for these values; start again with only "
            "product and add one level at a time from the options it returns."
        )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        open_level = next((level for level in select.levels if level.selected_option is None), None)
        if select.vehicle_id is None and open_level is None:
            raise LayoutChanged(PageType.SELECT, "no open level and no vehicle id", page.url)
    selected = {
        level.level: level.selected_option
        for level in select.levels
        if level.selected_option is not None
    }
    if select.vehicle_id is None:
        return VehicleSelectionResult.from_pages(
            [page],
            selected=selected,
            next_level=open_level.level,
            options=open_level.options,
            complete=False,
            vehicle=None,
            type_code=None,
            summary=None,
        )
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    product = selected["product"].value if "product" in selected else None
    brand = services.brands.for_vehicle_id(vid, product=product)
    return VehicleSelectionResult.from_pages(
        [page],
        selected=selected,
        next_level=None,
        options=[],
        complete=True,
        vehicle=VehicleRef.from_id(vid, brand.id),
        type_code=select.type_code,
        summary=select.summary,
    )


def _vehicle_id(services: Services, raw: str) -> VehicleId:
    vid = VehicleId.parse(raw, brand_segments=services.brands.brand_segments())
    if not _CODE.fullmatch(vid.type_code) or not _CODE.fullmatch(vid.market):
        raise InvalidInput(
            f"{raw!r} is not a RealOEM vehicle id (e.g. VB13-USA-10-2005-E90-BMW-325i); get one "
            "from decode_vin or select_vehicle."
        )
    return vid


async def _load(
    services: Services,
    page_type: PageType,
    params: dict[str, str],
    vid: VehicleId,
    *,
    refresh: bool,
    cache_only: bool,
) -> Page | None:
    """The page from the cache only (None on a miss), or fetched as usual."""
    if cache_only:
        return services.client.cached(page_type, page_type.value, params)
    return await _fetch(services, page_type, params, vid, refresh=refresh)


async def _fetch(
    services: Services,
    page_type: PageType,
    params: dict[str, str],
    vid: VehicleId,
    *,
    refresh: bool,
) -> Page:
    """Fetch a vehicle page; RealOEM redirects unknown vehicle ids to its landing page."""
    page = await services.client.fetch(page_type, page_type.value, params, refresh=refresh)
    if page.redirected_away:
        raise NotFound(
            f"RealOEM has no vehicle {vid}. Use a vehicle id from decode_vin or select_vehicle."
        )
    return page


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/tools/test_part_groups.py tests/tools/test_diagram_parts.py tests/tools/test_select_vehicle.py -q`
Expected: PASS (`45 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, then `… files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/catalog.py server/tests/tools/test_part_groups.py server/tests/tools/test_diagram_parts.py
git commit -m "feat(catalog): add list_part_groups, list_diagrams, get_diagram_parts and fetch helpers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 5: Skill and delivery

### Task 6: `diagram-browse` skill

ARD §5.12 and PRD F3. Skills load from the plugin's default `skills/` folder, so no manifest edit is
needed. The skill refers to tools by short name. `find_vehicle` (vehicle-index branch) may not be
merged yet, so the skill says "if the `find_vehicle` tool is available". The main group table uses
the numbers and names asserted against the E90 fixture in Task 2 (`test_bmw_specs_and_main_groups`).

**Files:**
- Create: `skills/diagram-browse/SKILL.md`
- Test: `server/tests/unit/test_skill_diagram_browse.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_skill_diagram_browse.py`:

```python
"""skills/diagram-browse/SKILL.md: trigger-oriented frontmatter and the facts the PRD requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "diagram-browse" / "SKILL.md"


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
    assert meta["name"] == "diagram-browse"
    for trigger in ("parts diagram", "parts groups", "production month"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_the_tool_chain() -> None:
    _, body = _read()
    for phrase in (
        "`decode_vin`",
        "`find_vehicle`",
        "`select_vehicle`",
        "`list_part_groups`",
        "`list_diagrams`",
        "`get_diagram_parts`",
        "every value from `selected`",
        "The parameter for the level `catalog` is `archive`",
        "auto-selected",
        "`YYYYMM00`",
    ):
        assert phrase in body, phrase


def test_body_lists_main_groups_as_named_by_realoem() -> None:
    _, body = _read()
    for row in (
        "| 11 | Engine |",
        "| 12 | Engine electrical system |",
        "| 13 | Fuel preparation system |",
        "| 17 | Radiator (cooling) |",
        "| 18 | Exhaust system |",
        "| 21 | Clutch |",
        "| 23 / 24 | Manual / automatic transmission |",
        "| 31 | Front axle |",
        "| 32 | Steering |",
        "| 33 | Rear axle |",
        "| 34 | Brakes |",
        "| 51 | Vehicle trim |",
        "| 61 | Vehicle electrical system |",
        "| 64 | Heater and air conditioning |",
    ):
        assert row in body, row


def test_body_explains_parts_lists_and_limits() -> None:
    _, body = _read()
    for phrase in (
        "Condition rows",
        "option code `S205A`",
        "production-date filtering",
        "nominal production date",
        "not date-filtered to a build month",
        "display space",
        "`image_width` x `image_height`",
        "`notes_legend`",
        "`--`",
        "Never fetch RealOEM pages directly",
        "`source_urls`",
    ):
        assert phrase in body, phrase
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_skill_diagram_browse.py -q`
Expected: FAIL (`4 failed`, each with `FileNotFoundError` for `skills/diagram-browse/SKILL.md`)

- [ ] **Step 3: Write the skill**

Create `skills/diagram-browse/SKILL.md`:

````markdown
---
name: diagram-browse
description: Browse RealOEM parts diagrams for a BMW, MINI, Rolls-Royce or BMW Motorrad vehicle. Use when the user asks "show me the parts diagram for ...", "what parts are in the oil pan / brakes / rear axle of my car", "list the parts groups", "which bolts hold ...", or wants to pick a vehicle by series, model, market and production month.
---

# Diagram browsing

Walks RealOEM's catalog the way its website does: vehicle -> main groups -> diagrams -> parts
list with the exploded-view image. Every step is one request and is cached for 30 days.

## 1. Get a vehicle id

- The user has a VIN: call `decode_vin` and use its `vehicle.vehicle_id`. It carries the car's
  own production month.
- If the `find_vehicle` tool is available, try it first to get a vehicle id without walking the
  cascade; its ids carry the vehicle's production-start month, so for a specific build month
  still use `select_vehicle` with `prod` (or `decode_vin`).
- Otherwise walk the cascade with `select_vehicle`, one level per call:
  1. Call it with `product` only (`P` cars, including MINI and Rolls-Royce; `M` motorcycles).
  2. Show the user `options` for `next_level` (their `label`s) and let them choose.
  3. Call again with every value from `selected` plus the chosen option's `value` for
     `next_level`. The parameter for the level `catalog` is `archive` (`0` current, `1`
     classic, for older models such as E30, E36, E46 and MINI R50/R53); every other level name
     is its own parameter. Production months are `YYYYMM00` codes such as `20051000`.
  4. Levels with a single option (and the USA market) are auto-selected: they appear in
     `selected` without a question to the user.
  5. Repeat until `complete` is true; then use `vehicle.vehicle_id`.
  If a value you sent is missing from `selected`, RealOEM did not accept it: offer `options`
  again.
- Ids from `lookup_part` rows carry a nominal production date: their date is only nominal;
  RealOEM treats the `_` form as undated (`VB13-USA---…`), so the list is not narrowed to a build
  month (undated ids are not date-filtered to a build month). Every other id's parts lists are
  filtered by its production month, so for a specific car prefer an id from `decode_vin` or
  `select_vehicle`.

## 2. Main groups

Call `list_part_groups` with the vehicle id. It returns the vehicle's `specs` and
`main_groups`. BMW main group numbers are stable across models, so you can often go straight to
`list_diagrams`:

| mg | Main group |
|---|---|
| 11 | Engine |
| 12 | Engine electrical system |
| 13 | Fuel preparation system |
| 17 | Radiator (cooling) |
| 18 | Exhaust system |
| 21 | Clutch |
| 23 / 24 | Manual / automatic transmission |
| 31 | Front axle |
| 32 | Steering |
| 33 | Rear axle |
| 34 | Brakes |
| 51 | Vehicle trim |
| 61 | Vehicle electrical system |
| 64 | Heater and air conditioning |

Not every vehicle has every group (motorcycles use their own names, e.g. 17 Cooling), and the
list is not filtered by transmission. If `list_diagrams` says the vehicle has no such main
group, call `list_part_groups`.

## 3. Diagrams

Call `list_diagrams` with the vehicle id and the two-digit `main_group`. Diagrams come grouped
by subgroup. Titles can repeat (two "OIL PAN" diagrams), so refer to a diagram by its `diag_id`
and show the user its name and subgroup.

## 4. Parts list

Call `get_diagram_parts` with the vehicle id and the `diag_id`. Present the rows as a table:
position, description, supplement, quantity, part number, price (USD, when shown) and notes.

- **Condition rows**: a row's `conditions` say when it applies, e.g. "For vehicles with
  Automatic transmission" with option code `S205A` = `Yes`: that part is only for vehicles with
  that factory option (SA code). Several rows with the same position are alternatives; use the
  conditions and dates to tell them apart. RealOEM cannot tell which options a car has.
- `valid_from` / `valid_to` give production-date limits. RealOEM already filters the list by
  the vehicle id's production month, which is why a part can be missing for another month
  (production-date filtering).
- `position` `--` marks accessories without a callout on the image (e.g. sealant "Required
  for repair"). `notes` codes such as `+core` are explained in `notes_legend`.
- The image is `image_url`. `hotspots` are boxes per position in display space: the same
  pixel space as `image_width` x `image_height` (e.g. 640 x 448), not the JPEG's own size.
- A `diag_id` from another vehicle still returns a list (RealOEM does not check it), filtered
  by this vehicle's date. Use diag_ids from this vehicle's `list_diagrams`.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Always cite the `source_urls` of the results you used, and link `diagram.url` for a diagram.
- Do not repeat calls you already made in this conversation; results are cached anyway.
- Use `refresh=true` only when the user says the data looks out of date.
- Brand notes: `brands/<brand>/README.md`.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_skill_diagram_browse.py -q`
Expected: PASS (`4 passed`)

Run: `claude plugin validate . --strict`
Expected: `✔ Validation passed` (if `claude` is not on your PATH, run the same command with the full
path of your Claude Code executable).

- [ ] **Step 5: Commit**

```bash
git add skills/diagram-browse/SKILL.md server/tests/unit/test_skill_diagram_browse.py
git commit -m "feat(skills): add diagram-browse skill" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment (these run inside `server/`)**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest -q
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: `BASELINE + 138 passed, 2 deselected` (102 new tests plus 36 fixture checks; `475 passed, 2 deselected` when `main` holds only the foundation and VIN decode, BASELINE 337), `All checks passed!`, and `… files already formatted` with 13 more files than on `main` (75 in that same setup).

- [ ] **Step 2: Nothing raw, generated or foundation-owned in the branch**

```bash
git status --short && git ls-files | grep -E '^\.research-raw/|\.sqlite3$|\.venv/' || echo clean
git diff --name-status main...HEAD | grep -v '^A' || echo "only additions"
```

Expected: no status lines, then `clean`, then `only additions` (the branch adds 32 files and
changes none).

- [ ] **Step 3: Push and open the pull request**

```bash
git push -u origin feat/diagram-browse
gh pr create --base main --head feat/diagram-browse --title "feat: diagram browsing (select_vehicle, list_part_groups, list_diagrams, get_diagram_parts)" --body "$(cat <<'EOF'
## Summary

Implements PRD F3 (feature C) per ARD §5.11:

- `select_vehicle(product="P", archive, series, body, model, market, prod, engine, steering, trans)`: one step of RealOEM's model cascade per call; reports every effective selection (auto-selected levels included), the next open level with its options, or the finished vehicle (id, type code, brand). The level `catalog` is sent as `archive`.
- `list_part_groups(vehicle_id)`: vehicle specs (canonical vehicle id, model, body, engine, steering, transmission) and main groups.
- `list_diagrams(vehicle_id, main_group)`: subgroups with their diagrams (diag id, name, showparts URL, thumbnail); Motorrad names printed twice are collapsed.
- `get_diagram_parts(vehicle_id, diag_id)`: image URL and size, hotspots in the image's display space, every parts row (position, description, supplement, qty, from/to, part number, USD price, notes, photo flag, indent) with its option-code conditions, and the notes legend.
- Exported for fitment: `fetch_diagram_list` / `fetch_diagram_parts` with `cache_only` (cache read, `None` on a miss).
- Input is validated before any request; unknown vehicle ids and missing main groups are `NotFound` (a missing main group is cached for 1 day); unparseable pages raise `LayoutChanged` and are expired from the cache.
- `skills/diagram-browse/SKILL.md`: getting a vehicle id (VIN, `find_vehicle` when available, cascade), BMW main group numbers, condition rows and option codes, production-date filtering, nominal dates of part-lookup ids, hotspot space, citing sources.
- 18 trimmed fixtures (partgrp, showparts, select); reuses VIN decode's select parser/models and the foundation's E90 main-groups fixture unchanged.

Only adds files; no foundation, part-lookup or VIN-decode file changed, no version bump.

## Test plan

- [x] `uv run pytest` (offline) and `uv run ruff check` / `ruff format --check`
- [x] Parser tests for every fixture (BMW, MINI, Rolls-Royce, Motorrad) incl. date filtering, EUR, condition rows, hotspots and `LayoutChanged` cases
- [x] Tool tests via in-memory `mcp.Client`: cascade stepping, unknown vehicle, missing main group, rejected before any request, broken pages not cached, `cache_only`
- [ ] `claude plugin validate . --strict` (tick after running it locally; Task 6 Step 4)
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
