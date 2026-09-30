# VIN Decode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/vin-decode` (PRD F2.1–F2.5, feature B): a `decode_vin` MCP tool that turns a 7- or 17-character VIN into RealOEM's vehicle (brand, product, catalog, series, body, model, market, production month, engine, steering, transmission, type code, vehicle id), flags full VINs whose manufacturer prefix contradicts the decoded brand, optionally adds production statistics, plus the `vin-decode` skill. The branch also ships the complete select-page parser (`parsers/select.py`, `models/select.py`) that feature C reuses unchanged for the model cascade.

**Architecture:** Pure parsers turn trimmed real RealOEM pages into pydantic models: `parse_select` reads every v2 list box of the select cascade (all options, the effective `.is-selected` row, codes from each level's query parameter) and the `#selectResults` block; `parse_production` reads the `#ps-vin-result` card. `tools/vin.py` (auto-discovered, no `server.py` edit) validates and normalizes the VIN before any request, sends only the last 7 characters (`select?vin=`, optionally `production?vin=`) through the foundation `RealOemClient` with a 180-day TTL, shortens misses to 1 day with `PageCache.shorten`, resolves the brand with `BrandRegistry.for_vehicle_id` and checks the WMI with `for_wmi`. Tests run offline against trimmed fixtures through the foundation harness (`make_services`, `FixtureTransport`, in-memory `mcp.Client`).

**Tech Stack:** Python ≥ 3.11, uv, mcp 2.x (`MCPServer`), httpx, selectolax (lexbor), pydantic 2, SQLite page cache (all from the foundation); pytest + AnyIO plugin, ruff.

---

## Before you start

- The foundation (`feat/foundation`) must already be merged into `main`. This plan uses its APIs
  exactly as they exist there: `Services`, `RealOemClient.fetch(page_type, path, params, *, refresh,
  ttl)`, `PageCache.shorten(url, ttl)`, `PageType`, `LayoutChanged`/`InvalidInput`/`RealOemError`,
  `parsers.common` (`tree`, `text`, `require`, `parse_yyyymm00`, `Node`), `BrandRegistry`
  (`for_vehicle_id`, `for_wmi`, `brand_segments`), `VehicleId.parse`, `ResultMeta.from_pages`,
  `VehicleRef.from_id`, and the test harness (`tests/harness.py`: `load_fixture`, `url`, `REPO_ROOT`,
  `BRANDS_DIR`; `tests/conftest.py`: `make_services`).
- Read `docs/ARD.md` §5.4, §5.7–§5.11 (the "B: decode_vin" contract) and §8, and
  `docs/research/realoem-site-notes.md` §4 (VIN flow) and §5.1 (select cascade) once.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.**
  Python commands use `uv run --directory server …`; paths after it (like
  `tests/unit/test_models_select.py`) are relative to `server/`. `git` paths are relative to the
  repository root.
- Never make requests to realoem.com while implementing. The only live test is opt-in (Task 11) and
  is not run as part of this plan.
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`.
- The 17-character VINs in the tests are made up (a real manufacturer prefix, zeros, and a captured
  last-7 serial). Never paste a real full VIN into code, fixtures or docs.
- This branch **only adds files**; it edits no foundation file. A sibling branch
  (`feat/part-lookup`) is developed in parallel and also only adds files, so the two never
  conflict.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that).
- Versions stay `0.1.0` everywhere; feature branches never bump them.
- Expected test counts below are for this branch on top of the foundation (197 tests). If other
  feature branches merged into `main` first, full-suite totals are higher; per-file counts are
  unchanged.
- The foundation's `tests/unit/test_fixtures.py` checks every fixture under
  `server/tests/fixtures/` (trimmed, no unmasked 17-character VIN), so the new fixtures are covered
  without extra tests here.

## File Structure

| Path | Responsibility |
|---|---|
| `server/src/realoem_mcp/models/select.py` | `LEVELS`, `LEVEL_PARAMS`, `SelectOption`, `SelectLevel` (+ `selected_option`), `SelectPage` (+ `level()`, `selected()`) — reused by C |
| `server/src/realoem_mcp/parsers/select.py` | `parse_select(html, *, url) -> SelectPage`: every v2 cascade level with all options, effective selection, result block — reused by C |
| `server/src/realoem_mcp/models/vin.py` | `ProductionStats`, `VinDecodeResult(ResultMeta)` |
| `server/src/realoem_mcp/parsers/production.py` | `parse_production(html, *, url) -> dict[str, ProductionStats]` keyed by type code |
| `server/src/realoem_mcp/tools/vin.py` | `VinInput`, `normalize_vin`, `pick_production`, `register()` → `decode_vin` tool |
| `skills/vin-decode/SKILL.md` | When/how to decode a VIN, how to present it, RealOEM's limits, next steps |
| `server/tests/fixtures/select/*.html` | 12 trimmed select pages: 5 VIN hits, 1 VIN miss, 1 v1-markup page, 5 mid-cascade pages (for C) |
| `server/tests/fixtures/production/*.html` | 4 trimmed `production?vin=` pages (BMW, MINI, Motorrad, miss) |
| `server/tests/unit/test_models_select.py` | Select model helpers |
| `server/tests/unit/parsers/test_select.py` | `parse_select` on every select fixture (VIN and mid-cascade) |
| `server/tests/unit/parsers/test_select_layout.py` | `LayoutChanged` on v1 markup and structurally broken pages |
| `server/tests/unit/test_models_vin.py` | VIN result models |
| `server/tests/unit/parsers/test_production.py` | `parse_production` incl. miss, several records, `LayoutChanged` |
| `server/tests/unit/test_vin_input.py` | `normalize_vin` accept/reject rules |
| `server/tests/unit/test_pick_production.py` | `pick_production` record selection and warnings |
| `server/tests/unit/test_skill_vin_decode.py` | Skill frontmatter and required statements |
| `server/tests/tools/test_vin.py` | `decode_vin` via in-memory `mcp.Client`: all brands/catalogs, not found, rejected before any request |
| `server/tests/tools/test_vin_cache.py` | Hits cached 180 days, misses 1 day, repeat calls free, `refresh` |
| `server/tests/tools/test_vin_wmi.py` | WMI confidence rules |
| `server/tests/tools/test_vin_production.py` | `include_production` |
| `server/tests/live/test_live_vin.py` | Opt-in live smoke test (2 requests) |

Decisions this plan makes where the ARD leaves room (feature C may rely on the first five):

- **Models stay exactly as in ARD §5.11** (`SelectOption(value, label, selected)`, `SelectLevel(level,
  label, options)`, `SelectPage(levels, vehicle_id, type_code, summary)`). Helpers are methods and
  properties only, so they never appear in structured output. `models/select.py` also exports
  `LEVELS` (cascade order) and `LEVEL_PARAMS` (level → query parameter; `catalog` → `archive`).
- **Every level on the page is parsed with all its options**, in page order. Levels the page does
  not show are omitted (motorcycles have no `body`/`engine`; an incomplete cascade stops after the
  first open level). `SelectLevel.label` is RealOEM's caption without the colon ("Prod Month").
- **Option codes come from the row's href**, from that level's query parameter, split by hand and
  percent-decoded (hrefs are unencoded: `model=R 1250 GS 19 (0J91, 0J93)`). Year headers
  (`li.ro-lb-group`) in the `prod` list are not options; every `prod` label already carries its year
  and every value is `YYYYMM00`, so no `group` field is added.
- **`parse_select` raises `LayoutChanged`** when: `#selectForm` or `#selectResults` is missing; no
  `[data-ro-level]` list box exists in `#selectForm` (v1 markup); a level name is unknown; a list box
  has no `.ro-lb-label` right before it (text and comment nodes in between are skipped); a row link
  lacks the level's parameter; a `prod` value is not a valid `YYYYMM00` (including month 00 or 13+,
  for which `parse_yyyymm00` raises `ValueError`); a level has no rows or more than one selected row; the result form has no id or no
  "Type Code". A VIN miss or an unfinished cascade is **not** an error: `vehicle_id`, `type_code` and
  `summary` are `None`.
- `summary` is the "You Have Selected:" text (e.g. `3 Series E93 BMW 328i`); `type_code` is the value
  of the "Type Code:" line; `vehicle_id` comes from `#selectResults input[name=id]`.
- **`parse_production` returns `{type_code: ProductionStats}`** in page order, `{}` for
  `.ps-vin-error`. The page styles `.ps-vin-match + .ps-vin-match`, so several records per serial are
  possible; `decode_vin` keeps the record whose type code equals the decoded one and warns about the
  others (or leaves `production` out with a warning when none matches). Two records with the same
  type code cannot be keyed and raise `LayoutChanged`.
- **VIN input:** remove whitespace, `.`, `-`, `_`, `/`; require ASCII (checked before uppercasing,
  because `"ſ".upper() == "S"`); uppercase; then only `A–Z0–9`, exactly 7 or 17
  characters, and no `I`, `O` or `Q` (ISO 3779 never uses them, so they are almost always a mistyped
  `1`/`0`). The check digit is not validated (it is only mandatory for North American VINs). Only the
  last 7 characters are ever sent; the first 3 of a 17-character VIN are the WMI.
- **Result mapping:** `product` from the selected `product` code (`P` → `car`, `M` → `motorcycle`),
  `catalog` from `archive` (`0` → `current`, `1` → `classic`); `series_name`, `body`, `engine`,
  `steering`, `transmission` are the selected rows' labels verbatim (`series_name` e.g. `3' E93 (2005 —
  2010)`); brand = `for_vehicle_id(vid, product="M" if motorcycle else "P")`;
  `vehicle = VehicleRef.from_id(vid, brand.id)`. Optional `VinDecodeResult` fields default to `None`
  (the serialized result is identical to the ARD contract).
- **Requests and cache:** `select?vin=<last7>` with `ttl=180 days`; a miss is shortened to 1 day and
  returned as `status="not_found"` without a production request. `production?vin=<last7>` uses the
  production default TTL (180 days); a production miss is shortened to 1 day and reported as a warning.
- **Unparseable pages are never kept (ARD §5.10):** when `parse_select`, `parse_production` or the
  selected-product/catalog mapping raises `LayoutChanged`, `decode_vin` expires that page with
  `services.cache.shorten(page.url, timedelta(0))` before re-raising, so the next call fetches it
  again. With `include_production=true` a broken production page fails the whole call.
- **WMI:** unknown prefix → `confidence="normal"` plus the warning "Unrecognized manufacturer prefix …"
  (also when not found); known prefix of another brand → `confidence="low"` plus a warning (only when
  found). The WMI lists come from the foundation's `brands/*/brand.toml` (not edited here): `bmw`
  WBA, WBS, WBY, WBX, 5UX, 5UM, 5YM, 4US, 3MW, LBV; `mini` WMW, WMZ; `rolls-royce` SCA; `motorrad`
  WB1, WB3.
- The raw full-VIN capture (`vin_fullvin17_PX22770_v2.html`) is **not** turned into a fixture: the
  tool never sends a 17-character VIN, so RealOEM never serves that page to it. Lowercase and
  too-short captures are not needed either (normalization and rejection happen before any request).
- Cache lifetimes are asserted by reading `expires_at − fetched_at` from the SQLite cache file,
  which is deterministic without patching the clock.

## Chunk 1: Select page parser

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

```bash
git checkout main && git pull && git checkout -b feat/vin-decode
```

Expected: `Switched to a new branch 'feat/vin-decode'`.

- [ ] **Step 2: Confirm the foundation is in place and green**

Run: `uv run --directory server pytest -q`
Expected: PASS (`197 passed, 1 deselected` when main has only the foundation; more if other feature
branches merged first)

### Task 1: Select-cascade models (`models/select.py`)

ARD §5.11. The level list and the level → query-parameter map live next to the models so that the
parser (this branch) and `select_vehicle` (feature C) share one definition. Only `catalog` is sent
under a different name (`archive`).

**Files:**
- Create: `server/src/realoem_mcp/models/select.py`
- Test: `server/tests/unit/test_models_select.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_select.py`:

```python
from realoem_mcp.models.select import (
    LEVEL_PARAMS,
    LEVELS,
    SelectLevel,
    SelectOption,
    SelectPage,
)


def _level(name: str, *values: str, selected: str | None = None) -> SelectLevel:
    options = [SelectOption(value=v, label=v.title(), selected=v == selected) for v in values]
    return SelectLevel(level=name, label=name.title(), options=options)


def test_levels_are_in_cascade_order_and_catalog_is_sent_as_archive() -> None:
    assert LEVELS == (
        "product",
        "catalog",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
        "steering",
        "trans",
    )
    assert LEVEL_PARAMS["catalog"] == "archive"
    assert all(LEVEL_PARAMS[level] == level for level in LEVELS if level != "catalog")


def test_selected_option_is_the_selected_row_or_none() -> None:
    assert _level("body", "Lim", "Cab", selected="Cab").selected_option == SelectOption(
        value="Cab", label="Cab", selected=True
    )
    assert _level("model", "320i", "325i").selected_option is None


def test_select_page_looks_up_levels_by_name() -> None:
    page = SelectPage(
        levels=[_level("product", "P", "M", selected="P"), _level("model", "320i", "325i")],
        vehicle_id=None,
        type_code=None,
        summary=None,
    )
    assert page.level("model") is page.levels[1]
    assert page.level("engine") is None
    assert page.selected("product").value == "P"
    assert page.selected("model") is None
    assert page.selected("engine") is None


def test_select_page_serializes_without_helper_properties() -> None:
    page = SelectPage(
        levels=[_level("product", "P", selected="P")],
        vehicle_id="WL13-USA-07-2008-E93-BMW-328i",
        type_code="WL13",
        summary="3 Series E93 BMW 328i",
    )
    assert page.model_dump() == {
        "levels": [
            {
                "level": "product",
                "label": "Product",
                "options": [{"value": "P", "label": "P", "selected": True}],
            }
        ],
        "vehicle_id": "WL13-USA-07-2008-E93-BMW-328i",
        "type_code": "WL13",
        "summary": "3 Series E93 BMW 328i",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_select.py -q`
Expected: FAIL with `No module named 'realoem_mcp.models.select'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/models/select.py`:

```python
"""Select-cascade models (ARD section 5.11): parser output of parsers/select.py, reused by C."""

from __future__ import annotations

from pydantic import BaseModel

# Cascade levels in page order (data-ro-level values). Classic cars add steering and trans.
LEVELS: tuple[str, ...] = (
    "product",
    "catalog",
    "series",
    "body",
    "model",
    "market",
    "prod",
    "engine",
    "steering",
    "trans",
)
# Query parameter that carries each level's code; only "catalog" differs from its level name.
LEVEL_PARAMS: dict[str, str] = {level: level for level in LEVELS} | {"catalog": "archive"}


class SelectOption(BaseModel):
    value: str  # the level's query parameter value, e.g. "E93", "Cab", "20080700"
    label: str  # text RealOEM shows, e.g. "3' E93 (2005 — 2010)", "Convertible", "07/2008"
    selected: bool  # effective selection, including levels RealOEM auto-selected


class SelectLevel(BaseModel):
    level: str  # one of LEVELS
    label: str  # RealOEM's caption without the colon, e.g. "Prod Month"
    options: list[SelectOption]

    @property
    def selected_option(self) -> SelectOption | None:
        return next((option for option in self.options if option.selected), None)


class SelectPage(BaseModel):
    levels: list[SelectLevel]  # in page order; absent levels (e.g. motorcycle body) are omitted
    vehicle_id: str | None  # set once the cascade is complete (or a VIN matched)
    type_code: str | None
    summary: str | None  # "You Have Selected:" text, e.g. "3 Series E93 BMW 328i"

    def level(self, name: str) -> SelectLevel | None:
        return next((level for level in self.levels if level.level == name), None)

    def selected(self, name: str) -> SelectOption | None:
        level = self.level(name)
        return level.selected_option if level is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_select.py -q`
Expected: PASS (`4 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models/select.py server/tests/unit/test_models_select.py
git commit -m "feat(models): add select-cascade models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Select fixtures and `parse_select`

Twelve trimmed select pages. VIN pages (site notes §4.6): BMW E93 `PX22770` (current catalog),
MINI R53 `TD86476` (Classic catalog, brand segment `Mini`), Rolls-Royce Ghost `UX52589`
(`Rolls_Royce`), Motorrad R 1200 GS `Z656595` (no body/engine level), E30 `1234567` (Classic, adds
Steering and Transmission), the miss `ZZZZZZZ`, and the same `PX22770` page captured with the v1 UI
(used in Task 3). Mid-cascade pages from the model cascade (reused by feature C): E90 with the body
auto-selected, E90 325i with the market auto-selected and the production months grouped by year,
E90 325i EUR 10/2005 with the steering list, K50 R 1250 GS (motorcycle: no body/engine), and
Classic E46 with five bodies.

This task writes the parser for well-formed pages; Task 3 adds the `LayoutChanged` checks.

**Files:**
- Create: `server/tests/fixtures/select/*.html` (12 files, generated), `server/src/realoem_mcp/parsers/select.py`
- Test: `server/tests/unit/parsers/test_select.py`

- [ ] **Step 1: Generate the fixtures and write the failing test**

`.research-raw/` is git-ignored and exists only in the main checkout. `RAW` below resolves it from
either the main checkout or a git worktree:

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_bmw_e93_PX22770_v2.html" tests/fixtures/select/vin_bmw_e93_px22770.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_bmw_e93_PX22770_v1.html" tests/fixtures/select/vin_bmw_e93_px22770_v1.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_mini_r53_TD86476_v2.html" tests/fixtures/select/vin_mini_r53_td86476.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_rr_ghost_UX52589_v2.html" tests/fixtures/select/vin_rr_ghost_ux52589.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_moto_r1200gs_Z656595_v2.html" tests/fixtures/select/vin_moto_r1200gs_z656595.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_numeric_1234567_v2.html" tests/fixtures/select/vin_e30_classic_1234567.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/vin_invalid_ZZZZZZZ_v2.html" tests/fixtures/select/vin_miss_zzzzzzz.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/02_select_P_E90.html" tests/fixtures/select/cascade_e90.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/03_select_P_E90_325i.html" tests/fixtures/select/cascade_e90_325i.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/08_select_P_E90_325i_EUR_200510.html" tests/fixtures/select/cascade_e90_325i_eur_200510.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/27_select_M_K50_R1250GS.html" tests/fixtures/select/cascade_k50_r1250gs.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/39_select_P_archive1_E46.html" tests/fixtures/select/cascade_classic_e46.html
```

Expected (stderr, one line per file; paths may print with `\` on Windows and sizes may differ by a
few bytes with line endings): `vin_bmw_e93_px22770.html: 74278 -> 51763 bytes`,
`vin_bmw_e93_px22770_v1.html: 46536 -> 24379 bytes`, `vin_mini_r53_td86476.html: 48979 -> 27592 bytes`,
`vin_rr_ghost_ux52589.html: 87452 -> 64857 bytes`, `vin_moto_r1200gs_z656595.html: 50470 -> 29023 bytes`,
`vin_e30_classic_1234567.html: 45565 -> 24186 bytes`, `vin_miss_zzzzzzz.html: 61800 -> 39431 bytes`,
`cascade_e90.html: 65431 -> 42643 bytes`, `cascade_e90_325i.html: 72378 -> 49131 bytes`,
`cascade_e90_325i_eur_200510.html: 78382 -> 54590 bytes`, `cascade_k50_r1250gs.html: 50793 -> 28116 bytes`,
`cascade_classic_e46.html: 35049 -> 13423 bytes`.

The foundation's `tests/unit/test_fixtures.py` automatically checks every new fixture: it must be
trimmed (`trim(html) == html`) and contain no unmasked 17-character VIN.

Create `server/tests/unit/parsers/test_select.py`:

```python
import re

import pytest

from realoem_mcp.models.select import SelectOption, SelectPage
from realoem_mcp.parsers.select import parse_select
from tests.harness import load_fixture, url


def _parse(slug: str, **params: str) -> SelectPage:
    return parse_select(load_fixture(f"select/{slug}.html"), url=url("select", **params))


def _selected(page: SelectPage) -> dict[str, tuple[str, str]]:
    """{level: (value, label)} for every level with a selected row."""
    return {
        level.level: (level.selected_option.value, level.selected_option.label)
        for level in page.levels
        if level.selected_option is not None
    }


def test_vin_hit_bmw_e93_every_level_selected() -> None:
    page = _parse("vin_bmw_e93_px22770", vin="PX22770")
    assert page.vehicle_id == "WL13-USA-07-2008-E93-BMW-328i"
    assert page.type_code == "WL13"
    assert page.summary == "3 Series E93 BMW 328i"
    assert [level.level for level in page.levels] == [
        "product",
        "catalog",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
    ]
    assert [level.label for level in page.levels] == [
        "Product",
        "Catalog",
        "Series",
        "Body",
        "Model",
        "Market",
        "Prod Month",
        "Engine",
    ]
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("0", "Current"),
        "series": ("E93", "3' E93 (2005 — 2010)"),
        "body": ("Cab", "Convertible"),
        "model": ("328i", "328i"),
        "market": ("USA", "USA"),
        "prod": ("20080700", "07/2008"),
        "engine": ("N52N", "N52N"),
    }


def test_vin_hit_keeps_every_option_of_every_level() -> None:
    page = _parse("vin_bmw_e93_px22770", vin="PX22770")
    assert page.level("product").options == [
        SelectOption(value="P", label="Car", selected=True),
        SelectOption(value="M", label="Motorcycle", selected=False),
    ]
    series = page.level("series").options
    assert len(series) == 243
    assert series[0] == SelectOption(value="E81", label="1' E81 (2006 — 2011)", selected=False)
    assert [option.value for option in page.level("engine").options] == ["N51", "N52N"]
    prod = page.level("prod").options
    assert len(prod) == 47  # year group headers (li.ro-lb-group) are not options
    assert (prod[0].value, prod[0].label) == ("20050900", "09/2005")
    assert (prod[-1].value, prod[-1].label) == ("20100200", "02/2010")


def test_vin_hit_mini_classic_catalog() -> None:
    page = _parse("vin_mini_r53_td86476", vin="TD86476")
    assert page.vehicle_id == "RE33-USA-04-2004-R53-Mini-Cooper_S"
    assert page.type_code == "RE33"
    assert page.summary == "MINI R53 Mini Cooper S"
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("R53", "MINI R53"),
        "body": ("HC", "3 doors"),
        "model": ("Cooper S", "Cooper S"),
        "market": ("USA", "USA"),
        "prod": ("20040400", "04/2004"),
        "engine": ("W11", "W11"),
    }


