# Supersession Chain Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/supersession` (PRD F5.1–F5.3, feature E): a `trace_supersession` MCP tool that follows RealOEM's "Superseded by" links from a BMW Group part number to the part that replaces it today and returns the status (`current` / `replaced` / `no_successor` / `ambiguous` / `not_found`), the chain of parts it read (dates and remarks), the current number, the alternatives when RealOEM names several open-ended successors, the predecessor history, and `complete` / `warnings` when the trace stopped early (hop limit, missing successor page, loop); plus the `supersession` skill.

**Architecture:** Pure reuse of feature A: each part is read with `tools.parts.fetch_part_xref` (one cached, rate-limited `partxref` request, input normalized and returned number verified). Because RealOEM's supersession lists are transitively closed (site notes §3.5), the tool jumps straight to the open-ended successor, so a typical trace is one or two requests. A pure `choose_successor` picks the link to follow; `trace_chain` runs the hop loop with a visited set and a hop limit and shapes a `SupersessionResult(ResultMeta)` from every page it read. `models/supersession.py` and `tools/supersession.py` are new files; the tool module is auto-discovered, so no foundation or part-lookup file changes.

**Tech Stack:** Python ≥ 3.11, uv, mcp 2.x (`MCPServer`, in-memory `mcp.Client` for tests), pydantic 2, pytest + AnyIO, ruff. Contract: `docs/ARD.md` §5.10, §5.11 ("A" and "E"), §8; site facts: `docs/research/realoem-site-notes.md` §3.4–§3.5.

---

## Before you start

- `feat/foundation` and `feat/part-lookup` are merged into `main`. This plan only **adds** files; it
  edits no foundation or part-lookup file. Read `docs/ARD.md` §5.10–§5.11 and §8 and
  `docs/research/realoem-site-notes.md` §3.5 once.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.**
  Python commands use `uv run --directory server …`, which runs inside `server/`; paths after it
  (like `tests/tools/test_supersession.py`) are relative to `server/`. `git` paths are relative to
  the repository root.
- Never make requests to realoem.com while implementing. Tests are offline: routes map URLs to
  fixture files. The only live test (Task 7) is opt-in and must not be run with `REALOEM_LIVE=1`.
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`.
- APIs used here (do not re-implement them):
  - Part lookup (feature A): `realoem_mcp.tools.parts.fetch_part_xref(services, part_number, *,
    series=None, refresh=False) -> tuple[PartXref | None, Page]` (normalizes raw input, raises
    `InvalidInput` before any request, returns `None` for "not found" and last-7 false matches);
    `realoem_mcp.parsers.part_numbers.normalize(raw) -> str`; models `PartXref` and
    `SupersessionEntry` in `realoem_mcp.models.parts` (`superseded_by` / `supersedes` lists in page
    order; `valid_to is None` = open-ended; `remark`; `in_catalog`).
  - Foundation: `ResultMeta.from_pages(pages, **fields)` (`realoem_mcp.models.common`),
    `realoem_mcp.errors.InvalidInput` / `RealOemError`, `realoem_mcp.http_client.Page`,
    `realoem_mcp.services.Services`.
  - Tests: `from tests.harness import MakeServices, Route, load_fixture, url`; the `make_services`
    fixture (in `tests/conftest.py`) returns `(services, transport)`, asserts at teardown that no
    unrouted URL was requested, and needs an `async` test (`pytestmark = pytest.mark.anyio`).
    `transport.requests` lists what was sent. `Route.fixture` is a path under
    `server/tests/fixtures/`; the harness reads it as `FIXTURES / path`, so an **absolute** path
    (pathlib ignores the left side) serves a file from pytest's `tmp_path` (used for the synthetic
    pages in Tasks 4–5).
  - Existing part-lookup fixtures reused as-is (`server/tests/fixtures/partxref/`):
    `oil_filter_11427953129.html` (current), `superseded_11427541827.html` (ENDED, three
    successors), `intermediate_11427566327.html` (ENDED, two successors),
    `spark_plug_12120037244.html` (current), `short_7953129.html` (7-digit query),
    `not_found_11426666661.html` ("was not found" error div).
- mcp 2.x: raising `ToolError("msg")` in a tool returns `is_error=True` with text
  `Error executing tool <name>: msg`; `result.structured_content` is the returned model as JSON.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that). Do not bump any version.

## File Structure

| Path | Responsibility |
|---|---|
| `server/tests/fixtures/supersession/spark_plug_pred_12120034087.html` | Trimmed real `partxref` page of the ENDED spark plug 12120034087 (one open-ended successor, 12120037244) |
| `server/src/realoem_mcp/models/supersession.py` | `SupersessionHop`, `SupersessionResult(ResultMeta)` incl. `complete` and `warnings` (ARD §5.11 E) |
| `server/src/realoem_mcp/tools/supersession.py` | `choose_successor(entries)`, `trace_chain(services, part_number, *, max_hops, refresh)` and the `trace_supersession` tool (`register`) |
| `skills/supersession/SKILL.md` | Skill: when to call `trace_supersession`, how to explain statuses, remarks and short-lived intermediates |
| `server/tests/unit/parsers/test_supersession_fixtures.py` | The new fixture is the right capture |
| `server/tests/unit/test_models_supersession.py` | Models and `SupersessionResult.from_pages` |
| `server/tests/unit/test_choose_successor.py` | Successor choice rules |
| `server/tests/tools/test_supersession.py` | `trace_supersession` through the in-memory `mcp.Client`: every status with its `complete`/`warnings`, cache, hop limit, loop guard, invalid input |
| `server/tests/unit/test_skill_supersession.py` | Skill frontmatter and required content |
| `server/tests/live/test_supersession_live.py` | Opt-in live smoke test (≤ 3 requests) |

### Algorithm (`trace_chain`)

ARD §5.11 fixes the result fields (including `complete` and `warnings`), the hop definition and
the stopped-early rules; ARD §6 leaves the rest of the algorithm to this plan. A **hop** is reading
one successor's `partxref` page, so a trace sends at most `1 + max_hops` requests (fewer when
pages are cached). `chain` lists the parts
whose pages were read and accepted, queried part first; each `SupersessionHop` takes
`part_number`, `description`, `valid_from` and `valid_to` from **that part's own page header**, and
`remark` from the "Superseded by" entry that led to it (`None` for the queried part).

1. `query = normalize(part_number)`; `max_hops` outside 1–10 → `InvalidInput`. Both happen before
   any request.
2. Read the queried part (`fetch_part_xref(services, query, refresh=refresh)`). `None` →
   `not_found` with empty `chain`, `alternatives` and `history`, `complete=True`, no warnings.
3. Loop, with `xref` = the last part in `chain` and `visited` = the numbers in `chain`:
   1. `xref.superseded_by` empty: `xref.ended` → `no_successor`; otherwise `current` (chain has
      one entry) or `replaced` (it has more); `current_part_number = xref.part_number` for both.
   2. `pick = choose_successor(xref.superseded_by)`: the open-ended entries (`valid_to is None`) if
      there are any, else all entries; the one with the latest `(valid_to, valid_from)` (missing
      dates count as earliest); ties keep page order. So an open-ended successor always beats a
      short-lived intermediate with a later start (site notes §3.5), and "latest end" is the
      fallback when nothing is open-ended.
   3. `pick` already in `visited` → **loop guard**: `ambiguous`, `alternatives` = the open-ended
      entries of `xref` (or `[pick]` when none is open-ended), warning
      `loop detected: <xref> is superseded by <pick>, which is already in the chain`. Nothing is
      fetched twice.
   4. If fewer than `max_hops` successor pages were read (`len(chain) <= max_hops`), read `pick`'s
      page (one request unless cached). Otherwise add the warning
      `hop limit reached (max_hops=<n>): the page of successor <pick> was not read`. A read page
      that is "not found" (or shows a different number) adds
      `successor page missing: RealOEM has no page for <pick>`.
   5. **Stopped early** (either warning of step 4): with more than one open-ended entry →
      `ambiguous` (`alternatives` = those entries; the tool could not check which replaces the
      other); otherwise `replaced` with `current_part_number = pick.part_number` (the newest
      successor RealOEM names) if `pick` is open-ended, else `None`. `chain` ends at `xref`.
   6. **Ambiguity check**: every other open-ended entry of `xref` must appear in the successor's
      `supersedes` list (then it is an intermediate the successor replaced). Otherwise
      `ambiguous` with `alternatives` = the open-ended entries; `chain` ends at `xref` (the
      successor's page is still in `source_urls` because it decided the answer).
   7. Append the successor to `chain` (remark = `pick.remark`) and continue.
4. `history` = `supersedes` of the last `chain` entry (for `current`/`replaced` that is the
   current part: every predecessor, because the lists are transitively closed). `alternatives` is
   empty unless `ambiguous`. `complete` is `True` exactly when there are no warnings (so a
   verified `ambiguous` from step 3.6 is complete; one from step 3.5 is not).
5. `ResultMeta.from_pages` over every page read, in request order (including a page read only for
   the ambiguity check or answered "not found").

Worked examples (fixtures): `11427541827` → reads 11427541827, jumps to the open-ended
11427953129 (skipping the intermediates 11427566327 and 11428683196), which is current →
`replaced`, 2 requests, `history` = 11428683196, 11427566327, 11427541827. `11427953129` →
`current`, 1 request. `12120034087` → `replaced` by 12120037244.

Decisions where the ARD leaves room:

- **Resolving several open-ended successors** (a stricter reading of F5.2): another open-ended
  entry counts as resolved, not ambiguous, when the chosen successor's `supersedes` list names it.
- **Warning texts** are fixed strings starting with `hop limit reached`, `successor page missing`
  or `loop detected` (tests assert them exactly; the skill keys on those prefixes).
- **Fixture folder.** Part-lookup's `test_partxref_fixture_set_is_complete` pins the exact set of
  files in `fixtures/partxref/`, so the one new capture goes to `fixtures/supersession/` (ARD §8
  allows `fixtures/<feature>/`) with its own completeness test; no part-lookup file changes.
- **Synthetic cases.** No real capture shows `no_successor`, `ambiguous`, a loop, a two-hop chain or
  a missing successor page. Those tests (Tasks 4–5) edit a real fixture in memory with plain
  string replacements (each asserts that the replaced text exists), write it to `tmp_path` and
  route the real URL to it. Every such test starts with a `# synthetic:` comment. Nothing
  synthetic is committed under `fixtures/`.

