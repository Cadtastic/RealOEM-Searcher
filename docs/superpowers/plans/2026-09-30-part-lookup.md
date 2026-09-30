# Part Lookup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/part-lookup` (PRD F1.1–F1.4, feature A): a `lookup_part` MCP tool that, for an 11-digit or 7-digit BMW Group part number, returns the part header (description, supplier reference, dates, weight), status (`current` / `ended` / `not_found`), superseded-by and supersedes lists and the series using the part (each tagged with its brand), or, narrowed to one series, the vehicles and diagrams showing it; plus the exported helpers other features reuse (`fetch_part_xref`, `parse_supersession`, `normalize`, `matches`) and the `part-lookup` skill.

**Architecture:** One RealOEM request per call (`partxref?q=<digits>[&series=<code>]`) through the foundation's cached, rate-limited `RealOemClient`. Input is validated and normalized before any request (`parsers/part_numbers.py`). Pure parsers turn the page into pydantic models: `parsers/supersession.py` (shared with features D and E) and `parsers/partxref.py`, which tags series and vehicles with brands via the foundation `BrandRegistry` and builds `VehicleRef` / `DiagramRef` only through the foundation helpers. `tools/parts.py` verifies the returned number (`matches`), derives the status and wraps everything in a `ResultMeta` result. The tool module is auto-discovered, so no foundation file changes.

**Tech Stack:** Python ≥ 3.11, uv, mcp 2.x (`MCPServer`, in-memory `mcp.Client` for tests), selectolax (lexbor), pydantic 2, pytest + AnyIO, ruff. Contract: `docs/ARD.md` §5.9–§5.11, §8; site facts: `docs/research/realoem-site-notes.md` §1 and §3.

---

## Before you start

- `feat/foundation` is merged into `main`. This plan only **adds** files; it edits no foundation
  file. Read `docs/ARD.md` §5.9–§5.11 and §8 and `docs/research/realoem-site-notes.md` §3 once.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.**
  Python commands use `uv run --directory server …`, which runs inside `server/`; paths after it
  (like `tests/unit/parsers/test_part_numbers.py`) are relative to `server/`. `git` paths are
  relative to the repository root.