def test_vin_hit_rolls_royce() -> None:
    page = _parse("vin_rr_ghost_ux52589", vin="UX52589")
    assert page.vehicle_id == "FK43-USA-12-2013-RR4-Rolls_Royce-Ghost"
    assert page.type_code == "FK43"
    assert page.summary == "Rolls-Royce Ghost RR4 Rolls-Royce Ghost"
    assert _selected(page)["series"] == ("RR4", "Rolls-Royce Ghost RR4")
    assert _selected(page)["engine"] == ("N74R", "N74R")
    assert len(page.level("prod").options) == 129


def test_vin_hit_motorcycle_has_no_body_or_engine_level() -> None:
    page = _parse("vin_moto_r1200gs_z656595", vin="Z656595")
    assert page.vehicle_id == "0A61-USA-09-2017-K50-BMW-R_1200_GS_17_0A51,_0A61_"
    assert page.type_code == "0A61"
    assert page.summary == "K50 (R 1200 GS, R 1250 GS) BMW R 1200 GS 17 (0A51, 0A61)"
    assert page.level("body") is None
    assert page.level("engine") is None
    assert _selected(page) == {
        "product": ("M", "Motorcycle"),
        "catalog": ("0", "Current"),
        "series": ("K50", "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)"),
        "model": ("R 1200 GS 17 (0A51, 0A61)", "R 1200 GS 17 (0A51, 0A61)"),
        "market": ("USA", "USA"),
        "prod": ("20170900", "09/2017"),
    }