## Chunk 1: Branch, fixture, models

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

```bash
git checkout main && git pull && git checkout -b feat/supersession
```

Expected: `Switched to a new branch 'feat/supersession'`.

- [ ] **Step 2: Confirm the part-lookup baseline is green**

Run: `uv run --directory server pytest -q && uv run --directory server ruff format --check`
Expected: PASS. Write down the baseline: **N** passed, **D** deselected, **F** files already
formatted. This branch is cut last (PRD order F0, F1, F2, F3, F6, F4, F5), so the numbers depend
on which branches are merged; every later full-suite expectation in this plan is a delta from
them. For reference, when `main` has only foundation and part-lookup the baseline is
`344 passed, 2 deselected` and `58 files already formatted`. If any test fails, stop and fix
`main` first.

This plan adds, in total: **+45** tests (Task 1: +4 = 2 fixture tests + 2 foundation fixture-check
cases; Task 2: +8; Task 3: +5; Task 4: +21; Task 5: +3; Task 6: +2; Task 7: +1 deselected live
test, not collected by default) and **+8** Python files (checked by `ruff format --check`).

### Task 1: Spark plug predecessor fixture

The oil filter chain is covered by part-lookup's fixtures. One more real capture adds a second,
independent chain: the ENDED spark plug 12120034087, whose only successor is the current
12120037244 (already committed as `partxref/spark_plug_12120037244.html`).

**Files:**
- Create: `server/tests/fixtures/supersession/spark_plug_pred_12120034087.html` (generated)
- Test: `server/tests/unit/parsers/test_supersession_fixtures.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_supersession_fixtures.py`:

```python
"""Each supersession fixture is the trimmed page RealOEM served for the part in its name."""

import pytest

from tests.harness import FIXTURES, load_fixture

# fixture slug -> text that only the right capture contains
MARKERS = {
    "spark_plug_pred_12120034087": "12120034087 - Spark plug, High Power</h1>",
}


def test_supersession_fixture_set_is_complete() -> None:
    present = {path.stem for path in (FIXTURES / "supersession").glob("*.html")}
    assert present == set(MARKERS)


@pytest.mark.parametrize(("slug", "marker"), MARKERS.items(), ids=list(MARKERS))
def test_supersession_fixture_is_the_right_capture(slug: str, marker: str) -> None:
    assert marker in load_fixture(f"supersession/{slug}.html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_supersession_fixtures.py -q`
Expected: FAIL (`2 failed`)

- [ ] **Step 3: Generate the fixture**