- Never make requests to realoem.com while implementing. Tests are offline: routes map URLs to
  fixture files. The only live test (Task 9) is opt-in and must not be run with `REALOEM_LIVE=1`.
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`.
- Foundation APIs used here (do not re-implement them):
  - `realoem_mcp.parsers.common`: `tree`, `text`, `require`, `parse_mdy`, `parse_my`, `Node`, `Tree`.
  - `realoem_mcp.errors`: `InvalidInput`, `LayoutChanged(page_type, detail, url)`, `RealOemError`.
  - `realoem_mcp.page_types.PageType.PARTXREF`; `services.client.fetch(PageType.PARTXREF,
    "partxref", {"q": ..., "series": ...}, refresh=...)` returns a `Page`.
  - `services.brands.for_series(code, label=...)`, `services.brands.for_vehicle_id(vid,
    product=...)`, `services.brands.brand_segments()`; `VehicleId.parse(raw, brand_segments=...)`.
  - `VehicleRef.from_id(vid, brand)`, `DiagramRef.build(client, vehicle_id, diag_id, name)`,
    `ResultMeta.from_pages(pages, **fields)` from `realoem_mcp.models.common`.
  - Tests: `from tests.harness import FIXTURES, MakeServices, Route, load_fixture, url`; the
    `make_services` fixture (in `tests/conftest.py`, typed `MakeServices`) returns
    `(services, transport)`, asserts at teardown that no unrouted URL was requested, and needs an
    `async` test (`pytestmark = pytest.mark.anyio`). `transport.requests` lists what was sent.
- mcp 2.x: raising `ToolError("msg")` in a tool returns `is_error=True` with text
  `Error executing tool <name>: msg`; `result.structured_content` is the returned model as JSON.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that). Do not bump any version.

## File Structure

| Path | Responsibility |
|---|---|
| `server/tests/fixtures/partxref/*.html` (16 files) | Trimmed real `partxref` pages (list in Task 1) |
| `server/src/realoem_mcp/parsers/part_numbers.py` | `normalize(raw)` (7/11 digits, separators stripped, else `InvalidInput`), `matches(query, returned)`, `JUNK_PART` |
| `server/src/realoem_mcp/models/parts.py` | `SupersessionEntry`, `SeriesUse`, `ModelUse`, `PartXref`, `PartLookupResult` (ARD §5.11) |
| `server/src/realoem_mcp/parsers/supersession.py` | `parse_supersession(tree, *, url) -> (superseded_by, supersedes)` and `checked_mdy` (strict date helper); reused by D and E |
| `server/src/realoem_mcp/parsers/partxref.py` | `parse_partxref(html, *, url, brands, client) -> PartXref \| None` |
| `server/src/realoem_mcp/tools/parts.py` | `fetch_part_xref(...)` (exported for D and E) and the `lookup_part` tool (`register`) |
| `skills/part-lookup/SKILL.md` | Skill: when and how to call `lookup_part`, how to present results |
| `server/tests/unit/parsers/test_partxref_fixtures.py` | Each fixture is the right capture |
| `server/tests/unit/parsers/test_part_numbers.py` | `normalize` / `matches` |
| `server/tests/unit/test_models_parts.py` | Models and `PartLookupResult.from_pages` |
| `server/tests/unit/parsers/test_supersession.py` | Supersession blocks, incl. `LayoutChanged` |
| `server/tests/unit/parsers/test_partxref.py` | Header, description, series per brand, not-found pages, `LayoutChanged` |
| `server/tests/unit/parsers/test_partxref_models.py` | Vehicle rows for one series (BMW, Motorrad, Rolls-Royce) |
| `server/tests/tools/test_parts.py` | `lookup_part` through the in-memory `mcp.Client`; `fetch_part_xref` |
| `server/tests/unit/test_skill_part_lookup.py` | Skill frontmatter and required rules |
| `server/tests/live/test_part_lookup_live.py` | Opt-in live smoke test (2 requests) |

Decisions this plan makes where the ARD leaves room (later feature plans may rely on them):

- **Parser signature.** `parse_partxref(html, *, url, brands, client)` takes two keyword-only
  arguments beyond ARD §5.9's `(html, *, url)`: `SeriesUse.brand` and `VehicleRef.brand` need the
  brand registry, and `DiagramRef.build` needs the client (ARD §5.10). It still performs no I/O.
  It returns `None` when the page shows RealOEM's "was not found" error div (unknown part, empty
  `q`); any other error text raises `LayoutChanged`.
- **Status.** `PartXref.ended` is exactly the page's "(ENDED)" marker on the To date.
  `lookup_part` reports `not_found` when the parser returns `None` or `matches()` fails (last-7
  false match, junk part `00000000000`); `ended` when `ended` is true **or** `superseded_by` is
  non-empty; otherwise `current`. The page `<title>` is never read (it says "Discontinued" on the
  no-vehicles template even for current parts).
- **Description** (ARD order): `<h1>number - description</h1>`, then
  `a.ecs-tuning-button[data-ecs-part-name]`, then a supersession link naming this part; else `None`.
- **Series rows.** `code` = the link's `series=` parameter; `name` = link text without the leading
  "BMW " (RealOEM prefixes every label with it) and without the date range; `brand` =
  `brands.for_series(code, label=<full link text>)`; dates via `parse_my` (`None` for "(–)").
- **Vehicle rows** (with `series`). `vehicle` = `VehicleRef.from_id(VehicleId.parse(<href id>,
  brand_segments=brands.brand_segments()), brand)`, keeping RealOEM's `_` id form verbatim;
  `brand` = `brands.for_vehicle_id(vid, product="M" if type code starts with "0" else "P")`;
  `diagram` = `DiagramRef.build(client, vid.raw, <href diagId>, <link text>)`. `body`/`engine` are
  the two fields after the model in the row text (the model is located by comparing with the id's
  model segment, because Rolls-Royce rows add a transmission and motorcycle names contain commas);
  blank and `N/A` become `None`. Only spaces and parentheses are mapped to `_` when comparing, so a
  model whose id segment differs in other ways gets `body`/`engine` = `None` (tested fallback; the
  vehicle id itself is always parsed from the link).
- **`series` input** is stripped, uppercased and must match `[A-Z0-9]{2,8}`, else `InvalidInput`
  before any request; a blank or whitespace-only value means "no series". Parameters are sent in
  the order `q`, `series`.
- **`LayoutChanged`** (NFR3, never silent partial data) when: no `div.content > h1` and no error
  div; an error div without "was not found"; an `h1` that is not a number; no header `dl` or no
  From/To in it; a From date that does not parse or a To that is neither `-` nor a date; a
  Weight that is not "<number> kg"; no
  `div.partSearchResults`; "was found on the following … vehicles" with no parseable rows; a series
  label without the `(MM/YYYY–MM/YYYY)` range or with an unparseable month; a result link that is
  neither `partxref?…series=` nor `showparts?id=…&diagId=…`; a supersession entry that is not
  `<a>number - description</a>` + `(from — to)[, remark]`, links elsewhere than `part`/`partxref`,
  or has an unparseable date; a page requested with `series` that shows a series list, or one
  requested without `series` that shows vehicle rows (`fetch_part_xref`). Dates go through
  `checked_mdy` (in `parsers/supersession.py`), which also
  turns impossible months/days (a `ValueError` from `parse_mdy`) into `LayoutChanged`.
- A page that raises `LayoutChanged` is expired in the cache (`cache.shorten(url, timedelta(0))`)
  before the error is re-raised, so the next call refetches it.
- `parse_supersession` gets the part's `div.content` container, not the whole page (site notes
  §1.5: scope parsing to data containers).
- Fixtures live only in `tests/fixtures/partxref/`; `parse_supersession` is tested on those pages
  plus an inline partsearch-style snippet, so no `fixtures/supersession/` folder is needed. Most
  captures were served as UI v1; partxref data markup is identical in v1 and v2 (site notes §1.3).

## Chunk 1: Branch, fixtures, part numbers, models

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

```bash
git checkout main && git pull && git checkout -b feat/part-lookup
```

Expected: `Switched to a new branch 'feat/part-lookup'`.

- [ ] **Step 2: Confirm the foundation baseline is green**

Run: `uv run --directory server pytest -q`
Expected: PASS (`196 passed, 1 deselected`, the foundation plan's final count). If the count
differs, stop and check that `feat/foundation` is fully merged.

### Task 1: partxref fixtures

Sixteen trimmed real pages cover every case this feature handles. `test_fixtures.py` (foundation)
already checks that every committed fixture is trimmed; this task adds a test that each fixture is
the capture its name claims.

| Fixture (`tests/fixtures/partxref/`) | Raw capture (`.research-raw/xref/`) | Case |
|---|---|---|
| `oil_filter_11427953129.html` | `xref_11427953129_nocookie.html` | Current part, 66 series, supersedes list |
| `oil_filter_11427953129_e90.html` | `xref_11427953129_series_E90_v2.html` | `series=E90`: 114 vehicle rows |
| `oil_filter_11427953129_e30_no_vehicles.html` | `xref_11427953129_series_E30_nomatch.html` | No-vehicles template ("Discontinued" title, current part) |
| `superseded_11427541827.html` | `xref_11427541827_superseded_v2.html` | Ended part, 3 successors, `h1` with description |
| `intermediate_11427566327.html` | `xref_11427566327_intermediate_v1.html` | Ended part with both blocks and a photo link in `h1` |
| `spark_plug_12120037244.html` | `xref_sparkplug_12120037244_v1.html` | Supplier `h3`, nonsense weight |
| `mini_oil_filter_11427622446.html` | `xref_mini_11427622446_v1.html` | MINI series labels |
| `motorrad_oil_filter_11427673541.html` | `xref_moto_11427673541_v1.html` | Motorcycle (and BMW i) series |
| `motorrad_oil_filter_11427673541_k25.html` | `xref_11427673541_series_K25.html` | `series=K25` motorcycle rows |
| `rr_oil_filter_11427583220.html` | `xref_rr_candidate_11427583220.html` | Rolls-Royce series |
| `rr_oil_filter_11427583220_rr4.html` | `xref_11427583220_series_RR4.html` | `series=RR4` rows with transmission field |
| `short_7953129.html` | `xref_short7_7953129.html` | 7-digit query → 11427953129 |
| `false_match_99999999999.html` | `xref_invalid_99999999999.html` | Last-7 false match → 00009999999 |
| `junk_abc.html` | `xref_garbage_abc.html` | Junk part 00000000000 |
| `empty_q.html` | `xref_empty_q.html` | Error div with literal `{0}` |
| `not_found_11426666661.html` | `xref_nonexistent_11426666661.html` | Error div "was not found" |

**Files:**
- Create: `server/tests/fixtures/partxref/*.html` (16 files, generated)
- Test: `server/tests/unit/parsers/test_partxref_fixtures.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_partxref_fixtures.py`:

```python
"""Each partxref fixture is the trimmed page RealOEM served for the part in its name."""

import pytest

from tests.harness import FIXTURES, load_fixture

# fixture slug -> text that only the right capture contains
MARKERS = {
    "oil_filter_11427953129": "Part 11427953129 was found on the following vehicles:",
    "oil_filter_11427953129_e90": "Part 11427953129 was found on the following E90 vehicles:",
    "oil_filter_11427953129_e30_no_vehicles": "11427953129 - Set oil-filter element</h1>",
    "superseded_11427541827": "11427541827 - Set oil-filter element</h1>",
    "intermediate_11427566327": "Part 11427566327 was found on the following vehicles:",
    "spark_plug_12120037244": "Part 12120037244 was found on the following vehicles:",
    "mini_oil_filter_11427622446": "Part 11427622446 was found on the following vehicles:",
    "motorrad_oil_filter_11427673541": "Part 11427673541 was found on the following vehicles:",
    "motorrad_oil_filter_11427673541_k25": (
        "Part 11427673541 was found on the following K25 vehicles:"
    ),
    "rr_oil_filter_11427583220": "Part 11427583220 was found on the following vehicles:",
    "rr_oil_filter_11427583220_rr4": "Part 11427583220 was found on the following RR4 vehicles:",
    "short_7953129": "partxref?q=7953129&amp;series=E81",
    "false_match_99999999999": "Part 00009999999 was found on the following vehicles:",
    "junk_abc": "Part 00000000000 was found on the following vehicles:",
    "empty_q": "The specified part {0} was not found.",
    "not_found_11426666661": "The specified part 11426666661 was not found.",
}


def test_partxref_fixture_set_is_complete() -> None:
    present = {path.stem for path in (FIXTURES / "partxref").glob("*.html")}
    assert present == set(MARKERS)


@pytest.mark.parametrize(("slug", "marker"), MARKERS.items(), ids=list(MARKERS))
def test_partxref_fixture_is_the_right_capture(slug: str, marker: str) -> None:
    assert marker in load_fixture(f"partxref/{slug}.html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_partxref_fixtures.py -q`
Expected: FAIL (`17 failed`)

- [ ] **Step 3: Generate the fixtures**

`.research-raw/` is git-ignored and exists only in the main checkout. `RAW` resolves it from either
the main checkout or a git worktree:

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
T="uv run --directory server python scripts/trim_fixture.py"
F=tests/fixtures/partxref
$T "$RAW/xref/xref_11427953129_nocookie.html" $F/oil_filter_11427953129.html
$T "$RAW/xref/xref_11427953129_series_E90_v2.html" $F/oil_filter_11427953129_e90.html
$T "$RAW/xref/xref_11427953129_series_E30_nomatch.html" $F/oil_filter_11427953129_e30_no_vehicles.html
$T "$RAW/xref/xref_11427541827_superseded_v2.html" $F/superseded_11427541827.html
$T "$RAW/xref/xref_11427566327_intermediate_v1.html" $F/intermediate_11427566327.html
$T "$RAW/xref/xref_sparkplug_12120037244_v1.html" $F/spark_plug_12120037244.html
$T "$RAW/xref/xref_mini_11427622446_v1.html" $F/mini_oil_filter_11427622446.html
$T "$RAW/xref/xref_moto_11427673541_v1.html" $F/motorrad_oil_filter_11427673541.html
$T "$RAW/xref/xref_11427673541_series_K25.html" $F/motorrad_oil_filter_11427673541_k25.html
$T "$RAW/xref/xref_rr_candidate_11427583220.html" $F/rr_oil_filter_11427583220.html
$T "$RAW/xref/xref_11427583220_series_RR4.html" $F/rr_oil_filter_11427583220_rr4.html
$T "$RAW/xref/xref_short7_7953129.html" $F/short_7953129.html
$T "$RAW/xref/xref_invalid_99999999999.html" $F/false_match_99999999999.html
$T "$RAW/xref/xref_garbage_abc.html" $F/junk_abc.html
$T "$RAW/xref/xref_empty_q.html" $F/empty_q.html
$T "$RAW/xref/xref_nonexistent_11426666661.html" $F/not_found_11426666661.html
```

Expected (stderr, one line per file; Windows prints `\` in the path; sizes may differ by a few
bytes with line endings):

```
tests/fixtures/partxref/oil_filter_11427953129.html: 34630 -> 13856 bytes
tests/fixtures/partxref/oil_filter_11427953129_e90.html: 51539 -> 30368 bytes
tests/fixtures/partxref/oil_filter_11427953129_e30_no_vehicles.html: 28392 -> 7428 bytes
tests/fixtures/partxref/superseded_11427541827.html: 28995 -> 8227 bytes
tests/fixtures/partxref/intermediate_11427566327.html: 27254 -> 6535 bytes
tests/fixtures/partxref/spark_plug_12120037244.html: 28517 -> 7826 bytes
tests/fixtures/partxref/mini_oil_filter_11427622446.html: 27617 -> 6935 bytes
tests/fixtures/partxref/motorrad_oil_filter_11427673541.html: 29401 -> 8726 bytes
tests/fixtures/partxref/motorrad_oil_filter_11427673541_k25.html: 29293 -> 8401 bytes
tests/fixtures/partxref/rr_oil_filter_11427583220.html: 31576 -> 10882 bytes
tests/fixtures/partxref/rr_oil_filter_11427583220_rr4.html: 29140 -> 8247 bytes
tests/fixtures/partxref/short_7953129.html: 34274 -> 13580 bytes
tests/fixtures/partxref/false_match_99999999999.html: 26997 -> 6342 bytes
tests/fixtures/partxref/junk_abc.html: 55925 -> 35171 bytes
tests/fixtures/partxref/empty_q.html: 25364 -> 5292 bytes
tests/fixtures/partxref/not_found_11426666661.html: 25625 -> 5333 bytes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/parsers/test_partxref_fixtures.py tests/unit/test_fixtures.py -q`
Expected: PASS (`54 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/partxref server/tests/unit/parsers/test_partxref_fixtures.py
git commit -m "test(parts): add trimmed partxref fixtures" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Part number normalization and verification (`parsers/part_numbers.py`)

ARD §5.11 and site notes §3.2: accept only 7 or 11 digits after removing spaces, dashes and dots;
RealOEM matches on the last 7 digits, so the returned number must be verified (exact for 11
digits, last 7 for 7 digits) and the junk part `00000000000` never matches.

**Files:**
- Create: `server/src/realoem_mcp/parsers/part_numbers.py`
- Test: `server/tests/unit/parsers/test_part_numbers.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_part_numbers.py`:

```python
import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.parsers.part_numbers import JUNK_PART, matches, normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("11427953129", "11427953129"),
        ("11 42 7 953 129", "11427953129"),
        ("11-42-7-953-129", "11427953129"),
        ("11.42.7.953.129", "11427953129"),
        ("  11427953129\n", "11427953129"),
        ("7953129", "7953129"),
        ("795 3129", "7953129"),
        ("00000000000", "00000000000"),
    ],
)
def test_normalize_accepts_7_or_11_digits_with_separators(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "abc", "1142795312", "114279531290", "123456", "11427953129a", "11_42_7_953_129"],
)
def test_normalize_rejects_everything_else(raw: str) -> None:
    with pytest.raises(InvalidInput) as info:
        normalize(raw)
    assert "11 digits" in info.value.message
    assert repr(raw) in info.value.message


@pytest.mark.parametrize(
    ("query", "returned", "expected"),
    [
        ("11427953129", "11427953129", True),
        ("7953129", "11427953129", True),
        ("99999999999", "00009999999", False),  # RealOEM's last-7 false match
        ("9999999", "00009999999", True),
        ("11427953129", "11427953128", False),
        ("7953129", "11427953128", False),
        ("00000000000", JUNK_PART, False),  # junk part never matches
        ("0000000", JUNK_PART, False),
    ],
)
def test_matches(query: str, returned: str, expected: bool) -> None:
    assert matches(query, returned) is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_part_numbers.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'realoem_mcp.parsers.part_numbers'`, `1 error`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/part_numbers.py`:

```python
"""BMW part numbers: input normalization and returned-number verification (site notes 3.2)."""

from __future__ import annotations

import re

from realoem_mcp.errors import InvalidInput

JUNK_PART = "00000000000"  # RealOEM's answer to junk input; never a real match
_SEPARATORS = re.compile(r"[\s.\-]+")
_DIGITS = re.compile(r"[0-9]{7}|[0-9]{11}")


def normalize(raw: str) -> str:
    """Digits of a part number: 11 digits or the 7-digit short form.

    Spaces, dashes and dots are removed first; anything else raises InvalidInput, so malformed
    input never reaches RealOEM.
    """
    digits = _SEPARATORS.sub("", raw)
    if not _DIGITS.fullmatch(digits):
        raise InvalidInput(
            f"{raw!r} is not a BMW part number. Enter 11 digits (e.g. 11427953129) or the last "
            "7 digits (7953129); spaces, dashes and dots are allowed."
        )
    return digits


def matches(query: str, returned: str) -> bool:
    """True when the part RealOEM returned is the part that was asked for.

    RealOEM matches on the last 7 digits, so an 11-digit query must match exactly and a 7-digit
    query must be the last 7 digits of an 11-digit number. The junk part never matches.
    """
    if returned == JUNK_PART or len(returned) != 11:
        return False
    if len(query) == 11:
        return returned == query
    return len(query) == 7 and returned.endswith(query)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_part_numbers.py -q`
Expected: PASS (`24 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers/part_numbers.py server/tests/unit/parsers/test_part_numbers.py
git commit -m "feat(parts): add part number normalize and matches" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Part lookup models (`models/parts.py`)

The models are exactly ARD §5.11. `PartLookupResult` extends the foundation `ResultMeta`, so
`PartLookupResult.from_pages([page], query=..., status=..., part=...)` fills `source_urls`,
`fetched_at`, `from_cache` and `requests_made`.

**Files:**
- Create: `server/src/realoem_mcp/models/parts.py`
- Test: `server/tests/unit/test_models_parts.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_parts.py`:

```python
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from realoem_mcp.http_client import Page
from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.models.parts import (
    ModelUse,
    PartLookupResult,
    PartXref,
    SeriesUse,
    SupersessionEntry,
)
from realoem_mcp.page_types import PageType

URL = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"


def _page() -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=URL,
        final_url=URL,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        from_cache=False,
    )


def _xref() -> PartXref:
    vehicle = VehicleRef(
        vehicle_id="VB53-USA-03_2005_E90_BMW_323i",
        type_code="VB53",
        market="USA",
        production_month="2005-03",
        series="E90",
        brand="bmw",
        model="323i",
    )
    diagram = DiagramRef(
        vehicle_id=vehicle.vehicle_id,
        diag_id="11_3867",
        name="Lubrication system-Oil filter",
        url="https://www.realoem.com/bmw/enUS/showparts?id=VB53-USA-03_2005_E90_BMW_323i&diagId=11_3867",
    )
    return PartXref(
        part_number="11427953129",
        description="Set oil-filter element",
        supplier_ref=None,
        weight_kg=None,
        valid_from=date(2017, 6, 1),
        valid_to=None,
        ended=False,
        superseded_by=[],
        supersedes=[
            SupersessionEntry(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
                in_catalog=False,
            )
        ],
        series=[
            SeriesUse(
                code="E90",
                name="3 Series E90",
                brand="bmw",
                production_from="2004-02",
                production_to="2008-09",
            )
        ],
        models=[ModelUse(vehicle=vehicle, body="Sedan", engine="N52", diagram=diagram)],
    )


def test_part_lookup_result_is_a_result_meta() -> None:
    result = PartLookupResult.from_pages(
        [_page()], query="11427953129", status="current", part=_xref()
    )
    assert isinstance(result, ResultMeta)
    data = result.model_dump(mode="json")
    assert data["source_urls"] == [URL]
    assert data["requests_made"] == 1
    assert data["status"] == "current"
    assert data["part"]["valid_from"] == "2017-06-01"
    assert data["part"]["supersedes"][0]["valid_to"] == "2006-03-17"
    assert data["part"]["series"][0]["brand"] == "bmw"
    assert data["part"]["models"][0]["diagram"]["diag_id"] == "11_3867"


def test_not_found_result_has_no_part() -> None:
    result = PartLookupResult.from_pages(
        [_page()], query="11426666661", status="not_found", part=None
    )
    assert result.part is None


def test_status_values_are_fixed() -> None:
    with pytest.raises(ValidationError):
        PartLookupResult.from_pages(
            [_page()], query="11427541827", status="discontinued", part=None
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_parts.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'realoem_mcp.models.parts'`, `1 error`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/models/parts.py`:

```python
"""Part lookup models (ARD section 5.11, feature A). PartXref is the partxref parser output."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef


class SupersessionEntry(BaseModel):
    part_number: str
    description: str | None
    valid_from: date | None
    valid_to: date | None  # None = open-ended
    remark: str | None  # e.g. "Exchangeable retrospectively"
    in_catalog: bool  # link was part?... (True) or partxref?q= (False)


class SeriesUse(BaseModel):
    code: str  # series= code from the link, e.g. "E90N"
    name: str  # label without the "BMW " prefix and dates, e.g. "3 Series E90 LCI"
    brand: str  # brand registry id
    production_from: str | None  # "YYYY-MM"
    production_to: str | None  # "YYYY-MM"


class ModelUse(BaseModel):
    vehicle: VehicleRef  # id from the link; its date is the series start, not a build month
    body: str | None
    engine: str | None
    diagram: DiagramRef


class PartXref(BaseModel):
    part_number: str
    description: str | None
    supplier_ref: str | None
    weight_kg: float | None
    valid_from: date | None
    valid_to: date | None
    ended: bool  # RealOEM marks the "To" date "(ENDED)"
    superseded_by: list[SupersessionEntry]
    supersedes: list[SupersessionEntry]
    series: list[SeriesUse]  # plain lookup
    models: list[ModelUse]  # lookup narrowed to one series


class PartLookupResult(ResultMeta):
    query: str  # normalized input
    status: Literal["current", "ended", "not_found"]
    part: PartXref | None  # None when not_found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_parts.py -q`
Expected: PASS (`3 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models/parts.py server/tests/unit/test_models_parts.py
git commit -m "feat(parts): add part lookup models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 2: Parsers

### Task 4: Supersession blocks (`parsers/supersession.py`)

Site notes §3.5. `div.superseded` ("Superseded by:") and `div.supersedes` ("Supersedes:") each hold
a `dl` of `dt > a` ("`<number> - <description>`") and `dd` ("`(<from> — <to or empty>)[, <remark>]`",
em dash). A `part?…` link means the part is still in some catalog (`in_catalog=True`); a
`partxref?q=` link means it is not. Absent blocks give empty lists. The same markup appears on
`part` and `partsearch` pages (feature D reuses this parser), where the `dd` may contain newlines
before the comma; `text()` collapses them. Never select on the template-bug class
`sup-by-{$t.count}`. The page type in `LayoutChanged` is taken from the URL path. Dates must
parse (an empty end date means open-ended), and links must point to `part` or `partxref`;
anything else raises `LayoutChanged` instead of returning `None` dates. `checked_mdy` is public
because `parsers/partxref.py` (and later partsearch in feature D) uses it for header dates.

**Files:**
- Create: `server/src/realoem_mcp/parsers/supersession.py`
- Test: `server/tests/unit/parsers/test_supersession.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_supersession.py`:

```python
from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.parsers.common import tree
from realoem_mcp.parsers.supersession import parse_supersession
from tests.harness import load_fixture, url

OIL_FILTER = "Set oil-filter element"


def _parse(slug: str, q: str) -> tuple[list[SupersessionEntry], list[SupersessionEntry]]:
    html = load_fixture(f"partxref/{slug}.html")
    return parse_supersession(tree(html), url=url("partxref", q=q))


def test_superseded_part_lists_every_successor() -> None:
    superseded_by, supersedes = _parse("superseded_11427541827", "11427541827")
    assert supersedes == []
    assert superseded_by == [
        SupersessionEntry(
            part_number="11427566327",
            description=OIL_FILTER,
            valid_from=date(2006, 2, 13),
            valid_to=date(2017, 1, 30),
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
        SupersessionEntry(
            part_number="11428683196",
            description=OIL_FILTER,
            valid_from=date(2016, 9, 1),
            valid_to=date(2017, 9, 21),
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
        SupersessionEntry(
            part_number="11427953129",
            description=OIL_FILTER,
            valid_from=date(2017, 6, 1),
            valid_to=None,
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
    ]


def test_current_part_lists_every_predecessor() -> None:
    superseded_by, supersedes = _parse("oil_filter_11427953129", "11427953129")
    assert superseded_by == []
    assert [e.part_number for e in supersedes] == ["11428683196", "11427566327", "11427541827"]
    oldest = supersedes[-1]
    assert (oldest.valid_from, oldest.valid_to) == (date(2004, 9, 1), date(2006, 3, 17))
    assert oldest.remark is None
    assert oldest.in_catalog is False  # partxref?q= link: no longer in any catalog


def test_intermediate_part_has_both_blocks() -> None:
    superseded_by, supersedes = _parse("intermediate_11427566327", "11427566327")
    assert [e.part_number for e in superseded_by] == ["11428683196", "11427953129"]
    assert [e.part_number for e in supersedes] == ["11427541827"]


def test_spark_plug_predecessor() -> None:
    superseded_by, supersedes = _parse("spark_plug_12120037244", "12120037244")
    assert superseded_by == []
    assert supersedes == [
        SupersessionEntry(
            part_number="12120034087",
            description="Spark plug, High Power",
            valid_from=date(2006, 6, 1),
            valid_to=date(2008, 11, 1),
            remark=None,
            in_catalog=False,
        )
    ]


def test_absent_blocks_give_empty_lists() -> None:
    assert _parse("motorrad_oil_filter_11427673541", "11427673541") == ([], [])
    assert _parse("not_found_11426666661", "11426666661") == ([], [])


def test_partsearch_style_whitespace_before_the_remark() -> None:
    html = (
        '<div class="superseded"><h3>Superseded by:</h3><dl>'
        '<dt><a href="part?id=VB13-USA-10-2005-E90-BMW-325i&amp;q=11427953129">'
        "11427953129 - Set oil-filter element</a></dt>"
        "<dd>(06/01/2017 &mdash; )\n\n        , Exchangeable retrospectively</dd>"
        "</dl></div>"
    )
    superseded_by, _ = parse_supersession(tree(html), url=url("partsearch", q="11427566327"))
    assert superseded_by[0].valid_to is None
    assert superseded_by[0].remark == "Exchangeable retrospectively"


@pytest.mark.parametrize(
    "block",
    [
        '<div class="superseded"><h3>Superseded by:</h3></div>',
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>09/01/2004</dd></dl></div>",
        '<div class="supersedes"><dl><dt>11427541827 - X</dt><dd>(09/01/2004 — )</dd></dl></div>',
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "</dl></div>",
        '<div class="supersedes"><dl><dt><a href="showparts?id=1">11427541827 - X</a></dt>'
        "<dd>(09/01/2004 — )</dd></dl></div>",
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>(2004-09-01 — )</dd></dl></div>",
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>(13/01/2004 — )</dd></dl></div>",
    ],
    ids=[
        "no dl",
        "no parentheses",
        "no link",
        "unpaired dt",
        "link target",
        "date format",
        "impossible month",
    ],
)
def test_broken_block_raises_layout_changed(block: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        parse_supersession(tree(block), url=url("partsearch", q="11427541827"))
    assert info.value.page_type == "partsearch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_supersession.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'realoem_mcp.parsers.supersession'`, `1 error`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/supersession.py`:

```python
"""Superseded-by / supersedes blocks shared by partxref, part and partsearch (site notes 3.5)."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.parsers.common import Node, Tree, parse_mdy, require, text

_LINK = re.compile(r"(?P<number>\d+)\s*-\s*(?P<description>.*)")
# "(02/13/2006 - 01/30/2017), Exchangeable retrospectively" or "(06/01/2017 - )", em dashes
_RANGE = re.compile(
    r"\((?P<start>[^\N{EM DASH})]*)\N{EM DASH}(?P<end>[^)]*)\)\s*(?:,\s*(?P<remark>.+))?"
)


def parse_supersession(
    root: Tree | Node, *, url: str
) -> tuple[list[SupersessionEntry], list[SupersessionEntry]]:
    """(superseded_by, supersedes); each list is empty when its block is absent."""
    return _block(root, "div.superseded", url), _block(root, "div.supersedes", url)


def checked_mdy(
    value: str, page_type: str, url: str, *, open_end: str | None = None
) -> date | None:
    """MM/DD/YYYY as a date; None only for the open-end marker; anything else is LayoutChanged.

    Guards against a date-format change silently turning every date into None (NFR3).
    """
    if open_end is not None and value.strip() == open_end:
        return None
    try:
        parsed = parse_mdy(value)
    except ValueError:  # impossible month or day
        parsed = None
    if parsed is None:
        raise LayoutChanged(page_type, f"unexpected date {value!r}", url)
    return parsed


def _page_type(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def _block(root: Tree | Node, selector: str, url: str) -> list[SupersessionEntry]:
    block = root.css_first(selector)
    if block is None:
        return []
    dl = require(block, "dl", _page_type(url), url)
    terms, details = dl.css("dt"), dl.css("dd")
    if len(terms) != len(details):
        raise LayoutChanged(_page_type(url), f"{selector} has unpaired dt/dd", url)
    return [_entry(dt, dd, url) for dt, dd in zip(terms, details, strict=True)]


def _entry(dt: Node, dd: Node, url: str) -> SupersessionEntry:
    link = dt.css_first("a")
    number = _LINK.fullmatch(text(link))
    dates = _RANGE.fullmatch(text(dd))
    if link is None or number is None or dates is None:
        detail = f"unexpected supersession entry {text(dt)!r} {text(dd)!r}"
        raise LayoutChanged(_page_type(url), detail, url)
    target = _page_type(link.attributes.get("href") or "")
    if target not in ("part", "partxref"):
        raise LayoutChanged(_page_type(url), f"unexpected supersession link to {target!r}", url)
    page_type = _page_type(url)
    return SupersessionEntry(
        part_number=number["number"],
        description=number["description"].strip() or None,
        valid_from=checked_mdy(dates["start"], page_type, url),
        valid_to=checked_mdy(dates["end"], page_type, url, open_end=""),
        remark=dates["remark"],
        in_catalog=target == "part",  # part?... = still in a catalog; partxref?q= = not
    )
```

`\N{EM DASH}` is the regex escape for "—" (ruff flags some literal dash characters as ambiguous).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_supersession.py -q`
Expected: PASS (`13 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers/supersession.py server/tests/unit/parsers/test_supersession.py
git commit -m "feat(parts): parse supersession blocks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: partxref header, description and series list (`parsers/partxref.py`)

Site notes §3.3, §3.4, §3.6. Anchor on `div.content > h1` (in the v2 layout an outer
`div.content` wraps the inner one; the child combinator finds the right one). Read the header `dl`
and the supplier `h3` among that container's **direct children** (the supersession blocks have
their own `h3`/`dl`); the ECS button sits inside `div.ecs-tuning-cta`, so it is found with a
descendant selector. Supersession blocks are parsed from the same container. Series rows are `div.partSearchResults li > a` with a
`partxref?…&series=<code>` href. Vehicle rows (`showparts` links) come in Task 6; until then a
page with vehicle rows raises `LayoutChanged` ("unexpected vehicle link").

**Files:**
- Create: `server/src/realoem_mcp/parsers/partxref.py`
- Test: `server/tests/unit/parsers/test_partxref.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_partxref.py`:

```python
from collections.abc import Callable
from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import PartXref, SeriesUse
from realoem_mcp.parsers.partxref import parse_partxref
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

Parse = Callable[..., PartXref | None]


@pytest.fixture
async def parse(make_services: MakeServices) -> Parse:
    """parse(slug, q=..., series=None, html=None): parse a partxref fixture (or html)."""
    services, _ = make_services({})

    def _parse(
        slug: str, *, q: str, series: str | None = None, html: str | None = None
    ) -> PartXref | None:
        params = {"q": q} if series is None else {"q": q, "series": series}
        page_html = html if html is not None else load_fixture(f"partxref/{slug}.html")
        return parse_partxref(
            page_html,
            url=url("partxref", **params),
            brands=services.brands,
            client=services.client,
        )

    return _parse


def _part(parse: Parse, slug: str, q: str, **kwargs: str) -> PartXref:
    xref = parse(slug, q=q, **kwargs)
    assert xref is not None
    return xref


async def test_current_part_with_series_list(parse: Parse) -> None:
    xref = _part(parse, "oil_filter_11427953129", "11427953129")
    assert xref.part_number == "11427953129"
    assert xref.description == "Set oil-filter element"  # from the ECS button
    assert (xref.supplier_ref, xref.weight_kg) == (None, None)
    assert (xref.valid_from, xref.valid_to, xref.ended) == (date(2017, 6, 1), None, False)
    assert xref.superseded_by == []
    assert [e.part_number for e in xref.supersedes] == [
        "11428683196",
        "11427566327",
        "11427541827",
    ]
    assert len(xref.series) == 66
    assert xref.series[0] == SeriesUse(
        code="E81",
        name="1 Series E81",
        brand="bmw",
        production_from="2006-02",
        production_to="2011-12",
    )
    e90n = next(s for s in xref.series if s.code == "E90N")
    assert (e90n.name, e90n.production_from, e90n.production_to) == (
        "3 Series E90 LCI",
        "2007-07",
        "2011-12",
    )
    assert xref.series[-1] == SeriesUse(
        code="MOSP",
        name="MS BMW Motorsport",
        brand="bmw",
        production_from=None,
        production_to=None,
    )
    assert {s.brand for s in xref.series} == {"bmw"}
    assert xref.models == []


async def test_superseded_part_on_no_vehicles_template(parse: Parse) -> None:
    xref = _part(parse, "superseded_11427541827", "11427541827")
    assert xref.description == "Set oil-filter element"  # from "<h1>number - description"
    assert (xref.valid_from, xref.valid_to) == (date(2004, 9, 1), date(2006, 3, 17))
    assert xref.ended is True
    assert xref.weight_kg == 0.047
    assert [e.part_number for e in xref.superseded_by] == [
        "11427566327",
        "11428683196",
        "11427953129",
    ]
    assert (xref.supersedes, xref.series, xref.models) == ([], [], [])


async def test_intermediate_part_with_photo_and_both_blocks(parse: Parse) -> None:
    xref = _part(parse, "intermediate_11427566327", "11427566327")
    assert xref.part_number == "11427566327"  # the photo link inside <h1> is ignored
    assert (xref.valid_to, xref.ended) == (date(2017, 1, 30), True)
    assert [e.part_number for e in xref.superseded_by] == ["11428683196", "11427953129"]
    assert [e.part_number for e in xref.supersedes] == ["11427541827"]
    assert [(s.code, s.brand) for s in xref.series] == [("MOSP", "bmw")]


async def test_spark_plug_supplier_and_weight_pass_through(parse: Parse) -> None:
    xref = _part(parse, "spark_plug_12120037244", "12120037244")
    assert xref.description == "Spark plug, High Power"
    assert xref.supplier_ref == "BOSCH ZGR6STE2"
    assert xref.weight_kg == 44.65  # nonsense on RealOEM, passed through as-is
    assert len(xref.series) == 17


async def test_mini_series_are_tagged_mini(parse: Parse) -> None:
    xref = _part(parse, "mini_oil_filter_11427622446", "11427622446")
    assert [(s.code, s.name) for s in xref.series[:3]] == [
        ("R56", "MINI R56"),
        ("R56N", "MINI R56 LCI"),
        ("R55", "MINI Clubman R55"),
    ]
    assert {s.brand for s in xref.series} == {"mini"}


async def test_motorcycle_series_are_tagged_motorrad(parse: Parse) -> None:
    xref = _part(parse, "motorrad_oil_filter_11427673541", "11427673541")
    by_code = {s.code: s for s in xref.series}
    assert by_code["K25"] == SeriesUse(
        code="K25",
        name="K25 (R 1200 GS)",
        brand="motorrad",
        production_from="2002-12",
        production_to="2012-12",
    )
    assert by_code["K255"].name == "K25 (R 1200 GS Adventure)"
    k_codes = [code for code in by_code if code.startswith("K")]
    assert len(k_codes) == 22  # K08 ... K61 plus KR1 and KR3 (R nineT)
    assert {by_code[code].brand for code in k_codes} == {"motorrad"}
    assert (by_code["I01"].name, by_code["I01"].brand) == ("i3 I01", "bmw")
    assert (by_code["A73"].production_from, by_code["A73"].brand) == (None, "bmw")


async def test_rolls_royce_series_are_tagged_rolls_royce(parse: Parse) -> None:
    xref = _part(parse, "rr_oil_filter_11427583220", "11427583220")
    by_code = {s.code: s for s in xref.series}
    assert (by_code["RR4"].name, by_code["RR4"].brand) == ("Ghost RR4", "rolls-royce")
    assert {by_code[c].brand for c in ("RR11", "RR12", "RR21", "RR5", "RR6", "RR31")} == {
        "rolls-royce"
    }
    assert (by_code["F07"].brand, by_code["MOSP"].brand) == ("bmw", "bmw")


@pytest.mark.parametrize(
    ("slug", "q"),
    [("not_found_11426666661", "11426666661"), ("empty_q", "")],
)
async def test_not_found_page_parses_to_none(parse: Parse, slug: str, q: str) -> None:
    assert parse(slug, q=q) is None


@pytest.mark.parametrize(
    ("slug", "q", "returned"),
    [
        ("short_7953129", "7953129", "11427953129"),
        ("false_match_99999999999", "99999999999", "00009999999"),
        ("junk_abc", "00000000000", "00000000000"),
    ],
)
async def test_parser_reports_the_number_realoem_returned(
    parse: Parse, slug: str, q: str, returned: str
) -> None:
    # Deciding whether it is the part that was asked for is matches()'s job (tools/parts.py).
    assert _part(parse, slug, q).part_number == returned


async def test_title_never_decides_the_status(parse: Parse) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e30_no_vehicles.html")
    assert "Discontinued BMW Part" in html
    xref = _part(parse, "oil_filter_11427953129_e30_no_vehicles", "11427953129", series="E30")
    assert (xref.ended, xref.valid_to, xref.series, xref.models) == (False, None, [], [])


async def test_heading_description_wins_over_the_ecs_attribute(parse: Parse) -> None:
    html = load_fixture("partxref/superseded_11427541827.html")
    html = html.replace(
        'data-ecs-part-name="Set oil-filter element"', 'data-ecs-part-name="ECS name"'
    )
    assert _part(parse, "", "11427541827", html=html).description == "Set oil-filter element"


async def test_description_falls_back_to_a_supersession_link_naming_the_part(
    parse: Parse,
) -> None:
    html = load_fixture("partxref/oil_filter_11427953129.html")
    html = html.replace(' data-ecs-part-name="Set oil-filter element"', "")
    assert _part(parse, "", "11427953129", html=html).description is None
    html = html.replace("11427541827 - Set oil-filter element", "11427953129 - Oil filter kit")
    assert _part(parse, "", "11427953129", html=html).description == "Oil filter kit"


BROKEN = [
    ("<html><body><p>maintenance</p></body></html>", "div.content > h1"),
    ('<div class="content"><div class="error">Server busy</div></div>', "unexpected error"),
    ('<div class="content"><h1>Oil filter</h1></div>', "unexpected part heading"),
    ('<div class="content"><h1>11427953129</h1></div>', "missing part header"),
    (
        '<div class="content"><h1>11427953129</h1><dl><dt>Weight:</dt><dd>1 kg</dd></dl></div>',
        "unexpected part header",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd></dl></div>",
        "div.partSearchResults",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>soon</dd></dl>"
        '<div class="partSearchResults"></div></div>',
        "unexpected date",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd></dl>"
        '<div class="partSearchResults">Part 11427953129 was found on the following vehicles:'
        "<div>BMW 1 Series E81</div></div></div>",
        "no series or vehicle rows",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd>"
        "<dt>Weight:</dt><dd>heavy</dd></dl>"
        '<div class="partSearchResults"></div></div>',
        "unexpected weight",
    ),
]


@pytest.mark.parametrize(("html", "detail"), BROKEN, ids=[d for _, d in BROKEN])
async def test_broken_page_raises_layout_changed(parse: Parse, html: str, detail: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        parse("", q="11427953129", html=html)
    assert info.value.page_type == "partxref"
    assert detail in info.value.detail


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        (
            "BMW 1 Series E81 (02/2006\N{EN DASH}12/2011)",
            "BMW 1 Series E81",
            "unexpected series label",
        ),
        (
            "BMW 1 Series E81 (02/2006\N{EN DASH}12/2011)",
            "BMW 1 Series E81 (13/2006\N{EN DASH}12/2011)",
            "unexpected production date",
        ),
        ("partxref?q=11427953129&amp;series=E81", "partxref?q=11427953129", "vehicle link"),
    ],
)
async def test_broken_series_row_raises_layout_changed(
    parse: Parse, old: str, new: str, detail: str
) -> None:
    html = load_fixture("partxref/oil_filter_11427953129.html")
    assert old in html
    with pytest.raises(LayoutChanged) as info:
        parse("", q="11427953129", html=html.replace(old, new))
    assert detail in info.value.detail
```

The `parse` fixture uses `make_services({})` only to get a real `BrandRegistry` and
`RealOemClient`; no request is made.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_partxref.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'realoem_mcp.parsers.partxref'`, `1 error`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/partxref.py`:

```python
"""partxref: part header, supersession and the series or vehicles using a part (site notes 3)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.parts import ModelUse, PartXref, SeriesUse, SupersessionEntry
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_my, require, text, tree
from realoem_mcp.parsers.supersession import checked_mdy, parse_supersession

PAGE = PageType.PARTXREF
_HEADING = re.compile(r"(?P<number>\d+)(?:\s*-\s*(?P<description>.+))?")
_WEIGHT = re.compile(r"(?P<kg>\d+(?:\.\d+)?)\s*kg")
# "BMW 3 Series E90 LCI (07/2007-12/2011)" or "BMW MS BMW Motorsport (-)", with an en dash
_SERIES_LABEL = re.compile(r"(?P<label>.+?)\s*\((?P<start>[\d/]*)\N{EN DASH}(?P<end>[\d/]*)\)")


def parse_partxref(
    html: str, *, url: str, brands: BrandRegistry, client: RealOemClient
) -> PartXref | None:
    """The partxref page as a PartXref, or None when RealOEM says the part was not found.

    brands tags each series and vehicle with its brand; client builds diagram URLs. No I/O.
    """
    root = tree(html)
    error = root.css_first("div.content > div.error")
    if error is not None:
        if "was not found" not in text(error):
            raise LayoutChanged(PAGE, f"unexpected error message {text(error)!r}", url)
        return None
    heading = require(root, "div.content > h1", PAGE, url)
    content = heading.parent
    match = _HEADING.fullmatch(text(heading))
    if content is None or match is None:
        raise LayoutChanged(PAGE, f"unexpected part heading {text(heading)!r}", url)
    number = match["number"]
    header = _header(content, url)
    superseded_by, supersedes = parse_supersession(content, url=url)
    results = require(content, "div.partSearchResults", PAGE, url)
    series, models = _uses(results, url=url, brands=brands, client=client)
    return PartXref(
        part_number=number,
        description=match["description"]
        or _ecs_name(content)
        or _named_in(number, superseded_by + supersedes),
        supplier_ref=_supplier(content),
        weight_kg=_weight(header.get("Weight"), url),
        valid_from=checked_mdy(header["From"], PAGE, url),
        valid_to=checked_mdy(header["To"], PAGE, url, open_end="-"),
        ended="(ENDED)" in header["To"],
        superseded_by=superseded_by,
        supersedes=supersedes,
        series=series,
        models=models,
    )


def _children(content: Node, tag: str) -> list[Node]:
    return [child for child in content.iter() if child.tag == tag]


def _header(content: Node, url: str) -> dict[str, str]:
    """The From/To/Weight <dl> right under the heading."""
    lists = _children(content, "dl")
    if not lists:
        raise LayoutChanged(PAGE, "missing part header <dl>", url)
    terms, details = lists[0].css("dt"), lists[0].css("dd")
    fields = {text(dt).rstrip(":"): text(dd) for dt, dd in zip(terms, details, strict=False)}
    if len(terms) != len(details) or "From" not in fields or "To" not in fields:
        raise LayoutChanged(PAGE, f"unexpected part header {sorted(fields)}", url)
    return fields


def _weight(value: str | None, url: str) -> float | None:
    """Weight text such as "0.047 kg" as 0.047 (passed through even when nonsense)."""
    if value is None:
        return None
    match = _WEIGHT.fullmatch(value)
    if match is None:
        raise LayoutChanged(PAGE, f"unexpected weight {value!r}", url)
    return float(match["kg"])


def _supplier(content: Node) -> str | None:
    """Optional supplier reference, e.g. <h3>BOSCH ZGR6STE2</h3> (not the supersession h3s)."""
    headings = _children(content, "h3")
    return (text(headings[0]) or None) if headings else None


def _ecs_name(content: Node) -> str | None:
    button = content.css_first("a.ecs-tuning-button[data-ecs-part-name]")
    if button is None:
        return None
    return (button.attributes.get("data-ecs-part-name") or "").strip() or None


def _named_in(number: str, entries: list[SupersessionEntry]) -> str | None:
    """Description from a supersession link that names this part."""
    return next((e.description for e in entries if e.part_number == number and e.description), None)


def _uses(
    results: Node, *, url: str, brands: BrandRegistry, client: RealOemClient
) -> tuple[list[SeriesUse], list[ModelUse]]:
    series: list[SeriesUse] = []
    models: list[ModelUse] = []
    for item in results.css("li"):
        link = require(item, "a[href]", PAGE, url)
        href = link.attributes.get("href") or ""
        target = urlsplit(href).path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(urlsplit(href).query))
        if target == "partxref" and params.get("series"):
            series.append(_series_use(link, params["series"], url, brands))
        else:
            raise LayoutChanged(PAGE, f"unexpected vehicle link {href!r}", url)
    if not series and not models and "was found on the following" in text(results):
        raise LayoutChanged(PAGE, "no series or vehicle rows under 'was found on'", url)
    return series, models


def _series_use(link: Node, code: str, url: str, brands: BrandRegistry) -> SeriesUse:
    label = text(link)
    match = _SERIES_LABEL.fullmatch(label)
    if match is None:
        raise LayoutChanged(PAGE, f"unexpected series label {label!r}", url)
    return SeriesUse(
        code=code,
        name=match["label"].removeprefix("BMW "),  # RealOEM prefixes every label with "BMW"
        brand=brands.for_series(code, label=label).id,
        production_from=_month(match["start"], url),
        production_to=_month(match["end"], url),
    )


def _month(value: str, url: str) -> str | None:
    """MM/YYYY as "YYYY-MM"; None when RealOEM shows no date; anything else is LayoutChanged."""
    if not value:
        return None
    try:
        month = parse_my(value)
    except ValueError:  # impossible month
        month = None
    if month is None:
        raise LayoutChanged(PAGE, f"unexpected production date {value!r}", url)
    return month
```

`\N{EN DASH}` matches the "–" RealOEM puts between the two dates of a series label.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_partxref.py -q`
Expected: PASS (`27 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers/partxref.py server/tests/unit/parsers/test_partxref.py
git commit -m "feat(parts): parse partxref header and series list" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: partxref vehicle rows for one series

Site notes §3.7. With `series=`, each `li` is "`<series>, <model>, <body>, <engine>[, <trans>],
<market>, (<type>) : <a href="/bmw/enUS/showparts?id=<id>&diagId=<diag>#<pn>">diagram</a>`". The
data comes from the href (`id`, `diagId`); the text before ` : ` only supplies body and engine.
Ids use the partxref `_` form (`VB13-USA-02_2004_E90_BMW_325i`), carry the series start month,
and are kept verbatim.

**Files:**
- Modify: `server/src/realoem_mcp/parsers/partxref.py`
- Test: `server/tests/unit/parsers/test_partxref_models.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_partxref_models.py`:

```python
"""partxref narrowed to one series (series=...): one row per type code x diagram."""

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.models.parts import ModelUse, PartXref
from realoem_mcp.parsers.partxref import parse_partxref
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    services, _ = make_services({})
    return services


def _parse(services: Services, slug: str, q: str, series: str, html: str | None = None) -> PartXref:
    xref = parse_partxref(
        html if html is not None else load_fixture(f"partxref/{slug}.html"),
        url=url("partxref", q=q, series=series),
        brands=services.brands,
        client=services.client,
    )
    assert xref is not None
    return xref


async def test_e90_rows_carry_vehicle_body_engine_and_diagram(services: Services) -> None:
    xref = _parse(services, "oil_filter_11427953129_e90", "11427953129", "E90")
    assert xref.series == []
    assert len(xref.models) == 114
    assert len({m.vehicle.type_code for m in xref.models}) == 55
    assert {m.vehicle.brand for m in xref.models} == {"bmw"}
    assert {m.vehicle.series for m in xref.models} == {"E90"}
    assert {m.diagram.diag_id for m in xref.models} == {"02_0092", "11_3753", "11_3867", "11_3971"}
    vb13 = [m for m in xref.models if m.vehicle.type_code == "VB13"]
    assert vb13[1] == ModelUse(
        vehicle=VehicleRef(
            vehicle_id="VB13-USA-02_2004_E90_BMW_325i",
            type_code="VB13",
            market="USA",
            production_month="2004-02",  # nominal: series start, not a build month
            series="E90",
            brand="bmw",
            model="325i",
        ),
        body="Sedan",
        engine="N52",
        diagram=DiagramRef(
            vehicle_id="VB13-USA-02_2004_E90_BMW_325i",
            diag_id="11_3867",
            name="Lubrication system-Oil filter",
            url="https://www.realoem.com/bmw/enUS/showparts?id=VB13-USA-02_2004_E90_BMW_325i&diagId=11_3867",
        ),
    )


async def test_motorcycle_rows_have_no_body_or_engine(services: Services) -> None:
    xref = _parse(services, "motorrad_oil_filter_11427673541_k25", "11427673541", "K25")
    assert len(xref.models) == 12
    first = xref.models[0]
    assert first.vehicle == VehicleRef(
        vehicle_id="0307-EUR-12_2002_K25_BMW_R_1200_GS_04_0307,0317_",
        type_code="0307",
        market="EUR",
        production_month="2002-12",
        series="K25",
        brand="motorrad",
        model="R_1200_GS_04_0307,0317_",
    )
    assert (first.body, first.engine) == (None, None)  # "N/A" and blank on RealOEM
    assert first.diagram.url == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0307-EUR-12_2002_K25_BMW_R_1200_GS_04_0307%2C0317_&diagId=02_0112"
    )
    assert {m.vehicle.brand for m in xref.models} == {"motorrad"}


async def test_rolls_royce_rows_skip_the_transmission_field(services: Services) -> None:
    xref = _parse(services, "rr_oil_filter_11427583220_rr4", "11427583220", "RR4")
    assert len(xref.models) == 12
    assert {(m.vehicle.brand, m.body, m.engine) for m in xref.models} == {
        ("rolls-royce", "Sedan", "N74R")
    }
    assert {m.vehicle.model for m in xref.models} == {"Ghost", "Ghost_EWB"}
    assert xref.models[0].vehicle.vehicle_id == "FK41-EUR-08_2008_RR4_Rolls_Royce_Ghost"


async def test_mini_row_is_tagged_mini(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    old_text = "3 Series E90, 323i, Sedan, N52, EUR, (VB51) :"
    old_link = "id=VB51-EUR-08_2004_E90_BMW_323i&amp;diagId=02_0092"
    assert old_text in html and old_link in html
    html = html.replace(old_text, "MINI R56, Cooper S, Hatchback, N14, USA, (MF73) :", 1)
    html = html.replace(old_link, "id=MF73-USA-02_2008_R56_Mini_Cooper_S&amp;diagId=11_3910", 1)
    row = _parse(services, "", "11427953129", "E90", html=html).models[0]
    assert (row.vehicle.brand, row.vehicle.series, row.vehicle.model) == ("mini", "R56", "Cooper_S")
    assert (row.body, row.engine) == ("Hatchback", "N14")
    assert row.diagram.diag_id == "11_3910"


async def test_unrecognized_row_text_leaves_body_and_engine_empty(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    html = html.replace("3 Series E90, 323i, Sedan, N52, EUR, (VB51) :", "(VB51) :")
    xref = _parse(services, "", "11427953129", "E90", html=html)
    assert (xref.models[0].body, xref.models[0].engine) == (None, None)
    assert xref.models[0].vehicle.type_code == "VB51"  # the id is still parsed from the link


async def test_row_without_diagram_id_raises_layout_changed(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    html = html.replace("&amp;diagId=02_0092#11427953129", "#11427953129", 1)
    with pytest.raises(LayoutChanged) as info:
        _parse(services, "", "11427953129", "E90", html=html)
    assert "unexpected vehicle link" in info.value.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_partxref_models.py -q`
Expected: FAIL (`5 failed, 1 passed`): the Task 5 parser raises `LayoutChanged` ("unexpected vehicle
link") on every vehicle row, which is why only `test_row_without_diagram_id_raises_layout_changed`
already passes.

- [ ] **Step 3: Write minimal implementation**

Make four edits to `server/src/realoem_mcp/parsers/partxref.py`.

In `server/src/realoem_mcp/parsers/partxref.py`, replace:

```python
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.parts import ModelUse, PartXref, SeriesUse, SupersessionEntry
```

with:

```python
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.models.parts import ModelUse, PartXref, SeriesUse, SupersessionEntry
```

In `server/src/realoem_mcp/parsers/partxref.py`, replace:

```python
from realoem_mcp.parsers.supersession import checked_mdy, parse_supersession
```

with:

```python
from realoem_mcp.parsers.supersession import checked_mdy, parse_supersession
from realoem_mcp.vehicle_ids import VehicleId
```

In `server/src/realoem_mcp/parsers/partxref.py`, replace:

```python
            series.append(_series_use(link, params["series"], url, brands))
        else:
```

with:

```python
            series.append(_series_use(link, params["series"], url, brands))
        elif target == "showparts" and params.get("id") and params.get("diagId"):
            models.append(_model_use(item, link, params, brands, client))
        else:
```

Append to `server/src/realoem_mcp/parsers/partxref.py` (after `_series_use`, separated by two
blank lines):

```python
_ID_SEPARATORS = re.compile(r"[ ()]+")  # how RealOEM turns model names into id segments


def _model_use(
    item: Node, link: Node, params: dict[str, str], brands: BrandRegistry, client: RealOemClient
) -> ModelUse:
    vid = VehicleId.parse(params["id"], brand_segments=brands.brand_segments())
    product = "M" if vid.type_code.startswith("0") else "P"  # motorcycle type codes start with 0
    brand = brands.for_vehicle_id(vid, product=product).id
    body, engine = _body_engine(text(item).partition(" : ")[0], vid)
    return ModelUse(
        vehicle=VehicleRef.from_id(vid, brand),
        body=body,
        engine=engine,
        diagram=DiagramRef.build(client, vid.raw, params["diagId"], text(link)),
    )


def _body_engine(label: str, vid: VehicleId) -> tuple[str | None, str | None]:
    """Body and engine from "3 Series E90, 325i, Sedan, N52, USA, (VB13)".

    Field counts vary (Rolls-Royce adds a transmission, series and model names can contain
    commas), so the model is located by comparing with the id's model segment and the two
    fields after it are body and engine. Blank and "N/A" become None.
    """
    fields = label.split(", ")
    for start in range(len(fields)):
        for end in range(start + 1, len(fields) + 1):
            if _ID_SEPARATORS.sub("_", ", ".join(fields[start:end])) == vid.model:
                body, engine = [*fields[end : end + 2], "", ""][:2]
                return _value(body), _value(engine)
    return None, None


def _value(field: str) -> str | None:
    field = field.strip()
    return None if field in ("", "N/A") else field
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/parsers -q && uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`111 passed`, `All checks passed!`, `54 files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers/partxref.py server/tests/unit/parsers/test_partxref_models.py
git commit -m "feat(parts): parse partxref vehicle rows for one series" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 3: Tool, skill, delivery

### Task 7: `lookup_part` tool and `fetch_part_xref` (`tools/parts.py`)

ARD §5.10–§5.11 and §6 "Part lookup". `fetch_part_xref` is the exported helper for features D and
E: it normalizes raw input (rejecting it before any request), fetches `partxref` with params `q`
then `series`, parses, and returns `(None, page)` when RealOEM reports not found or `matches()`
fails. Pages are cached by the client before they are parsed, so when parsing (or the
series-shape check) raises `LayoutChanged`, `fetch_part_xref` calls
`services.cache.shorten(page.url, timedelta(0))` before re-raising (ARD §5.10): a broken page is
never served from the cache. The tool adds the status and wraps the result with
`PartLookupResult.from_pages`. Every
`RealOemError` (invalid input, bot challenge, layout change, upstream error) becomes a `ToolError`.
The module defines `register(app, services)`, so the foundation's auto-discovery picks it up
(`tests/tools/test_server.py` and `test_stdio.py` then also see `lookup_part`).

**Files:**
- Create: `server/src/realoem_mcp/tools/parts.py`
- Test: `server/tests/tools/test_parts.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_parts.py`:

```python
import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.errors import InvalidInput
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.tools.parts import fetch_part_xref
from tests.harness import MakeServices, Route, url

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
OIL_FILTER_E90 = url("partxref", q="11427953129", series="E90")


async def _lookup(services: Services, **arguments: object) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("lookup_part", arguments)


async def test_current_part_lists_series_by_brand(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    result = await _lookup(services, part_number="11-42-7-953-129")
    assert result.is_error is False
    data = result.structured_content
    assert (data["query"], data["status"]) == ("11427953129", "current")
    assert data["source_urls"] == [OIL_FILTER]
    assert (data["from_cache"], data["requests_made"]) == (False, 1)
    part = data["part"]
    assert part["part_number"] == "11427953129"
    assert part["description"] == "Set oil-filter element"
    assert part["valid_from"] == "2017-06-01"
    assert len(part["supersedes"]) == 3
    assert len(part["series"]) == 66
    assert part["series"][0] == {
        "code": "E81",
        "name": "1 Series E81",
        "brand": "bmw",
        "production_from": "2006-02",
        "production_to": "2011-12",
    }
    assert part["models"] == []
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_repeat_lookup_uses_the_cache_until_refresh(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    await _lookup(services, part_number="11427953129")
    cached = await _lookup(services, part_number="11 42 7 953 129")
    assert cached.structured_content["from_cache"] is True
    assert cached.structured_content["requests_made"] == 0
    assert len(transport.requests) == 1
    refreshed = await _lookup(services, part_number="11427953129", refresh=True)
    assert refreshed.structured_content["requests_made"] == 1
    assert len(transport.requests) == 2


async def test_series_narrowing_returns_vehicles_and_diagrams(make_services: MakeServices) -> None:
    services, transport = make_services(
        {OIL_FILTER_E90: "partxref/oil_filter_11427953129_e90.html"}
    )
    result = await _lookup(services, part_number="11427953129", series=" e90 ")
    data = result.structured_content
    assert data["status"] == "current"
    assert data["source_urls"] == [OIL_FILTER_E90]  # q first, then series
    models = data["part"]["models"]
    assert len(models) == 114
    assert models[0]["vehicle"]["vehicle_id"] == "VB51-EUR-08_2004_E90_BMW_323i"
    assert models[0]["diagram"]["url"] == (
        "https://www.realoem.com/bmw/enUS/showparts?id=VB51-EUR-08_2004_E90_BMW_323i&diagId=02_0092"
    )
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("q", "fixture", "successor"),
    [
        ("11427541827", "partxref/superseded_11427541827.html", "11427953129"),
        ("11427566327", "partxref/intermediate_11427566327.html", "11427953129"),
    ],
)
async def test_ended_part_points_to_its_successors(
    make_services: MakeServices, q: str, fixture: str, successor: str
) -> None:
    services, _ = make_services({url("partxref", q=q): fixture})
    data = (await _lookup(services, part_number=q)).structured_content
    assert data["status"] == "ended"
    assert data["part"]["ended"] is True
    assert data["part"]["superseded_by"][-1]["part_number"] == successor
    assert data["part"]["superseded_by"][-1]["valid_to"] is None


async def test_status_never_comes_from_the_title(make_services: MakeServices) -> None:
    e30 = url("partxref", q="11427953129", series="E30")
    services, _ = make_services({e30: "partxref/oil_filter_11427953129_e30_no_vehicles.html"})
    data = (await _lookup(services, part_number="11427953129", series="E30")).structured_content
    assert data["status"] == "current"  # the page title says "Discontinued BMW Part"
    assert (data["part"]["series"], data["part"]["models"]) == ([], [])


async def test_seven_digit_short_form(make_services: MakeServices) -> None:
    services, _ = make_services({url("partxref", q="7953129"): "partxref/short_7953129.html"})
    data = (await _lookup(services, part_number="795 3129")).structured_content
    assert (data["query"], data["status"]) == ("7953129", "current")
    assert data["part"]["part_number"] == "11427953129"


@pytest.mark.parametrize(
    ("q", "fixture"),
    [
        ("11426666661", "partxref/not_found_11426666661.html"),  # error div
        ("99999999999", "partxref/false_match_99999999999.html"),  # returns 00009999999
        ("00000000000", "partxref/junk_abc.html"),  # junk part
        ("0000000", "partxref/junk_abc.html"),  # junk part, short form
    ],
)
async def test_not_found(make_services: MakeServices, q: str, fixture: str) -> None:
    services, transport = make_services({url("partxref", q=q): fixture})
    data = (await _lookup(services, part_number=q)).structured_content
    assert (data["query"], data["status"], data["part"]) == (q, "not_found", None)
    assert data["source_urls"] == [url("partxref", q=q)]
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"part_number": "abc"}, "is not a BMW part number"),
        ({"part_number": ""}, "is not a BMW part number"),
        ({"part_number": "1142795312"}, "is not a BMW part number"),
        ({"part_number": "114279531290"}, "is not a BMW part number"),
        ({"part_number": "11427953129", "series": "E9 0"}, "is not a RealOEM series code"),
    ],
)
async def test_malformed_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, str], message: str
) -> None:
    services, transport = make_services({})
    result = await _lookup(services, **arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_blank_series_means_no_series(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: "partxref/oil_filter_11427953129.html"})
    data = (await _lookup(services, part_number="11427953129", series=" ")).structured_content
    assert len(data["part"]["series"]) == 66
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_series_list_on_a_narrowed_page_is_a_layout_change(
    make_services: MakeServices,
) -> None:
    services, _ = make_services({OIL_FILTER_E90: "partxref/oil_filter_11427953129.html"})
    result = await _lookup(services, part_number="11427953129", series="E90")
    assert result.is_error is True
    assert "series list on a page narrowed to one series" in result.content[0].text


async def test_vehicle_rows_on_a_plain_lookup_are_a_layout_change(
    make_services: MakeServices,
) -> None:
    services, _ = make_services({OIL_FILTER: "partxref/oil_filter_11427953129_e90.html"})
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "vehicle rows on a page without a series" in result.content[0].text


async def test_unexpected_page_structure_is_reported(make_services: MakeServices) -> None:
    services, _ = make_services({OIL_FILTER: Route(fixture=None)})  # empty 200 page
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "did not have the expected structure" in result.content[0].text


async def test_unparseable_page_is_not_kept_in_the_cache(make_services: MakeServices) -> None:
    services, transport = make_services({OIL_FILTER: Route(fixture=None)})  # empty 200 page
    first = await _lookup(services, part_number="11427953129")
    second = await _lookup(services, part_number="11427953129")
    assert (first.is_error, second.is_error) == (True, True)
    assert len(transport.requests) == 2  # the broken page was not served from the cache


async def test_bot_challenge_is_reported(make_services: MakeServices) -> None:
    challenge = Route(
        fixture="common/cloudflare_challenge.html",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    services, transport = make_services({OIL_FILTER: challenge})
    result = await _lookup(services, part_number="11427953129")
    assert result.is_error is True
    assert "bot challenge" in result.content[0].text
    assert len(transport.requests) == 1  # never retried


async def test_fetch_part_xref_for_other_features(make_services: MakeServices) -> None:
    missing = url("partxref", q="11426666661")
    services, transport = make_services(
        {
            OIL_FILTER: "partxref/oil_filter_11427953129.html",
            missing: "partxref/not_found_11426666661.html",
        }
    )
    xref, page = await fetch_part_xref(services, "11427953129")
    assert xref is not None and xref.part_number == "11427953129"
    assert (page.url, page.from_cache) == (OIL_FILTER, False)
    none, page = await fetch_part_xref(services, "11426666661")
    assert (none, page.url) == (None, missing)
    with pytest.raises(InvalidInput):
        await fetch_part_xref(services, "abc")
    assert len(transport.requests) == 2
```

The junk-part cases route `q=00000000000` / `q=0000000` to the page RealOEM serves for junk input
(captured with `q=abc`, which the tool itself rejects before any request).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_parts.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'realoem_mcp.tools.parts'`, `1 error`)

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/tools/parts.py`:

```python
"""lookup_part tool and fetch_part_xref helper (ARD section 5.11, feature A)."""

from __future__ import annotations

import re
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.parts import PartLookupResult, PartXref
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.part_numbers import matches, normalize
from realoem_mcp.parsers.partxref import parse_partxref
from realoem_mcp.services import Services

_SERIES = re.compile(r"[A-Z0-9]{2,8}")  # E90, E90N, RR4, K255, MOSP


def _series_code(raw: str) -> str:
    code = raw.strip().upper()
    if not _SERIES.fullmatch(code):
        raise InvalidInput(
            f"{raw!r} is not a RealOEM series code. Use a code from a lookup_part result's "
            "series list, e.g. E90, E90N, R56, RR4 or K25."
        )
    return code


async def fetch_part_xref(
    services: Services, part_number: str, *, series: str | None = None, refresh: bool = False
) -> tuple[PartXref | None, Page]:
    """Fetch and parse partxref for raw user input (one request, or none when cached).

    Returns (None, page) when RealOEM reports the part as not found or returns a different part
    (last-7-digit false match, junk part 00000000000). Raises InvalidInput before any request
    for malformed input. A blank series means no series. A page that fails to parse is dropped
    from the cache before LayoutChanged is re-raised, so the next call fetches it again. Used by
    lookup_part and by the fitment and supersession features.
    """
    query = normalize(part_number)
    params = {"q": query}
    if series is not None and series.strip():
        params["series"] = _series_code(series)
    page = await services.client.fetch(PageType.PARTXREF, "partxref", params, refresh=refresh)
    try:
        xref = _parse(services, page, narrowed="series" in params)
    except LayoutChanged:
        services.cache.shorten(page.url, timedelta(0))  # never keep a page we cannot parse
        raise
    if xref is None or not matches(query, xref.part_number):
        return None, page
    return xref, page


def _parse(services: Services, page: Page, *, narrowed: bool) -> PartXref | None:
    xref = parse_partxref(page.html, url=page.url, brands=services.brands, client=services.client)
    if xref is not None and not narrowed and xref.models:
        raise LayoutChanged(PageType.PARTXREF, "vehicle rows on a page without a series", page.url)
    if xref is not None and narrowed and xref.series:
        raise LayoutChanged(
            PageType.PARTXREF, "series list on a page narrowed to one series", page.url
        )
    return xref


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def lookup_part(
        part_number: str, series: str | None = None, refresh: bool = False
    ) -> PartLookupResult:
        """Look up a BMW, MINI, Rolls-Royce or BMW Motorrad part number on RealOEM.

        Use it when the user gives a part number and asks what it is, whether it is current,
        what replaced it, or which vehicles use it. part_number: 11 digits or the 7-digit short
        form; spaces, dashes and dots are fine (e.g. "11 42 7 953 129"). series (optional): a
        series code from a previous result's part.series[].code (e.g. "E90", "R56", "RR4",
        "K25") to list that series' vehicles and the diagrams showing the part.

        Returns status "current", "ended" (RealOEM marks it ENDED or lists a successor) or
        "not_found", plus part: description (may be null), supplier_ref, weight_kg,
        valid_from/valid_to, superseded_by and supersedes (with dates and remarks), series
        (each with code, name, brand and production range; plain lookup) or models (vehicle id,
        body, engine and diagram link per row; with series). Model vehicle ids carry the
        series start month, not a specific car's build month. Cite source_urls. One request
        to RealOEM, none when cached; refresh=true fetches a fresh copy.
        """
        try:
            query = normalize(part_number)
            xref, page = await fetch_part_xref(
                services, part_number, series=series, refresh=refresh
            )
        except RealOemError as err:
            raise ToolError(err.message) from err
        if xref is None:
            status = "not_found"
        elif xref.ended or xref.superseded_by:
            status = "ended"
        else:
            status = "current"
        return PartLookupResult.from_pages([page], query=query, status=status, part=xref)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/tools -q`
Expected: PASS (`28 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/parts.py server/tests/tools/test_parts.py
git commit -m "feat(parts): add lookup_part tool and fetch_part_xref" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: `part-lookup` skill

ARD §5.12. Frontmatter `name` + trigger-oriented `description` (a single line; no `: ` inside it,
so it stays valid YAML). The body tells Claude when to call `lookup_part`, how to read the status,
to group series by brand, to offer series narrowing, to point to supersession when a part ended, to
cite `source_urls`, and never to fetch RealOEM directly.

**Files:**
- Create: `skills/part-lookup/SKILL.md`
- Test: `server/tests/unit/test_skill_part_lookup.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_skill_part_lookup.py`:

```python
"""skills/part-lookup/SKILL.md: frontmatter and the rules the skill must state (ARD 5.12)."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "part-lookup" / "SKILL.md"


def _split() -> tuple[dict[str, str], str]:
    lines = SKILL.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", "SKILL.md must start with YAML frontmatter"
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, "\n".join(lines[end + 1 :])


def test_frontmatter_names_the_skill_and_its_triggers() -> None:
    fields, _ = _split()
    assert set(fields) == {"name", "description"}
    assert fields["name"] == "part-lookup"
    description = fields["description"]
    assert len(description) <= 1024
    for trigger in (
        "part number",
        "MINI",
        "Rolls-Royce",
        "Motorrad",
        "fits",
        "current",
        "replaced",
    ):
        assert trigger in description


def test_body_routes_everything_through_lookup_part() -> None:
    _, body = _split()
    for required in ("lookup_part", "series", "superseded_by", "source_urls", "brand"):
        assert required in body
    assert "Never fetch realoem.com" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_skill_part_lookup.py -q`
Expected: FAIL (`2 failed`)

- [ ] **Step 3: Write the skill**

Create `skills/part-lookup/SKILL.md`:

````markdown
---
name: part-lookup
description: Look up BMW, MINI, Rolls-Royce and BMW Motorrad OEM part numbers on RealOEM. Use whenever the user mentions a BMW Group part number (11 digits such as 11427953129 or 11 42 7 953 129, or the 7-digit short form 7953129) or asks what a part is, what it fits or which models use it, whether a part is current, discontinued or superseded, or what replaced it (its replacement).
---

# Part lookup

Answer questions about a BMW Group part number with the `lookup_part` tool of the `realoem` MCP
server. Never fetch realoem.com yourself (no WebFetch, no browser): every request must go through the
MCP tools, which rate-limit, cache and parse RealOEM for you.

## When to use

- The user gives a part number: "What is 11427953129?", "Is 11427541827 still current?",
  "What replaced 12120034087?", "Which cars use 11 42 7 566 327?".
- The user asks what fits or which models use a part they already identified.
- For "does part X fit my car" with a specific vehicle or VIN, prefer the fitment tools when they
  are available; `lookup_part` lists series and vehicles, not one car's build.

## Steps

1. Call `lookup_part(part_number=...)` with the number as the user wrote it. Spaces, dashes and dots
   are fine; 11 digits or the last 7 digits are accepted. If the tool reports that the input is not
   a BMW part number, ask the user to check the number; do not guess digits.
2. Read `status`:
   - `current`: RealOEM does not mark the part ENDED and lists no successor.
   - `ended`: RealOEM marks the part ENDED or lists a successor. Say so and show `superseded_by`.
   - `not_found`: RealOEM does not know this number. The tool already rejects RealOEM's
     last-7-digit false matches and its junk part `00000000000`, so report "not found" and ask the
     user to double-check the number.
3. Present the part: `part_number`, `description` (may be missing; say "no description on
   RealOEM"), `supplier_ref` when present (e.g. "BOSCH ZGR6STE2"), `valid_from`/`valid_to`, and
   `weight_kg` as "RealOEM lists …" (RealOEM weights are sometimes nonsense).
4. Group `part.series` by `brand` (bmw, mini, rolls-royce, motorrad) and list each series with its
   `name`, `code` and production range. For long lists summarize per brand and model family.
5. Offer series narrowing: "Want the exact models for a series?" Check the series code (e.g. E90,
   E90N) in `part.series` before narrowing. If the user picks one, call
   `lookup_part(part_number=..., series=<code>)` with the `code` from the result (e.g. `E90N`, not
   the label "E90 LCI"). The result's `part.models` lists one row per vehicle type and diagram with
   `vehicle` (vehicle id, type code, market, model), `body`, `engine` and `diagram` (name and
   RealOEM link). Group rows by vehicle and list the diagrams under each. `vehicle.model` is in
   RealOEM's id form (`R_1200_GS_04_0307,0317_`); show it with underscores as spaces. An empty
   `part.models` means RealOEM lists no vehicle of that series using the part: say "not listed
   for <series>", not "not found".
6. Supersession: `superseded_by` lists every successor with dates and remarks (the list is already
   transitive). The successor with an empty `valid_to` is the current replacement; intermediates can
   be short-lived. "Exchangeable retrospectively" means the new part also fits older vehicles.
   `supersedes` lists earlier numbers. If a `trace_supersession` tool is available, use it for the
   full chain with dates; otherwise look up the open-ended successor with `lookup_part` if the user
   wants its details.

## Rules

- Always cite RealOEM: include the `source_urls` of every result you used, and diagram links from
  `diagram.url` when you mention a diagram.
- Never call a part discontinued because of a page title; only `status` and `superseded_by` count.
- Vehicle ids from series rows carry the series start month, not a specific car's build month. For a
  particular car, get its vehicle id from `decode_vin` or `select_vehicle` when those tools exist.
- If a tool reports that a RealOEM page "did not have the expected structure", retry once with
  `refresh=true`; if it fails again, tell the user the plugin needs an update and give the URL.
- Call tools only for what the user asked. Results are cached; pass `refresh=true` only when the
  user asks for fresh data.
- Brand notes (vehicle id formats, series quirks) are in `brands/<brand>/README.md` of this plugin.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_skill_part_lookup.py -q`
Expected: PASS (`2 passed`)

Then validate the plugin: `claude plugin validate . --strict`
Expected: `✔ Validation passed`. If `claude` is not on `PATH` (e.g. only the desktop app is
installed), use `"$APPDATA/Claude/claude-code/<version>/claude.exe" plugin validate . --strict`, or
skip this check and note it in the PR.

- [ ] **Step 5: Commit**

```bash
git add skills/part-lookup/SKILL.md server/tests/unit/test_skill_part_lookup.py
git commit -m "feat(skills): add part-lookup skill" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Opt-in live smoke test

ARD §8: live tests carry `@pytest.mark.live`, are deselected by default and skipped unless
`REALOEM_LIVE=1`. This one makes exactly two requests (a plain lookup of the superseded oil filter
and the E90-narrowed lookup of its successor). Do **not** run it with `REALOEM_LIVE=1` while
implementing; CI never runs it.

**Files:**
- Test: `server/tests/live/test_part_lookup_live.py`

- [ ] **Step 1: Write the test**

Create `server/tests/live/test_part_lookup_live.py`:

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


async def test_lookup_part_against_realoem(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            plain = await client.call_tool("lookup_part", {"part_number": "11427541827"})
            narrowed = await client.call_tool(
                "lookup_part", {"part_number": "11427953129", "series": "E90"}
            )
    finally:
        await services.aclose()
    assert plain.is_error is False, plain.content
    assert plain.structured_content["status"] == "ended"
    successors = plain.structured_content["part"]["superseded_by"]
    assert "11427953129" in [entry["part_number"] for entry in successors]
    assert narrowed.is_error is False, narrowed.content
    assert narrowed.structured_content["status"] == "current"
    assert narrowed.structured_content["part"]["models"], "expected E90 vehicles"
    assert narrowed.structured_content["requests_made"] == 1
```

- [ ] **Step 2: Verify it is deselected by default**

Run: `uv run --directory server pytest tests/live -q; echo "exit=$?"`
Expected: PASS (`2 deselected`, `exit=5`: pytest exits with 5 when every collected test is deselected)

- [ ] **Step 3: Verify it is skipped without `REALOEM_LIVE=1`**

Run: `uv run --directory server pytest tests/live -q -m live`
Expected: PASS (`2 skipped`)

- [ ] **Step 4: Lint**

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, `58 files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/live/test_part_lookup_live.py
git commit -m "test(live): add opt-in part lookup smoke test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: `343 passed, 2 deselected`, `All checks passed!`, `58 files already formatted`.

- [ ] **Step 2: Smoke-test the tool over stdio with the plugin's launch command**

This lists the tools and calls `lookup_part` with malformed input, which is rejected before any
request, so nothing is sent to RealOEM.

```bash
uv run --quiet --directory server python - <<'EOF'
import asyncio
from pathlib import Path

from mcp import Client, StdioServerParameters

root = Path.cwd().parent  # uv --directory makes server/ the working directory
params = StdioServerParameters(
    command="uv",
    args=["run", "--quiet", "--directory", str(root / "server"), "realoem-mcp"],
    env={"REALOEM_BRANDS_DIR": str(root / "brands")},
)


async def main() -> None:
    async with Client(params) as client:
        tools = await client.list_tools()
        print("tools:", sorted(tool.name for tool in tools.tools))
        result = await client.call_tool("lookup_part", {"part_number": "abc"})
        print("is_error:", result.is_error, result.content[0].text)


asyncio.run(main())
EOF
```

Expected: `tools: ['cache_clear', 'lookup_part', 'server_status']` and
`is_error: True Error executing tool lookup_part: 'abc' is not a BMW part number. Enter 11 digits (e.g. 11427953129) or the last 7 digits (7953129); spaces, dashes and dots are allowed.`
(plus an `INFO mcp.server.mcpserver.server: Tool 'lookup_part' failed: …` line from the server's
stderr log).

- [ ] **Step 3: Confirm nothing raw or generated is staged and no foundation file changed**

Run: `git status --short && git diff --name-only main... | grep -vE '^(server/src/realoem_mcp/(parsers/(part_numbers|supersession|partxref)|models/parts|tools/parts)\.py|server/tests/(fixtures/partxref/.*\.html|unit/parsers/test_(part_numbers|partxref|partxref_fixtures|partxref_models|supersession)\.py|unit/test_(models_parts|skill_part_lookup)\.py|tools/test_parts\.py|live/test_part_lookup_live\.py)|skills/part-lookup/SKILL\.md)$' || echo clean`
Expected: no `git status` output and `clean`.

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin feat/part-lookup
gh pr create --base main --head feat/part-lookup --title "feat: part number lookup (lookup_part)" --body "$(cat <<'EOF'
## Summary

Implements PRD F1 (feature A) per ARD §5.9–§5.11:

- `lookup_part(part_number, series=None, refresh=False)`: one `partxref` request (cached 7 days). Returns status `current` / `ended` / `not_found`, description, supplier reference, valid-from/to, weight, superseded-by and supersedes lists, and the series using the part tagged with their brand (BMW, MINI, Rolls-Royce, Motorrad), or with `series` the vehicles (vehicle id, body, engine) and diagrams showing it.
- Input validated before any request (7 or 11 digits; spaces, dashes, dots allowed; series codes checked). Unexpected page structure (including unparseable dates and empty result lists) raises `LayoutChanged` instead of returning partial data. RealOEM's last-7-digit false matches and the junk part `00000000000` are reported as not found; the page title is never used for the status.
- Exported for later features: `tools.parts.fetch_part_xref`, `parsers.supersession.parse_supersession`, `parsers.part_numbers.normalize` / `matches`.
- `part-lookup` skill; 16 trimmed partxref fixtures; parser, tool and "rejected before any request" tests; opt-in live smoke test.
- No foundation file changed; no version bump.

## Test plan

- [x] `uv run pytest` (offline), `uv run ruff check`, `uv run ruff format --check`
- [x] stdio smoke test lists `lookup_part` and rejects malformed input without a request
- [x] `claude plugin validate . --strict` (if `claude` was not available, change this line to "skipped: claude CLI not available" and leave it unticked)
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