def test_vin_hit_classic_e30_adds_steering_and_transmission() -> None:
    page = _parse("vin_e30_classic_1234567", vin="1234567")
    assert page.vehicle_id == "1251-EUR-11-1986-E30-BMW-325e"
    assert page.type_code == "1251"
    assert [level.level for level in page.levels][-2:] == ["steering", "trans"]
    assert page.level("trans").label == "Transmission"
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("E30", "3' E30 (1981 — 1994)"),
        "body": ("2-T", "Coupe"),
        "model": ("325e", "325e"),
        "market": ("EUR", "EUR"),
        "prod": ("19861100", "11/1986"),
        "engine": ("M20", "M20"),
        "steering": ("L", "Left hand drive"),
        "trans": ("M", "Manual"),
    }
    assert page.level("trans").options == [
        SelectOption(value="M", label="Manual", selected=True),
        SelectOption(value="A", label="Automatic", selected=False),
    ]


def test_vin_miss_has_no_vehicle() -> None:
    page = _parse("vin_miss_zzzzzzz", vin="ZZZZZZZ")
    assert (page.vehicle_id, page.type_code, page.summary) == (None, None, None)
    assert [level.level for level in page.levels] == ["product", "catalog", "series"]
    assert page.selected("series") is None


def test_cascade_series_selected_body_auto_selected_model_open() -> None:
    page = _parse("cascade_e90", product="P", archive="0", series="E90")
    assert page.vehicle_id is None
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("0", "Current"),
        "series": ("E90", "3' E90 (2004 — 2023)"),
        "body": ("Lim", "Sedan"),
    }
    models = page.level("model").options
    assert len(models) == 20
    assert (models[0].value, models[-1].value) == ("316i", "M3")
    assert not any(option.selected for option in models)


def test_cascade_market_auto_selected_prod_list_grouped_by_year() -> None:
    page = _parse(
        "cascade_e90_325i", product="P", archive="0", series="E90", body="Lim", model="325i"
    )
    assert _selected(page)["market"] == ("USA", "USA")
    assert [option.value for option in page.level("market").options] == [
        "CHN",
        "EUR",
        "IDN",
        "IND",
        "MYS",
        "RUS",
        "THA",
        "USA",
    ]
    prod = page.level("prod")
    assert prod.selected_option is None
    assert len(prod.options) == 27
    assert (prod.options[0].value, prod.options[0].label) == ("20040200", "02/2004")
    assert (prod.options[-1].value, prod.options[-1].label) == ("20060800", "08/2006")
    assert page.level("engine") is None


def test_cascade_eur_offers_steering() -> None:
    page = _parse(
        "cascade_e90_325i_eur_200510",
        product="P",
        archive="0",
        series="E90",
        body="Lim",
        model="325i",
        market="EUR",
        prod="20051000",
    )
    assert page.vehicle_id is None
    assert _selected(page)["engine"] == ("N52", "N52")
    assert page.level("steering").options == [
        SelectOption(value="L", label="Left hand drive", selected=False),
        SelectOption(value="R", label="Right hand drive", selected=False),
    ]


def test_cascade_motorcycle_model_values_keep_spaces_and_commas() -> None:
    page = _parse(
        "cascade_k50_r1250gs",
        product="M",
        archive="0",
        series="K50",
        model="R 1250 GS 19 (0J91, 0J93)",
    )
    assert [level.level for level in page.levels] == [
        "product",
        "catalog",
        "series",
        "model",
        "market",
        "prod",
    ]
    assert _selected(page)["model"] == ("R 1250 GS 19 (0J91, 0J93)", "R 1250 GS 19 (0J91, 0J93)")
    assert len(page.level("model").options) == 13
    assert page.level("prod").selected_option is None
    assert len(page.level("prod").options) == 26


def test_cascade_classic_series_offers_five_bodies() -> None:
    page = _parse("cascade_classic_e46", product="P", archive="1", series="E46")
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("E46", "3' E46 (1997 — 2023)"),
    }
    assert [(o.value, o.label) for o in page.level("body").options] == [
        ("Lim", "Sedan"),
        ("Cab", "Convertible"),
        ("Cou", "Coupe"),
        ("com", "Compact"),
        ("tou", "Touring"),
    ]
    assert page.level("series").options[0] == SelectOption(
        value="ISE", label="Isetta (1955 — 1962)", selected=False
    )


@pytest.mark.parametrize(
    "slug",
    ["vin_bmw_e93_px22770", "cascade_e90_325i_eur_200510", "cascade_k50_r1250gs"],
)
def test_every_prod_option_is_a_yyyymm00_code(slug: str) -> None:
    prod = _parse(slug).level("prod")
    assert all(re.fullmatch(r"(19|20)\d{2}(0[1-9]|1[0-2])00", o.value) for o in prod.options)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_select.py -q`
Expected: FAIL with `No module named 'realoem_mcp.parsers.select'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/select.py`:

```python
"""select page (v2 list boxes): cascade levels, options and result block (site notes 4.2-4.3, 5.1).

Used by decode_vin (B) and, unchanged, by the model cascade in C.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from realoem_mcp.models.select import LEVEL_PARAMS, SelectLevel, SelectOption, SelectPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, require, text, tree

PAGE = PageType.SELECT


def parse_select(html: str, *, url: str) -> SelectPage:
    root = tree(html)
    form = require(root, "#selectForm", PAGE, url)
    levels = [_parse_level(card) for card in form.css("[data-ro-level]")]
    vehicle_id, type_code, summary = _parse_results(require(root, "#selectResults", PAGE, url))
    return SelectPage(levels=levels, vehicle_id=vehicle_id, type_code=type_code, summary=summary)


def _parse_level(card: Node) -> SelectLevel:
    level = card.attributes.get("data-ro-level") or ""
    param = LEVEL_PARAMS.get(level, level)
    options: list[SelectOption] = []
    for row in card.css("a.ro-lb-row"):
        value = _query_param(row.attributes.get("href") or "", param) or ""
        selected = "is-selected" in (row.attributes.get("class") or "").split()
        options.append(SelectOption(value=value, label=text(row), selected=selected))
    return SelectLevel(level=level, label=_caption(card) or "", options=options)


def _caption(card: Node) -> str | None:
    """Text of the .ro-lb-label element right before the list box, without the colon."""
    node = card.prev
    while node is not None and node.is_text_node:
        node = node.prev
    if node is None or "ro-lb-label" not in (node.attributes.get("class") or "").split():
        return None
    return text(node).rstrip(":").strip() or None


def _query_param(href: str, name: str) -> str | None:
    # RealOEM's hrefs are not URL-encoded ("model=Cooper S"), so split by hand and only
    # percent-decode; parse_qsl would also turn a literal "+" into a space.
    for pair in urlsplit(href).query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key == name:
            return unquote(value)
    return None


def _parse_results(results: Node) -> tuple[str | None, str | None, str | None]:
    """(vehicle_id, type_code, summary); all None until the cascade is complete or a VIN hit."""
    id_input = results.css_first('input[name="id"]')
    if id_input is None:
        return None, None, None
    values: dict[str, str] = {}
    for line in results.css(".searchResults-line"):
        label = text(line.css_first(".searchResults-label")).rstrip(":")
        values[label] = text(line.css_first(".searchResults-value"))
    vehicle_id = (id_input.attributes.get("value") or "").strip() or None
    return vehicle_id, values.get("Type Code"), values.get("You Have Selected") or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_select.py tests/unit/test_fixtures.py -q`
Expected: PASS (`44 passed`; test_fixtures.py now also checks the 12 new fixtures)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/select server/src/realoem_mcp/parsers/select.py server/tests/unit/parsers/test_select.py
git commit -m "feat(parsers): parse select cascade and VIN result pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `parse_select` raises `LayoutChanged` on unexpected structure

NFR3: never return partial or guessed data. The v1 capture is a real page with the other markup
variant; the other broken pages are the E93 fixture with one structural edit each.

**Files:**
- Modify: `server/src/realoem_mcp/parsers/select.py`
- Test: `server/tests/unit/parsers/test_select_layout.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_select_layout.py`:

```python
"""parse_select raises LayoutChanged instead of guessing (NFR3). Broken pages are real fixtures
with one structural edit each."""

import re

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.select import parse_select
from tests.harness import load_fixture, url

URL = url("select", vin="PX22770")
HIT = load_fixture("select/vin_bmw_e93_px22770.html")


def _layout_error(html: str) -> LayoutChanged:
    with pytest.raises(LayoutChanged) as info:
        parse_select(html, url=URL)
    assert info.value.page_type == "select"
    assert info.value.url == URL
    return info.value


def test_v1_markup_is_rejected() -> None:
    error = _layout_error(load_fixture("select/vin_bmw_e93_px22770_v1.html"))
    assert error.detail == "no v2 list boxes ([data-ro-level]) in #selectForm"


def test_page_without_select_form() -> None:
    error = _layout_error(load_fixture("common/partgrp_e90_325i.html"))
    assert error.detail == "missing '#selectForm'"


def test_page_without_result_block() -> None:
    error = _layout_error(HIT.replace('id="selectResults"', 'id="somethingElse"'))
    assert error.detail == "missing '#selectResults'"


def test_unknown_level() -> None:
    error = _layout_error(HIT.replace('data-ro-level="engine"', 'data-ro-level="colour"'))
    assert error.detail == "unknown cascade level 'colour'"


def test_comment_between_caption_and_list_box_is_ignored() -> None:
    html = HIT.replace(
        '<div class="ro-lb-label">Engine:</div>',
        '<div class="ro-lb-label">Engine:</div><!-- list box -->',
    )
    assert parse_select(html, url=URL).level("engine").label == "Engine"


def test_level_without_caption() -> None:
    error = _layout_error(HIT.replace('<div class="ro-lb-label">Engine:</div>', ""))
    assert error.detail == "no .ro-lb-label before level 'engine'"


def test_row_link_without_the_level_parameter() -> None:
    error = _layout_error(HIT.replace("&amp;engine=", "&amp;motor="))
    assert error.detail == "row in level 'engine' has no engine= in its link"


@pytest.mark.parametrize("value", ["2008-07", "20081300", "20080000"])
def test_prod_value_that_is_not_yyyymm00(value: str) -> None:
    error = _layout_error(HIT.replace("prod=20080700", f"prod={value}"))
    assert error.detail == f"prod value {value!r} is not YYYYMM00"


def test_level_without_rows() -> None:
    html = re.sub(r"<li><a [^>]*&amp;engine=[^>]*>[^<]*</a></li>", "", HIT)
    error = _layout_error(html)
    assert error.detail == "level 'engine' has no rows"


def test_level_with_two_selected_rows() -> None:
    html = HIT.replace(
        '<a class="ro-lb-row" href="/bmw/enUS/select?archive=0&amp;product=M">',
        '<a class="ro-lb-row is-selected" href="/bmw/enUS/select?archive=0&amp;product=M">',
    )
    error = _layout_error(html)
    assert error.detail == "level 'product' has more than one selected row"


def test_result_form_without_type_code() -> None:
    html = HIT.replace(
        '<span class="searchResults-label">Type Code:</span>',
        '<span class="searchResults-label">Code:</span>',
    )
    error = _layout_error(html)
    assert error.detail == "#selectResults has a form but no vehicle id or type code"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_select_layout.py -q`
Expected: FAIL (`11 failed, 2 passed`; only the missing #selectForm and #selectResults cases pass)

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/parsers/select.py` with:

```python
"""select page (v2 list boxes): cascade levels, options and result block (site notes 4.2-4.3, 5.1).

Used by decode_vin (B) and, unchanged, by the model cascade in C.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.select import LEVEL_PARAMS, SelectLevel, SelectOption, SelectPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_yyyymm00, require, text, tree

PAGE = PageType.SELECT


def parse_select(html: str, *, url: str) -> SelectPage:
    root = tree(html)
    form = require(root, "#selectForm", PAGE, url)
    cards = form.css("[data-ro-level]")
    if not cards:
        raise LayoutChanged(PAGE, "no v2 list boxes ([data-ro-level]) in #selectForm", url)
    levels = [_parse_level(card, url) for card in cards]
    vehicle_id, type_code, summary = _parse_results(require(root, "#selectResults", PAGE, url), url)
    return SelectPage(levels=levels, vehicle_id=vehicle_id, type_code=type_code, summary=summary)