`.research-raw/` is git-ignored and exists only in the main checkout. `RAW` resolves it from either
the main checkout or a git worktree:

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/xref/xref_sparkplug_pred_12120034087.html" tests/fixtures/supersession/spark_plug_pred_12120034087.html
```

Expected (stderr; Windows prints `\` in the path):
`tests/fixtures/supersession/spark_plug_pred_12120034087.html: 27781 -> 7067 bytes`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/unit/parsers/test_supersession_fixtures.py tests/unit/test_fixtures.py -q -k supersession`
Expected: PASS (`4 passed` and some deselected: the 2 new tests plus the foundation's
`test_fixtures.py` checks that the new file is trimmed and has no unmasked VIN; the deselected
count is the other fixtures' checks)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/supersession server/tests/unit/parsers/test_supersession_fixtures.py
git commit -m "test(supersession): add spark plug predecessor fixture" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Result models (`models/supersession.py`)

**Files:**
- Create: `server/src/realoem_mcp/models/supersession.py`
- Test: `server/tests/unit/test_models_supersession.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_supersession.py`:

```python
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from realoem_mcp.http_client import Page
from realoem_mcp.models.common import ResultMeta
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.models.supersession import SupersessionHop, SupersessionResult
from realoem_mcp.page_types import PageType

BASE = "https://www.realoem.com/bmw/enUS/partxref?q="


def _page(q: str, *, from_cache: bool, day: int) -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=BASE + q,
        final_url=BASE + q,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, day, 12, 0, tzinfo=UTC),
        from_cache=from_cache,
    )


def _fields() -> dict[str, object]:
    return {
        "query": "11427541827",
        "status": "replaced",
        "current_part_number": "11427953129",
        "chain": [
            SupersessionHop(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
            ),
            SupersessionHop(
                part_number="11427953129",
                description="Set oil-filter element",
                valid_from=date(2017, 6, 1),
                valid_to=None,
                remark="Exchangeable retrospectively",
            ),
        ],
        "alternatives": [],
        "history": [
            SupersessionEntry(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
                in_catalog=False,
            )
        ],
        "complete": True,
        "warnings": [],
    }


def test_result_extends_result_meta_with_the_ard_fields() -> None:
    assert issubclass(SupersessionResult, ResultMeta)
    assert list(SupersessionResult.model_fields) == [
        "source_urls",
        "fetched_at",
        "from_cache",
        "requests_made",
        "query",
        "status",
        "current_part_number",
        "chain",
        "alternatives",
        "history",
        "complete",
        "warnings",
    ]
    assert list(SupersessionHop.model_fields) == [
        "part_number",
        "description",
        "valid_from",
        "valid_to",
        "remark",
    ]


def test_from_pages_covers_every_page_of_the_chain() -> None:
    pages = [
        _page("11427541827", from_cache=True, day=28),
        _page("11427953129", from_cache=False, day=30),
    ]
    result = SupersessionResult.from_pages(pages, **_fields())
    data = result.model_dump(mode="json")
    assert data["source_urls"] == [BASE + "11427541827", BASE + "11427953129"]
    assert data["fetched_at"] == "2026-09-28T12:00:00Z"
    assert (data["from_cache"], data["requests_made"]) == (False, 1)
    assert data["chain"][1] == {
        "part_number": "11427953129",
        "description": "Set oil-filter element",
        "valid_from": "2017-06-01",
        "valid_to": None,
        "remark": "Exchangeable retrospectively",
    }
    assert data["history"][0]["in_catalog"] is False
    assert (data["complete"], data["warnings"]) == (True, [])


@pytest.mark.parametrize(
    "status", ["current", "replaced", "no_successor", "ambiguous", "not_found"]
)
def test_status_accepts_the_five_ard_values(status: str) -> None:
    pages = [_page("11427541827", from_cache=False, day=30)]
    assert SupersessionResult.from_pages(pages, **{**_fields(), "status": status}).status == status


def test_status_rejects_lookup_part_statuses() -> None:
    pages = [_page("11427541827", from_cache=False, day=30)]
    with pytest.raises(ValidationError):
        SupersessionResult.from_pages(pages, **{**_fields(), "status": "ended"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_supersession.py -q`
Expected: FAIL (`1 error`: `ModuleNotFoundError: No module named 'realoem_mcp.models.supersession'`)

- [ ] **Step 3: Write the models**

Create `server/src/realoem_mcp/models/supersession.py`:

```python
"""Supersession chain models (ARD section 5.11, feature E)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta
from realoem_mcp.models.parts import SupersessionEntry


class SupersessionHop(BaseModel):
    part_number: str
    description: str | None
    valid_from: date | None  # from this part's own partxref page
    valid_to: date | None  # None = open-ended
    remark: str | None  # remark of the link that led here; None for the queried part


class SupersessionResult(ResultMeta):
    query: str  # normalized input
    status: Literal["current", "replaced", "no_successor", "ambiguous", "not_found"]
    current_part_number: str | None  # set for current and replaced
    chain: list[SupersessionHop]  # parts whose pages were read, queried part first
    alternatives: list[SupersessionEntry]  # successors the trace could not choose between
    history: list[SupersessionEntry]  # "Supersedes" list of the last part in chain
    complete: bool  # False when the trace stopped early (hop limit, missing page, loop)
    warnings: list[str]  # one entry per reason the trace stopped early
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_supersession.py -q`
Expected: PASS (`8 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models/supersession.py server/tests/unit/test_models_supersession.py
git commit -m "feat(supersession): add supersession result models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 2: Tool

### Task 3: Successor choice (`choose_successor`)

**Files:**
- Create: `server/src/realoem_mcp/tools/supersession.py`
- Test: `server/tests/unit/test_choose_successor.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_choose_successor.py`:

```python
from datetime import date

import pytest

from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.tools.supersession import choose_successor


def _entry(number: str, start: date | None, end: date | None) -> SupersessionEntry:
    return SupersessionEntry(
        part_number=number,
        description=None,
        valid_from=start,
        valid_to=end,
        remark=None,
        in_catalog=True,
    )


def test_open_ended_entry_wins_over_a_later_start() -> None:
    # site notes 3.5: intermediates can start later than the current part, so the open end wins
    entries = [
        _entry("11111111111", date(2006, 2, 13), date(2017, 1, 30)),
        _entry("22222222222", date(2017, 6, 1), None),
        _entry("33333333333", date(2018, 1, 1), date(2018, 9, 21)),
    ]
    assert choose_successor(entries).part_number == "22222222222"


def test_latest_start_among_open_ended_entries() -> None:
    entries = [
        _entry("11111111111", date(2016, 9, 1), None),
        _entry("22222222222", date(2017, 6, 1), None),
        _entry("33333333333", None, None),
    ]
    assert choose_successor(entries).part_number == "22222222222"


def test_without_open_end_the_latest_end_then_the_latest_start() -> None:
    entries = [
        _entry("11111111111", date(2006, 2, 13), date(2017, 1, 30)),
        _entry("22222222222", date(2016, 9, 1), date(2017, 9, 21)),
        _entry("33333333333", date(2017, 1, 1), date(2017, 9, 21)),
    ]
    assert choose_successor(entries).part_number == "33333333333"


def test_ties_keep_page_order() -> None:
    entries = [
        _entry("11111111111", date(2017, 6, 1), None),
        _entry("22222222222", date(2017, 6, 1), None),
    ]
    assert choose_successor(entries).part_number == "11111111111"


def test_empty_list_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        choose_successor([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_choose_successor.py -q`
Expected: FAIL (`1 error`: `ModuleNotFoundError: No module named 'realoem_mcp.tools.supersession'`)

- [ ] **Step 3: Write `choose_successor`**

The module has no `register` yet; the server's auto-discovery skips modules without one.

Create `server/src/realoem_mcp/tools/supersession.py`:

```python
"""trace_supersession tool (ARD section 5.11, feature E; site notes 3.5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from realoem_mcp.models.parts import SupersessionEntry


def _day(value: date | None) -> date:
    return value or date.min


def choose_successor(entries: Sequence[SupersessionEntry]) -> SupersessionEntry:
    """The successor to follow from a non-empty "Superseded by" list.

    Lists are transitively closed and the open-ended entry is the current part (site notes 3.5),
    so open-ended entries win; among them the latest start. Without an open-ended entry, the
    latest end (then the latest start). Ties keep page order.
    """
    candidates = [e for e in entries if e.valid_to is None] or list(entries)
    return max(candidates, key=lambda e: (_day(e.valid_to), _day(e.valid_from)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_choose_successor.py -q`
Expected: PASS (`5 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/supersession.py server/tests/unit/test_choose_successor.py
git commit -m "feat(supersession): choose the successor to follow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `trace_supersession` tool

This task implements Algorithm steps 1–5, including the hop-limit and missing-page warnings,
without the loop guard (3.3) and without the ambiguity rules (the "more than one open-ended entry"
branch of 3.5 and step 3.6); Task 5 adds them. The hop limit already guarantees termination.

**Files:**
- Modify: `server/src/realoem_mcp/tools/supersession.py` (replace the whole file)
- Test: `server/tests/tools/test_supersession.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_supersession.py`:

```python
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import MakeServices, Route, load_fixture, url

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")  # current
SUPERSEDED = url("partxref", q="11427541827")  # ended; successors ...566327, ...683196, ...953129
INTERMEDIATE = url("partxref", q="11427566327")  # ended; successors ...683196, ...953129
SPARK_PLUG = url("partxref", q="12120037244")  # current
SPARK_PLUG_PRED = url("partxref", q="12120034087")  # ended; successor 12120037244
REAL = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    SUPERSEDED: "partxref/superseded_11427541827.html",
    INTERMEDIATE: "partxref/intermediate_11427566327.html",
    SPARK_PLUG: "partxref/spark_plug_12120037244.html",
    SPARK_PLUG_PRED: "supersession/spark_plug_pred_12120034087.html",
}
RETRO = "Exchangeable retrospectively"
OIL_FILTER_HISTORY = ["11428683196", "11427566327", "11427541827"]


async def _trace(services: Services, **arguments: object) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("trace_supersession", arguments)


def _numbers(entries: list[dict[str, object]]) -> list[object]:
    return [entry["part_number"] for entry in entries]


async def test_current_part(make_services: MakeServices) -> None:
    services, transport = make_services(REAL)
    result = await _trace(services, part_number="11 42 7 953 129")
    assert result.is_error is False
    data = result.structured_content
    assert (data["query"], data["status"]) == ("11427953129", "current")
    assert data["current_part_number"] == "11427953129"
    assert data["chain"] == [
        {
            "part_number": "11427953129",
            "description": "Set oil-filter element",
            "valid_from": "2017-06-01",
            "valid_to": None,
            "remark": None,
        }
    ]
    assert data["alternatives"] == []
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert data["history"][2]["in_catalog"] is False
    assert (data["complete"], data["warnings"]) == (True, [])
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == (
        [OIL_FILTER],
        False,
        1,
    )
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_replaced_part_jumps_to_the_open_ended_successor(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(REAL)
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert data["chain"] == [
        {
            "part_number": "11427541827",
            "description": "Set oil-filter element",
            "valid_from": "2004-09-01",
            "valid_to": "2006-03-17",
            "remark": None,
        },
        {
            "part_number": "11427953129",
            "description": "Set oil-filter element",
            "valid_from": "2017-06-01",
            "valid_to": None,
            "remark": RETRO,
        },
    ]
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert data["alternatives"] == []
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert data["requests_made"] == 2
    assert (data["complete"], data["warnings"]) == (True, [])
    # the short-lived intermediates 11427566327 and 11428683196 are never fetched
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


@pytest.mark.parametrize(
    ("start", "current", "start_url", "current_url"),
    [
        ("11427566327", "11427953129", INTERMEDIATE, OIL_FILTER),
        ("12120034087", "12120037244", SPARK_PLUG_PRED, SPARK_PLUG),
    ],
)
async def test_other_real_chains(
    make_services: MakeServices,
    start: str,
    current: str,
    start_url: str,
    current_url: str,
) -> None:
    services, _ = make_services(REAL)
    data = (await _trace(services, part_number=start)).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", current)
    assert [hop["part_number"] for hop in data["chain"]] == [start, current]
    assert [hop["remark"] for hop in data["chain"]] == [None, RETRO]
    assert start in _numbers(data["history"])
    assert data["source_urls"] == [start_url, current_url]
    assert (data["complete"], data["warnings"]) == (True, [])


async def test_seven_digit_short_form(make_services: MakeServices) -> None:
    short = url("partxref", q="7953129")
    services, transport = make_services({short: "partxref/short_7953129.html"})
    data = (await _trace(services, part_number="795-3129")).structured_content
    assert (data["query"], data["status"]) == ("7953129", "current")
    assert data["current_part_number"] == "11427953129"
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [short]


async def test_repeat_trace_uses_the_cache_until_refresh(make_services: MakeServices) -> None:
    services, transport = make_services(REAL)
    await _trace(services, part_number="11427541827")
    cached = (await _trace(services, part_number="11427541827")).structured_content
    assert (cached["from_cache"], cached["requests_made"]) == (True, 0)
    assert len(transport.requests) == 2
    fresh = (await _trace(services, part_number="11427541827", refresh=True)).structured_content
    assert (fresh["from_cache"], fresh["requests_made"]) == (False, 2)
    assert len(transport.requests) == 4


async def test_not_found(make_services: MakeServices) -> None:
    missing = url("partxref", q="11426666661")
    services, transport = make_services({missing: "partxref/not_found_11426666661.html"})
    data = (await _trace(services, part_number="11426666661")).structured_content
    assert (data["status"], data["current_part_number"]) == ("not_found", None)
    assert (data["chain"], data["alternatives"], data["history"]) == ([], [], [])
    assert (data["complete"], data["warnings"]) == (True, [])
    assert data["source_urls"] == [missing]
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"part_number": "abc"}, "is not a BMW part number"),
        ({"part_number": "1142754182"}, "is not a BMW part number"),
        ({"part_number": "11427541827", "max_hops": 0}, "max_hops must be between 1 and 10"),
        ({"part_number": "11427541827", "max_hops": 11}, "max_hops must be between 1 and 10"),
    ],
)
async def test_invalid_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, object], message: str
) -> None:
    services, transport = make_services({})
    result = await _trace(services, **arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unexpected_page_structure_is_reported(make_services: MakeServices) -> None:
    services, _ = make_services({SUPERSEDED: Route(fixture=None)})  # empty 200 page
    result = await _trace(services, part_number="11427541827")
    assert result.is_error is True
    assert "did not have the expected structure" in result.content[0].text


async def test_unparseable_successor_page_is_not_kept_in_the_cache(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(
        {SUPERSEDED: REAL[SUPERSEDED], OIL_FILTER: Route(fixture=None)}  # empty 200 page
    )
    first = await _trace(services, part_number="11427541827")
    second = await _trace(services, part_number="11427541827")
    assert (first.is_error, second.is_error) == (True, True)
    # the predecessor comes from the cache; the broken successor page is fetched again
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER, OIL_FILTER]


# --- Synthetic pages -------------------------------------------------------------------------
# RealOEM has no captured example of these cases, so each test below edits a real fixture with
# plain string replacements and serves the result from tmp_path (pathlib: FIXTURES / <absolute
# path> is that absolute path). Every edit asserts that its "old" text is present.

SUPERSEDED_BLOCK = '<div class="superseded">'
SUPERSEDES_BLOCK = '<div class="supersedes">'
END_683196 = "(09/01/2016 — 09/21/2017)"  # 11428683196 in the 11427541827 page
END_953129 = "(06/01/2017 — )"  # 11427953129 in the 11427541827 page


def _synthetic(tmp_path: Path, fixture: str, *edits: tuple[str, str]) -> str:
    html = load_fixture(fixture)
    for old, new in edits:
        assert old in html, f"{fixture} no longer contains {old!r}"
        html = html.replace(old, new)
    path = tmp_path / Path(fixture).name
    path.write_text(html, encoding="utf-8")
    return str(path)


def _superseded_by(number: str, description: str, dates: str) -> str:
    """A one-entry "Superseded by" block in RealOEM's markup, inserted before "Supersedes"."""
    return (
        f'<div class="superseded"><h3>Superseded by:</h3><dl><dt class="sup-by-{{$t.count}}">'
        f'<a href="part?id=VB13-USA-10-2005-E90-BMW-325i&amp;q={number}">{number} - '
        f"{description}</a></dt><dd>{dates}, {RETRO}</dd></dl></div>{SUPERSEDES_BLOCK}"
    )


async def test_ended_without_successor(make_services: MakeServices, tmp_path: Path) -> None:
    # synthetic: 11427541827 (ENDED) with its "Superseded by" block renamed away
    page = _synthetic(
        tmp_path, "partxref/superseded_11427541827.html", (SUPERSEDED_BLOCK, '<div class="x">')
    )
    services, transport = make_services({SUPERSEDED: page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("no_successor", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["chain"][0]["valid_to"] == "2006-03-17"
    assert (data["alternatives"], data["history"]) == ([], [])
    assert (data["complete"], data["warnings"]) == (True, [])
    assert len(transport.requests) == 1


async def test_without_open_ended_successor_the_latest_end_is_followed(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 given an end date, so no successor of 11427541827 is open-ended
    page = _synthetic(
        tmp_path,
        "partxref/superseded_11427541827.html",
        (END_953129, "(06/01/2017 — 01/31/2025)"),
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: REAL[OIL_FILTER]})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


async def test_open_ended_predecessor_of_the_latest_successor_is_not_ambiguous(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11428683196 left open-ended; 11427953129 starts later and lists it as supersedes
    page = _synthetic(
        tmp_path, "partxref/superseded_11427541827.html", (END_683196, "(09/01/2016 — )")
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: REAL[OIL_FILTER]})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert data["alternatives"] == []
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


@pytest.mark.parametrize(
    ("max_hops", "requests", "chain", "warnings"),
    [
        (2, 3, ["11427541827", "11427953129", "12120037244"], []),
        (
            1,
            2,
            ["11427541827", "11427953129"],
            ["hop limit reached (max_hops=1): the page of successor 12120037244 was not read"],
        ),
    ],
)
async def test_hop_limit(
    make_services: MakeServices,
    tmp_path: Path,
    max_hops: int,
    requests: int,
    chain: list[str],
    warnings: list[str],
) -> None:
    # synthetic: 11427953129 "superseded by" 12120037244 (a real current page; only the numbers
    # matter), making a two-hop chain 11427541827 -> 11427953129 -> 12120037244
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        (SUPERSEDES_BLOCK, _superseded_by("12120037244", "Spark plug", "(01/01/2025 — )")),
    )
    services, transport = make_services({**REAL, OIL_FILTER: page})
    data = (await _trace(services, part_number="11427541827", max_hops=max_hops)).structured_content
    # at the limit the successor's number is reported but its page is not read
    assert (data["status"], data["current_part_number"]) == ("replaced", "12120037244")
    assert [hop["part_number"] for hop in data["chain"]] == chain
    assert (data["complete"], data["warnings"]) == (not warnings, warnings)
    assert data["requests_made"] == requests
    assert len(transport.requests) == requests


@pytest.mark.parametrize(
    ("end_953129", "current"),
    [(END_953129, "11427953129"), ("(06/01/2017 — 01/31/2025)", None)],
    ids=["open-ended-successor", "no-open-ended-successor"],
)
async def test_successor_without_a_page_ends_the_trace(
    make_services: MakeServices, tmp_path: Path, end_953129: str, current: str | None
) -> None:
    # synthetic routing: RealOEM answers "not found" for the chosen successor 11427953129;
    # synthetic page in the second case: 11427953129 given an end date in the 11427541827 page,
    # so the newest successor RealOEM names is not open-ended and no current part is known
    page = _synthetic(tmp_path, "partxref/superseded_11427541827.html", (END_953129, end_953129))
    services, _ = make_services(
        {SUPERSEDED: page, OIL_FILTER: "partxref/not_found_11426666661.html"}
    )
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", current)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["history"] == []
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert data["complete"] is False
    assert data["warnings"] == ["successor page missing: RealOEM has no page for 11427953129"]


async def test_successor_ended_without_successor(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 marked ENDED with no "Superseded by" block, one hop after 11427541827
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        ("<dd>-</dd>", "<dd>01/31/2025 (ENDED)</dd>"),
    )
    services, transport = make_services({SUPERSEDED: REAL[SUPERSEDED], OIL_FILTER: page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("no_successor", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827", "11427953129"]
    assert data["chain"][1]["valid_to"] == "2025-01-31"
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_supersession.py -q`
Expected: FAIL (`21 failed`: the server has no `trace_supersession` tool yet)

- [ ] **Step 3: Write the tool**

Replace the whole of `server/src/realoem_mcp/tools/supersession.py` with:

```python
"""trace_supersession tool (ARD section 5.11, feature E; site notes 3.5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.parts import PartXref, SupersessionEntry
from realoem_mcp.models.supersession import SupersessionHop, SupersessionResult
from realoem_mcp.parsers.part_numbers import normalize
from realoem_mcp.services import Services
from realoem_mcp.tools.parts import fetch_part_xref

MIN_HOPS, MAX_HOPS = 1, 10


def _day(value: date | None) -> date:
    return value or date.min


def choose_successor(entries: Sequence[SupersessionEntry]) -> SupersessionEntry:
    """The successor to follow from a non-empty "Superseded by" list.

    Lists are transitively closed and the open-ended entry is the current part (site notes 3.5),
    so open-ended entries win; among them the latest start. Without an open-ended entry, the
    latest end (then the latest start). Ties keep page order.
    """
    candidates = [e for e in entries if e.valid_to is None] or list(entries)
    return max(candidates, key=lambda e: (_day(e.valid_to), _day(e.valid_from)))


def _hop(xref: PartXref, remark: str | None) -> SupersessionHop:
    return SupersessionHop(
        part_number=xref.part_number,
        description=xref.description,
        valid_from=xref.valid_from,
        valid_to=xref.valid_to,
        remark=remark,
    )


async def trace_chain(
    services: Services, part_number: str, *, max_hops: int = 5, refresh: bool = False
) -> SupersessionResult:
    """Follow "Superseded by" links from part_number; one partxref request per part read.

    A hop is one successor page read, so at most 1 + max_hops requests. Raises InvalidInput
    before any request for a malformed part number or max_hops outside 1-10.
    """
    query = normalize(part_number)
    if not MIN_HOPS <= max_hops <= MAX_HOPS:
        raise InvalidInput(f"max_hops must be between {MIN_HOPS} and {MAX_HOPS}, not {max_hops}.")
    xref, page = await fetch_part_xref(services, query, refresh=refresh)
    pages: list[Page] = [page]
    if xref is None:
        return SupersessionResult.from_pages(
            pages,
            query=query,
            status="not_found",
            current_part_number=None,
            chain=[],
            alternatives=[],
            history=[],
            complete=True,
            warnings=[],
        )
    chain = [_hop(xref, None)]
    warnings: list[str] = []
    current: str | None = None
    while True:
        if not xref.superseded_by:
            if xref.ended:
                status = "no_successor"
            else:
                status = "current" if len(chain) == 1 else "replaced"
                current = xref.part_number
            break
        pick = choose_successor(xref.superseded_by)
        successor = None
        if len(chain) > max_hops:
            warnings.append(
                f"hop limit reached (max_hops={max_hops}): the page of successor "
                f"{pick.part_number} was not read"
            )
        else:
            successor, page = await fetch_part_xref(services, pick.part_number, refresh=refresh)
            pages.append(page)
            if successor is None:
                warnings.append(
                    f"successor page missing: RealOEM has no page for {pick.part_number}"
                )
        if successor is None:  # stopped early: hop limit or missing page
            status = "replaced"
            current = pick.part_number if pick.valid_to is None else None
            break
        chain.append(_hop(successor, pick.remark))
        xref = successor
    return SupersessionResult.from_pages(
        pages,
        query=query,
        status=status,
        current_part_number=current,
        chain=chain,
        alternatives=[],
        history=xref.supersedes,
        complete=not warnings,
        warnings=warnings,
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def trace_supersession(
        part_number: str, max_hops: int = 5, refresh: bool = False
    ) -> SupersessionResult:
        """Trace a BMW Group part number to the part that replaces it today.

        Use it when the user asks whether a part is current, what replaced it, or for its
        supersession history. part_number: 11 digits or the 7-digit short form; spaces, dashes
        and dots are fine. max_hops (1-10, default 5): how many successor pages may be read;
        one is usually enough because RealOEM lists every later number on each page.

        Returns status "current" (the part itself is current), "replaced" (current_part_number
        is the replacement), "no_successor" (ended, RealOEM names no replacement), "ambiguous"
        (several open-ended successors, or links that loop back; see alternatives) or
        "not_found". chain lists the parts whose pages were read, queried part first, with their
        dates and the remark of the link that led to each (e.g. "Exchangeable retrospectively").
        complete=false with warnings means the trace stopped early (hop limit, missing successor
        page, or a loop); current_part_number is then the newest successor RealOEM names, or null,
        unconfirmed by its own page. history is the "Supersedes" list of the
        last chain entry. Cite source_urls. One request per part read, none when cached;
        refresh=true fetches fresh copies.
        """
        try:
            return await trace_chain(services, part_number, max_hops=max_hops, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/tools/test_supersession.py tests/unit/test_choose_successor.py -q`
Expected: PASS (`26 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/supersession.py server/tests/tools/test_supersession.py
git commit -m "feat(supersession): add trace_supersession tool" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Ambiguous successors and loop guard

**Files:**
- Modify: `server/src/realoem_mcp/tools/supersession.py` (replace the whole file)
- Test: `server/tests/tools/test_supersession.py` (append)

- [ ] **Step 1: Write the failing tests**

Keep two blank lines between the file's current last line and the appended block.

Append to the end of `server/tests/tools/test_supersession.py`:

```python
# --- Ambiguity and loops ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("successor_page", "warnings"),
    [
        (REAL[OIL_FILTER], []),
        (
            "partxref/not_found_11426666661.html",
            ["successor page missing: RealOEM has no page for 11427953129"],
        ),
    ],
    ids=["successor-does-not-list-it", "successor-has-no-page"],
)
async def test_distinct_open_ended_successors_are_ambiguous(
    make_services: MakeServices, tmp_path: Path, successor_page: str, warnings: list[str]
) -> None:
    # synthetic: 11428683196 renamed to 11427000001 (unknown to 11427953129) and left open-ended
    page = _synthetic(
        tmp_path,
        "partxref/superseded_11427541827.html",
        ("11428683196", "11427000001"),
        (END_683196, "(09/01/2016 — )"),
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: successor_page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("ambiguous", None)
    assert _numbers(data["alternatives"]) == ["11427000001", "11427953129"]
    assert [a["valid_to"] for a in data["alternatives"]] == [None, None]
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["history"] == []
    # the latest successor's page was read to check whether it replaces the other one
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert (data["complete"], data["warnings"]) == (not warnings, warnings)
    assert len(transport.requests) == 2


async def test_links_looping_back_stop_the_trace(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 "superseded by" 11427541827, which points back to 11427953129
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        (SUPERSEDES_BLOCK, _superseded_by("11427541827", "Set oil-filter element", END_953129)),
    )
    services, transport = make_services({OIL_FILTER: page, SUPERSEDED: REAL[SUPERSEDED]})
    data = (await _trace(services, part_number="11427953129")).structured_content
    assert (data["status"], data["current_part_number"]) == ("ambiguous", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427953129", "11427541827"]
    assert _numbers(data["alternatives"]) == ["11427953129"]
    assert data["complete"] is False
    assert data["warnings"] == [
        "loop detected: 11427541827 is superseded by 11427953129, which is already in the chain"
    ]
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER, SUPERSEDED]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_supersession.py -q`
Expected: FAIL (`3 failed, 21 passed`: the two `test_distinct_open_ended_successors_are_ambiguous`
cases and `test_links_looping_back_stop_the_trace` get status `replaced`)

- [ ] **Step 3: Add the loop guard and the ambiguity rules**

Replace the whole of `server/src/realoem_mcp/tools/supersession.py` with:

```python
"""trace_supersession tool (ARD section 5.11, feature E; site notes 3.5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.parts import PartXref, SupersessionEntry
from realoem_mcp.models.supersession import SupersessionHop, SupersessionResult
from realoem_mcp.parsers.part_numbers import normalize
from realoem_mcp.services import Services
from realoem_mcp.tools.parts import fetch_part_xref

MIN_HOPS, MAX_HOPS = 1, 10


def _day(value: date | None) -> date:
    return value or date.min


def choose_successor(entries: Sequence[SupersessionEntry]) -> SupersessionEntry:
    """The successor to follow from a non-empty "Superseded by" list.

    Lists are transitively closed and the open-ended entry is the current part (site notes 3.5),
    so open-ended entries win; among them the latest start. Without an open-ended entry, the
    latest end (then the latest start). Ties keep page order.
    """
    candidates = [e for e in entries if e.valid_to is None] or list(entries)
    return max(candidates, key=lambda e: (_day(e.valid_to), _day(e.valid_from)))


def _hop(xref: PartXref, remark: str | None) -> SupersessionHop:
    return SupersessionHop(
        part_number=xref.part_number,
        description=xref.description,
        valid_from=xref.valid_from,
        valid_to=xref.valid_to,
        remark=remark,
    )


async def trace_chain(
    services: Services, part_number: str, *, max_hops: int = 5, refresh: bool = False
) -> SupersessionResult:
    """Follow "Superseded by" links from part_number; one partxref request per part read.

    A hop is one successor page read, so at most 1 + max_hops requests. Raises InvalidInput
    before any request for a malformed part number or max_hops outside 1-10.
    """
    query = normalize(part_number)
    if not MIN_HOPS <= max_hops <= MAX_HOPS:
        raise InvalidInput(f"max_hops must be between {MIN_HOPS} and {MAX_HOPS}, not {max_hops}.")
    xref, page = await fetch_part_xref(services, query, refresh=refresh)
    pages: list[Page] = [page]
    if xref is None:
        return SupersessionResult.from_pages(
            pages,
            query=query,
            status="not_found",
            current_part_number=None,
            chain=[],
            alternatives=[],
            history=[],
            complete=True,
            warnings=[],
        )
    chain = [_hop(xref, None)]
    visited = {xref.part_number}
    alternatives: list[SupersessionEntry] = []
    warnings: list[str] = []
    current: str | None = None
    while True:
        if not xref.superseded_by:
            if xref.ended:
                status = "no_successor"
            else:
                status = "current" if len(chain) == 1 else "replaced"
                current = xref.part_number
            break
        open_ended = [e for e in xref.superseded_by if e.valid_to is None]
        pick = choose_successor(xref.superseded_by)
        if pick.part_number in visited:  # RealOEM's links loop back into the chain
            status, alternatives = "ambiguous", open_ended or [pick]
            warnings.append(
                f"loop detected: {xref.part_number} is superseded by {pick.part_number}, "
                "which is already in the chain"
            )
            break
        successor = None
        if len(chain) > max_hops:
            warnings.append(
                f"hop limit reached (max_hops={max_hops}): the page of successor "
                f"{pick.part_number} was not read"
            )
        else:
            successor, page = await fetch_part_xref(services, pick.part_number, refresh=refresh)
            pages.append(page)
            if successor is None:
                warnings.append(
                    f"successor page missing: RealOEM has no page for {pick.part_number}"
                )
        if successor is None:  # stopped early: hop limit or missing page
            if len(open_ended) > 1:
                status, alternatives = "ambiguous", open_ended
            else:
                status = "replaced"
                current = pick.part_number if pick.valid_to is None else None
            break
        others = {e.part_number for e in open_ended} - {pick.part_number}
        if not others <= {e.part_number for e in successor.supersedes}:
            status, alternatives = "ambiguous", open_ended  # distinct open-ended successors
            break
        chain.append(_hop(successor, pick.remark))
        visited.add(successor.part_number)
        xref = successor
    return SupersessionResult.from_pages(
        pages,
        query=query,
        status=status,
        current_part_number=current,
        chain=chain,
        alternatives=alternatives,
        history=xref.supersedes,
        complete=not warnings,
        warnings=warnings,
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def trace_supersession(
        part_number: str, max_hops: int = 5, refresh: bool = False
    ) -> SupersessionResult:
        """Trace a BMW Group part number to the part that replaces it today.

        Use it when the user asks whether a part is current, what replaced it, or for its
        supersession history. part_number: 11 digits or the 7-digit short form; spaces, dashes
        and dots are fine. max_hops (1-10, default 5): how many successor pages may be read;
        one is usually enough because RealOEM lists every later number on each page.

        Returns status "current" (the part itself is current), "replaced" (current_part_number
        is the replacement), "no_successor" (ended, RealOEM names no replacement), "ambiguous"
        (several open-ended successors, or links that loop back; see alternatives) or
        "not_found". chain lists the parts whose pages were read, queried part first, with their
        dates and the remark of the link that led to each (e.g. "Exchangeable retrospectively").
        complete=false with warnings means the trace stopped early (hop limit, missing successor
        page, or a loop); current_part_number is then the newest successor RealOEM names, or null,
        unconfirmed by its own page. history is the "Supersedes" list of the
        last chain entry. Cite source_urls. One request per part read, none when cached;
        refresh=true fetches fresh copies.
        """
        try:
            return await trace_chain(services, part_number, max_hops=max_hops, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `uv run --directory server pytest -q`
Expected: PASS (`N + 41` passed, `D` deselected; `385 passed, 2 deselected` when `main` has only
foundation and part-lookup)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, `F + 6` files already formatted; `64` when `main` has
only foundation and part-lookup)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools/supersession.py server/tests/tools/test_supersession.py
git commit -m "feat(supersession): report ambiguous successors and supersession loops" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 3: Skill, live test, delivery

### Task 6: `supersession` skill

**Files:**
- Create: `skills/supersession/SKILL.md`
- Test: `server/tests/unit/test_skill_supersession.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_skill_supersession.py`:

```python
"""skills/supersession/SKILL.md: frontmatter and the rules the skill must state (ARD 5.12)."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "supersession" / "SKILL.md"


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
    assert fields["name"] == "supersession"
    description = fields["description"]
    assert len(description) <= 1024
    for trigger in ("part number", "current", "superseded", "replaced", "history"):
        assert trigger in description


def test_body_explains_statuses_and_rules() -> None:
    _, body = _split()
    for required in (
        "trace_supersession",
        "current_part_number",
        "complete",
        "warnings",
        "loop detected",
        "no_successor",
        "ambiguous",
        "alternatives",
        "history",
        "source_urls",
        "Exchangeable retrospectively",
        "also fits",
        "short-lived",
        "Motorsport",
        "page title",
    ):
        assert required in body, required
    assert "Never fetch realoem.com" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_skill_supersession.py -q`
Expected: FAIL (`2 failed`: `FileNotFoundError` for `skills/supersession/SKILL.md`)

- [ ] **Step 3: Write the skill**

Create `skills/supersession/SKILL.md`:

````markdown
---
name: supersession
description: Trace a BMW, MINI, Rolls-Royce or BMW Motorrad OEM part number to the part that replaces it today, with the supersession chain, dates and remarks. Use whenever the user asks whether a part number is current, discontinued, superseded or replaced, what the latest or replacement number is, or for a part's supersession history.
---

# Supersession chain

Answer "is this part current, and what replaced it?" with the `trace_supersession` tool of the
`realoem` MCP server. Never fetch realoem.com yourself (no WebFetch, no browser): every request must
go through the MCP tools, which rate-limit, cache and parse RealOEM for you.

## When to use

- "Is 11427541827 still current?", "What replaced 12120034087?", "What's the latest number for
  11 42 7 566 327?", "Show the supersession history of 11427953129."
- After `lookup_part` shows `superseded_by` entries and the user wants the replacement confirmed.
- Not for fitment on a specific car; use the fitment tools for that when they are available.

## Steps

1. Call `trace_supersession(part_number=...)` with the number as the user wrote it (11 digits or
   the last 7; spaces, dashes and dots are fine). Keep the default `max_hops=5`: RealOEM lists every
   later number on each page, so a trace usually reads one or two pages. If the tool says the input
   is not a BMW part number, ask the user to check it; do not guess digits.
2. Read `status`:
   - `current`: the part itself is current (not ENDED, no successor).
   - `replaced`: `current_part_number` is the replacement. Lead with it: "11427541827 was replaced
     by 11427953129."
   - `no_successor`: RealOEM marks the part ENDED and names no replacement. Say exactly that; do not
     call it "no longer available" or suggest a replacement yourself.
   - `ambiguous`: RealOEM names several open-ended successors, or (with a "loop detected"
     warning) links that loop back to a part already in `chain`. List every entry in
     `alternatives` with its dates and remark and say that RealOEM does not identify a single
     replacement; suggest confirming with a BMW parts counter.
   - `not_found`: RealOEM does not know this number; ask the user to double-check it.
3. Present `chain` in order (queried part first): part number, description, `valid_from` to
   `valid_to` (empty `valid_to` = still current), and the `remark` of each step.
4. Check `complete`. When it is false the trace stopped early and `warnings` says why: "hop
   limit reached", "successor page missing" or "loop detected". Tell the user the reason. For
   `current_part_number`, say "RealOEM names X as the successor" rather than "X is current",
   because its own page was not confirmed; if it is null, report the last chain entry, the successor
   named in the warning or in `alternatives`, and offer `lookup_part` on the last chain entry to
   list all its successors. After a hop-limit warning, offer to continue with a larger `max_hops`
   (up to 10); otherwise offer to check X with `lookup_part`.
5. `history` is the "Supersedes" list of the last chain entry: every earlier number RealOEM knows,
   with dates. Mention it when the user asks for the history, or to show that the numbers they
   hold are older versions of the current part.

## Explaining the results

- "Exchangeable retrospectively" (the only remark RealOEM shows) means the newer part also fits
  the older vehicles, so it can replace the old number on those cars.
- RealOEM's lists are complete in both directions: an ended part lists all its successors and the
  current part lists all its predecessors. That is why the trace jumps straight to the open-ended
  successor instead of visiting every number.
- Intermediate numbers can be short-lived or limited to special applications (for example
  11428683196, valid 09/2016 to 09/2017 and listed for Motorsport vehicles). Do not recommend an
  intermediate number when an open-ended successor exists.
- `in_catalog=false` on a `history` or `alternatives` entry means RealOEM no longer shows that
  number in any vehicle catalog; it is not proof that the part cannot be bought.

## Rules

- Always cite RealOEM: include the `source_urls` of every result you used.
- Never call a part discontinued because of a page title or a description; only `status`,
  `chain` and the dates count.
- If a tool reports that a RealOEM page "did not have the expected structure", retry once with
  `refresh=true`; if it fails again, tell the user the plugin needs an update and give the URL.
- Call tools only for what the user asked. Results are cached; pass `refresh=true` only when the
  user asks for fresh data.
- Brand notes are in `brands/<brand>/README.md` of this plugin.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_skill_supersession.py -q`
Expected: PASS (`2 passed`)

- [ ] **Step 5: Commit**

```bash
git add skills/supersession/SKILL.md server/tests/unit/test_skill_supersession.py
git commit -m "docs(skills): add supersession skill" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Opt-in live smoke test

ARD §8: live tests carry `@pytest.mark.live`, are deselected by default and skipped unless
`REALOEM_LIVE=1`. This one traces 11427541827 (2 requests today; at most 3 if RealOEM adds a
successor). Do **not** run it with `REALOEM_LIVE=1` while implementing; CI never runs it.

**Files:**
- Test: `server/tests/live/test_supersession_live.py`

- [ ] **Step 1: Write the test**

Create `server/tests/live/test_supersession_live.py`:

```python
"""Opt-in live smoke test (2 requests).

Run: REALOEM_LIVE=1 uv run pytest -m live tests/live/test_supersession_live.py
"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_trace_supersession_against_realoem(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            result = await client.call_tool("trace_supersession", {"part_number": "11427541827"})
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert (data["status"], data["complete"], data["warnings"]) == ("replaced", True, [])
    assert data["chain"][0]["part_number"] == "11427541827"
    assert data["current_part_number"] == data["chain"][-1]["part_number"]
    assert "11427541827" in [entry["part_number"] for entry in data["history"]]
    assert data["requests_made"] <= 3
```

- [ ] **Step 2: Verify it is deselected by default**

Run: `uv run --directory server pytest tests/live/test_supersession_live.py -q; echo "exit=$?"`
Expected: PASS (`1 deselected`, `exit=5`: pytest exits with 5 when every collected test is
deselected)

- [ ] **Step 3: Verify it is skipped without `REALOEM_LIVE=1`**

Run: `uv run --directory server pytest tests/live/test_supersession_live.py -q -m live`
Expected: PASS (`1 skipped`)

- [ ] **Step 4: Lint**

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, `F + 8` files already formatted; `66` when `main` has
only foundation and part-lookup)

- [ ] **Step 5: Commit**

```bash
git add server/tests/live/test_supersession_live.py
git commit -m "test(live): add opt-in supersession smoke test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: `N + 43` passed, `D + 1` deselected, `All checks passed!`, `F + 8` files already
formatted (`387 passed, 3 deselected` and `66` when `main` has only foundation and part-lookup).

- [ ] **Step 2: Smoke-test the tool over stdio with the plugin's launch command**

This lists the tools and calls `trace_supersession` with an invalid `max_hops`, which is rejected
before any request, so nothing is sent to RealOEM.

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
        result = await client.call_tool(
            "trace_supersession", {"part_number": "11427541827", "max_hops": 0}
        )
        print("is_error:", result.is_error, result.content[0].text)


asyncio.run(main())
EOF
```

Expected: a sorted `tools:` list that includes `trace_supersession` (plus the tools from earlier
branches; with only foundation and part-lookup merged it is
`['cache_clear', 'lookup_part', 'server_status', 'trace_supersession']`) and
`is_error: True Error executing tool trace_supersession: max_hops must be between 1 and 10, not 0.`
(plus an `INFO mcp.server.mcpserver.server: Tool 'trace_supersession' failed: …` line from the
server's stderr log).

- [ ] **Step 3: Validate the plugin**

Run: `claude plugin validate . --strict`
Expected: `✔ Validation passed`. If `claude` is not on `PATH` (e.g. only the desktop app is
installed), use its bundled CLI, for example on Windows
`"$APPDATA/Claude/claude-code/<version>/claude.exe" plugin validate . --strict`, or skip this check
and note it in the PR.

- [ ] **Step 4: Confirm nothing raw or generated is staged and no other file changed**

Run: `git status --short && git diff --name-only main... | grep -vE '^(server/src/realoem_mcp/(models|tools)/supersession\.py|server/tests/(fixtures/supersession/spark_plug_pred_12120034087\.html|unit/parsers/test_supersession_fixtures\.py|unit/test_(models_supersession|choose_successor|skill_supersession)\.py|tools/test_supersession\.py|live/test_supersession_live\.py)|skills/supersession/SKILL\.md)$' || echo clean`
Expected: no `git status` output and `clean`.

- [ ] **Step 5: Push and open the pull request**

```bash
git push -u origin feat/supersession
gh pr create --base main --head feat/supersession --title "feat: supersession chain (trace_supersession)" --body "$(cat <<'EOF'
## Summary

Implements PRD F5 (feature E) per ARD §5.11:

- `trace_supersession(part_number, max_hops=5, refresh=False)`: follows RealOEM's "Superseded by" links with `fetch_part_xref` (one cached `partxref` request per part read). Because RealOEM's lists are transitively closed, it jumps straight to the open-ended successor, so a typical trace is one or two requests (11427541827 → 11427953129: 2).
- Statuses `current`, `replaced`, `no_successor`, `ambiguous` (distinct open-ended successors, or links that loop back), `not_found`; `chain` with each part's dates and the remark of the link that led to it; `alternatives`; `history` (the last part's "Supersedes" list).
- Loop guard (no page is read twice) and hop limit (`max_hops` 1–10, else rejected before any request). When the trace stops early (hop limit, missing successor page, loop) the result has `complete=false` and a specific warning; `current_part_number` is then the newest successor RealOEM names (or null).
- `supersession` skill; one new trimmed fixture (spark plug 12120034087, in `fixtures/supersession/` per ARD §8); synthetic cases are built in-test from real fixtures and labeled; opt-in live smoke test.
- No foundation or part-lookup file changed; no version bump.

## Test plan

- [x] `uv run pytest` (offline), `uv run ruff check`, `uv run ruff format --check`
- [x] stdio smoke test lists `trace_supersession` and rejects invalid input without a request
- [ ] `claude plugin validate . --strict` (tick only if Step 3 ran; otherwise replace this line with "skipped: claude CLI not available")
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