def _parse_level(card: Node, url: str) -> SelectLevel:
    level = card.attributes.get("data-ro-level") or ""
    param = LEVEL_PARAMS.get(level)
    if param is None:
        raise LayoutChanged(PAGE, f"unknown cascade level {level!r}", url)
    caption = _caption(card)
    if caption is None:
        raise LayoutChanged(PAGE, f"no .ro-lb-label before level {level!r}", url)
    options: list[SelectOption] = []
    for row in card.css("a.ro-lb-row"):
        value = _query_param(row.attributes.get("href") or "", param)
        if not value:
            raise LayoutChanged(PAGE, f"row in level {level!r} has no {param}= in its link", url)
        if level == "prod" and not _is_yyyymm00(value):
            raise LayoutChanged(PAGE, f"prod value {value!r} is not YYYYMM00", url)
        selected = "is-selected" in (row.attributes.get("class") or "").split()
        options.append(SelectOption(value=value, label=text(row), selected=selected))
    if not options:
        raise LayoutChanged(PAGE, f"level {level!r} has no rows", url)
    if sum(option.selected for option in options) > 1:
        raise LayoutChanged(PAGE, f"level {level!r} has more than one selected row", url)
    return SelectLevel(level=level, label=caption, options=options)


def _is_yyyymm00(value: str) -> bool:
    try:
        return parse_yyyymm00(value) is not None
    except ValueError:  # month 00 or 13+
        return False


def _caption(card: Node) -> str | None:
    """Text of the .ro-lb-label element right before the list box, without the colon."""
    node = card.prev
    while node is not None and (node.is_text_node or node.is_comment_node):
        node = node.prev
    if node is None or "ro-lb-label" not in (node.attributes.get("class") or "").split():
        return None
    return text(node).rstrip(":").strip() or None


def _query_param(href: str, name: str) -> str | None:
    # RealOEM's hrefs are not URL-encoded ("model=Cooper S"), so split by hand and only
    # percent-decode; parse_qsl would also turn a literal "+" into a space.
    for pair in urlsplit(href).query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key == name:
            return unquote(value)
    return None


def _parse_results(results: Node, url: str) -> tuple[str | None, str | None, str | None]:
    """(vehicle_id, type_code, summary); all None until the cascade is complete or a VIN hit."""
    id_input = results.css_first('input[name="id"]')
    if id_input is None:
        return None, None, None
    values: dict[str, str] = {}
    for line in results.css(".searchResults-line"):
        label = text(line.css_first(".searchResults-label")).rstrip(":")
        values[label] = text(line.css_first(".searchResults-value"))
    vehicle_id = (id_input.attributes.get("value") or "").strip()
    type_code = values.get("Type Code")
    if not vehicle_id or not type_code:
        raise LayoutChanged(PAGE, "#selectResults has a form but no vehicle id or type code", url)
    return vehicle_id, type_code, values.get("You Have Selected") or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers -q`
Expected: PASS (`52 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers/select.py server/tests/unit/parsers/test_select_layout.py
git commit -m "feat(parsers): raise LayoutChanged on unexpected select pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 2: VIN models and production page

### Task 4: VIN result models (`models/vin.py`)

ARD §5.11. `VinDecodeResult` extends the foundation's `ResultMeta`, so a tool builds it with
`VinDecodeResult.from_pages(pages, **fields)`. The optional fields default to `None` so a
`not_found` result needs only the status fields.

**Files:**
- Create: `server/src/realoem_mcp/models/vin.py`
- Test: `server/tests/unit/test_models_vin.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_vin.py`:

```python
from datetime import UTC, datetime

from realoem_mcp.http_client import Page
from realoem_mcp.models.vin import ProductionStats, VinDecodeResult
from realoem_mcp.page_types import PageType
from tests.harness import url

SELECT_URL = url("select", vin="ZZZZZZZ")


def _page() -> Page:
    return Page(
        page_type=PageType.SELECT,
        url=SELECT_URL,
        final_url=SELECT_URL,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=False,
    )


def test_not_found_result_only_needs_the_status_fields() -> None:
    result = VinDecodeResult.from_pages(
        [_page()], serial="ZZZZZZZ", status="not_found", confidence="normal", warnings=[]
    )
    assert result.model_dump() == {
        "source_urls": [SELECT_URL],
        "fetched_at": datetime(2026, 9, 30, tzinfo=UTC),
        "from_cache": False,
        "requests_made": 1,
        "serial": "ZZZZZZZ",
        "status": "not_found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": None,
        "product": None,
        "catalog": None,
        "series_name": None,
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
        "production": None,
    }


def test_production_stats_fields() -> None:
    stats = ProductionStats(
        built_month="2008-07",
        seq_in_month=321,
        total_in_month=547,
        seq_in_type=None,
        total_in_type=None,
    )
    assert stats.model_dump() == {
        "built_month": "2008-07",
        "seq_in_month": 321,
        "total_in_month": 547,
        "seq_in_type": None,
        "total_in_type": None,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_vin.py -q`
Expected: FAIL with `No module named 'realoem_mcp.models.vin'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/models/vin.py`:

```python
"""VIN decode models (ARD section 5.11)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta, VehicleRef


class ProductionStats(BaseModel):
    built_month: str  # "YYYY-MM"
    seq_in_month: int | None  # this serial's position among the vehicles built that month
    total_in_month: int | None
    seq_in_type: int | None  # position across all production of the type code
    total_in_type: int | None


class VinDecodeResult(ResultMeta):
    serial: str  # last 7 VIN characters: the only part sent to RealOEM
    status: Literal["found", "not_found"]
    confidence: Literal["normal", "low"]
    warnings: list[str]
    vehicle: VehicleRef | None = None
    product: Literal["car", "motorcycle"] | None = None
    catalog: Literal["current", "classic"] | None = None
    series_name: str | None = None  # RealOEM's series label, e.g. "3' E93 (2005 — 2010)"
    body: str | None = None  # e.g. "Convertible"; None for motorcycles
    engine: str | None = None  # e.g. "N52N"; None for motorcycles
    steering: str | None = None  # e.g. "Left hand drive"; only when RealOEM shows it
    transmission: str | None = None  # e.g. "Manual"; Classic-catalog cars only
    production: ProductionStats | None = None  # only with include_production
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_vin.py -q`
Expected: PASS (`2 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models/vin.py server/tests/unit/test_models_vin.py
git commit -m "feat(models): add VIN decode result models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Production fixtures and `parse_production`

Site notes §4.4. `production?vin=` shows one `.ps-vin-match` card per record: `span.ps-vin-meta`
("— type WL13, USA, engine N52N — built July 2008"; motorcycles have no engine) and a second
`div.ps-vin-meta` ("… was VIN 321 of 547 built that month, and 12,557 of 17,781 across all WL13
production."). A miss is `<div id="ps-vin-result" class="ps-vin-error">`. The page carries no vehicle
id, so the result is keyed by type code. The Motorrad page was captured with the v1 UI; the
production markup does not differ between variants.

**Files:**
- Create: `server/tests/fixtures/production/*.html` (4 files, generated), `server/src/realoem_mcp/parsers/production.py`
- Test: `server/tests/unit/parsers/test_production.py`

- [ ] **Step 1: Generate the fixtures and write the failing test**

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/production_vin_PX22770_v2.html" tests/fixtures/production/vin_bmw_e93_px22770.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/production_vin_mini_TD86476_v2.html" tests/fixtures/production/vin_mini_r53_td86476.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/production_vin_moto_Z656595_v1.html" tests/fixtures/production/vin_moto_r1200gs_z656595.html
uv run --directory server python scripts/trim_fixture.py "$RAW/vin/production_vin_invalid_ZZZZZZZ_v2.html" tests/fixtures/production/vin_miss_zzzzzzz.html
```

Expected: `vin_bmw_e93_px22770.html: 62980 -> 34169 bytes`, `vin_mini_r53_td86476.html: 62998 -> 34187 bytes`,
`vin_moto_r1200gs_z656595.html: 62860 -> 34052 bytes`, `vin_miss_zzzzzzz.html: 62277 -> 33468 bytes`
(stderr; sizes may differ by a few bytes with line endings).

Create `server/tests/unit/parsers/test_production.py`:

```python
import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.parsers.common import tree
from realoem_mcp.parsers.production import parse_production
from tests.harness import load_fixture, url

BMW = load_fixture("production/vin_bmw_e93_px22770.html")
MINI = load_fixture("production/vin_mini_r53_td86476.html")


def _parse(html: str, serial: str = "PX22770") -> dict[str, ProductionStats]:
    return parse_production(html, url=url("production", vin=serial))


def test_bmw_match() -> None:
    assert _parse(BMW) == {
        "WL13": ProductionStats(
            built_month="2008-07",
            seq_in_month=321,
            total_in_month=547,
            seq_in_type=12557,
            total_in_type=17781,
        )
    }


def test_mini_match() -> None:
    assert _parse(MINI, "TD86476") == {
        "RE33": ProductionStats(
            built_month="2004-04",
            seq_in_month=228,
            total_in_month=1392,
            seq_in_type=36422,
            total_in_type=82906,
        )
    }


def test_motorcycle_match_without_engine() -> None:
    # Captured with the v1 UI; the production markup is the same in both variants.
    html = load_fixture("production/vin_moto_r1200gs_z656595.html")
    assert _parse(html, "Z656595") == {
        "0A61": ProductionStats(
            built_month="2017-09",
            seq_in_month=73,
            total_in_month=246,
            seq_in_type=1896,
            total_in_type=3207,
        )
    }


def test_no_record_is_an_empty_dict() -> None:
    assert _parse(load_fixture("production/vin_miss_zzzzzzz.html"), "ZZZZZZZ") == {}


def test_several_matches_keep_page_order() -> None:
    mini_match = tree(MINI).css_first(".ps-vin-match").html
    html = BMW.replace('<div class="ps-vin-match">', mini_match + '<div class="ps-vin-match">', 1)
    assert list(_parse(html)) == ["RE33", "WL13"]


def test_two_records_for_one_type_code_raise_layout_changed() -> None:
    bmw_match = tree(BMW).css_first(".ps-vin-match").html
    html = BMW.replace('<div class="ps-vin-match">', bmw_match + '<div class="ps-vin-match">', 1)
    with pytest.raises(LayoutChanged) as info:
        _parse(html)
    assert info.value.detail == "type WL13 has more than one production record"


def test_missing_counts_become_none() -> None:
    html = BMW.replace("built that month", "made that month").replace("across all", "in all")
    stats = _parse(html)["WL13"]
    assert stats.built_month == "2008-07"
    assert (stats.seq_in_month, stats.total_in_month) == (None, None)
    assert (stats.seq_in_type, stats.total_in_type) == (None, None)


@pytest.mark.parametrize(
    ("html", "detail"),
    [
        (load_fixture("select/vin_miss_zzzzzzz.html"), "missing '#ps-vin-result'"),
        (
            BMW.replace('class="ps-vin-match"', 'class="ps-vin-other"'),
            "#ps-vin-result has neither a match nor an error",
        ),
        (
            BMW.replace("type WL13,", "code WL13,"),
            "no type or build month in '— code WL13, USA, engine N52N — built July 2008'",
        ),
        (
            BMW.replace("July&nbsp;2008", "Juli&nbsp;2008"),
            "no type or build month in '— type WL13, USA, engine N52N — built Juli 2008'",
        ),
    ],
    ids=["no-result-block", "no-match", "no-type", "unknown-month"],
)
def test_broken_page_raises_layout_changed(html: str, detail: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        _parse(html)
    assert info.value.page_type == "production"
    assert info.value.detail == detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_production.py -q`
Expected: FAIL with `No module named 'realoem_mcp.parsers.production'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/production.py`:

```python
"""production?vin= page: build statistics for a VIN serial (site notes 4.4)."""

from __future__ import annotations

import re

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, require, text, tree

PAGE = PageType.PRODUCTION
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_TYPE = re.compile(r"\btype (?P<type>[0-9A-Z]+)\b")
_BUILT = re.compile(r"\bbuilt (?P<month>[A-Z][a-z]+) (?P<year>\d{4})\b")
_IN_MONTH = re.compile(r"\bVIN (?P<seq>[\d,]+) of (?P<total>[\d,]+) built that month")
_IN_TYPE = re.compile(r"\b(?P<seq>[\d,]+) of (?P<total>[\d,]+) across all\b")


def parse_production(html: str, *, url: str) -> dict[str, ProductionStats]:
    """Build statistics keyed by type code, in page order; {} when RealOEM has no record."""
    result = require(tree(html), "#ps-vin-result", PAGE, url)
    if "ps-vin-error" in (result.attributes.get("class") or "").split():
        return {}
    matches = result.css(".ps-vin-match")
    if not matches:
        raise LayoutChanged(PAGE, "#ps-vin-result has neither a match nor an error", url)
    stats: dict[str, ProductionStats] = {}
    for match in matches:
        type_code, record = _parse_match(match, url)
        if type_code in stats:
            raise LayoutChanged(PAGE, f"type {type_code} has more than one production record", url)
        stats[type_code] = record
    return stats


def _parse_match(match: Node, url: str) -> tuple[str, ProductionStats]:
    metas = [text(node) for node in match.css(".ps-vin-meta")]
    head = metas[0] if metas else ""
    type_code = _TYPE.search(head)
    built = _BUILT.search(head)
    if type_code is None or built is None or built["month"] not in MONTHS:
        raise LayoutChanged(PAGE, f"no type or build month in {head!r}", url)
    counts = " ".join(metas[1:])
    in_month = _IN_MONTH.search(counts)
    in_type = _IN_TYPE.search(counts)
    month = MONTHS.index(built["month"]) + 1
    return type_code["type"], ProductionStats(
        built_month=f"{built['year']}-{month:02d}",
        seq_in_month=_int(in_month, "seq"),
        total_in_month=_int(in_month, "total"),
        seq_in_type=_int(in_type, "seq"),
        total_in_type=_int(in_type, "total"),
    )


def _int(match: re.Match[str] | None, group: str) -> int | None:
    return int(match[group].replace(",", "")) if match is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_production.py tests/unit/test_fixtures.py -q`
Expected: PASS (`48 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/production server/src/realoem_mcp/parsers/production.py server/tests/unit/parsers/test_production.py
git commit -m "feat(parsers): parse production statistics for a VIN serial" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 3: `decode_vin` tool

### Task 6: VIN input rules (`normalize_vin`)

ARD §5.11: VINs are normalized (uppercase, separators removed) and reduced to the last 7 characters
**before any request**, so short and full VINs share a cache entry and a full VIN is never sent.
The rules are listed under "Decisions" at the top of this plan. `tools/vin.py` starts with only the
input helper; build_server skips tool modules without `register`, so the module is safe to add now.

**Files:**
- Create: `server/src/realoem_mcp/tools/vin.py`
- Test: `server/tests/unit/test_vin_input.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_vin_input.py`:

```python
import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.tools.vin import VinInput, normalize_vin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PX22770", VinInput(serial="PX22770", wmi=None)),
        ("px22770", VinInput(serial="PX22770", wmi=None)),
        (" px-22 770 ", VinInput(serial="PX22770", wmi=None)),
        ("...PX22770", VinInput(serial="PX22770", wmi=None)),
        ("1234567", VinInput(serial="1234567", wmi=None)),
        ("WBA0000000PX22770", VinInput(serial="PX22770", wmi="WBA")),
        ("wba 0000000 px22770", VinInput(serial="PX22770", wmi="WBA")),
        ("WBA-0000000-PX22770", VinInput(serial="PX22770", wmi="WBA")),
        ("WBA.0000000/PX22770", VinInput(serial="PX22770", wmi="WBA")),
    ],
)
def test_normalize_vin_keeps_the_last_seven_and_the_prefix(raw: str, expected: VinInput) -> None:
    assert normalize_vin(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "A VIN has 17 characters; give all 17 or just the last 7 (got 0)."),
        ("PX2277", "A VIN has 17 characters; give all 17 or just the last 7 (got 6)."),
        ("PX227701", "A VIN has 17 characters; give all 17 or just the last 7 (got 8)."),
        ("WBA0000000PX2277", "A VIN has 17 characters; give all 17 or just the last 7 (got 16)."),
        ("PX22770#", "'PX22770#' is not a VIN: a VIN has only letters and digits."),
        ("PX2Ä770", "'PX2Ä770' is not a VIN: a VIN has only letters and digits."),
        # U+017F (long s) upper-cases to an ASCII "S"; it must still be rejected.
        ("PX2\u017f770", "'PX2\u017f770' is not a VIN: a VIN has only letters and digits."),
        (
            "PX2277O",
            "VINs never contain the letters I, O or Q (found O); "
            "check for a 1 or 0 typed as a letter.",
        ),
        (
            "WBAIQ00000PX22770",
            "VINs never contain the letters I, O or Q (found I, Q); "
            "check for a 1 or 0 typed as a letter.",
        ),
    ],
)
def test_normalize_vin_rejects_malformed_input(raw: str, message: str) -> None:
    with pytest.raises(InvalidInput) as info:
        normalize_vin(raw)
    assert info.value.message == message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_vin_input.py -q`
Expected: FAIL with `No module named 'realoem_mcp.tools.vin'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/tools/vin.py`:

```python
"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from realoem_mcp.errors import InvalidInput

_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_vin_input.py -q`
Expected: PASS (`18 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/vin.py server/tests/unit/test_vin_input.py
git commit -m "feat(vin): validate and normalize VIN input" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `decode_vin` for a serial, with VIN cache lifetimes

One request: `select?vin=<last 7>` with `ttl=180 days` (ARD §5.4). `parse_select` gives the selected
levels and the result block; no `vehicle_id` means `not_found`, and that cache entry is shortened to
1 day with `services.cache.shorten`. The brand comes from the vehicle id and the product level
(`M` → Motorrad). WMI checks follow in Task 8 and production statistics in Task 9.

The client caches every fetched page before it is parsed, so a page that raises `LayoutChanged`
(while parsing, or while mapping the selected product/catalog) would otherwise stay cached for 180
days. `_expire_if_unparseable` expires it immediately (`cache.shorten(url, timedelta(0))`) and
re-raises (ARD §5.10); the tests serve a broken page twice and expect two requests. The second
broken-page test writes an edited copy of a fixture to `tmp_path` and routes to its absolute path
(`FIXTURES / "<absolute path>"` is that absolute path).

Tests talk to the real server in memory (`mcp.Client(build_server(services))`), with
`make_services(routes)` serving fixtures by URL; `transport.requests` records what was sent.

**Files:**
- Modify: `server/src/realoem_mcp/tools/vin.py`
- Test: `server/tests/tools/test_vin.py`, `server/tests/tools/test_vin_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/tools/test_vin.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import load_fixture, url

pytestmark = pytest.mark.anyio

SELECT_PX22770 = url("select", vin="PX22770")
ROUTES = {
    SELECT_PX22770: "select/vin_bmw_e93_px22770.html",
    url("select", vin="TD86476"): "select/vin_mini_r53_td86476.html",
    url("select", vin="UX52589"): "select/vin_rr_ghost_ux52589.html",
    url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
    url("select", vin="1234567"): "select/vin_e30_classic_1234567.html",
    url("select", vin="ZZZZZZZ"): "select/vin_miss_zzzzzzz.html",
}


async def _decode(services: Services, **arguments: Any) -> dict[str, Any]:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", arguments)
    assert result.is_error is False, result.content
    data = dict(result.structured_content)
    data.pop("fetched_at")
    return data


async def test_decode_vin_is_listed_with_a_required_vin(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools["decode_vin"].input_schema
    assert schema["required"] == ["vin"]
    assert schema["properties"]["refresh"]["default"] is False
    assert "RealOEM's best match" in tools["decode_vin"].description


async def test_bmw_serial_decodes_every_field(make_services) -> None:
    services, transport = make_services(ROUTES)
    assert await _decode(services, vin="px22770") == {
        "source_urls": [SELECT_PX22770],
        "from_cache": False,
        "requests_made": 1,
        "serial": "PX22770",
        "status": "found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": {
            "vehicle_id": "WL13-USA-07-2008-E93-BMW-328i",
            "type_code": "WL13",
            "market": "USA",
            "production_month": "2008-07",
            "series": "E93",
            "brand": "bmw",
            "model": "328i",
        },
        "product": "car",
        "catalog": "current",
        "series_name": "3' E93 (2005 — 2010)",
        "body": "Convertible",
        "engine": "N52N",
        "steering": None,
        "transmission": None,
        "production": None,
    }
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770]


@pytest.mark.parametrize(
    ("vin", "vehicle_id", "brand", "expected"),
    [
        (
            "TD86476",
            "RE33-USA-04-2004-R53-Mini-Cooper_S",
            "mini",
            {
                "product": "car",
                "catalog": "classic",
                "series_name": "MINI R53",
                "body": "3 doors",
                "engine": "W11",
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "UX52589",
            "FK43-USA-12-2013-RR4-Rolls_Royce-Ghost",
            "rolls-royce",
            {
                "product": "car",
                "catalog": "current",
                "series_name": "Rolls-Royce Ghost RR4",
                "body": "Sedan",
                "engine": "N74R",
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "Z656595",
            "0A61-USA-09-2017-K50-BMW-R_1200_GS_17_0A51,_0A61_",
            "motorrad",
            {
                "product": "motorcycle",
                "catalog": "current",
                "series_name": "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)",
                "body": None,
                "engine": None,
                "steering": None,
                "transmission": None,
            },
        ),
        (
            "1234567",
            "1251-EUR-11-1986-E30-BMW-325e",
            "bmw",
            {
                "product": "car",
                "catalog": "classic",
                "series_name": "3' E30 (1981 — 1994)",
                "body": "Coupe",
                "engine": "M20",
                "steering": "Left hand drive",
                "transmission": "Manual",
            },
        ),
    ],
    ids=["mini-classic", "rolls-royce", "motorrad", "bmw-classic-e30"],
)
async def test_other_brands_and_catalogs(
    make_services, vin: str, vehicle_id: str, brand: str, expected: dict[str, Any]
) -> None:
    services, _ = make_services(ROUTES)
    data = await _decode(services, vin=vin)
    assert (data["status"], data["confidence"], data["warnings"]) == ("found", "normal", [])
    assert (data["vehicle"]["vehicle_id"], data["vehicle"]["brand"]) == (vehicle_id, brand)
    assert {key: data[key] for key in expected} == expected


async def test_unknown_serial_is_not_found(make_services) -> None:
    services, _ = make_services(ROUTES)
    assert await _decode(services, vin="ZZZZZZZ") == {
        "source_urls": [url("select", vin="ZZZZZZZ")],
        "from_cache": False,
        "requests_made": 1,
        "serial": "ZZZZZZZ",
        "status": "not_found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": None,
        "product": None,
        "catalog": None,
        "series_name": None,
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
        "production": None,
    }


async def test_full_vin_sends_only_the_last_seven(make_services) -> None:
    services, transport = make_services(ROUTES)
    data = await _decode(services, vin="WBA-0000000-PX22770")
    assert data["serial"] == "PX22770"
    assert data["vehicle"]["vehicle_id"] == "WL13-USA-07-2008-E93-BMW-328i"
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770]


@pytest.mark.parametrize(
    ("vin", "message"),
    [
        ("PX2277", "give all 17 or just the last 7 (got 6)"),
        ("WBA0000000PX2277", "give all 17 or just the last 7 (got 16)"),
        ("PX22770#", "a VIN has only letters and digits"),
        ("PX2277O", "VINs never contain the letters I, O or Q (found O)"),
    ],
)
async def test_malformed_vin_is_rejected_before_any_request(
    make_services, vin: str, message: str
) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin})
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unparseable_page_is_an_error_and_not_kept_in_the_cache(make_services) -> None:
    services, transport = make_services({SELECT_PX22770: "select/vin_bmw_e93_px22770_v1.html"})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("decode_vin", {"vin": "PX22770"})
        second = await client.call_tool("decode_vin", {"vin": "PX22770"})
    for result in (first, second):
        assert result.is_error is True
        assert "RealOEM's select page did not have the expected structure" in result.content[0].text
    assert [str(request.url) for request in transport.requests] == [SELECT_PX22770] * 2


async def test_hit_without_a_selected_product_is_a_layout_error(make_services, tmp_path) -> None:
    html = load_fixture("select/vin_bmw_e93_px22770.html").replace(
        '<a class="ro-lb-row is-selected" href="/bmw/enUS/select?archive=0&amp;product=P"',
        '<a class="ro-lb-row" href="/bmw/enUS/select?archive=0&amp;product=P"',
    )
    broken = Path(tmp_path) / "select_without_product.html"
    broken.write_text(html, encoding="utf-8")
    # Route fixtures are paths under tests/fixtures/; an absolute path replaces that prefix.
    services, transport = make_services({SELECT_PX22770: str(broken)})
    async with Client(build_server(services)) as client:
        first = await client.call_tool("decode_vin", {"vin": "PX22770"})
        second = await client.call_tool("decode_vin", {"vin": "PX22770"})
    for result in (first, second):
        assert result.is_error is True
        assert "VIN result has no known product selected" in result.content[0].text
    assert len(transport.requests) == 2
```

Create `server/tests/tools/test_vin_cache.py`:

```python
"""VIN hits stay cached 180 days, misses only 1 day (ARD section 5.4)."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import url

pytestmark = pytest.mark.anyio

HIT = url("select", vin="PX22770")
MISS = url("select", vin="ZZZZZZZ")
ROUTES = {HIT: "select/vin_bmw_e93_px22770.html", MISS: "select/vin_miss_zzzzzzz.html"}


def cache_lifetime(services: Services, page_url: str) -> timedelta:
    """expires_at - fetched_at of a cached page, read straight from the SQLite cache file."""
    with closing(sqlite3.connect(services.cache.path)) as conn:
        fetched_at, expires_at = conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (page_url,)
        ).fetchone()
    return datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at)


async def _call(client: Client, **arguments: object) -> dict:
    result = await client.call_tool("decode_vin", arguments)
    assert result.is_error is False, result.content
    return result.structured_content


async def test_hit_is_cached_for_180_days(make_services) -> None:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="PX22770")
    assert cache_lifetime(services, HIT) == timedelta(days=180)


async def test_miss_is_cached_for_1_day(make_services) -> None:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="ZZZZZZZ")
    assert cache_lifetime(services, MISS) == timedelta(days=1)


async def test_repeat_and_full_vin_are_answered_from_the_cache(make_services) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        first = await _call(client, vin="PX22770")
        again = await _call(client, vin="WBA0000000PX22770")
        miss_first = await _call(client, vin="ZZZZZZZ")
        miss_again = await _call(client, vin="zzzzzzz")
    assert (first["from_cache"], first["requests_made"]) == (False, 1)
    assert (again["from_cache"], again["requests_made"]) == (True, 0)
    assert again["vehicle"] == first["vehicle"]
    assert (miss_first["requests_made"], miss_again["requests_made"]) == (1, 0)
    assert miss_again["status"] == "not_found"
    assert [str(request.url) for request in transport.requests] == [HIT, MISS]


async def test_refresh_fetches_again(make_services) -> None:
    services, transport = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        await _call(client, vin="PX22770")
        refreshed = await _call(client, vin="PX22770", refresh=True)
    assert (refreshed["from_cache"], refreshed["requests_made"]) == (False, 1)
    assert len(transport.requests) == 2
    assert cache_lifetime(services, HIT) == timedelta(days=180)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory server pytest tests/tools/test_vin.py tests/tools/test_vin_cache.py -q`
Expected: FAIL (`18 failed`; the tool does not exist yet, e.g. `KeyError: 'decode_vin'` and `Unknown tool: decode_vin`)

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/tools/vin.py` with:

```python
"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.select import SelectPage
from realoem_mcp.models.vin import VinDecodeResult
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

VIN_HIT_TTL = timedelta(days=180)
VIN_MISS_TTL = timedelta(days=1)
EXPIRE_NOW = timedelta(0)
_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")
_PRODUCTS = {"P": "car", "M": "motorcycle"}
_CATALOGS = {"0": "current", "1": "classic"}


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def decode_vin(vin: str, refresh: bool = False) -> VinDecodeResult:
        """Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM.

        Use when the user gives a VIN (all 17 characters or just the last 7) and wants to know
        the vehicle, or before looking up parts for their specific car. Only the last 7
        characters are sent to RealOEM. Returns status ("found" or "not_found"); vehicle
        (vehicle_id to pass to list_part_groups or check_fitment, type_code, market,
        production_month, series, brand, model); product ("car"/"motorcycle"); catalog
        ("current"/"classic"); series_name, body, engine, and steering and transmission when
        RealOEM shows them. RealOEM silently picks one vehicle per serial, so present the result
        as RealOEM's best match. RealOEM has no option codes, paint or upholstery for a VIN.
        refresh=true ignores the cache.
        """
        try:
            return await _decode(services, vin, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err


async def _decode(services: Services, raw: str, *, refresh: bool) -> VinDecodeResult:
    vin = normalize_vin(raw)
    warnings: list[str] = []
    page = await services.client.fetch(
        PageType.SELECT, "select", {"vin": vin.serial}, refresh=refresh, ttl=VIN_HIT_TTL
    )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
                status="not_found",
                confidence="normal",
                warnings=warnings,
            )
        product = _code(select, "product", _PRODUCTS, page.url)
        catalog = _code(select, "catalog", _CATALOGS, page.url)
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    brand = services.brands.for_vehicle_id(vid, product="M" if product == "motorcycle" else "P")
    return VinDecodeResult.from_pages(
        [page],
        serial=vin.serial,
        status="found",
        confidence="normal",
        warnings=warnings,
        vehicle=VehicleRef.from_id(vid, brand.id),
        product=product,
        catalog=catalog,
        series_name=_label(select, "series"),
        body=_label(select, "body"),
        engine=_label(select, "engine"),
        steering=_label(select, "steering"),
        transmission=_label(select, "trans"),
    )


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise


def _code(select: SelectPage, level: str, names: dict[str, str], url: str) -> str:
    option = select.selected(level)
    if option is None or option.value not in names:
        raise LayoutChanged(PageType.SELECT, f"VIN result has no known {level} selected", url)
    return names[option.value]


def _label(select: SelectPage, level: str) -> str | None:
    option = select.selected(level)
    return option.label if option is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/tools/test_vin.py tests/tools/test_vin_cache.py tests/unit/test_vin_input.py -q`
Expected: PASS (`36 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/vin.py server/tests/tools/test_vin.py server/tests/tools/test_vin_cache.py
git commit -m "feat(vin): add decode_vin tool with VIN cache lifetimes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 4: Manufacturer prefix check and production statistics

### Task 8: WMI confidence (PRD F2.3)

ARD §5.11: for a 17-character VIN, `services.brands.for_wmi(vin[:3])` is compared with the decoded
brand. A known prefix of another brand → `confidence="low"` plus a warning; an unknown prefix →
`confidence="normal"` plus "Unrecognized manufacturer prefix …"; 7 characters → no check. The
prefixes come from the foundation's `brands/*/brand.toml` (`bmw`: WBA, WBS, WBY, WBX, 5UX, 5UM,
5YM, 4US, 3MW, LBV; `mini`: WMW, WMZ; `rolls-royce`: SCA; `motorrad`: WB1, WB3). The made-up serial
`TEST001` is routed to the E93 page so extra BMW prefixes can be tested without another real serial.

**Files:**
- Modify: `server/src/realoem_mcp/tools/vin.py`
- Test: `server/tests/tools/test_vin_wmi.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_vin_wmi.py`:

```python
"""Full VINs: the manufacturer prefix (WMI) is checked against the decoded brand (PRD F2.3).

The 17-character VINs below are made up: a real prefix, zeros, and a captured last-7 serial.
"""

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from tests.harness import url

pytestmark = pytest.mark.anyio

ROUTES = {
    url("select", vin="PX22770"): "select/vin_bmw_e93_px22770.html",
    url("select", vin="TD86476"): "select/vin_mini_r53_td86476.html",
    url("select", vin="UX52589"): "select/vin_rr_ghost_ux52589.html",
    url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
    url("select", vin="ZZZZZZZ"): "select/vin_miss_zzzzzzz.html",
    url("select", vin="TEST001"): "select/vin_bmw_e93_px22770.html",  # made-up serial
}


async def _decode(make_services, vin: str) -> dict:
    services, _ = make_services(ROUTES)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin})
    assert result.is_error is False, result.content
    return result.structured_content


@pytest.mark.parametrize(
    ("vin", "brand"),
    [
        ("WBA0000000PX22770", "bmw"),
        ("WBS0000000PX22770", "bmw"),
        ("5UX0000000PX22770", "bmw"),
        ("LBV0000000TEST001", "bmw"),
        ("WBX0000000TEST001", "bmw"),
        ("WMW0000000TD86476", "mini"),
        ("SCA0000000UX52589", "rolls-royce"),
        ("WB10000000Z656595", "motorrad"),
    ],
)
async def test_matching_prefix_is_normal_confidence(make_services, vin: str, brand: str) -> None:
    data = await _decode(make_services, vin)
    assert data["vehicle"]["brand"] == brand
    assert (data["confidence"], data["warnings"]) == ("normal", [])


async def test_prefix_of_another_brand_is_low_confidence(make_services) -> None:
    data = await _decode(make_services, "WMW0000000PX22770")
    assert data["status"] == "found"
    assert data["vehicle"]["brand"] == "bmw"
    assert data["confidence"] == "low"
    assert data["warnings"] == [
        "The VIN's manufacturer prefix WMW belongs to MINI, but RealOEM matched serial PX22770 "
        "to a BMW vehicle; it is probably a different vehicle with the same last 7 characters."
    ]


async def test_car_prefix_on_a_motorcycle_serial_is_low_confidence(make_services) -> None:
    data = await _decode(make_services, "WBA0000000Z656595")
    assert data["vehicle"]["brand"] == "motorrad"
    assert data["confidence"] == "low"
    (warning,) = data["warnings"]
    assert "belongs to BMW, but RealOEM matched serial Z656595 to a BMW Motorrad vehicle" in warning


async def test_unrecognized_prefix_keeps_normal_confidence_with_a_warning(make_services) -> None:
    data = await _decode(make_services, "JHM0000000PX22770")
    assert data["vehicle"]["brand"] == "bmw"
    assert data["confidence"] == "normal"
    assert data["warnings"] == [
        "Unrecognized manufacturer prefix JHM: it is not a known BMW, MINI, Rolls-Royce or "
        "BMW Motorrad prefix."
    ]


async def test_unrecognized_prefix_is_reported_even_when_not_found(make_services) -> None:
    data = await _decode(make_services, "JHM0000000ZZZZZZZ")
    assert (data["status"], data["confidence"]) == ("not_found", "normal")
    assert data["warnings"][0].startswith("Unrecognized manufacturer prefix JHM")


async def test_seven_characters_skip_the_prefix_check(make_services) -> None:
    data = await _decode(make_services, "TD86476")
    assert (data["confidence"], data["warnings"]) == ("normal", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_vin_wmi.py -q`
Expected: FAIL (`4 failed, 9 passed`; matching prefixes and 7-character input already pass)

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/tools/vin.py` with:

```python
"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.select import SelectPage
from realoem_mcp.models.vin import VinDecodeResult
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

VIN_HIT_TTL = timedelta(days=180)
VIN_MISS_TTL = timedelta(days=1)
EXPIRE_NOW = timedelta(0)
_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")
_PRODUCTS = {"P": "car", "M": "motorcycle"}
_CATALOGS = {"0": "current", "1": "classic"}


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def decode_vin(vin: str, refresh: bool = False) -> VinDecodeResult:
        """Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM.

        Use when the user gives a VIN (all 17 characters or just the last 7) and wants to know
        the vehicle, or before looking up parts for their specific car. Only the last 7
        characters are sent to RealOEM. Returns status ("found" or "not_found"); vehicle
        (vehicle_id to pass to list_part_groups or check_fitment, type_code, market,
        production_month, series, brand, model); product ("car"/"motorcycle"); catalog
        ("current"/"classic"); series_name, body, engine, and steering and transmission when
        RealOEM shows them. RealOEM silently picks one vehicle per serial, so present the result
        as RealOEM's best match; confidence is "low" when a full VIN's manufacturer prefix does
        not match the decoded brand, and warnings explain why. RealOEM has no option codes, paint
        or upholstery for a VIN. refresh=true ignores the cache.
        """
        try:
            return await _decode(services, vin, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err


async def _decode(services: Services, raw: str, *, refresh: bool) -> VinDecodeResult:
    vin = normalize_vin(raw)
    warnings: list[str] = []
    wmi_brand = None
    if vin.wmi is not None:
        wmi_brand = services.brands.for_wmi(vin.wmi)
        if wmi_brand is None:
            warnings.append(
                f"Unrecognized manufacturer prefix {vin.wmi}: it is not a known BMW, MINI, "
                "Rolls-Royce or BMW Motorrad prefix."
            )
    page = await services.client.fetch(
        PageType.SELECT, "select", {"vin": vin.serial}, refresh=refresh, ttl=VIN_HIT_TTL
    )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
                status="not_found",
                confidence="normal",
                warnings=warnings,
            )
        product = _code(select, "product", _PRODUCTS, page.url)
        catalog = _code(select, "catalog", _CATALOGS, page.url)
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    brand = services.brands.for_vehicle_id(vid, product="M" if product == "motorcycle" else "P")
    confidence = "normal"
    if wmi_brand is not None and wmi_brand.id != brand.id:
        confidence = "low"
        warnings.append(
            f"The VIN's manufacturer prefix {vin.wmi} belongs to {wmi_brand.display_name}, but "
            f"RealOEM matched serial {vin.serial} to a {brand.display_name} vehicle; it is "
            "probably a different vehicle with the same last 7 characters."
        )
    return VinDecodeResult.from_pages(
        [page],
        serial=vin.serial,
        status="found",
        confidence=confidence,
        warnings=warnings,
        vehicle=VehicleRef.from_id(vid, brand.id),
        product=product,
        catalog=catalog,
        series_name=_label(select, "series"),
        body=_label(select, "body"),
        engine=_label(select, "engine"),
        steering=_label(select, "steering"),
        transmission=_label(select, "trans"),
    )


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise


def _code(select: SelectPage, level: str, names: dict[str, str], url: str) -> str:
    option = select.selected(level)
    if option is None or option.value not in names:
        raise LayoutChanged(PageType.SELECT, f"VIN result has no known {level} selected", url)
    return names[option.value]


def _label(select: SelectPage, level: str) -> str | None:
    option = select.selected(level)
    return option.label if option is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/tools -q`
Expected: PASS (`36 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/vin.py server/tests/tools/test_vin_wmi.py
git commit -m "feat(vin): flag full VINs whose manufacturer prefix contradicts the brand" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: `include_production` (PRD F2.4)

With `include_production=true` and a found vehicle, one more request: `production?vin=<last 7>`
(default production TTL, 180 days). `pick_production` keeps the record for the decoded type code:
no record → warning (and the cache entry is shortened to 1 day); only another type → no statistics
plus a warning; several records → the decoded type's statistics plus a warning. A `not_found` VIN
makes no production request. An unreadable production page raises `LayoutChanged` for the whole call
and is expired from the cache like the select page.

**Files:**
- Modify: `server/src/realoem_mcp/tools/vin.py`
- Test: `server/tests/unit/test_pick_production.py`, `server/tests/tools/test_vin_production.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/unit/test_pick_production.py`:

```python
from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.tools.vin import pick_production

WL13 = ProductionStats(
    built_month="2008-07", seq_in_month=321, total_in_month=547, seq_in_type=1, total_in_type=2
)
RE33 = ProductionStats(
    built_month="2004-04", seq_in_month=228, total_in_month=1392, seq_in_type=3, total_in_type=4
)


def test_single_record_for_the_decoded_type() -> None:
    assert pick_production({"WL13": WL13}, "PX22770", "WL13") == (WL13, [])


def test_no_record() -> None:
    assert pick_production({}, "PX22770", "WL13") == (
        None,
        ["RealOEM has no production record for serial PX22770."],
    )


def test_record_for_another_type_is_left_out() -> None:
    assert pick_production({"RE33": RE33}, "PX22770", "WL13") == (
        None,
        [
            "RealOEM's production record for serial PX22770 is for type RE33, not the decoded "
            "type WL13; build statistics were left out."
        ],
    )


def test_records_for_other_types_only_are_left_out() -> None:
    assert pick_production({"RE33": RE33, "RE31": RE33}, "PX22770", "WL13") == (
        None,
        [
            "RealOEM's production records for serial PX22770 are for types RE33, RE31, not the "
            "decoded type WL13; build statistics were left out."
        ],
    )


def test_several_records_pick_the_decoded_type_and_warn() -> None:
    assert pick_production({"RE33": RE33, "WL13": WL13}, "PX22770", "WL13") == (
        WL13,
        [
            "RealOEM's production records list 2 vehicles for serial PX22770 (types RE33, WL13); "
            "the decoded vehicle may not be the right one."
        ],
    )
```

`test_vin_production.py` reuses `cache_lifetime` from Task 7's `test_vin_cache.py`.

Create `server/tests/tools/test_vin_production.py`:

```python
"""include_production=true: one extra production?vin= request (PRD F2.4)."""

from datetime import timedelta

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import url
from tests.tools.test_vin_cache import cache_lifetime

pytestmark = pytest.mark.anyio

SELECT = url("select", vin="PX22770")
PRODUCTION = url("production", vin="PX22770")
SELECT_MISS = url("select", vin="ZZZZZZZ")


async def _decode(services: Services, vin: str) -> dict:
    async with Client(build_server(services)) as client:
        result = await client.call_tool("decode_vin", {"vin": vin, "include_production": True})
    assert result.is_error is False, result.content
    return result.structured_content


async def test_include_production_parameter_defaults_to_false(make_services) -> None:
    services, _ = make_services({})
    async with Client(build_server(services)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert tools["decode_vin"].input_schema["properties"]["include_production"]["default"] is False


async def test_production_statistics_are_added(make_services) -> None:
    services, transport = make_services(
        {
            SELECT: "select/vin_bmw_e93_px22770.html",
            PRODUCTION: "production/vin_bmw_e93_px22770.html",
        }
    )
    data = await _decode(services, "PX22770")
    assert data["production"] == {
        "built_month": "2008-07",
        "seq_in_month": 321,
        "total_in_month": 547,
        "seq_in_type": 12557,
        "total_in_type": 17781,
    }
    assert data["source_urls"] == [SELECT, PRODUCTION]
    assert (data["requests_made"], data["warnings"]) == (2, [])
    assert [str(request.url) for request in transport.requests] == [SELECT, PRODUCTION]
    assert cache_lifetime(services, PRODUCTION) == timedelta(days=180)


async def test_production_miss_is_a_warning_cached_for_1_day(make_services) -> None:
    services, _ = make_services(
        {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "production/vin_miss_zzzzzzz.html"}
    )
    data = await _decode(services, "PX22770")
    assert data["status"] == "found"
    assert data["production"] is None
    assert data["warnings"] == ["RealOEM has no production record for serial PX22770."]
    assert cache_lifetime(services, PRODUCTION) == timedelta(days=1)
    assert cache_lifetime(services, SELECT) == timedelta(days=180)


async def test_production_record_for_another_type_is_left_out(make_services) -> None:
    services, _ = make_services(
        {
            SELECT: "select/vin_bmw_e93_px22770.html",
            PRODUCTION: "production/vin_mini_r53_td86476.html",
        }
    )
    data = await _decode(services, "PX22770")
    assert data["production"] is None
    assert data["warnings"] == [
        "RealOEM's production record for serial PX22770 is for type RE33, not the decoded type "
        "WL13; build statistics were left out."
    ]


async def test_motorcycle_production(make_services) -> None:
    services, _ = make_services(
        {
            url("select", vin="Z656595"): "select/vin_moto_r1200gs_z656595.html",
            url("production", vin="Z656595"): "production/vin_moto_r1200gs_z656595.html",
        }
    )
    data = await _decode(services, "WB10000000Z656595")
    assert data["production"]["built_month"] == "2017-09"
    assert (data["production"]["seq_in_month"], data["production"]["total_in_month"]) == (73, 246)


async def test_unparseable_production_page_fails_and_is_not_kept(make_services) -> None:
    services, transport = make_services(
        {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "select/vin_miss_zzzzzzz.html"}
    )
    async with Client(build_server(services)) as client:
        for _ in range(2):
            result = await client.call_tool(
                "decode_vin", {"vin": "PX22770", "include_production": True}
            )
            assert result.is_error is True
            assert "missing '#ps-vin-result'" in result.content[0].text
    assert [str(request.url) for request in transport.requests] == [SELECT, PRODUCTION, PRODUCTION]


async def test_no_production_request_when_the_vin_is_not_found(make_services) -> None:
    services, transport = make_services({SELECT_MISS: "select/vin_miss_zzzzzzz.html"})
    data = await _decode(services, "ZZZZZZZ")
    assert (data["status"], data["production"], data["requests_made"]) == ("not_found", None, 1)
    assert [str(request.url) for request in transport.requests] == [SELECT_MISS]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory server pytest tests/unit/test_pick_production.py tests/tools/test_vin_production.py -q`
Expected: FAIL with `cannot import name 'pick_production'`

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/tools/vin.py` with:

```python
"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.select import SelectPage
from realoem_mcp.models.vin import ProductionStats, VinDecodeResult
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.production import parse_production
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

VIN_HIT_TTL = timedelta(days=180)
VIN_MISS_TTL = timedelta(days=1)
EXPIRE_NOW = timedelta(0)
_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")
_PRODUCTS = {"P": "car", "M": "motorcycle"}
_CATALOGS = {"0": "current", "1": "classic"}


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)


def pick_production(
    matches: dict[str, ProductionStats], serial: str, type_code: str
) -> tuple[ProductionStats | None, list[str]]:
    """The build statistics for the decoded type code, plus warnings about the other records."""
    if not matches:
        return None, [f"RealOEM has no production record for serial {serial}."]
    stats = matches.get(type_code)
    if stats is None:
        types = ", ".join(matches)
        if len(matches) == 1:
            found = f"RealOEM's production record for serial {serial} is for type {types}"
        else:
            found = f"RealOEM's production records for serial {serial} are for types {types}"
        return None, [f"{found}, not the decoded type {type_code}; build statistics were left out."]
    if len(matches) > 1:
        return stats, [
            f"RealOEM's production records list {len(matches)} vehicles for serial {serial} "
            f"(types {', '.join(matches)}); the decoded vehicle may not be the right one."
        ]
    return stats, []


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def decode_vin(
        vin: str, include_production: bool = False, refresh: bool = False
    ) -> VinDecodeResult:
        """Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM.

        Use when the user gives a VIN (all 17 characters or just the last 7) and wants to know
        the vehicle, or before looking up parts for their specific car. Only the last 7
        characters are sent to RealOEM. Returns status ("found" or "not_found"); vehicle
        (vehicle_id to pass to list_part_groups or check_fitment, type_code, market,
        production_month, series, brand, model); product ("car"/"motorcycle"); catalog
        ("current"/"classic"); series_name, body, engine, and steering and transmission when
        RealOEM shows them. RealOEM silently picks one vehicle per serial, so present the result
        as RealOEM's best match; confidence is "low" when a full VIN's manufacturer prefix does
        not match the decoded brand, and warnings explain why. include_production=true adds one
        request for build statistics (build month, number within that month and within the type
        code). RealOEM has no option codes, paint or upholstery for a VIN. refresh=true ignores
        the cache.
        """
        try:
            return await _decode(
                services, vin, include_production=include_production, refresh=refresh
            )
        except RealOemError as err:
            raise ToolError(err.message) from err


async def _decode(
    services: Services, raw: str, *, include_production: bool, refresh: bool
) -> VinDecodeResult:
    vin = normalize_vin(raw)
    warnings: list[str] = []
    wmi_brand = None
    if vin.wmi is not None:
        wmi_brand = services.brands.for_wmi(vin.wmi)
        if wmi_brand is None:
            warnings.append(
                f"Unrecognized manufacturer prefix {vin.wmi}: it is not a known BMW, MINI, "
                "Rolls-Royce or BMW Motorrad prefix."
            )
    page = await services.client.fetch(
        PageType.SELECT, "select", {"vin": vin.serial}, refresh=refresh, ttl=VIN_HIT_TTL
    )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
                status="not_found",
                confidence="normal",
                warnings=warnings,
            )
        product = _code(select, "product", _PRODUCTS, page.url)
        catalog = _code(select, "catalog", _CATALOGS, page.url)
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    brand = services.brands.for_vehicle_id(vid, product="M" if product == "motorcycle" else "P")
    confidence = "normal"
    if wmi_brand is not None and wmi_brand.id != brand.id:
        confidence = "low"
        warnings.append(
            f"The VIN's manufacturer prefix {vin.wmi} belongs to {wmi_brand.display_name}, but "
            f"RealOEM matched serial {vin.serial} to a {brand.display_name} vehicle; it is "
            "probably a different vehicle with the same last 7 characters."
        )
    pages = [page]
    production = None
    if include_production:
        production_page = await services.client.fetch(
            PageType.PRODUCTION, "production", {"vin": vin.serial}, refresh=refresh
        )
        pages.append(production_page)
        with _expire_if_unparseable(services, production_page):
            matches = parse_production(production_page.html, url=production_page.url)
        if not matches:
            services.cache.shorten(production_page.url, VIN_MISS_TTL)
        production, notes = pick_production(matches, vin.serial, select.type_code)
        warnings.extend(notes)
    return VinDecodeResult.from_pages(
        pages,
        serial=vin.serial,
        status="found",
        confidence=confidence,
        warnings=warnings,
        vehicle=VehicleRef.from_id(vid, brand.id),
        product=product,
        catalog=catalog,
        series_name=_label(select, "series"),
        body=_label(select, "body"),
        engine=_label(select, "engine"),
        steering=_label(select, "steering"),
        transmission=_label(select, "trans"),
        production=production,
    )


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise


def _code(select: SelectPage, level: str, names: dict[str, str], url: str) -> str:
    option = select.selected(level)
    if option is None or option.value not in names:
        raise LayoutChanged(PageType.SELECT, f"VIN result has no known {level} selected", url)
    return names[option.value]


def _label(select: SelectPage, level: str) -> str | None:
    option = select.selected(level)
    return option.label if option is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/test_pick_production.py tests/tools -q`
Expected: PASS (`48 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/vin.py server/tests/unit/test_pick_production.py server/tests/tools/test_vin_production.py
git commit -m "feat(vin): add optional production statistics to decode_vin" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 5: Skill, live test, delivery

### Task 10: `vin-decode` skill

ARD §5.12 and PRD F2.5. Skills load from the plugin's default `skills/` folder, so no manifest edit
is needed. The skill refers to tools by short name. `list_part_groups` (feature C) and
`check_fitment` (feature D) may not be merged yet; the skill says to use them "if they are
available".

**Files:**
- Create: `skills/vin-decode/SKILL.md`
- Test: `server/tests/unit/test_skill_vin_decode.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_skill_vin_decode.py`:

```python
"""skills/vin-decode/SKILL.md: trigger-oriented frontmatter and the facts the PRD requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "vin-decode" / "SKILL.md"


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
    assert meta["name"] == "vin-decode"
    for trigger in ("VIN", "decode my VIN", "what car is this VIN", "last 7"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_tool_use_limits_and_next_steps() -> None:
    _, body = _read()
    for phrase in (
        "`decode_vin`",
        "`include_production=true`",
        "without `include_production`",
        "underscores as spaces",
        "RealOEM's best match",
        "`confidence` is `low`",
        "option codes",
        "paint",
        "upholstery",
        "`list_part_groups`",
        "`check_fitment`",
        "`vehicle.vehicle_id`",
        "Never fetch RealOEM pages directly",
    ):
        assert phrase in body, phrase
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_skill_vin_decode.py -q`
Expected: FAIL with `FileNotFoundError` (`2 failed`)

- [ ] **Step 3: Write the skill**

Create `skills/vin-decode/SKILL.md`:

````markdown
---
name: vin-decode
description: Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM. Use when the user gives a VIN (all 17 characters or the last 7) or asks "decode my VIN", "what car is this VIN", "what engine / build date does VIN ... have", or wants parts for their own car identified by its VIN.
---

# VIN decode

Turns a VIN into the vehicle RealOEM has on file for it (series, model, body, engine, market,
production month, type code) and a vehicle id that the other RealOEM tools accept.

## Steps

1. Call `decode_vin` with the VIN as the user gave it: all 17 characters or just the last 7.
   Spaces, dashes and dots are fine, and case does not matter. The server sends only the last 7
   characters to RealOEM.
   - Add `include_production=true` only when the user asks when the vehicle was built or how many
     were made; it costs one more request. If RealOEM's production page cannot be read, the whole
     call fails; call `decode_vin` again without `include_production` to still get the vehicle.
   - Use `refresh=true` only if the user says the answer looks out of date (results are cached
     for 180 days).
2. If the tool returns an error about the input, show it and ask for the VIN again. VINs never
   contain the letters I, O or Q; a "0" or "1" typed as a letter is the usual mistake.
3. `status` is `not_found`: RealOEM has no vehicle for that serial. Ask the user to check the last 7
   characters, or to identify the vehicle by model instead.
4. `status` is `found`: present the result as described below.

## Presenting the result

- Call it **RealOEM's best match** for the serial. RealOEM matches only the last 7 characters and
  silently picks one vehicle; it never offers alternatives.
- If `confidence` is `low`, say so first: the VIN's manufacturer prefix belongs to a different
  brand than the decoded vehicle, so the match is probably a different vehicle with the same last
  7 characters. Ask the user to double-check the VIN.
- Show every entry of `warnings`.
- Show: brand (`vehicle.brand`), `series_name`, model (`vehicle.model`, which comes from the
  vehicle id: show its underscores as spaces, e.g. `Cooper_S` as "Cooper S"), `body`, `engine`,
  `vehicle.market`, production month (`vehicle.production_month`), `steering` and `transmission`
  when present, `vehicle.type_code`, catalog (`classic` = RealOEM's Classic catalog for older
  vehicles) and `vehicle.vehicle_id`.
- Motorcycles have no body or engine in RealOEM; `product` is `motorcycle`.
- With `production`: built month, "number N of M built that month" (`seq_in_month` /
  `total_in_month`) and "number N of M of this type code" (`seq_in_type` / `total_in_type`).
- Link the pages in `source_urls`.

## What RealOEM cannot tell you

RealOEM does not have option codes (SA codes), paint, upholstery, model year or the factory build
sheet for a VIN, and it shows a transmission only for Classic-catalog cars. Say so plainly instead
of guessing, and suggest a BMW dealer or a dedicated VIN decoder for option codes.

## Next steps

Use `vehicle.vehicle_id` from this result with the other RealOEM tools, if they are available:

- Parts diagrams for this vehicle: `list_part_groups` with the vehicle id.
- Does a part fit this vehicle: `check_fitment` with the part number and the vehicle id.

Prefer this vehicle id over ids from part lookups: it carries the vehicle's own production month,
and RealOEM filters parts lists by that month.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Do not call `decode_vin` again for a VIN you already decoded in this conversation.
- Brand notes: `brands/<brand>/README.md`.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_skill_vin_decode.py -q`
Expected: PASS (`2 passed`)

Run: `claude plugin validate . --strict`
Expected: `✔ Validation passed` (if claude is not on your PATH, run the same command with the full
path of your Claude Code executable).

- [ ] **Step 5: Commit**

```bash
git add skills/vin-decode/SKILL.md server/tests/unit/test_skill_vin_decode.py
git commit -m "feat(skills): add vin-decode skill" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Opt-in live smoke test

ARD §8: live tests carry `@pytest.mark.live`, are deselected by default and skipped unless
`REALOEM_LIVE=1`. This one decodes `PX22770` with production statistics: exactly 2 requests. Do
**not** run it with `REALOEM_LIVE=1` while implementing; CI never runs it.

**Files:**
- Test: `server/tests/live/test_live_vin.py`

- [ ] **Step 1: Write the test**

Create `server/tests/live/test_live_vin.py`:

```python
"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_decode_vin_live(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            result = await client.call_tool(
                "decode_vin", {"vin": "PX22770", "include_production": True}
            )
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert data["requests_made"] == 2
    assert data["vehicle"]["vehicle_id"] == "WL13-USA-07-2008-E93-BMW-328i"
    assert data["production"]["built_month"] == "2008-07"
```

- [ ] **Step 2: Verify it is deselected by default**

Run: `uv run --directory server pytest tests/live -q; echo "exit=$?"`
Expected: PASS (`2 deselected`, `exit=5`: pytest exits with 5 when every collected test is deselected)

- [ ] **Step 3: Verify it is skipped without `REALOEM_LIVE=1`**

Run: `uv run --directory server pytest tests/live -q -m live`
Expected: PASS (`2 skipped`)

- [ ] **Step 4: Lint**

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/live/test_live_vin.py
git commit -m "test(live): add opt-in decode_vin smoke test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest -q
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: `337 passed, 2 deselected`, `All checks passed!`, `62 files already formatted` (higher
counts if other feature branches are already on main).

- [ ] **Step 2: No full VIN in any committed fixture, nothing raw or generated staged**

```bash
grep -rEl '(^|[^A-Za-z0-9])[A-HJ-NPR-Z0-9]{17}([^A-Za-z0-9]|$)' server/tests/fixtures || echo "no full VINs"
git status --short && git ls-files | grep -E '^\.research-raw/|\.sqlite3$|\.venv/' || echo clean
```

Expected: `no full VINs`, then no status lines and `clean`.

- [ ] **Step 3: Confirm the branch only adds files**

Run: `git diff --name-status main...HEAD | grep -v '^A' || echo "only additions"`
Expected: `only additions`

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin feat/vin-decode
gh pr create --base main --head feat/vin-decode --title "feat: VIN decode (decode_vin tool, select and production parsers, vin-decode skill)" --body "$(cat <<'EOF'
## Summary

Implements PRD F2 (feature B) per ARD §5.11:

- `decode_vin(vin, include_production=False, refresh=False)`: accepts the last 7 or all 17 VIN characters (uppercased, separators removed, I/O/Q rejected) and sends only the last 7 to RealOEM (`select?vin=`, optionally `production?vin=`). Malformed input is rejected before any request.
- Returns brand, product, catalog, series, body, model, market, production month, engine, steering/transmission (Classic cars), type code and vehicle id; `not_found` for unknown serials.
- Full VINs: the manufacturer prefix (WMI) is checked against the decoded brand; a mismatch gives `confidence="low"` plus a warning, an unknown prefix a warning.
- VIN hits are cached 180 days; select and production misses are shortened to 1 day.
- `parsers/select.py` + `models/select.py`: full v2 select-page parser (every level's options, effective selection, result block), ready for reuse by the diagram-browsing cascade; `LayoutChanged` on v1 markup or unexpected structure.
- `parsers/production.py`: production statistics per type code.
- `skills/vin-decode/SKILL.md`: triggers, presentation as RealOEM's best match, no option codes/paint/upholstery, next steps (`list_part_groups`, `check_fitment`).
- 16 trimmed fixtures (VIN pages for BMW, MINI, Rolls-Royce, Motorrad and a Classic E30; mid-cascade select pages; production pages); no full VIN in any fixture.

Only adds files; no foundation file changed, no version bump.

## Test plan

- [x] `uv run pytest` (offline) and `uv run ruff check` / `ruff format --check`
- [x] Parser tests on every fixture incl. mid-cascade pages and `LayoutChanged` cases
- [x] Tool tests via in-memory `mcp.Client`: all brands/catalogs, not found, rejected before any request, cache lifetimes, WMI confidence, production statistics
- [ ] `claude plugin validate . --strict` (tick after running it locally; Task 10 Step 4)
- [ ] CI green
- [ ] Optional: `REALOEM_LIVE=1 uv run pytest -m live tests/live/test_live_vin.py` (2 requests)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
