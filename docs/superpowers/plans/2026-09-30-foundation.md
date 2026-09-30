# Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `feat/foundation` (PRD F0.1–F0.6): an installable Claude Code plugin whose local stdio MCP server (`realoem`) has a polite, cached RealOEM HTTP client, the brand registry, vehicle-id and parser helpers, the `server_status` and `cache_clear` tools, the offline test harness, fixture tooling and CI, so the feature branches A–E only add files.

**Architecture:** A uv-managed Python package `realoem-mcp` in `server/` (src layout) built on the official `mcp` 2.x SDK (`MCPServer`). All RealOEM traffic goes through one `RealOemClient` (one request in flight, ≥ 2 s spacing, honest User-Agent, only `Cookie: ro_ui=v2`, challenge detection, retries) backed by a SQLite page cache. Tools are discovered with `pkgutil` from `realoem_mcp.tools` and receive a `Services` container. Brand data lives in `brands/<id>/brand.toml`. Tests run offline against trimmed real pages served by a fixture transport. The ARD (`docs/ARD.md`) is the contract: names, signatures and module paths below follow it.

**Tech Stack:** Python ≥ 3.11, uv (uv_build backend), mcp 2.2, httpx 0.28, selectolax 0.4 (lexbor backend), pydantic 2, platformdirs, SQLite (stdlib); pytest + AnyIO plugin, ruff; GitHub Actions with `astral-sh/setup-uv`.

---

## Before you start

- **Preconditions:** `main` already contains the docs (`docs/PRD.md`, `docs/ARD.md`,
  `docs/research/realoem-site-notes.md` and every plan in `docs/superpowers/plans/`), `.gitignore`
  and `.gitattributes` (`* text=auto eol=lf`), and `git status` shows a clean working tree. If any of
  that is missing, stop and ask; this plan does not create them.
- Read `docs/ARD.md` §3–§8 once; this plan implements its foundation parts. Site facts are in
  `docs/research/realoem-site-notes.md`.
- Shell: Git Bash (Windows) or any POSIX shell. **Every command runs from the repository root.** Python
  commands use `uv run --directory server …`, which runs inside `server/` with the project's
  virtual environment; paths after it (like `tests/unit/test_config.py`) are relative to `server/`.
  `git` paths are relative to the repository root.
- uv: install from https://docs.astral.sh/uv/getting-started/installation/ if `uv --version` fails. uv
  downloads a matching Python if none is installed.
- mcp 2.x crash course: `MCPServer(name, instructions=..., version=...)` is the server;
  `@app.tool()` registers an `async def` whose pydantic return type becomes the tool's
  `structured_content`; raising `mcp.server.mcpserver.exceptions.ToolError("msg")` returns a result
  with `is_error=True` and text `Error executing tool <name>: msg`. Tests talk to a server in-process
  with `async with mcp.Client(app) as c: r = await c.call_tool("name", {...})`.
- Never make requests to realoem.com while implementing. The only live test is opt-in (Task 20).
- Raw captured pages live in the git-ignored `.research-raw/` folder of the main checkout. Never
  commit anything from it; commit only fixtures produced by `server/scripts/trim_fixture.py`.
- Commit messages are Conventional Commits and end with a blank line plus
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in each commit command
  produces exactly that).
- Versions stay `0.1.0` everywhere (`pyproject.toml`, `__version__`, `plugin.json`,
  `marketplace.json`); feature branches never bump them.

## File Structure

| Path | Responsibility |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest; declares MCP server `realoem` launched with `uv run --directory ${CLAUDE_PLUGIN_ROOT}/server realoem-mcp` |
| `.claude-plugin/marketplace.json` | Single-plugin marketplace `realoem-searcher` (owner Cadtastic, source `.`) |
| `.github/workflows/ci.yml` | ruff + offline pytest on ubuntu (3.11, 3.13) and windows (3.13) |
| `LICENSE` | MIT, Copyright (c) 2026 Cadtastic |
| `README.md` | What it is, install, requirements, politeness, configuration, dev commands |
| `brands/{bmw,mini,rolls-royce,motorrad}/brand.toml` | Brand registry data (ARD §5.7 table) |
| `brands/{bmw,mini,rolls-royce,motorrad}/README.md` | Short brand notes for skills |
| `server/pyproject.toml`, `server/uv.lock` | Project `realoem-mcp` 0.1.0, deps, console script, ruff + pytest config |
| `server/src/realoem_mcp/__init__.py` | `__version__` |
| `server/src/realoem_mcp/config.py` | `Settings` (frozen, env overrides, min-interval clamp, fixed UA and lang) |
| `server/src/realoem_mcp/errors.py` | `RealOemError` → `InvalidInput`, `NotFound`, `BotChallenge`, `LayoutChanged`, `UpstreamError` |
| `server/src/realoem_mcp/page_types.py` | `PageType` (values = URL paths) with default TTLs, `PageType.parse` |
| `server/src/realoem_mcp/http_client.py` | `Page`, `build_url`, `RealOemClient` (cache, lock, spacing, headers, cookie pinning, retries, challenge, X-RO-UI) |
| `server/src/realoem_mcp/cache.py` | `PageCache` (SQLite, WAL, `expires_at`, schema version), `CacheStats` |
| `server/src/realoem_mcp/vehicle_ids.py` | `VehicleId.parse` for the three id forms |
| `server/src/realoem_mcp/brands.py` | `Brand`, `BrandRegistry` (load, resolution rules) |
| `server/src/realoem_mcp/models/common.py` | `ResultMeta.from_pages`, `VehicleRef.from_id`, `DiagramRef.build` |
| `server/src/realoem_mcp/parsers/common.py` | `tree`, `text`, `require`, date/price parsers, `canonical_url`, `json_ld` |
| `server/src/realoem_mcp/services.py` | `Services` container (+ `extras`) and `create_services` |
| `server/src/realoem_mcp/tools/admin.py` | `server_status`, `cache_clear` tools |
| `server/src/realoem_mcp/server.py` | `build_server(services)` with tool auto-discovery; `main()` on stdio, logs to stderr |
| `server/scripts/trim_fixture.py` | Raw page → trimmed fixture (ARD §8 rules) |
| `server/scripts/capture_page.py` | Polite single-page capture (raw HTML + headers) into `.research-raw/<page-type>/` |
| `server/tests/harness.py` | `load_fixture`, `Route`, `FixtureTransport`, `url`, `LANDING_URL`, `FakeClock` |
| `server/tests/conftest.py` | `anyio_backend`, `make_services`, live-test skipping |
| `server/tests/fixtures/common/*.html` | Trimmed Cloudflare challenge and E90 partgrp pages |
| `server/tests/unit/…`, `server/tests/tools/…`, `server/tests/live/…` | Unit, tool (in-memory MCP client) and opt-in live tests |

Decisions this plan makes where the ARD leaves room (feature plans may rely on them):

- `build_url(settings, path, params)` is also a module-level function in `http_client.py`
  (`RealOemClient.build_url` delegates to it; the harness `url()` uses it). `path` must match
  `[a-z]+`.
- `FixtureTransport` normalizes route keys and request URLs with `str(httpx.URL(...))`, so a key
  written by hand (`?model=R 1250`) or built with `url()` matches what httpx sends.
- An unmatched request gets HTTP 404, which the client does not retry and turns into
  `UpstreamError(404)`; `transport.unmatched` lists that URL once, and the `make_services` teardown
  fails the test.
- Redirects are followed at most 3 times (`max_redirects=3`) and only within the base URL's
  scheme + host + port; any other target (another host, or an https → http downgrade) raises
  `UpstreamError` before that request is sent. Every hop, including redirects and retries, is
  origin-checked, rate limited, counted and logged by the client's httpx request/response hooks.
- `RealOemClient.requests_made` counts every HTTP request actually sent (retries, redirect hops,
  failures and challenges included). `ResultMeta.requests_made` is unchanged: pages a tool call
  fetched from the network.
- `build_url` raises `ValueError` for a `dmode` parameter in any letter case (AD7: never sent).
- Non-200 responses that are not challenges, retryable statuses or redirects-away raise
  `UpstreamError(status, url)`. Any other `httpx.RequestError` (network, decoding, too many
  redirects) raises `UpstreamError(None, url, <exception name>)` without retry; only timeouts retry.
- `Settings` rejects non-finite `min_interval_s` / `timeout_s` (`nan`, `inf`), and a non-finite
  `Retry-After` falls back to the default 5 s / 15 s backoff.
- `trim_fixture.py` keeps only the `class` and `data-ecs-part-name` attributes of
  `a.ecs-tuning-button` (the affiliate `href` and other attributes are dropped), and masks VINs that
  stand alone or follow any percent-encoded character (`%3d`, `%2F`, ...). Test data uses the
  synthetic VIN `WBATEST0000000001`; never put a real VIN in code, tests, fixtures or docs.
- `CacheStats.bytes` is the total UTF-8 size of cached HTML. `json_ld` returns a list of matching
  objects. `Brand` list fields are tuples; `Brand.extra` is excluded from hashing and equality, so
  brands are hashable.
- Foundation fixtures live in `tests/fixtures/common/` so feature branches never touch them.

## Chunk 1: Project scaffold, settings, errors, page types

### Task 0: Branch

- [ ] **Step 1: Start from an up-to-date `main`**

`main` contains only `docs/` (PRD, ARD, site notes, all plans), `.gitignore` and `.gitattributes`
at this point (see Preconditions). Check the tree is clean first:

Run: `git status --short`
Expected: no output.

```bash
git checkout main
if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then git pull --ff-only origin main; fi
git checkout -b feat/foundation
```

Expected: `Switched to a new branch 'feat/foundation'`.

### Task 1: uv project skeleton

The server is a uv project in `server/` with a src layout. pytest runs with `pythonpath = ["."]`
(so tests import `tests.harness` and `scripts.*`), `--import-mode=importlib` (test files in different
folders may share a name) and `-m "not live"` by default.

**Files:**
- Create: `server/pyproject.toml`, `server/src/realoem_mcp/__init__.py`, `server/tests/__init__.py`, `server/tests/conftest.py`, `server/uv.lock` (generated)
- Test: `server/tests/unit/test_package.py`

- [ ] **Step 1: Write the failing test**

Create `server/pyproject.toml`:

```toml
[project]
name = "realoem-mcp"
version = "0.1.0"
description = "MCP server for looking up BMW Group OEM parts on RealOEM.com"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "httpx>=0.28,<1",
    "mcp>=2.2,<3",
    "platformdirs>=4",
    "pydantic>=2.11,<3",
    "selectolax>=0.4,<0.5",
]

[project.scripts]
realoem-mcp = "realoem_mcp.server:main"

[dependency-groups]
dev = [
    "anyio>=4",
    "pytest>=8",
    "ruff>=0.14",
]

[build-system]
requires = ["uv_build>=0.11.13,<0.12.0"]
build-backend = "uv_build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = ["-m", "not live", "--import-mode=importlib"]
markers = [
    "live: sends real requests to www.realoem.com; opt-in with REALOEM_LIVE=1 and -m live",
]
```

Create empty file `server/tests/__init__.py`.

Create `server/tests/conftest.py` (Task 16 extends it):

```python
"""Shared pytest fixtures. Helpers to import live in tests/harness.py (ARD section 8)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.live tests unless REALOEM_LIVE=1."""
    if os.environ.get("REALOEM_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set REALOEM_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
```

Create `server/tests/unit/test_package.py`:

```python
from realoem_mcp import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv sync --directory server`
Expected: FAIL with `Expected a Python module at` (the package does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/__init__.py`:

```python
"""RealOEM MCP server: polite, cached access to RealOEM.com for Claude."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv sync --directory server`
Expected: PASS; resolves the dependencies, writes `server/uv.lock` and installs `realoem-mcp==0.1.0`.

Run: `uv run --directory server pytest -q`
Expected: PASS (`1 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`, `4 files already formatted`)

- [ ] **Step 5: Commit**

```bash
git add server/pyproject.toml server/uv.lock server/src/realoem_mcp/__init__.py server/tests/__init__.py server/tests/conftest.py server/tests/unit/test_package.py
git commit -m "build(server): scaffold realoem-mcp uv project" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Settings (`config.py`)

ARD §5.2. `lang` and `user_agent` are `init=False` fields, so neither the environment nor a caller can
change them (AD12, AD13). `min_interval_s` is clamped to ≥ 1.0 even when set directly. `nan` and
`inf` are rejected (a `nan` interval would silently disable spacing; `inf` would hang), both from the
environment (the error names the variable) and when constructing `Settings` directly.

**Files:**
- Create: `server/src/realoem_mcp/config.py`
- Test: `server/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_config.py`:

```python
from pathlib import Path

import pytest

from realoem_mcp import __version__
from realoem_mcp.config import DEFAULT_BRANDS_DIR, USER_AGENT, Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.base_url == "https://www.realoem.com"
    assert settings.lang == "enUS"
    assert settings.min_interval_s == 2.0
    assert settings.timeout_s == 20.0
    assert settings.cache_dir.name  # platformdirs user cache dir
    assert settings.data_dir.name  # platformdirs user data dir
    assert settings.data_dir != settings.cache_dir
    assert settings.brands_dir == DEFAULT_BRANDS_DIR
    assert (DEFAULT_BRANDS_DIR.parent / "server" / "pyproject.toml").exists()


def test_user_agent_is_honest_and_versioned() -> None:
    expected = f"RealOEM-Searcher/{__version__} (+https://github.com/Cadtastic/RealOEM-Searcher)"
    assert expected == USER_AGENT
    assert Settings().user_agent == USER_AGENT


def test_from_env_overrides(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "REALOEM_BASE_URL": "http://localhost:8080/",
            "REALOEM_MIN_INTERVAL": "3.5",
            "REALOEM_TIMEOUT": "7",
            "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
            "REALOEM_DATA_DIR": str(tmp_path / "data"),
            "REALOEM_BRANDS_DIR": str(tmp_path / "brands"),
        }
    )
    assert settings.base_url == "http://localhost:8080"
    assert settings.min_interval_s == 3.5
    assert settings.timeout_s == 7.0
    assert settings.cache_dir == tmp_path / "cache"
    assert settings.data_dir == tmp_path / "data"
    assert settings.brands_dir == tmp_path / "brands"


def test_min_interval_is_clamped_to_one_second() -> None:
    assert Settings.from_env({"REALOEM_MIN_INTERVAL": "0.1"}).min_interval_s == 1.0
    assert Settings(min_interval_s=0).min_interval_s == 1.0


def test_user_agent_and_lang_cannot_be_overridden() -> None:
    settings = Settings.from_env({"REALOEM_USER_AGENT": "Mozilla/5.0", "REALOEM_LANG": "de"})
    assert settings.user_agent == USER_AGENT
    assert settings.lang == "enUS"
    with pytest.raises(TypeError):
        Settings(user_agent="Mozilla/5.0")  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["soon", "nan", "inf", "-inf"])
@pytest.mark.parametrize("name", ["REALOEM_MIN_INTERVAL", "REALOEM_TIMEOUT"])
def test_bad_number_names_the_variable(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


@pytest.mark.parametrize("field", ["min_interval_s", "timeout_s"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_values_are_rejected_directly(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        Settings(**{field: value})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.config'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/config.py`:

```python
"""Runtime settings. Every field except lang and user_agent can be overridden by environment."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from realoem_mcp import __version__

REPO_URL = "https://github.com/Cadtastic/RealOEM-Searcher"
USER_AGENT = f"RealOEM-Searcher/{__version__} (+{REPO_URL})"
MIN_INTERVAL_FLOOR_S = 1.0
# src/realoem_mcp/config.py -> parents[3] is the repository root that holds brands/.
DEFAULT_BRANDS_DIR = Path(__file__).resolve().parents[3] / "brands"


def _default_cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir("realoem-searcher"))


def _default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir("realoem-searcher"))


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://www.realoem.com"
    min_interval_s: float = 2.0
    timeout_s: float = 20.0
    cache_dir: Path = field(default_factory=_default_cache_dir)
    data_dir: Path = field(default_factory=_default_data_dir)  # durable data (vehicle index)
    brands_dir: Path = DEFAULT_BRANDS_DIR
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

    def __post_init__(self) -> None:
        for name in ("min_interval_s", "timeout_s"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number, got {getattr(self, name)!r}")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(
            self, "min_interval_s", max(float(self.min_interval_s), MIN_INTERVAL_FLOOR_S)
        )
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        object.__setattr__(self, "cache_dir", Path(self.cache_dir))
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "brands_dir", Path(self.brands_dir))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        kwargs: dict[str, object] = {}
        if value := env.get("REALOEM_BASE_URL"):
            kwargs["base_url"] = value
        if value := env.get("REALOEM_MIN_INTERVAL"):
            kwargs["min_interval_s"] = _to_float("REALOEM_MIN_INTERVAL", value)
        if value := env.get("REALOEM_TIMEOUT"):
            kwargs["timeout_s"] = _to_float("REALOEM_TIMEOUT", value)
        if value := env.get("REALOEM_CACHE_DIR"):
            kwargs["cache_dir"] = Path(value)
        if value := env.get("REALOEM_DATA_DIR"):
            kwargs["data_dir"] = Path(value)
        if value := env.get("REALOEM_BRANDS_DIR"):
            kwargs["brands_dir"] = Path(value)
        return cls(**kwargs)  # type: ignore[arg-type]


def _to_float(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of seconds, got {value!r}")
    return number
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_config.py -q`
Expected: PASS (`17 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/config.py server/tests/unit/test_config.py
git commit -m "feat(server): add env-overridable Settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Error hierarchy (`errors.py`)

ARD §5.3. `.message` is the user-facing text (NFR8); tools turn it into a `ToolError`.

**Files:**
- Create: `server/src/realoem_mcp/errors.py`
- Test: `server/tests/unit/test_errors.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_errors.py`:

```python
from realoem_mcp.errors import (
    BotChallenge,
    InvalidInput,
    LayoutChanged,
    NotFound,
    RealOemError,
    UpstreamError,
)


def test_hierarchy() -> None:
    for cls in (InvalidInput, NotFound, BotChallenge, LayoutChanged, UpstreamError):
        assert issubclass(cls, RealOemError)


def test_message_is_user_facing() -> None:
    err = InvalidInput("Part numbers have 7 or 11 digits.")
    assert err.message == "Part numbers have 7 or 11 digits."
    assert str(err) == err.message


def test_bot_challenge_names_the_url() -> None:
    err = BotChallenge("https://www.realoem.com/bmw/enUS/partxref?q=11427953129")
    assert err.url.endswith("q=11427953129")
    assert "bot challenge" in err.message
    assert "open https://www.realoem.com/bmw/enUS/partxref?q=11427953129 in a browser" in (
        err.message
    )


def test_layout_changed_fields() -> None:
    err = LayoutChanged("partxref", "missing 'div.content > h1'", "https://x/partxref?q=1")
    assert (err.page_type, err.detail, err.url) == (
        "partxref",
        "missing 'div.content > h1'",
        "https://x/partxref?q=1",
    )
    assert "partxref" in err.message
    assert "missing 'div.content > h1'" in err.message


def test_upstream_error_status_or_detail() -> None:
    assert "HTTP 503" in UpstreamError(503, "https://x/a").message
    timeout = UpstreamError(None, "https://x/a", "timed out")
    assert timeout.status is None
    assert "timed out" in timeout.message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_errors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.errors'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/errors.py`:

```python
"""Error hierarchy. `.message` is written for the end user (NFR8)."""

from __future__ import annotations


class RealOemError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInput(RealOemError):
    """Input rejected before any request was made."""


class NotFound(RealOemError):
    """RealOEM has no such part, vehicle or VIN."""


class BotChallenge(RealOemError):
    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            "RealOEM is showing a bot challenge (Cloudflare) and is blocking automated requests. "
            f"Try again later, or open {url} in a browser."
        )


class LayoutChanged(RealOemError):
    def __init__(self, page_type: str, detail: str, url: str) -> None:
        self.page_type = str(page_type)
        self.detail = detail
        self.url = url
        super().__init__(
            f"RealOEM's {self.page_type} page did not have the expected structure ({detail}). "
            f"The site may have changed; this plugin needs an update. Page: {url}"
        )


class UpstreamError(RealOemError):
    def __init__(self, status: int | None, url: str, detail: str | None = None) -> None:
        self.status = status
        self.url = url
        reason = f"HTTP {status}" if status is not None else (detail or "a network error")
        super().__init__(f"RealOEM request failed ({reason}) for {url}. Try again later.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_errors.py -q`
Expected: PASS (`5 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/errors.py server/tests/unit/test_errors.py
git commit -m "feat(server): add RealOemError hierarchy" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Page types and TTLs (`page_types.py`)

ARD §5.4. Values are the URL path strings, which is also what `cache_clear(page_type=...)` accepts.
`VEHICLES` (vehicles index, 1 day) is included for a later branch.

**Files:**
- Create: `server/src/realoem_mcp/page_types.py`
- Test: `server/tests/unit/test_page_types.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_page_types.py`:

```python
from datetime import timedelta

import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.page_types import PageType


def test_values_are_path_strings() -> None:
    assert [p.value for p in PageType] == [
        "select",
        "production",
        "partgrp",
        "showparts",
        "partxref",
        "partsearch",
        "part",
        "vehicles",
    ]


@pytest.mark.parametrize(
    ("page_type", "days"),
    [
        (PageType.SELECT, 30),
        (PageType.PRODUCTION, 180),
        (PageType.PARTGRP, 30),
        (PageType.SHOWPARTS, 30),
        (PageType.PARTXREF, 7),
        (PageType.PARTSEARCH, 7),
        (PageType.PART, 7),
        (PageType.VEHICLES, 1),
    ],
)
def test_default_ttls(page_type: PageType, days: int) -> None:
    assert page_type.ttl == timedelta(days=days)


def test_parse_accepts_values_and_rejects_others() -> None:
    assert PageType.parse("partxref") is PageType.PARTXREF
    with pytest.raises(InvalidInput, match="use one of: select, production"):
        PageType.parse("vin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_page_types.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.page_types'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/page_types.py`:

```python
"""RealOEM page types. Values are the URL path segments; each type has a default cache TTL."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from realoem_mcp.errors import InvalidInput


class PageType(StrEnum):
    SELECT = "select"
    PRODUCTION = "production"
    PARTGRP = "partgrp"
    SHOWPARTS = "showparts"
    PARTXREF = "partxref"
    PARTSEARCH = "partsearch"
    PART = "part"
    VEHICLES = "vehicles"

    @property
    def ttl(self) -> timedelta:
        return DEFAULT_TTLS[self]

    @classmethod
    def parse(cls, value: str) -> PageType:
        try:
            return cls(value)
        except ValueError:
            allowed = ", ".join(member.value for member in cls)
            raise InvalidInput(f"Unknown page type {value!r}; use one of: {allowed}.") from None


DEFAULT_TTLS: dict[PageType, timedelta] = {
    PageType.SELECT: timedelta(days=30),
    PageType.PRODUCTION: timedelta(days=180),
    PageType.PARTGRP: timedelta(days=30),
    PageType.SHOWPARTS: timedelta(days=30),
    PageType.PARTXREF: timedelta(days=7),
    PageType.PARTSEARCH: timedelta(days=7),
    PageType.PART: timedelta(days=7),
    PageType.VEHICLES: timedelta(days=1),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_page_types.py -q`
Expected: PASS (`10 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/page_types.py server/tests/unit/test_page_types.py
git commit -m "feat(server): add PageType enum with cache TTLs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 2: Fixture tooling

### Task 5: `trim_fixture.py`

ARD §8 trimming rules: drop `<script>` except JSON-LD and the `partsimgmap` script; drop `<style>`,
`<link>` except canonical, `<iframe>`, `<ins>`, comments and ad containers (`[id^="realoem-com_"]`);
keep `a.ecs-tuning-button[data-ecs-part-name]` with only its `class` and `data-ecs-part-name`
attributes (the affiliate `href` goes) and empty it; mask 17-character
VINs to `XXXXXXXXXX` + last 7, also right after any percent-encoded character (links such as
`vin%3dWBA…`). Tests use the synthetic VIN `WBATEST0000000001` (masked `XXXXXXXXXX0000001`). Whitespace-only
lines are collapsed, and the output is idempotent (`trim(trim(x)) == trim(x)`), which Task 6 relies on
to verify committed fixtures.

**Files:**
- Create: `server/scripts/__init__.py`, `server/scripts/trim_fixture.py`
- Test: `server/tests/unit/test_trim_fixture.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_trim_fixture.py`:

```python
from pathlib import Path

from scripts.trim_fixture import main, mask_vins, trim

RAW = """<!DOCTYPE html>
<html><head>
<!-- tracking tag -->
<script>window.ads = 1;</script>
<script src="/cdn-cgi/challenge-platform/main.js"></script>
<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>
<link rel="stylesheet" href="/bmw/css/common.css">
<link rel="alternate" hreflang="de" href="https://www.realoem.com/bmw/de/partgrp">
<link rel="canonical" href="https://www.realoem.com/bmw/enUS/partgrp?id=VB13">
<style>body { color: red }</style>
<title>Parts</title>
</head><body>
<div id="realoem-com_leaderboard_atf"><div>ad</div></div>
<iframe src="https://ads.example/"></iframe>
<ins class="adsbygoogle"></ins>
<div class="content"><h1>11427953129</h1>
<a class="ecs-tuning-button" data-ecs-part-number="11427953129"
   data-ecs-part-name="Set oil-filter element" href="https://click.example/">
   Shop this part <span>at ECS</span></a>
<p>VIN WBATEST0000000001 and serial 0000001</p>
<a href="/login?next=%2fselect%3fvin%3dWBATEST0000000001">Sign In</a>
<a href="/share?u=%2fvin%2FWBATEST0000000001">Share</a>
</div>
<div id="partsimg"><script>var partsimgmap=[["01",78,255,87,271]];</script></div>
</body></html>
"""


def test_removes_scripts_except_json_ld_and_partsimgmap() -> None:
    out = trim(RAW)
    assert "window.ads" not in out
    assert "challenge-platform" not in out
    assert '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>' in out
    assert 'var partsimgmap=[["01",78,255,87,271]];' in out


def test_removes_chrome_but_keeps_canonical_link() -> None:
    out = trim(RAW)
    for gone in ("<style", "<iframe", "<ins", "tracking tag", "realoem-com_", "stylesheet"):
        assert gone not in out
    assert 'hreflang="de"' not in out
    assert '<link rel="canonical" href="https://www.realoem.com/bmw/enUS/partgrp?id=VB13">' in out
    assert "<h1>11427953129</h1>" in out


def test_keeps_only_ecs_class_and_part_name_and_empties_the_button() -> None:
    out = trim(RAW)
    assert '<a class="ecs-tuning-button" data-ecs-part-name="Set oil-filter element"></a>' in out
    assert "click.example" not in out
    assert "data-ecs-part-number" not in out
    assert "Shop this part" not in out
    assert "at ECS" not in out


def test_masks_full_vins_everywhere() -> None:
    out = trim(RAW)
    assert "WBATEST0000000001" not in out
    assert "VIN XXXXXXXXXX0000001 and serial 0000001" in out
    assert "vin%3dXXXXXXXXXX0000001" in out
    assert "vin%2FXXXXXXXXXX0000001" in out


def test_mask_vins_leaves_part_numbers_and_words_alone() -> None:
    text = "11427953129 ABCDEFGHJKLMNPRST 12345678901234567 WBATEST0000000001X"
    assert mask_vins(text) == text


def test_trim_is_idempotent() -> None:
    once = trim(RAW)
    assert trim(once) == once
    assert once.endswith("</html>\n")


def test_cli_writes_trimmed_file(tmp_path: Path) -> None:
    raw = tmp_path / "raw.html"
    raw.write_text(RAW, encoding="utf-8")
    out = tmp_path / "fixtures" / "partgrp" / "sample.html"
    assert main([str(raw), str(out)]) == 0
    assert out.read_text(encoding="utf-8") == trim(RAW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_trim_fixture.py -q`
Expected: FAIL with `ModuleNotFoundError` for `scripts.trim_fixture`

- [ ] **Step 3: Write minimal implementation**

Create empty file `server/scripts/__init__.py`.

Create `server/scripts/trim_fixture.py`:

```python
"""Turn a raw RealOEM capture into a small, committable test fixture (ARD section 8).

Usage (from server/):
    uv run python scripts/trim_fixture.py <raw.html> tests/fixtures/<page-type>/<slug>.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser, LexborNode

# Uppercase VIN alphabet (no I, O, Q) with at least one digit and one letter, standing alone or
# right after any percent-encoded character, as in next=%2fenUS%2fselect%3fvin%3dWBA...
_VIN = re.compile(
    r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2}))"
    r"(?=[A-HJ-NPR-Z0-9]{0,16}[0-9])(?=[A-HJ-NPR-Z0-9]{0,16}[A-HJ-NPR-Z])"
    r"[A-HJ-NPR-Z0-9]{17}"
    r"(?![A-Za-z0-9])"
)
_REMOVE = "style, iframe, ins, [id^='realoem-com_']"
_ECS_KEEP = ("class", "data-ecs-part-name")
_BLANK_LINES = re.compile(r"\n[ \t\r\n]*\n")


def mask_vins(html: str) -> str:
    """Replace every 17-character VIN with XXXXXXXXXX + its last 7 characters."""
    return _VIN.sub(lambda m: "XXXXXXXXXX" + m.group(0)[-7:], html)


def _keep_script(script: LexborNode) -> bool:
    if (script.attributes.get("type") or "").lower() == "application/ld+json":
        return True
    return "partsimgmap" in script.text(deep=True)


def _drop_trailing_whitespace(body: LexborNode | None) -> None:
    # Keeps trim() idempotent: a newline after </html> is re-parsed into <body>.
    while body is not None and body.last_child is not None:
        last = body.last_child
        if not last.is_text_node or last.text(deep=False).strip():
            return
        last.decompose()


def trim(html: str) -> str:
    tree = LexborHTMLParser(html)
    for node in tree.css("script"):
        if not _keep_script(node):
            node.decompose()
    for node in tree.css("link"):
        if (node.attributes.get("rel") or "").lower() != "canonical":
            node.decompose()
    for node in tree.css(_REMOVE):
        node.decompose()
    for node in [n for n in tree.root.traverse() if n.is_comment_node]:
        node.decompose()
    for button in tree.css("a.ecs-tuning-button[data-ecs-part-name]"):
        for child in list(button.iter(include_text=True)):
            child.decompose()
        for name in [n for n in button.attributes if n not in _ECS_KEEP]:
            del button.attrs[name]
    _drop_trailing_whitespace(tree.body)
    compact = _BLANK_LINES.sub("\n", tree.html or "")
    return mask_vins(compact).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trim a raw RealOEM page into a test fixture.")
    parser.add_argument("raw", type=Path, help="raw capture, e.g. ../.research-raw/xref/x.html")
    parser.add_argument("out", type=Path, help="fixture path under tests/fixtures/")
    args = parser.parse_args(argv)
    trimmed = trim(args.raw.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(trimmed, encoding="utf-8", newline="\n")
    before, after = args.raw.stat().st_size, len(trimmed.encode("utf-8"))
    print(f"{args.out}: {before} -> {after} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_trim_fixture.py -q`
Expected: PASS (`7 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/scripts/__init__.py server/scripts/trim_fixture.py server/tests/unit/test_trim_fixture.py
git commit -m "feat(scripts): add trim_fixture for committable test fixtures" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Foundation fixtures

Two trimmed real pages: the Cloudflare challenge that curl's default UA received
(`.research-raw/xref/default_curl_ua_xref.html`, served with HTTP 403 and `Cf-Mitigated: challenge`)
and the E90 325i main-groups page (`.research-raw/diagrams/05_partgrp_E90_325i_v2.html`, which has a
canonical link and five JSON-LD blocks). Tests assert every committed fixture is already trimmed and
contains no unmasked VIN-like string (17 characters of the VIN alphabet with a letter and a digit).

**Files:**
- Create: `server/tests/fixtures/common/cloudflare_challenge.html`, `server/tests/fixtures/common/partgrp_e90_325i.html` (generated)
- Test: `server/tests/unit/test_fixtures.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_fixtures.py`:

```python
"""Every committed fixture must be the output of scripts/trim_fixture.py (ARD AD10)."""

import re
from pathlib import Path

import pytest

from scripts.trim_fixture import trim

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ALL_FIXTURES = sorted(FIXTURES.rglob("*.html"))
MASKED_VIN = re.compile(r"X{10}[A-HJ-NPR-Z0-9]{7}")
VIN_LIKE = re.compile(
    r"(?=[A-HJ-NPR-Z0-9]{0,16}[0-9])(?=[A-HJ-NPR-Z0-9]{0,16}[A-HJ-NPR-Z])[A-HJ-NPR-Z0-9]{17}"
)


def test_fixture_folder_is_not_empty() -> None:
    assert ALL_FIXTURES, f"no fixtures under {FIXTURES}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_is_trimmed(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    assert trim(html) == html, f"re-run scripts/trim_fixture.py for {path.name}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_has_no_unmasked_vin(path: Path) -> None:
    html = MASKED_VIN.sub("", path.read_text(encoding="utf-8"))
    assert VIN_LIKE.findall(html) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q`
Expected: FAIL with `AssertionError: no fixtures under` (`1 failed, 2 skipped`)

- [ ] **Step 3: Generate the fixtures**

`.research-raw/` is git-ignored and exists only in the main checkout. `RAW` below resolves it from
either the main checkout or a git worktree:

```bash
RAW="$(git rev-parse --path-format=absolute --git-common-dir)/../.research-raw"
uv run --directory server python scripts/trim_fixture.py "$RAW/xref/default_curl_ua_xref.html" tests/fixtures/common/cloudflare_challenge.html
uv run --directory server python scripts/trim_fixture.py "$RAW/diagrams/05_partgrp_E90_325i_v2.html" tests/fixtures/common/partgrp_e90_325i.html
```

Expected (stderr): `…cloudflare_challenge.html: 5556 -> 1068 bytes` and
`…partgrp_e90_325i.html: 52821 -> 30325 bytes` (sizes may differ by a few bytes with line endings).
Open both files and check that no `<script>` remains except `application/ld+json` blocks.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_fixtures.py -q`
Expected: PASS (`5 passed`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/common/cloudflare_challenge.html server/tests/fixtures/common/partgrp_e90_325i.html server/tests/unit/test_fixtures.py
git commit -m "test(fixtures): add trimmed Cloudflare challenge and partgrp fixtures" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 3: Page, test harness, cache

### Task 7: `Page` and `build_url` (`http_client.py`, part 1)

ARD §5.5 rules 1 and 7. `build_url` keeps params in the given order and encodes with
`urlencode(..., quote_via=quote)` (spaces → `%20`, commas and parentheses encoded).
`Page.redirected_away` is true when the final URL's path no longer ends with the requested path
(e.g. the 301 to `/bmw/` for an invalid vehicle id). A `dmode` parameter is rejected with
`ValueError` (AD7: `dmode=0` switches diagram lists into a mode without diagIds).

**Files:**
- Create: `server/src/realoem_mcp/http_client.py`
- Test: `server/tests/unit/test_page.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_page.py`:

```python
from datetime import UTC, datetime

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.http_client import Page, build_url
from realoem_mcp.page_types import PageType


def test_build_url_keeps_param_order_and_encodes_with_percent_20() -> None:
    got = build_url(
        Settings(),
        "select",
        {"product": "M", "series": "K50", "model": "R 1250 GS 19 (0J91, 0J93)"},
    )
    assert got == (
        "https://www.realoem.com/bmw/enUS/select"
        "?product=M&series=K50&model=R%201250%20GS%2019%20%280J91%2C%200J93%29"
    )


def test_build_url_without_params_has_no_query() -> None:
    assert build_url(Settings(), "select", {}) == "https://www.realoem.com/bmw/enUS/select"


def test_build_url_uses_configured_base_url() -> None:
    got = build_url(Settings(base_url="http://127.0.0.1:9/"), "partxref", {"q": "11427953129"})
    assert got == "http://127.0.0.1:9/bmw/enUS/partxref?q=11427953129"


@pytest.mark.parametrize("path", ["", "../admin", "partxref?q=1", "PartXref", "a/b"])
def test_build_url_rejects_odd_paths(path: str) -> None:
    with pytest.raises(ValueError, match="invalid RealOEM path"):
        build_url(Settings(), path, {})


@pytest.mark.parametrize("key", ["dmode", "DMode"])
def test_build_url_never_sends_dmode(key: str) -> None:
    with pytest.raises(ValueError, match="dmode is never sent"):
        build_url(Settings(), "partgrp", {"id": "VB13-USA-10-2005-E90-BMW-325i", key: "0"})


def _page(url: str, final_url: str) -> Page:
    return Page(
        page_type=PageType.PARTGRP,
        url=url,
        final_url=final_url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=False,
    )


def test_redirected_away_detects_landing_page() -> None:
    requested = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13"
    assert _page(requested, "https://www.realoem.com/bmw/").redirected_away
    assert _page(requested, "https://www.realoem.com/bmw/enUS/").redirected_away


def test_same_page_is_not_redirected_away() -> None:
    requested = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"
    assert not _page(requested, requested).redirected_away
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_page.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.http_client'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/http_client.py` (Task 10 replaces it with the full client):

```python
"""The only way the server talks to RealOEM: rate limited, cached, honest (AD6, AD8, AD13, AD14)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode, urlsplit

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType

_PATH_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Page:
    page_type: PageType
    url: str  # canonical request URL (cache key)
    final_url: str  # after redirects
    status: int
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool

    @property
    def redirected_away(self) -> bool:
        """True when RealOEM redirected to another page (e.g. /bmw/ for an invalid id)."""
        requested = urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1]
        return not urlsplit(self.final_url).path.rstrip("/").endswith("/" + requested)


def build_url(settings: Settings, path: str, params: Mapping[str, str]) -> str:
    """`{base_url}/bmw/{lang}/{path}?{params}`, params in the order given, spaces as %20."""
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"invalid RealOEM path {path!r}")
    if any(key.lower() == "dmode" for key in params):
        raise ValueError("dmode is never sent to RealOEM (AD7)")
    url = f"{settings.base_url}/bmw/{settings.lang}/{path}"
    if params:
        url += "?" + urlencode(list(params.items()), quote_via=quote)
    return url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_page.py -q`
Expected: PASS (`12 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/http_client.py server/tests/unit/test_page.py
git commit -m "feat(server): add Page and build_url" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Test harness (`tests/harness.py`)

ARD §8. Tests import these helpers with `from tests.harness import ...`:

- `load_fixture(rel)` reads `tests/fixtures/<rel>`.
- `Route(fixture, status, headers, redirect_to)`: one canned response; a plain string route is a
  fixture path with status 200.
- `FixtureTransport(routes)`: keys are full URLs (use `url()`). Both keys and request URLs are
  normalized with `str(httpx.URL(...))`, so encoding differences cannot cause false misses. Every
  request is appended to `.requests`; a URL with no route is appended to `.unmatched` and answered
  with HTTP 404 (not retried by the client, so it is recorded once); a redirect target without its own route is answered with an empty HTTP 200, so
  `Route(redirect_to=LANDING_URL)` alone reproduces the invalid-vehicle-id case.
- `url(path, **params)` is `build_url` with default `Settings`.
- `FakeClock` is a monotonic clock whose `sleep` advances time instantly and records each wait.
- `MakeServices` is the type of the `make_services` fixture added in Task 16 (it names `Services`
  only under `TYPE_CHECKING`, so this file imports fine before `services.py` exists).

**Files:**
- Create: `server/tests/harness.py`
- Test: `server/tests/unit/test_harness.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_harness.py`:

```python
import httpx
import pytest

from tests.harness import (
    LANDING_URL,
    UNMATCHED_STATUS,
    FakeClock,
    FixtureTransport,
    Route,
    load_fixture,
    url,
)

pytestmark = pytest.mark.anyio


def test_url_matches_client_encoding() -> None:
    assert url("partxref", q="11427953129", series="E90") == (
        "https://www.realoem.com/bmw/enUS/partxref?q=11427953129&series=E90"
    )
    assert url("showparts", id="0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_") == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_"
    )


def test_load_fixture_reads_utf8_text() -> None:
    assert "<title>Just a moment...</title>" in load_fixture("common/cloudflare_challenge.html")


async def test_routes_serve_fixture_status_and_headers() -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport(
        {target: Route("common/cloudflare_challenge.html", 403, {"cf-mitigated": "challenge"})}
    )
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(target)
    assert response.status_code == 403
    assert response.headers["cf-mitigated"] == "challenge"
    assert "Just a moment..." in response.text
    assert [str(r.url) for r in transport.requests] == [target]
    assert transport.unmatched == []


async def test_string_route_is_a_fixture_path() -> None:
    target = url("partgrp", id="VB13-USA-10-2005-E90-BMW-325i")
    transport = FixtureTransport({target: "common/partgrp_e90_325i.html"})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(target)
    assert response.status_code == 200
    assert 'rel="canonical"' in response.text


async def test_redirect_to_unrouted_landing_is_empty_200() -> None:
    target = url("partgrp", id="VB13")
    transport = FixtureTransport({target: Route(redirect_to=LANDING_URL)})
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
        response = await http.get(target)
    assert response.status_code == 200
    assert str(response.url) == LANDING_URL
    assert response.text == ""
    assert [str(r.url) for r in transport.requests] == [target, LANDING_URL]
    assert transport.unmatched == []


async def test_unmatched_url_is_recorded_and_answered_with_404() -> None:
    transport = FixtureTransport({})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(url("part", q="1"))
    assert response.status_code == UNMATCHED_STATUS == 404
    assert transport.unmatched == [url("part", q="1")]


async def test_route_keys_are_normalized_like_httpx() -> None:
    # A hand-written key with unencoded characters still matches what httpx sends.
    transport = FixtureTransport({"https://www.realoem.com/bmw/enUS/select?model=R 1250": Route()})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(url("select", model="R 1250"))
    assert response.status_code == 200
    assert transport.unmatched == []


async def test_fake_clock_advances_on_sleep() -> None:
    clock = FakeClock(start=10.0)
    await clock.sleep(2.5)
    assert clock() == 12.5
    assert clock.sleeps == [2.5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_harness.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.harness'`

- [ ] **Step 3: Write minimal implementation**

Create `server/tests/harness.py`:

```python
"""Offline test harness: fixture loading, canned HTTP routes, fake clock (ARD section 8)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.http_client import build_url

if TYPE_CHECKING:
    from realoem_mcp.services import Services  # added in Task 16

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
BRANDS_DIR = REPO_ROOT / "brands"
LANDING_URL = "https://www.realoem.com/bmw/"  # redirect target for invalid vehicle ids
UNMATCHED_STATUS = 404  # not retried by the client, so each stray URL is recorded once

_URL_SETTINGS = Settings()


def load_fixture(rel: str) -> str:
    """Text of fixtures/<rel>, e.g. load_fixture("common/cloudflare_challenge.html")."""
    return (FIXTURES / rel).read_text(encoding="utf-8")


def url(path: str, **params: str) -> str:
    """The URL RealOemClient.build_url produces with default Settings (same encoding/order)."""
    return build_url(_URL_SETTINGS, path, params)


def _normalize(raw: str) -> str:
    # Both sides go through httpx.URL, so the comparison is immune to httpx re-encoding.
    return str(httpx.URL(raw))


@dataclass
class Route:
    """One canned response."""

    fixture: str | None = None  # path under fixtures/, or None for an empty body
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    redirect_to: str | None = None  # emits a 301 to this URL


class FixtureTransport(httpx.AsyncBaseTransport):
    """Serves routes keyed by full URL; records every request and every unmatched URL."""

    def __init__(self, routes: Mapping[str, Route | str]) -> None:
        self.routes: dict[str, Route] = {
            _normalize(key): Route(fixture=value) if isinstance(value, str) else value
            for key, value in routes.items()
        }
        self.redirect_targets = {
            _normalize(route.redirect_to) for route in self.routes.values() if route.redirect_to
        }
        self.requests: list[httpx.Request] = []
        self.unmatched: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = _normalize(str(request.url))
        route = self.routes.get(key)
        if route is None:
            if key in self.redirect_targets:
                return httpx.Response(200, content=b"", request=request)
            self.unmatched.append(key)
            return httpx.Response(
                UNMATCHED_STATUS, text=f"unexpected request: {key}", request=request
            )
        headers = dict(route.headers)
        if route.redirect_to is not None:
            headers["Location"] = route.redirect_to
            return httpx.Response(301, headers=headers, content=b"", request=request)
        body = load_fixture(route.fixture).encode("utf-8") if route.fixture else b""
        headers.setdefault("Content-Type", "text/html;charset=UTF-8")
        return httpx.Response(route.status, headers=headers, content=body, request=request)


class FakeClock:
    """Monotonic clock plus sleep that advances it instantly and records each wait."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# Type of the make_services fixture (tests/conftest.py).
MakeServices = Callable[[Mapping[str, Route | str]], tuple["Services", FixtureTransport]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_harness.py -q`
Expected: PASS (`8 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/harness.py server/tests/unit/test_harness.py
git commit -m "test: add offline fixture transport harness" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Page cache (`cache.py`)

ARD §5.6. One SQLite connection (`check_same_thread=False`, autocommit, WAL). `put` stores
`expires_at = fetched_at + ttl`; `get` returns only unexpired rows as `Page(from_cache=True)`;
`shorten` only ever lowers `expires_at`. Timestamps are fixed-width UTC ISO strings (microseconds
always present), so string comparison in SQL is correct. A missing or different `schema_version`
drops and recreates `pages`.

**Files:**
- Create: `server/src/realoem_mcp/cache.py`
- Test: `server/tests/unit/test_cache.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_cache.py`:

```python
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.cache import DB_FILENAME, SCHEMA_VERSION, PageCache
from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

XREF = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"
GRP = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"


def _page(url: str, page_type: PageType, *, age: timedelta = timedelta(0), html: str = "<p>ok</p>"):
    return Page(
        page_type=page_type,
        url=url,
        final_url=url,
        status=200,
        html=html,
        fetched_at=datetime.now(UTC) - age,
        from_cache=False,
    )


@pytest.fixture
def cache(tmp_path: Path):
    cache = PageCache(tmp_path / "cache")
    yield cache
    cache.close()


def test_creates_database_in_cache_dir(tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "nested" / "cache")
    try:
        assert cache.path == tmp_path / "nested" / "cache" / DB_FILENAME
        assert cache.path.exists()
    finally:
        cache.close()


def test_put_then_get_round_trips_as_cached(cache: PageCache) -> None:
    page = _page(XREF, PageType.PARTXREF)
    cache.put(page, timedelta(days=7))
    hit = cache.get(XREF)
    assert hit is not None
    assert hit.from_cache is True
    assert (hit.page_type, hit.url, hit.final_url, hit.status, hit.html) == (
        PageType.PARTXREF,
        XREF,
        XREF,
        200,
        "<p>ok</p>",
    )
    assert hit.fetched_at == page.fetched_at
    assert hit.fetched_at.tzinfo is not None


def test_miss_returns_none(cache: PageCache) -> None:
    assert cache.get(XREF) is None


def test_expired_entry_is_not_returned(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=8)), timedelta(days=7))
    assert cache.get(XREF) is None


def test_shorten_caps_lifetime(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=2)), timedelta(days=180))
    cache.shorten(XREF, timedelta(days=1))
    assert cache.get(XREF) is None


def test_shorten_never_extends_lifetime(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, age=timedelta(days=2)), timedelta(days=1))
    cache.shorten(XREF, timedelta(days=30))
    assert cache.get(XREF) is None


def test_shorten_unknown_url_is_a_no_op(cache: PageCache) -> None:
    cache.shorten(XREF, timedelta(days=1))
    assert cache.stats().entries == 0


def test_clear_all_and_by_page_type(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.put(_page(GRP, PageType.PARTGRP), timedelta(days=30))
    assert cache.clear(PageType.PARTGRP) == 1
    assert cache.get(GRP) is None
    assert cache.get(XREF) is not None
    assert cache.clear() == 1
    assert cache.stats().entries == 0


def test_stats_counts_entries_and_utf8_bytes(cache: PageCache) -> None:
    cache.put(_page(XREF, PageType.PARTXREF, html="ä"), timedelta(days=7))
    cache.put(_page(GRP, PageType.PARTGRP, html="abc"), timedelta(days=7))
    stats = cache.stats()
    assert (stats.entries, stats.bytes, stats.path) == (2, 5, cache.path)


def test_schema_version_mismatch_resets_tables(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.close()
    with closing(sqlite3.connect(tmp_path / DB_FILENAME)) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
        conn.commit()
    reopened = PageCache(tmp_path)
    try:
        assert reopened.stats().entries == 0
        with closing(sqlite3.connect(tmp_path / DB_FILENAME)) as conn:
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert version == (SCHEMA_VERSION,)
    finally:
        reopened.close()


def test_matching_schema_keeps_data(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF, PageType.PARTXREF), timedelta(days=7))
    cache.close()
    reopened = PageCache(tmp_path)
    try:
        assert reopened.get(XREF) is not None
    finally:
        reopened.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_cache.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.cache'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/cache.py`:

```python
"""SQLite cache of raw RealOEM pages, keyed by request URL (AD5)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

SCHEMA_VERSION = "1"
DB_FILENAME = "pages.sqlite3"

_CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, page_type TEXT NOT NULL, final_url TEXT NOT NULL, status INTEGER NOT NULL,
  html TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL)
"""
_CREATE_META = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _iso(value: datetime) -> str:
    # Fixed-width UTC timestamps compare correctly as strings.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int  # total UTF-8 size of the cached HTML
    path: Path


class PageCache:
    def __init__(self, cache_dir: Path) -> None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / DB_FILENAME
        # Autocommit; one connection used only from the event-loop thread.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(_CREATE_META)
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is not None and row[0] == SCHEMA_VERSION:
            self._conn.execute(_CREATE_PAGES)
            return
        self._conn.execute("DROP TABLE IF EXISTS pages")
        self._conn.execute(_CREATE_PAGES)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )

    def get(self, url: str) -> Page | None:
        row = self._conn.execute(
            "SELECT page_type, url, final_url, status, html, fetched_at FROM pages "
            "WHERE url = ? AND expires_at > ?",
            (url, _iso(datetime.now(UTC))),
        ).fetchone()
        if row is None:
            return None
        page_type, url, final_url, status, html, fetched_at = row
        return Page(
            page_type=PageType(page_type),
            url=url,
            final_url=final_url,
            status=status,
            html=html,
            fetched_at=datetime.fromisoformat(fetched_at),
            from_cache=True,
        )

    def put(self, page: Page, ttl: timedelta) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO pages "
            "(url, page_type, final_url, status, html, fetched_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                page.url,
                page.page_type.value,
                page.final_url,
                page.status,
                page.html,
                _iso(page.fetched_at),
                _iso(page.fetched_at + ttl),
            ),
        )

    def shorten(self, url: str, ttl: timedelta) -> None:
        """Cap an entry's lifetime at fetched_at + ttl (used for negative results)."""
        row = self._conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return
        capped = _iso(datetime.fromisoformat(row[0]) + ttl)
        if capped < row[1]:
            self._conn.execute("UPDATE pages SET expires_at = ? WHERE url = ?", (capped, url))

    def clear(self, page_type: PageType | None = None) -> int:
        if page_type is None:
            cursor = self._conn.execute("DELETE FROM pages")
        else:
            cursor = self._conn.execute(
                "DELETE FROM pages WHERE page_type = ?", (PageType(page_type).value,)
            )
        return cursor.rowcount

    def stats(self) -> CacheStats:
        entries, size = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(html AS BLOB))), 0) FROM pages"
        ).fetchone()
        return CacheStats(entries=entries, bytes=size, path=self.path)

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_cache.py -q`
Expected: PASS (`11 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/cache.py server/tests/unit/test_cache.py
git commit -m "feat(server): add SQLite PageCache" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 4: HTTP client

### Task 10: `RealOemClient` core

ARD §5.5 rules 1–3, 7, 8 and §7 observability:

- A cache hit is returned **without taking the lock**; otherwise the global `asyncio.Lock` is taken
  and the cache re-checked. Building the `Page` and writing the cache also happen inside the lock.
- Every request httpx sends, **including each redirect hop**, passes through the async request
  hook `_on_request`: it checks the target's scheme + host + port against the base URL, waits until
  `min_interval_s` has passed since the previous request **start** (injected `clock`/`sleep`), counts
  the request in `requests_made`, and stamps a start time; the response hook logs one INFO line per
  hop. `max_redirects=3` bounds redirect loops.
- Headers: honest `User-Agent`, `Accept: text/html`, `Accept-Language: en-US`, and exactly
  `Cookie: ro_ui=v2`. The cookie is set by a request hook, which httpx runs for every redirect hop
  too (httpx drops `Cookie` when redirecting), and the cookie jar has a policy that rejects every
  server cookie (AD14). A hop to another origin (another host, or https → http) surfaces as
  `UpstreamError` before it is sent (§7: only GET to the base URL).
- Only HTTP 200 pages are cached (default TTL from the page type, or `ttl=`). A redirect away is
  returned uncached; other statuses raise `UpstreamError`, and so does any `httpx.RequestError`
  (network error, undecodable body, too many redirects), named in the message.
- Log lines go to the `realoem_mcp.http_client` logger (stderr in production, Task 18).

Task 11 adds challenge detection, retries and the `X-RO-UI` check inside `_get_with_retries`.

**Files:**
- Modify: `server/src/realoem_mcp/http_client.py`
- Test: `server/tests/unit/test_http_client.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_http_client.py`:

```python
import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import USER_AGENT, Settings
from realoem_mcp.errors import UpstreamError
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.page_types import PageType
from tests.harness import LANDING_URL, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
GRP_PARAMS = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
GRP = url("partgrp", **GRP_PARAMS)
BAD_PARAMS = {"id": "VB13"}
BAD_ID = url("partgrp", **BAD_PARAMS)


@pytest.fixture
async def make_client(tmp_path: Path):
    made: list[tuple[RealOemClient, PageCache, FixtureTransport]] = []

    def factory(routes):
        transport = FixtureTransport(routes)
        clock = FakeClock()
        cache = PageCache(tmp_path / f"cache{len(made)}")
        client = RealOemClient(
            Settings(cache_dir=tmp_path), cache, transport=transport, clock=clock, sleep=clock.sleep
        )
        made.append((client, cache, transport))
        return client, transport, clock

    yield factory
    for client, cache, transport in made:
        await client.aclose()
        cache.close()
        assert transport.unmatched == []


async def test_sends_honest_headers_and_only_the_ro_ui_cookie(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    (request,) = transport.requests
    assert request.method == "GET"
    assert request.headers["User-Agent"] == USER_AGENT
    assert request.headers["Accept"] == "text/html"
    assert request.headers["Accept-Language"] == "en-US"
    assert request.headers["Cookie"] == "ro_ui=v2"


async def test_server_cookies_are_never_sent_back(make_client) -> None:
    set_cookies = {"Set-Cookie": "ro_ui=v1; Path=/", "X-Other": "1"}
    client, transport, _ = make_client({XREF: Route(headers=set_cookies), GRP: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]


async def test_fetch_returns_page_and_caches_it(make_client) -> None:
    client, transport, _ = make_client({XREF: "common/partgrp_e90_325i.html"})
    first = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    second = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (first.url, first.final_url, first.status) == (XREF, XREF, 200)
    assert first.page_type is PageType.PARTXREF
    assert first.from_cache is False
    assert first.fetched_at.tzinfo is not None
    assert 'rel="canonical"' in first.html
    assert second.from_cache is True
    assert second.html == first.html
    assert len(transport.requests) == 1
    assert client.requests_made == 1


async def test_refresh_bypasses_cache(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert page.from_cache is False
    assert len(transport.requests) == 2


async def test_ttl_override_is_used_when_writing(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, ttl=timedelta(0))
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert len(transport.requests) == 2


async def test_cached_never_touches_the_network(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    hit = client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert hit is not None
    assert hit.from_cache is True
    assert client.cached(PageType.PARTGRP, "partgrp", GRP_PARAMS) is None
    assert len(transport.requests) == 1


async def test_requests_are_spaced_by_min_interval(make_client) -> None:
    client, _, clock = make_client({XREF: Route(), GRP: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    clock.now += 0.5  # half a second of "work" between the two calls
    await client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    assert clock.sleeps == [1.5]


async def test_cache_hits_are_not_rate_limited(make_client) -> None:
    client, _, clock = make_client({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert clock.sleeps == []


async def test_concurrent_calls_for_one_url_make_one_request(make_client) -> None:
    client, transport, _ = make_client({XREF: Route()})
    pages = await asyncio.gather(
        *(client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS) for _ in range(3))
    )
    assert len(transport.requests) == 1
    assert sorted(p.from_cache for p in pages) == [False, True, True]


async def test_redirect_to_landing_is_returned_uncached(make_client) -> None:
    client, transport, clock = make_client({BAD_ID: Route(redirect_to=LANDING_URL)})
    page = await client.fetch(PageType.PARTGRP, "partgrp", BAD_PARAMS)
    assert page.redirected_away
    assert (page.url, page.final_url, page.status) == (BAD_ID, LANDING_URL, 200)
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]
    assert clock.sleeps == [2.0]  # the redirect hop is rate limited like any request
    assert client.requests_made == 2
    assert client.cached(PageType.PARTGRP, "partgrp", BAD_PARAMS) is None


async def test_same_host_redirect_loop_is_bounded(make_client) -> None:
    client, transport, clock = make_client({XREF: Route(redirect_to=XREF)})
    with pytest.raises(UpstreamError, match="TooManyRedirects"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert len(transport.requests) == 4  # the request plus MAX_REDIRECTS (3) hops
    assert clock.sleeps == [2.0, 2.0, 2.0]


async def test_https_to_http_downgrade_is_refused(make_client) -> None:
    downgrade = XREF.replace("https://", "http://")
    client, transport, _ = make_client({XREF: Route(redirect_to=downgrade)})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert f"redirected off-site to {downgrade}" in info.value.message
    assert len(transport.requests) == 1
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_undecodable_body_raises_upstream_error(make_client) -> None:
    # Plain HTML labelled as gzip cannot be decoded.
    broken = Route("common/partgrp_e90_325i.html", headers={"Content-Encoding": "gzip"})
    client, _, _ = make_client({XREF: broken})
    with pytest.raises(UpstreamError, match="DecodingError"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)


async def test_redirect_to_another_host_is_refused(make_client) -> None:
    client, transport, _ = make_client({XREF: Route(redirect_to="https://tracker.example/x")})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert "redirected off-site to https://tracker.example/x" in info.value.message
    assert [str(r.url) for r in transport.requests] == [XREF]  # the off-site hop is never sent
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_non_200_raises_upstream_error_and_is_not_cached(make_client) -> None:
    client, _, _ = make_client({XREF: Route(status=404)})
    with pytest.raises(UpstreamError) as info:
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert info.value.status == 404
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is None


async def test_logs_one_info_line_per_network_request(make_client, caplog) -> None:
    client, _, _ = make_client({XREF: Route()})
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    messages = [r.getMessage() for r in caplog.records]
    assert messages[0].startswith(f"partxref {XREF} -> 200 in ")
    assert messages[0].endswith("(cache miss)")
    assert messages[1] == f"partxref {XREF} cache hit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_http_client.py -q`
Expected: FAIL with `ImportError: cannot import name 'RealOemClient' from 'realoem_mcp.http_client'`

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/http_client.py` with:

```python
"""The only way the server talks to RealOEM: rate limited, cached, honest (AD6, AD8, AD13, AD14)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import UpstreamError
from realoem_mcp.page_types import PageType

if TYPE_CHECKING:
    from realoem_mcp.cache import PageCache

log = logging.getLogger(__name__)

COOKIE = "ro_ui=v2"
MAX_REDIRECTS = 3
_PATH_RE = re.compile(r"[a-z]+")
_PAGE_TYPE = "realoem_page_type"  # request extension keys (httpx keeps them across redirects)
_STARTED = "realoem_started"


@dataclass(frozen=True)
class Page:
    page_type: PageType
    url: str  # canonical request URL (cache key)
    final_url: str  # after redirects
    status: int
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool

    @property
    def redirected_away(self) -> bool:
        """True when RealOEM redirected to another page (e.g. /bmw/ for an invalid id)."""
        requested = urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1]
        return not urlsplit(self.final_url).path.rstrip("/").endswith("/" + requested)


def build_url(settings: Settings, path: str, params: Mapping[str, str]) -> str:
    """`{base_url}/bmw/{lang}/{path}?{params}`, params in the order given, spaces as %20."""
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"invalid RealOEM path {path!r}")
    if any(key.lower() == "dmode" for key in params):
        raise ValueError("dmode is never sent to RealOEM (AD7)")
    url = f"{settings.base_url}/bmw/{settings.lang}/{path}"
    if params:
        url += "?" + urlencode(list(params.items()), quote_via=quote)
    return url


class _RejectAllCookies(DefaultCookiePolicy):
    """AD14: cookies the server sets are never stored, so they are never sent back."""

    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False


class _OffsiteRedirect(Exception):
    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.target = target


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


class RealOemClient:
    def __init__(
        self,
        settings: Settings,
        cache: PageCache,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_start: float | None = None
        self.requests_made = 0  # every request sent: retries, redirect hops and failures included
        self._origin = _origin(httpx.URL(settings.base_url))
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=settings.timeout_s,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            cookies=CookieJar(policy=_RejectAllCookies()),
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html",
                "Accept-Language": "en-US",
            },
            event_hooks={"request": [self._on_request], "response": [self._on_response]},
        )

    def build_url(self, path: str, params: Mapping[str, str]) -> str:
        return build_url(self._settings, path, params)

    def cached(self, page_type: PageType, path: str, params: Mapping[str, str]) -> Page | None:
        """Cache-only lookup: an unexpired hit or None. Never touches the network."""
        page = self._cache.get(self.build_url(path, params))
        return page if page is not None and page.page_type == page_type else None

    async def fetch(
        self,
        page_type: PageType,
        path: str,
        params: Mapping[str, str],
        *,
        refresh: bool = False,
        ttl: timedelta | None = None,
    ) -> Page:
        url = self.build_url(path, params)
        if not refresh and (hit := self._cache.get(url)) is not None:
            log.info("%s %s cache hit", page_type.value, url)
            return hit
        async with self._lock:
            if not refresh and (hit := self._cache.get(url)) is not None:
                log.info("%s %s cache hit", page_type.value, url)
                return hit
            response = await self._get_with_retries(page_type, url)
            page = Page(
                page_type=page_type,
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                html=response.text,
                fetched_at=datetime.now(UTC),
                from_cache=False,
            )
            if page.redirected_away:
                return page
            if page.status != 200:
                raise UpstreamError(page.status, url)
            self._cache.put(page, ttl if ttl is not None else page_type.ttl)
            return page

    async def _get_with_retries(self, page_type: PageType, url: str) -> httpx.Response:
        # Task 11 adds challenge detection, retries and the X-RO-UI check here.
        try:
            return await self._send(page_type, url)
        except _OffsiteRedirect as exc:
            raise UpstreamError(None, url, f"redirected off-site to {exc.target}") from None
        except httpx.RequestError as exc:  # network, decoding, too many redirects
            raise UpstreamError(None, url, type(exc).__name__) from None

    async def _send(self, page_type: PageType, url: str) -> httpx.Response:
        try:
            return await self._http.get(url, extensions={_PAGE_TYPE: page_type.value})
        except httpx.RequestError as exc:
            log.info("%s %s failed: %s (cache miss)", page_type.value, url, type(exc).__name__)
            raise

    async def _on_request(self, request: httpx.Request) -> None:
        # Runs for every hop, redirects included, so each one is checked, spaced and counted.
        if _origin(request.url) != self._origin:
            raise _OffsiteRedirect(str(request.url))
        request.headers["Cookie"] = COOKIE  # httpx drops Cookie when it follows a redirect
        if self._last_start is not None:
            wait = self._settings.min_interval_s - (self._clock() - self._last_start)
            if wait > 0:
                await self._sleep(wait)
        self._last_start = self._clock()
        self.requests_made += 1
        request.extensions[_STARTED] = time.perf_counter()

    async def _on_response(self, response: httpx.Response) -> None:
        request = response.request
        elapsed_ms = (time.perf_counter() - request.extensions[_STARTED]) * 1000
        log.info(
            "%s %s -> %d in %.0f ms (cache miss)",
            request.extensions.get(_PAGE_TYPE, "?"),
            request.url,
            response.status_code,
            elapsed_ms,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_http_client.py tests/unit/test_page.py tests/unit/test_cache.py -q`
Expected: PASS (`39 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/http_client.py server/tests/unit/test_http_client.py
git commit -m "feat(server): add rate-limited, cached RealOemClient" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Challenges, retries, `X-RO-UI`

ARD §5.5 rules 4–6 and AD8:

- `BotChallenge` when the status is 403/503 with `cf-mitigated: challenge`, or the body contains
  `<title>Just a moment...</title>`. Never retried.
- 429 / 5xx / timeouts: up to 2 retries, waiting `Retry-After` seconds (capped at 30; a
  non-numeric or non-finite value such as `nan` falls back) or 5 s then 15 s; still failing →
  `UpstreamError`. Every attempt counts in `requests_made`.
- `X-RO-UI` present and not starting with `v2` → `LayoutChanged` (AD7).

**Files:**
- Modify: `server/src/realoem_mcp/http_client.py`
- Test: `server/tests/unit/test_http_client_errors.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_http_client_errors.py`:

```python
from pathlib import Path

import httpx
import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.errors import BotChallenge, LayoutChanged, UpstreamError
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.page_types import PageType
from tests.harness import FakeClock, load_fixture, url

pytestmark = pytest.mark.anyio

PARAMS = {"q": "11427953129"}
XREF = url("partxref", **PARAMS)
CHALLENGE = load_fixture("common/cloudflare_challenge.html")


class Script:
    """httpx handler that plays back responses (or exceptions) in order."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
async def run(tmp_path: Path):
    made: list[tuple[RealOemClient, PageCache]] = []

    async def fetch(script: Script):
        clock = FakeClock()
        cache = PageCache(tmp_path / f"cache{len(made)}")
        client = RealOemClient(
            Settings(cache_dir=tmp_path),
            cache,
            transport=httpx.MockTransport(script),
            clock=clock,
            sleep=clock.sleep,
        )
        made.append((client, cache))
        page = await client.fetch(PageType.PARTXREF, "partxref", PARAMS)
        return page, clock, client

    yield fetch
    for client, cache in made:
        await client.aclose()
        cache.close()


async def test_cloudflare_403_is_a_bot_challenge_and_never_retried(run) -> None:
    script = Script(httpx.Response(403, headers={"cf-mitigated": "challenge"}, text=CHALLENGE))
    with pytest.raises(BotChallenge) as info:
        await run(script)
    assert script.calls == 1
    assert info.value.url == XREF


async def test_challenge_title_is_detected_even_with_status_200(run) -> None:
    with pytest.raises(BotChallenge):
        await run(Script(httpx.Response(200, text=CHALLENGE)))


async def test_503_challenge_is_not_retried(run) -> None:
    script = Script(httpx.Response(503, headers={"cf-mitigated": "challenge"}, text=""))
    with pytest.raises(BotChallenge):
        await run(script)
    assert script.calls == 1


async def test_5xx_is_retried_after_5_seconds(run) -> None:
    script = Script(httpx.Response(503, text="busy"), httpx.Response(200, text="<p>ok</p>"))
    page, clock, client = await run(script)
    assert page.html == "<p>ok</p>"
    assert script.calls == 2
    assert clock.sleeps == [5.0]
    assert client.requests_made == 2  # every attempt sent is counted


async def test_retry_after_is_honoured_and_capped_at_30_seconds(run) -> None:
    script = Script(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429, headers={"Retry-After": "120"}),
        httpx.Response(200, text="ok"),
    )
    _, clock, _ = await run(script)
    assert clock.sleeps == [7.0, 30.0]


async def test_non_finite_retry_after_falls_back_to_default_backoff(run) -> None:
    script = Script(
        httpx.Response(429, headers={"Retry-After": "nan"}),
        httpx.Response(429, headers={"Retry-After": "inf"}),
        httpx.Response(200, text="ok"),
    )
    _, clock, _ = await run(script)
    assert clock.sleeps == [5.0, 15.0]


async def test_gives_up_after_two_retries(run) -> None:
    script = Script(*(httpx.Response(500) for _ in range(3)))
    with pytest.raises(UpstreamError) as info:
        await run(script)
    assert info.value.status == 500
    assert script.calls == 3


async def test_backoff_is_5_then_15_seconds(run) -> None:
    script = Script(httpx.Response(502), httpx.Response(502), httpx.Response(200, text="ok"))
    _, clock, _ = await run(script)
    assert clock.sleeps == [5.0, 15.0]


async def test_timeouts_are_retried(run) -> None:
    script = Script(httpx.ReadTimeout("slow"), httpx.Response(200, text="ok"))
    page, clock, _ = await run(script)
    assert page.status == 200
    assert clock.sleeps == [5.0]


async def test_repeated_timeouts_raise_upstream_error(run) -> None:
    script = Script(*(httpx.ReadTimeout("slow") for _ in range(3)))
    with pytest.raises(UpstreamError) as info:
        await run(script)
    assert info.value.status is None
    assert "timed out" in info.value.message


async def test_network_error_raises_upstream_error(run) -> None:
    with pytest.raises(UpstreamError, match="ConnectError"):
        await run(Script(httpx.ConnectError("refused")))


async def test_ui_variant_other_than_v2_is_a_layout_change(run) -> None:
    with pytest.raises(LayoutChanged) as info:
        await run(Script(httpx.Response(200, headers={"X-RO-UI": "v1"}, text="ok")))
    assert info.value.page_type == "partxref"
    assert "X-RO-UI" in info.value.detail


async def test_ui_variant_v2_new_is_accepted(run) -> None:
    page, _, _ = await run(Script(httpx.Response(200, headers={"X-RO-UI": "v2+new"}, text="ok")))
    assert page.status == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_http_client_errors.py -q`
Expected: FAIL (`11 failed, 2 passed`: challenges are not detected, nothing is retried, `X-RO-UI` is not checked)

- [ ] **Step 3: Write minimal implementation**

In `server/src/realoem_mcp/http_client.py`, replace:

```python
import logging
```

with:

```python
import logging
import math
```

In `server/src/realoem_mcp/http_client.py`, replace:

```python
from realoem_mcp.errors import UpstreamError
```

with:

```python
from realoem_mcp.errors import BotChallenge, LayoutChanged, UpstreamError
```

In `server/src/realoem_mcp/http_client.py`, replace:

```python
MAX_REDIRECTS = 3
```

with:

```python
MAX_REDIRECTS = 3
MAX_RETRIES = 2
RETRY_DELAYS_S = (5.0, 15.0)
RETRY_AFTER_CAP_S = 30.0
CHALLENGE_TITLE = "<title>Just a moment...</title>"
```

In `server/src/realoem_mcp/http_client.py`, replace:

```python
        # Task 11 adds challenge detection, retries and the X-RO-UI check here.
        try:
            return await self._send(page_type, url)
        except _OffsiteRedirect as exc:
            raise UpstreamError(None, url, f"redirected off-site to {exc.target}") from None
        except httpx.RequestError as exc:  # network, decoding, too many redirects
            raise UpstreamError(None, url, type(exc).__name__) from None
```

with:

```python
        attempt = 0
        while True:
            try:
                response = await self._send(page_type, url)
            except httpx.TimeoutException:
                if attempt >= MAX_RETRIES:
                    raise UpstreamError(None, url, "timed out") from None
                await self._sleep(RETRY_DELAYS_S[attempt])
                attempt += 1
                continue
            except _OffsiteRedirect as exc:
                raise UpstreamError(None, url, f"redirected off-site to {exc.target}") from None
            except httpx.RequestError as exc:  # network, decoding, too many redirects
                raise UpstreamError(None, url, type(exc).__name__) from None
            if _is_challenge(response):
                raise BotChallenge(url)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    raise UpstreamError(response.status_code, url)
                await self._sleep(_retry_delay(response, attempt))
                attempt += 1
                continue
            ui = response.headers.get("X-RO-UI")
            if ui is not None and not ui.startswith("v2"):
                raise LayoutChanged(page_type, f"X-RO-UI is {ui!r}, expected v2", url)
            return response
```

Append to `server/src/realoem_mcp/http_client.py`:

```python


def _is_challenge(response: httpx.Response) -> bool:
    if (
        response.status_code in (403, 503)
        and response.headers.get("cf-mitigated", "").lower() == "challenge"
    ):
        return True
    return CHALLENGE_TITLE in response.text


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return RETRY_DELAYS_S[attempt]
    if not math.isfinite(seconds):
        return RETRY_DELAYS_S[attempt]
    return min(max(seconds, 0.0), RETRY_AFTER_CAP_S)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_http_client_errors.py tests/unit/test_http_client.py -q`
Expected: PASS (`29 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/http_client.py server/tests/unit/test_http_client_errors.py
git commit -m "feat(server): detect bot challenges and retry transient failures" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 5: Vehicle ids and brand registry

### Task 12: Vehicle ids (`vehicle_ids.py`)

ARD §5.8 and site notes §2. Three forms: `VB13-USA-10-2005-E90-BMW-325i`,
`VB13-USA-02_2004_E90_BMW_325i` (xref links) and `VB13-USA---E90-BMW-325i`. After the series token
the parser matches the **longest** known brand segment (`Rolls_Royce` contains the `_` separator);
the rest is the model. Input is percent-decoded once and trimmed; `str(vid)` is that decoded `raw`.
Unknown shapes keep `raw` and parse only `type_code` and `market` (`""` when absent).

**Files:**
- Create: `server/src/realoem_mcp/vehicle_ids.py`
- Test: `server/tests/unit/test_vehicle_ids.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_vehicle_ids.py`:

```python
import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.vehicle_ids import DEFAULT_BRAND_SEGMENTS, VehicleId


def test_dash_form() -> None:
    vid = VehicleId.parse("VB13-USA-10-2005-E90-BMW-325i")
    assert vid == VehicleId(
        raw="VB13-USA-10-2005-E90-BMW-325i",
        type_code="VB13",
        market="USA",
        month="10",
        year="2005",
        series="E90",
        brand_segment="BMW",
        model="325i",
    )
    assert vid.production_month == "2005-10"
    assert str(vid) == "VB13-USA-10-2005-E90-BMW-325i"


def test_xref_underscore_form() -> None:
    vid = VehicleId.parse("VB13-USA-02_2004_E90_BMW_325i")
    assert (vid.type_code, vid.market, vid.production_month) == ("VB13", "USA", "2004-02")
    assert (vid.series, vid.brand_segment, vid.model) == ("E90", "BMW", "325i")


def test_empty_date_form() -> None:
    vid = VehicleId.parse("VB13-USA---E90-BMW-325i")
    assert (vid.type_code, vid.market, vid.production_month) == ("VB13", "USA", None)
    assert (vid.series, vid.brand_segment, vid.model) == ("E90", "BMW", "325i")


@pytest.mark.parametrize(
    ("raw", "series", "brand_segment", "model"),
    [
        ("MF73-USA-02-2008-R56-Mini-Cooper_S", "R56", "Mini", "Cooper_S"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", "RR4", "Rolls_Royce", "Ghost"),
        ("FK41-EUR-06_2010_RR4_Rolls_Royce_Ghost", "RR4", "Rolls_Royce", "Ghost"),
        (
            "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_",
            "K50",
            "BMW",
            "R_1250_GS_19_0J91,_0J93_",
        ),
    ],
)
def test_brand_variants_use_longest_brand_segment(
    raw: str, series: str, brand_segment: str, model: str
) -> None:
    vid = VehicleId.parse(raw)
    assert (vid.series, vid.brand_segment, vid.model) == (series, brand_segment, model)


def test_percent_decoded_once_and_trimmed() -> None:
    vid = VehicleId.parse("  0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_ ")
    assert vid.raw == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert VehicleId.parse("A-B-01-2000-X-BMW-100%2541").model == "100%41"


def test_unknown_brand_segment_keeps_series_and_date() -> None:
    vid = VehicleId.parse("AB12-USA-01-2020-G20-Zinoro-X")
    assert (vid.series, vid.brand_segment, vid.model, vid.production_month) == (
        "G20",
        None,
        None,
        "2020-01",
    )
    assert VehicleId.parse("AB12-USA-01-2020-G20-Zinoro-X", brand_segments=["Zinoro"]).model == (
        "X"
    )


def test_unknown_shape_parses_only_type_code_and_market() -> None:
    vid = VehicleId.parse("VB13-USA")
    assert vid == VehicleId(raw="VB13-USA", type_code="VB13", market="USA")
    assert VehicleId.parse("VB13") == VehicleId(raw="VB13", type_code="VB13", market="")


def test_empty_id_is_invalid_input() -> None:
    with pytest.raises(InvalidInput):
        VehicleId.parse("   ")


def test_default_brand_segments() -> None:
    assert DEFAULT_BRAND_SEGMENTS == ("Rolls_Royce", "Mini", "BMW")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_vehicle_ids.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.vehicle_ids'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/vehicle_ids.py`:

```python
"""RealOEM vehicle ids, e.g. VB13-USA-10-2005-E90-BMW-325i (site notes section 2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote

from realoem_mcp.errors import InvalidInput

DEFAULT_BRAND_SEGMENTS: tuple[str, ...] = ("Rolls_Royce", "Mini", "BMW")

_HEAD = r"(?P<type>[^-]+)-(?P<market>[^-]+)-"
# (pattern, separator between series, brand segment and model)
_FORMS: tuple[tuple[re.Pattern[str], str], ...] = (
    # VB13-USA-10-2005-E90-BMW-325i
    (re.compile(_HEAD + r"(?P<month>\d{2})-(?P<year>\d{4})-(?P<rest>.+)"), "-"),
    # VB13-USA-02_2004_E90_BMW_325i (partxref links)
    (re.compile(_HEAD + r"(?P<month>\d{2})_(?P<year>\d{4})_(?P<rest>.+)"), "_"),
    # VB13-USA---E90-BMW-325i (no date)
    (re.compile(_HEAD + r"--(?P<rest>.+)"), "-"),
)


@dataclass(frozen=True)
class VehicleId:
    raw: str
    type_code: str
    market: str
    month: str | None = None  # "10"
    year: str | None = None  # "2005"
    series: str | None = None
    brand_segment: str | None = None
    model: str | None = None

    @classmethod
    def parse(
        cls, raw: str, *, brand_segments: Sequence[str] = DEFAULT_BRAND_SEGMENTS
    ) -> VehicleId:
        text = unquote(raw).strip()
        if not text:
            raise InvalidInput("The vehicle id is empty.")
        for pattern, sep in _FORMS:
            match = pattern.fullmatch(text)
            if match is None:
                continue
            series, _, after = match["rest"].partition(sep)
            brand_segment, model = _split_brand(after, sep, brand_segments)
            return cls(
                raw=text,
                type_code=match["type"],
                market=match["market"],
                month=match.groupdict().get("month"),
                year=match.groupdict().get("year"),
                series=series or None,
                brand_segment=brand_segment,
                model=model,
            )
        type_code, _, rest = text.partition("-")
        return cls(raw=text, type_code=type_code, market=rest.split("-", 1)[0])

    @property
    def production_month(self) -> str | None:
        """Production month as "YYYY-MM", or None when the id carries no date."""
        if self.year is None or self.month is None:
            return None
        return f"{self.year}-{self.month}"

    def __str__(self) -> str:
        return self.raw


def _split_brand(
    after: str, sep: str, brand_segments: Sequence[str]
) -> tuple[str | None, str | None]:
    for segment in sorted(brand_segments, key=len, reverse=True):
        if after == segment:
            return segment, None
        if after.startswith(segment + sep):
            return segment, after[len(segment) + len(sep) :] or None
    return None, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_vehicle_ids.py -q`
Expected: PASS (`12 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/vehicle_ids.py server/tests/unit/test_vehicle_ids.py
git commit -m "feat(server): parse RealOEM vehicle ids" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Brand registry (`brands.py`, `brands/*/brand.toml`)

ARD §5.7. Candidates are always tried in ascending `priority`. `for_series` checks
`label_keywords` (case-sensitive substring of the label) before `series_patterns`, then falls back to
`bmw` (product `P` or unknown) or `motorrad` (`M`). `for_vehicle_id` uses the id's brand segment; when
several brands share it (`BMW` → bmw + motorrad) it matches series patterns among them (narrowed by
`product` when given) and falls back to the lowest-priority candidate. Unknown TOML keys go to
`Brand.extra` (declared with `hash=False, compare=False`, so a frozen `Brand` stays hashable); a
brand's `id` must equal its directory name. The fallback needs the `bmw` and `motorrad` brands.

**Files:**
- Create: `server/src/realoem_mcp/brands.py`, `brands/bmw/brand.toml`, `brands/mini/brand.toml`, `brands/rolls-royce/brand.toml`, `brands/motorrad/brand.toml`, `brands/bmw/README.md`, `brands/mini/README.md`, `brands/rolls-royce/README.md`, `brands/motorrad/README.md`
- Test: `server/tests/unit/test_brands.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_brands.py`:

```python
from pathlib import Path

import pytest

from realoem_mcp.brands import Brand, BrandRegistry
from realoem_mcp.vehicle_ids import VehicleId
from tests.harness import BRANDS_DIR


@pytest.fixture(scope="module")
def registry() -> BrandRegistry:
    return BrandRegistry.load(BRANDS_DIR)


def test_loads_all_four_brands_in_priority_order(registry: BrandRegistry) -> None:
    assert [(b.id, b.priority) for b in registry] == [
        ("mini", 10),
        ("rolls-royce", 20),
        ("motorrad", 30),
        ("bmw", 100),
    ]


def test_brand_toml_values(registry: BrandRegistry) -> None:
    mini = registry.get("mini")
    assert mini == Brand(
        id="mini",
        display_name="MINI",
        product="P",
        id_brand_segments=("Mini",),
        series_patterns=(r"^R5\d$", r"^R6\d$", r"^F5[4-7]$", r"^F60$", r"^J0\d$", r"^U25$"),
        label_keywords=("MINI",),
        wmi=("WMW", "WMZ"),
        notes="Classic catalog (archive=1) holds R50/R52/R53.",
        dedupe_repeated_names=False,
        priority=10,
    )
    assert registry.get("motorrad").product == "M"
    assert registry.get("motorrad").dedupe_repeated_names is True
    assert registry.get("rolls-royce").id_brand_segments == ("Rolls_Royce",)
    assert registry.get("bmw").wmi == (
        "WBA",
        "WBS",
        "WBY",
        "WBX",
        "5UX",
        "5UM",
        "5YM",
        "4US",
        "3MW",
        "LBV",
    )


def test_brands_are_hashable(registry: BrandRegistry) -> None:
    assert hash(registry.get("bmw")) == hash(registry.get("bmw"))
    assert len(set(registry)) == 4


def test_brand_segments(registry: BrandRegistry) -> None:
    assert set(registry.brand_segments()) == {"Mini", "Rolls_Royce", "BMW"}


@pytest.mark.parametrize(
    ("code", "label", "product", "expected"),
    [
        ("R56", None, None, "mini"),
        ("F56", None, None, "mini"),
        ("RR4", None, None, "rolls-royce"),
        ("R21N", None, None, "rolls-royce"),
        ("K50", None, None, "motorrad"),
        ("KR1", None, None, "motorrad"),
        ("T24", None, None, "motorrad"),
        ("E90", None, None, "bmw"),
        ("E90N", None, "P", "bmw"),
        ("K25", "BMW K25 (R 1200 GS)", "M", "motorrad"),
        ("XYZ", "BMW MINI R56", None, "mini"),
        ("R11N", "BMW Phantom R11N", None, "rolls-royce"),
        ("K12", None, "P", "bmw"),
        ("ZZZ", None, "M", "motorrad"),
    ],
)
def test_for_series(
    registry: BrandRegistry, code: str, label: str | None, product: str | None, expected: str
) -> None:
    assert registry.for_series(code, label=label, product=product).id == expected


@pytest.mark.parametrize(
    ("raw", "product", "expected"),
    [
        ("MF73-USA-02-2008-R56-Mini-Cooper_S", None, "mini"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", None, "rolls-royce"),
        ("VB13-USA-10-2005-E90-BMW-325i", None, "bmw"),
        ("0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", None, "motorrad"),
        ("0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", "M", "motorrad"),
        ("VB13-USA-10-2005-E90-BMW-325i", "P", "bmw"),
        ("VB13-USA", None, "bmw"),
    ],
)
def test_for_vehicle_id(
    registry: BrandRegistry, raw: str, product: str | None, expected: str
) -> None:
    vid = VehicleId.parse(raw, brand_segments=registry.brand_segments())
    assert registry.for_vehicle_id(vid, product=product).id == expected


def test_for_wmi(registry: BrandRegistry) -> None:
    assert registry.for_wmi("WBA").id == "bmw"
    assert registry.for_wmi("LBV").id == "bmw"
    assert registry.for_wmi("wmw").id == "mini"
    assert registry.for_wmi("SCA1234").id == "rolls-royce"
    assert registry.for_wmi("WB1").id == "motorrad"
    assert registry.for_wmi("1FT") is None


def test_unknown_keys_go_to_extra(tmp_path: Path) -> None:
    (tmp_path / "zinoro").mkdir()
    (tmp_path / "zinoro" / "brand.toml").write_text(
        'id = "zinoro"\ndisplay_name = "Zinoro"\nproduct = "P"\nlogo = "z.png"\n',
        encoding="utf-8",
    )
    (brand,) = BrandRegistry.load(tmp_path)
    assert brand.extra == {"logo": "z.png"}
    assert (brand.series_patterns, brand.dedupe_repeated_names, brand.priority) == ((), False, 100)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('display_name = "X"\nproduct = "P"\n', "missing required key 'id'"),
        ('id = "x"\ndisplay_name = "X"\nproduct = "Q"\n', "product must be 'P' or 'M'"),
        ('id = "other"\ndisplay_name = "X"\nproduct = "P"\n', "must match its directory"),
    ],
)
def test_invalid_brand_files(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "brand.toml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        BrandRegistry.load(tmp_path)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BrandRegistry.load(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_brands.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.brands'`

- [ ] **Step 3: Write minimal implementation**

Create `brands/mini/brand.toml`:

```toml
id = "mini"
display_name = "MINI"
product = "P"                         # P = cars, M = motorcycles
id_brand_segments = ["Mini"]          # vehicle-id brand segment(s)
series_patterns = ['^R5\d$', '^R6\d$', '^F5[4-7]$', '^F60$', '^J0\d$', '^U25$']
label_keywords = ["MINI"]             # used when classifying partxref series labels
wmi = ["WMW", "WMZ"]
notes = "Classic catalog (archive=1) holds R50/R52/R53."
dedupe_repeated_names = false
priority = 10                         # lower = checked first when matching series patterns
```

Create `brands/rolls-royce/brand.toml`:

```toml
id = "rolls-royce"
display_name = "Rolls-Royce"
product = "P"                         # P = cars, M = motorcycles
id_brand_segments = ["Rolls_Royce"]   # vehicle-id brand segment(s); contains the "_" separator
series_patterns = ['^RR\d+N?$', '^R[12]\dN$']
label_keywords = ["Rolls-Royce", "Phantom", "Ghost", "Wraith", "Dawn", "Cullinan", "Spectre"]
wmi = ["SCA"]
notes = "Vehicle ids use the brand segment Rolls_Royce. LCI series can look like R11N / R21N."
dedupe_repeated_names = false
priority = 20                         # lower = checked first when matching series patterns
```

Create `brands/motorrad/brand.toml`:

```toml
id = "motorrad"
display_name = "BMW Motorrad"
product = "M"                         # P = cars, M = motorcycles
id_brand_segments = ["BMW"]           # shared with bmw; resolved by series pattern / product
series_patterns = ['^K', '^R\d', '^T\d']
label_keywords = []
wmi = ["WB1", "WB3"]
notes = "Product M. No body or engine cascade levels. Diagram names are printed twice."
dedupe_repeated_names = true          # "Engine Engine" -> "Engine"
priority = 30                         # lower = checked first when matching series patterns
```

Create `brands/bmw/brand.toml`:

```toml
id = "bmw"
display_name = "BMW"
product = "P"                         # P = cars, M = motorcycles
id_brand_segments = ["BMW"]           # vehicle-id brand segment(s)
series_patterns = []                  # fallback brand for cars: matches nothing explicitly
label_keywords = []
wmi = ["WBA", "WBS", "WBY", "WBX", "5UX", "5UM", "5YM", "4US", "3MW", "LBV"]
notes = "Fallback for every car series not claimed by another brand. LCI series end in N (E90N)."
dedupe_repeated_names = false
priority = 100                        # lower = checked first when matching series patterns
```

Create `brands/bmw/README.md`:

```markdown
# BMW (cars)

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Fallback brand for product `P` (cars): any series not claimed by MINI or Rolls-Royce is BMW,
  including BMW i, M/Motorsport (`MOSP`) and Zinoro.
- Vehicle ids use the brand segment `BMW`, e.g. `VB13-USA-10-2005-E90-BMW-325i`.
- Series codes are opaque; LCI (facelift) series end in `N` (`E90N`). Read codes from links, never
  from labels.
- Classic catalog (`archive=1`) holds E21, E30, E36, E46, E39, E38, E31, Z3 and others; Classic cars
  add Steering and Transmission cascade levels.
- WMI prefixes: `WBA`, `WBS` (M), `WBY` (i), `WBX`, US-built `5UX`, `5UM`, `5YM`, `4US`, Mexico `3MW`,
  China `LBV`.
```

Create `brands/mini/README.md`:

```markdown
# MINI

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Vehicle ids use the brand segment `Mini`, e.g. `MF73-USA-02-2008-R56-Mini-Cooper_S`.
- partxref series labels still start with "BMW" ("BMW MINI R56"); classify by the `MINI` keyword.
- R50/R52/R53 are in the Classic catalog (`archive=1`); newer series (R5x, R6x, F54–F57, F60, J0x,
  U25) are Current.
- WMI prefixes: `WMW`, `WMZ`.
```

Create `brands/rolls-royce/README.md`:

```markdown
# Rolls-Royce

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Vehicle ids use the brand segment `Rolls_Royce`, which contains the `_` separator used by partxref
  ids, e.g. `FK43-USA-06-2010-RR4-Rolls_Royce-Ghost`.
- Series codes: `RR1`…`RRnn`, LCI forms such as `R11N` and `R21N`.
- partxref model rows add a transmission field; vehicle specs add Transmission.
- Main groups include `92 BESPOKE` and `83`.
- WMI prefix: `SCA`.
```

Create `brands/motorrad/README.md`:

```markdown
# BMW Motorrad

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Product `M`. Vehicle ids share the brand segment `BMW` with cars, e.g.
  `0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_`; the registry resolves them by series pattern
  (`K…` incl. KR1/KM3, `R<digit>…`, `T<digit>…` for old bikes such as T24) or by `product="M"`.
- No body (`ohne`) or engine cascade levels; vehicle specs show Body `N/A`.
- Diagram and subgroup names are printed twice ("Engine Engine"); `dedupe_repeated_names = true`.
- Supplements may be German (`SILBER`) even under `enUS`; fewer prices are shown.
- WMI prefixes: `WB1`, `WB3`.
```

Create `server/src/realoem_mcp/brands.py`:

```python
"""Brand registry loaded from brands/<id>/brand.toml (AD9)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from realoem_mcp.vehicle_ids import VehicleId

_LIST_KEYS = ("id_brand_segments", "series_patterns", "label_keywords", "wmi")
_KNOWN_KEYS = {"id", "display_name", "product", "notes", "dedupe_repeated_names", "priority"}
_KNOWN_KEYS.update(_LIST_KEYS)


@dataclass(frozen=True)
class Brand:
    id: str
    display_name: str
    product: str  # "P" cars, "M" motorcycles
    id_brand_segments: tuple[str, ...] = ()
    series_patterns: tuple[str, ...] = ()
    label_keywords: tuple[str, ...] = ()
    wmi: tuple[str, ...] = ()
    notes: str = ""
    dedupe_repeated_names: bool = False
    priority: int = 100
    extra: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @classmethod
    def from_toml(cls, path: Path) -> Brand:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in ("id", "display_name", "product"):
            if key not in data:
                raise ValueError(f"{path}: missing required key {key!r}")
        if data["product"] not in ("P", "M"):
            raise ValueError(f"{path}: product must be 'P' or 'M', got {data['product']!r}")
        if data["id"] != path.parent.name:
            raise ValueError(f"{path}: id {data['id']!r} must match its directory name")
        return cls(
            id=data["id"],
            display_name=data["display_name"],
            product=data["product"],
            id_brand_segments=tuple(data.get("id_brand_segments", ())),
            series_patterns=tuple(data.get("series_patterns", ())),
            label_keywords=tuple(data.get("label_keywords", ())),
            wmi=tuple(data.get("wmi", ())),
            notes=data.get("notes", ""),
            dedupe_repeated_names=bool(data.get("dedupe_repeated_names", False)),
            priority=int(data.get("priority", 100)),
            extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
        )

    def matches_label(self, label: str) -> bool:
        return any(keyword in label for keyword in self.label_keywords)

    def matches_series(self, code: str) -> bool:
        return any(re.search(pattern, code) for pattern in self.series_patterns)


class BrandRegistry:
    def __init__(self, brands: Iterable[Brand]) -> None:
        self._brands = sorted(brands, key=lambda b: (b.priority, b.id))
        self._by_id = {b.id: b for b in self._brands}

    @classmethod
    def load(cls, directory: Path) -> BrandRegistry:
        files = sorted(Path(directory).glob("*/brand.toml"))
        if not files:
            raise FileNotFoundError(f"No brands/*/brand.toml files found under {directory}")
        return cls(Brand.from_toml(path) for path in files)

    def __iter__(self) -> Iterator[Brand]:
        return iter(self._brands)

    def __len__(self) -> int:
        return len(self._brands)

    def get(self, brand_id: str) -> Brand:
        return self._by_id[brand_id]

    def brand_segments(self) -> tuple[str, ...]:
        segments: dict[str, None] = {}
        for brand in self._brands:
            segments.update(dict.fromkeys(brand.id_brand_segments))
        return tuple(segments)

    def for_series(
        self, code: str | None, *, label: str | None = None, product: str | None = None
    ) -> Brand:
        candidates = [b for b in self._brands if product is None or b.product == product]
        return self._match(code, label, candidates) or self._fallback(product)

    def for_vehicle_id(self, vid: VehicleId, *, product: str | None = None) -> Brand:
        candidates = [b for b in self._brands if vid.brand_segment in b.id_brand_segments]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return self.for_series(vid.series, product=product)
        narrowed = [b for b in candidates if product is None or b.product == product] or candidates
        return self._match(vid.series, None, narrowed) or narrowed[-1]

    def for_wmi(self, prefix: str) -> Brand | None:
        wmi = prefix[:3].upper()
        return next((b for b in self._brands if wmi in b.wmi), None)

    @staticmethod
    def _match(code: str | None, label: str | None, candidates: list[Brand]) -> Brand | None:
        if label:
            for brand in candidates:
                if brand.matches_label(label):
                    return brand
        if code:
            for brand in candidates:
                if brand.matches_series(code):
                    return brand
        return None

    def _fallback(self, product: str | None) -> Brand:
        """Default brand per product; the registry must contain "bmw" and "motorrad"."""
        return self.get("motorrad" if product == "M" else "bmw")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_brands.py -q`
Expected: PASS (`29 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add brands server/src/realoem_mcp/brands.py server/tests/unit/test_brands.py
git commit -m "feat(brands): add brand registry and four brand.toml files" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 6: Shared models and parser helpers

### Task 14: Shared models (`models/common.py`)

ARD §5.10. `ResultMeta.from_pages(pages, **fields)` fills `source_urls` (request URLs, de-duplicated
in order), `fetched_at` (oldest), `from_cache` (all cached) and `requests_made` (pages with
`from_cache=False`). Feature branches build `VehicleRef` and `DiagramRef` only through
`VehicleRef.from_id(vid, brand)` and `DiagramRef.build(client, vehicle_id, diag_id, name)`, whose URL
comes from `client.build_url("showparts", ...)` (never an href join, never a `#fragment`).

**Files:**
- Create: `server/src/realoem_mcp/models/__init__.py`, `server/src/realoem_mcp/models/common.py`
- Test: `server/tests/unit/test_models_common.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_models_common.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Page, RealOemClient
from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.vehicle_ids import VehicleId

pytestmark = pytest.mark.anyio


class LookupResult(ResultMeta):
    query: str


def _page(url: str, day: int, *, from_cache: bool) -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=url,
        final_url=url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, day, tzinfo=UTC),
        from_cache=from_cache,
    )


def test_from_pages_fills_the_four_meta_fields() -> None:
    pages = [
        _page("https://x/a", 20, from_cache=True),
        _page("https://x/b", 10, from_cache=False),
        _page("https://x/a", 25, from_cache=False),
    ]
    result = LookupResult.from_pages(pages, query="11427953129")
    assert result.source_urls == ["https://x/a", "https://x/b"]
    assert result.fetched_at == datetime(2026, 9, 10, tzinfo=UTC)
    assert result.from_cache is False
    assert result.requests_made == 2
    assert result.query == "11427953129"


def test_from_pages_all_cached() -> None:
    result = LookupResult.from_pages([_page("https://x/a", 1, from_cache=True)], query="q")
    assert (result.from_cache, result.requests_made) == (True, 0)


def test_from_pages_needs_a_page() -> None:
    with pytest.raises(ValueError, match="at least one page"):
        LookupResult.from_pages([], query="q")


def test_vehicle_ref_from_id_copies_id_fields() -> None:
    vid = VehicleId.parse("MF73-USA-02-2008-R56-Mini-Cooper_S")
    assert VehicleRef.from_id(vid, "mini") == VehicleRef(
        vehicle_id="MF73-USA-02-2008-R56-Mini-Cooper_S",
        type_code="MF73",
        market="USA",
        production_month="2008-02",
        series="R56",
        brand="mini",
        model="Cooper_S",
    )


def test_vehicle_ref_from_undated_id() -> None:
    ref = VehicleRef.from_id(VehicleId.parse("VB13-USA---E90-BMW-325i"), "bmw")
    assert (ref.vehicle_id, ref.production_month) == ("VB13-USA---E90-BMW-325i", None)


async def test_diagram_ref_build_uses_client_build_url(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    client = RealOemClient(Settings(cache_dir=tmp_path), cache)
    try:
        ref = DiagramRef.build(
            client, "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", "11_5146", "Oil filter"
        )
    finally:
        await client.aclose()
        cache.close()
    assert ref.vehicle_id == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert (ref.diag_id, ref.name) == ("11_5146", "Oil filter")
    assert ref.url == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_&diagId=11_5146"
    )
    assert "#" not in ref.url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_models_common.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.models'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/models/__init__.py`:

```python
"""Pydantic models: parser outputs and tool results."""
```

Create `server/src/realoem_mcp/models/common.py`:

```python
"""Shared result models (ARD section 5.10). Build VehicleRef/DiagramRef only via these helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel

if TYPE_CHECKING:
    from realoem_mcp.http_client import Page, RealOemClient
    from realoem_mcp.vehicle_ids import VehicleId


class ResultMeta(BaseModel):
    source_urls: list[str]
    fetched_at: datetime  # oldest fetched_at among pages used (UTC)
    from_cache: bool  # True only if every page came from cache
    requests_made: int  # pages this call fetched from the network

    @classmethod
    def from_pages(cls, pages: Sequence[Page], **fields: Any) -> Self:
        if not pages:
            raise ValueError("from_pages needs at least one page")
        return cls(
            source_urls=list(dict.fromkeys(page.url for page in pages)),
            fetched_at=min(page.fetched_at for page in pages),
            from_cache=all(page.from_cache for page in pages),
            requests_made=sum(1 for page in pages if not page.from_cache),
            **fields,
        )


class VehicleRef(BaseModel):
    vehicle_id: str
    type_code: str
    market: str
    production_month: str | None  # "YYYY-MM"
    series: str | None
    brand: str  # brand registry id: bmw | mini | rolls-royce | motorrad
    model: str | None

    @classmethod
    def from_id(cls, vid: VehicleId, brand: str) -> VehicleRef:
        return cls(
            vehicle_id=vid.raw,
            type_code=vid.type_code,
            market=vid.market,
            production_month=vid.production_month,
            series=vid.series,
            brand=brand,
            model=vid.model,
        )


class DiagramRef(BaseModel):
    vehicle_id: str
    diag_id: str  # "{mg}_{nnnn}"
    name: str
    url: str

    @classmethod
    def build(cls, client: RealOemClient, vehicle_id: str, diag_id: str, name: str) -> DiagramRef:
        url = client.build_url("showparts", {"id": vehicle_id, "diagId": diag_id})
        return cls(vehicle_id=vehicle_id, diag_id=diag_id, name=name, url=url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_models_common.py -q`
Expected: PASS (`6 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/models server/tests/unit/test_models_common.py
git commit -m "feat(server): add shared result models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: Parser helpers (`parsers/common.py`)

ARD §5.9. selectolax's **lexbor** backend (`selectolax.lexbor.LexborHTMLParser`; the older Modest
`selectolax.parser.HTMLParser` is deprecated). `require` raises `LayoutChanged` when a selector is
missing (NFR3). Value parsers return `None` when the value is absent (`""`, `"-"`) and raise
`ValueError` for an impossible month. `json_ld` returns every object of a given `@type`, including
objects inside lists and `@graph`, skipping invalid JSON.

**Files:**
- Create: `server/src/realoem_mcp/parsers/__init__.py`, `server/src/realoem_mcp/parsers/common.py`
- Test: `server/tests/unit/parsers/test_common.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/parsers/test_common.py`:

```python
from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.common import (
    canonical_url,
    json_ld,
    parse_mdy,
    parse_my,
    parse_price_usd,
    parse_yyyymm00,
    require,
    text,
    tree,
)
from tests.harness import load_fixture

PARTGRP_URL = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"


def test_text_collapses_whitespace() -> None:
    doc = tree("<dd>(06/01/2017 &mdash;\n\n   ), Exchangeable   retrospectively</dd>")
    assert text(doc.css_first("dd")) == "(06/01/2017 — ), Exchangeable retrospectively"
    assert text(None) == ""


def test_require_returns_node_or_raises_layout_changed() -> None:
    doc = tree('<div class="content"><h1>11427953129</h1></div>')
    assert text(require(doc, "div.content > h1", "partxref", "https://x")) == "11427953129"
    with pytest.raises(LayoutChanged) as info:
        require(doc, "div.partSearchResults", "partxref", "https://x/partxref?q=1")
    assert info.value.page_type == "partxref"
    assert info.value.url == "https://x/partxref?q=1"
    assert "div.partSearchResults" in info.value.detail


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("09/01/2004", date(2004, 9, 1)),
        ("03/17/2006 (ENDED)", date(2006, 3, 17)),
        ("(06/01/2017 — )", date(2017, 6, 1)),
        ("-", None),
        ("", None),
    ],
)
def test_parse_mdy(value: str, expected: date | None) -> None:
    assert parse_mdy(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("04/2006", "2006-04"), ("Up To 12/2011", "2011-12"), ("", None), ("--", None)],
)
def test_parse_my(value: str, expected: str | None) -> None:
    assert parse_my(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("20051000", "2005-10"), ("20080700", "2008-07"), ("200510", None), ("", None)],
)
def test_parse_yyyymm00(value: str, expected: str | None) -> None:
    assert parse_yyyymm00(value) == expected


def test_invalid_month_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid month"):
        parse_my("13/2006")
    with pytest.raises(ValueError, match="invalid month"):
        parse_yyyymm00("20051300")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("$12.25", 12.25), ("$551.84", 551.84), ("$1,234.50", 1234.5), (" $ 7 ", 7.0), ("", None)],
)
def test_parse_price_usd(value: str, expected: float | None) -> None:
    assert parse_price_usd(value) == expected


def test_canonical_url_from_real_partgrp_page() -> None:
    doc = tree(load_fixture("common/partgrp_e90_325i.html"))
    assert canonical_url(doc) == PARTGRP_URL
    assert canonical_url(tree("<p>no head</p>")) is None


def test_json_ld_from_real_partgrp_page() -> None:
    doc = tree(load_fixture("common/partgrp_e90_325i.html"))
    (page,) = json_ld(doc, "CollectionPage")
    assert page["url"] == PARTGRP_URL
    items = page["mainEntity"]["itemListElement"]
    assert len(items) == int(page["mainEntity"]["numberOfItems"]) == 39
    assert items[4] == {
        "@type": "ListItem",
        "position": 5,
        "url": PARTGRP_URL + "&mg=11",
        "name": "ENGINE",
    }
    (crumbs,) = json_ld(doc, "BreadcrumbList")
    assert crumbs["itemListElement"][1]["name"] == "BMW 3 Series E90 325i"
    assert json_ld(doc, "Product") == []


def test_json_ld_handles_graphs_lists_and_bad_json() -> None:
    doc = tree(
        '<script type="application/ld+json">{not json</script>'
        '<script type="application/ld+json">[{"@type": "ImageObject", "n": 1}]</script>'
        '<script type="application/ld+json">{"@graph": [{"@type": ["Thing", "ImageObject"]}]}'
        "</script>"
    )
    assert json_ld(doc, "ImageObject") == [
        {"@type": "ImageObject", "n": 1},
        {"@type": ["Thing", "ImageObject"]},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/parsers/test_common.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.parsers'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/parsers/__init__.py`:

```python
"""Pure HTML parsers: parse_<page>(html, *, url) -> model. No I/O."""
```

Create `server/src/realoem_mcp/parsers/common.py`:

```python
"""selectolax helpers and value parsers shared by every page parser (ARD section 5.9)."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from realoem_mcp.errors import LayoutChanged

Tree = LexborHTMLParser
Node = LexborNode

_MDY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_MY = re.compile(r"(\d{2})/(\d{4})")
_YYYYMM00 = re.compile(r"(\d{4})(\d{2})00")
_PRICE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")


def tree(html: str) -> Tree:
    return LexborHTMLParser(html)


def text(node: Node | None) -> str:
    """All text under node with whitespace collapsed; "" for None."""
    if node is None:
        return ""
    return " ".join(node.text(deep=True).split())


def require(root: Tree | Node, selector: str, page_type: str, url: str) -> Node:
    """First match of selector, or LayoutChanged when the page lacks it."""
    node = root.css_first(selector)
    if node is None:
        raise LayoutChanged(page_type, f"missing {selector!r}", url)
    return node


def parse_mdy(value: str) -> date | None:
    """First MM/DD/YYYY in value (e.g. "03/17/2006 (ENDED)") as a date; None if absent."""
    match = _MDY.search(value)
    if match is None:
        return None
    month, day, year = (int(group) for group in match.groups())
    return date(year, month, day)


def parse_my(value: str) -> str | None:
    """First MM/YYYY in value as "YYYY-MM"; None if absent."""
    match = _MY.search(value)
    if match is None:
        return None
    month, year = match.groups()
    return _year_month(year, month)


def parse_yyyymm00(value: str) -> str | None:
    """RealOEM prod code "20051000" as "2005-10"; None if value is not in that form."""
    match = _YYYYMM00.fullmatch(value.strip())
    if match is None:
        return None
    year, month = match.groups()
    return _year_month(year, month)


def parse_price_usd(value: str) -> float | None:
    """Price text such as "$1,234.56" as 1234.56; None when no price is shown."""
    match = _PRICE.search(value)
    if match is None:
        return None
    return float(match.group(1).replace(",", ""))


def canonical_url(root: Tree | Node) -> str | None:
    link = root.css_first('link[rel="canonical"]')
    if link is None:
        return None
    return link.attributes.get("href") or None


def json_ld(root: Tree | Node, type_: str) -> list[dict[str, Any]]:
    """Every JSON-LD object whose @type is type_, in document order. Invalid blocks are skipped."""
    found: list[dict[str, Any]] = []
    for script in root.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text(deep=True))
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            for obj in item.get("@graph", [item]):
                if isinstance(obj, dict) and _has_type(obj, type_):
                    found.append(obj)
    return found


def _has_type(obj: dict[str, Any], type_: str) -> bool:
    declared = obj.get("@type")
    return declared == type_ or (isinstance(declared, list) and type_ in declared)


def _year_month(year: str, month: str) -> str:
    if not 1 <= int(month) <= 12:
        raise ValueError(f"invalid month {month!r}")
    return f"{year}-{month}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/parsers/test_common.py -q`
Expected: PASS (`24 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/parsers server/tests/unit/parsers/test_common.py
git commit -m "feat(parsers): add shared selectolax and value helpers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 7: Services, MCP server, capture script, live test

### Task 16: Services container and `make_services`

ARD §5.2a and §8. `create_services` loads brands first (fails fast on a bad `brands_dir`), then
opens the cache and client. `aclose()` closes the client, the cache and every `extras` value that
has a `close()` method (awaited if it returns an awaitable); it attempts every close even if one
raises, then re-raises the first error. The `make_services` fixture (async, so only for
`@pytest.mark.anyio` tests) returns `(services, transport)` with a `FakeClock` (no real waiting) and
a per-call cache/data directory under `tmp_path`; its teardown first closes every `Services` it made,
then asserts `transport.unmatched == []`.

**Files:**
- Create: `server/src/realoem_mcp/services.py`
- Modify: `server/tests/conftest.py`
- Test: `server/tests/unit/test_services.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_services.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.services import Services, create_services
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio


class Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class AsyncClosable(Closable):
    async def close(self) -> None:  # type: ignore[override]
        self.closed = True


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR)


async def test_create_services_wires_settings_cache_client_and_brands(tmp_path: Path) -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport({target: Route()})
    clock = FakeClock()
    services = create_services(
        _settings(tmp_path), transport=transport, clock=clock, sleep=clock.sleep
    )
    try:
        assert isinstance(services, Services)
        assert services.cache.path.parent == tmp_path / "cache"
        assert len(services.brands) == 4
        assert services.extras == {}
        page = await services.client.fetch(PageType.PARTXREF, "partxref", {"q": "11427953129"})
        assert page.url == target
        assert services.cache.stats().entries == 1
    finally:
        await services.aclose()


async def test_aclose_closes_extras_with_a_close_method(tmp_path: Path) -> None:
    services = create_services(_settings(tmp_path))
    sync_extra, async_extra = Closable(), AsyncClosable()
    services.extras.update({"index": sync_extra, "other": async_extra, "plain": {"a": 1}})
    await services.aclose()
    assert sync_extra.closed
    assert async_extra.closed


class Broken:
    def close(self) -> None:
        raise RuntimeError("boom")


async def test_aclose_closes_everything_even_if_one_close_fails(tmp_path: Path) -> None:
    services = create_services(_settings(tmp_path))
    after = Closable()
    services.extras.update({"broken": Broken(), "after": after})
    with pytest.raises(RuntimeError, match="boom"):
        await services.aclose()
    assert after.closed
    with pytest.raises(sqlite3.ProgrammingError):
        services.cache.stats()  # the cache was closed too


async def test_make_services_fixture_returns_services_and_transport(make_services) -> None:
    params = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
    target = url("partgrp", **params)
    services, transport = make_services({target: "common/partgrp_e90_325i.html"})
    page = await services.client.fetch(PageType.PARTGRP, "partgrp", params)
    assert page.status == 200
    assert [str(r.url) for r in transport.requests] == [target]
    assert services.settings.min_interval_s == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_services.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.services'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/services.py`:

```python
"""Services container handed to every tool (ARD section 5.2a)."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import RealOemClient


@dataclass
class Services:
    settings: Settings
    cache: PageCache
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)  # branch-owned singletons

    async def aclose(self) -> None:
        """Close the client, the cache and every extra with close(); re-raise the first error."""
        closers: list[Callable[[], Any]] = [self.client.aclose, self.cache.close]
        for extra in self.extras.values():
            close = getattr(extra, "close", None)
            if callable(close):
                closers.append(close)
        errors: list[Exception] = []
        for close in closers:
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


def create_services(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Services:
    brands = BrandRegistry.load(settings.brands_dir)
    cache = PageCache(settings.cache_dir)
    client = RealOemClient(
        settings,
        cache,
        transport=transport,
        clock=clock or time.monotonic,
        sleep=sleep or asyncio.sleep,
    )
    return Services(settings=settings, cache=cache, client=client, brands=brands)
```

Replace the whole of `server/tests/conftest.py` with:

```python
"""Shared pytest fixtures. Helpers to import live in tests/harness.py (ARD section 8)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, MakeServices, Route


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def make_services(tmp_path: Path) -> AsyncIterator[MakeServices]:
    """make_services(routes) -> (services, transport), offline and with a fake clock.

    Async fixture: use it only from tests marked @pytest.mark.anyio. Teardown closes every
    Services it created, then fails the test if any request had no route.
    """
    created: list[tuple[Services, FixtureTransport]] = []

    def factory(routes: Mapping[str, Route | str]) -> tuple[Services, FixtureTransport]:
        n = len(created)
        transport = FixtureTransport(routes)
        clock = FakeClock()
        settings = Settings(
            cache_dir=tmp_path / f"cache{n}", data_dir=tmp_path / f"data{n}", brands_dir=BRANDS_DIR
        )
        services = create_services(settings, transport=transport, clock=clock, sleep=clock.sleep)
        created.append((services, transport))
        return services, transport

    yield factory
    for services, _ in created:
        await services.aclose()
    for _, transport in created:
        assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.live tests unless REALOEM_LIVE=1."""
    if os.environ.get("REALOEM_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set REALOEM_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest -q`
Expected: PASS (`180 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/services.py server/tests/conftest.py server/tests/unit/test_services.py
git commit -m "feat(server): add Services container and make_services fixture" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 17: Admin tools and `build_server`

ARD §5.10–§5.11 and AD15. `build_server` walks `realoem_mcp.tools` with `pkgutil.iter_modules` and
calls every module-level `register(app, services)`; feature branches add a module and never edit
`server.py`. Each tool is an `async def` with a docstring written for the model, catches
`RealOemError` and raises `ToolError(err.message)`, and returns a pydantic model. Admin tools are
exempt from `ResultMeta` and make no RealOEM request.

**Files:**
- Create: `server/src/realoem_mcp/tools/__init__.py`, `server/src/realoem_mcp/tools/admin.py`, `server/src/realoem_mcp/server.py`
- Test: `server/tests/tools/test_admin.py`, `server/tests/tools/test_server.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_admin.py`:

```python
import pytest
from mcp import Client

from realoem_mcp import __version__
from realoem_mcp.config import USER_AGENT
from realoem_mcp.page_types import PageType
from realoem_mcp.server import build_server
from tests.harness import url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
GRP_PARAMS = {"id": "VB13-USA-10-2005-E90-BMW-325i"}
GRP = url("partgrp", **GRP_PARAMS)
PAGE = "common/partgrp_e90_325i.html"


async def test_server_status_reports_settings_and_cache(make_services) -> None:
    services, transport = make_services({XREF: PAGE})
    await services.client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    async with Client(build_server(services)) as client:
        result = await client.call_tool("server_status", {})
    assert result.is_error is False
    status = result.structured_content
    assert status["version"] == __version__
    assert status["base_url"] == "https://www.realoem.com"
    assert status["user_agent"] == USER_AGENT
    assert status["min_interval_s"] == 2.0
    assert status["cache_path"] == str(services.cache.path)
    assert status["cache_entries"] == 1
    assert status["cache_bytes"] > 1000
    assert status["requests_made"] == 1
    assert len(transport.requests) == 1  # server_status itself makes no request


async def test_cache_clear_by_page_type_then_all(make_services) -> None:
    services, _ = make_services({XREF: PAGE, GRP: PAGE})
    await services.client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await services.client.fetch(PageType.PARTGRP, "partgrp", GRP_PARAMS)
    async with Client(build_server(services)) as client:
        by_type = await client.call_tool("cache_clear", {"page_type": "partgrp"})
        everything = await client.call_tool("cache_clear", {})
    assert by_type.structured_content == {"removed": 1}
    assert everything.structured_content == {"removed": 1}
    assert services.cache.stats().entries == 0


async def test_cache_clear_rejects_unknown_page_type(make_services) -> None:
    services, transport = make_services({})
    async with Client(build_server(services)) as client:
        result = await client.call_tool("cache_clear", {"page_type": "vin"})
    assert result.is_error is True
    assert "Unknown page type 'vin'" in result.content[0].text
    assert transport.requests == []
```

Create `server/tests/tools/test_server.py`:

```python
import pytest
from mcp import Client

from realoem_mcp.server import build_server

pytestmark = pytest.mark.anyio

ADMIN_TOOLS = {"server_status", "cache_clear"}


async def test_build_server_discovers_tool_modules(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services)
    assert app.name == "realoem"
    async with Client(app) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools.tools}
    assert names >= ADMIN_TOOLS
    for tool in tools.tools:
        assert tool.description, f"{tool.name} needs a docstring for the model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.server'`

- [ ] **Step 3: Write minimal implementation**

Create `server/src/realoem_mcp/tools/__init__.py`:

```python
"""MCP tools. build_server loads every module here that defines register(app, services)."""
```

Create `server/src/realoem_mcp/tools/admin.py`:

```python
"""Admin tools: server_status, cache_clear (ARD section 5.11). Exempt from ResultMeta."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from realoem_mcp import __version__
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.services import Services


class ServerStatus(BaseModel):
    version: str
    base_url: str
    user_agent: str
    min_interval_s: float
    cache_path: str
    cache_entries: int
    cache_bytes: int
    requests_made: int


class CacheClearResult(BaseModel):
    removed: int


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def server_status() -> ServerStatus:
        """Report this RealOEM server's version, request settings and cache size.

        Use it to troubleshoot (for example before telling the user RealOEM is unreachable) or
        when the user asks how the plugin talks to RealOEM. Makes no request to RealOEM.
        Returns version, base_url, user_agent, min_interval_s (seconds between requests),
        cache_path, cache_entries, cache_bytes and requests_made (HTTP requests sent to
        RealOEM since start, counting retries and redirect hops).
        """
        stats = services.cache.stats()
        return ServerStatus(
            version=__version__,
            base_url=services.settings.base_url,
            user_agent=services.settings.user_agent,
            min_interval_s=services.settings.min_interval_s,
            cache_path=str(stats.path),
            cache_entries=stats.entries,
            cache_bytes=stats.bytes,
            requests_made=services.client.requests_made,
        )

    @app.tool()
    async def cache_clear(page_type: str | None = None) -> CacheClearResult:
        """Delete cached RealOEM pages so the next lookups fetch fresh copies.

        Prefer refresh=true on a single data tool call; use this only when the user asks to clear
        the cache or many answers look stale. page_type limits the clear to one page type:
        select, production, partgrp, showparts, partxref, partsearch, part or vehicles. Omit it
        to clear everything. Returns removed (the number of cached pages deleted).
        """
        try:
            target = PageType.parse(page_type) if page_type is not None else None
        except RealOemError as err:
            raise ToolError(err.message) from err
        return CacheClearResult(removed=services.cache.clear(target))
```

Create `server/src/realoem_mcp/server.py` (Task 18 adds `main()`):

```python
"""MCP server entry point: build_server(services) and main() (stdio)."""

from __future__ import annotations

import importlib
import pkgutil

from mcp.server.mcpserver import MCPServer

import realoem_mcp.tools
from realoem_mcp import __version__
from realoem_mcp.services import Services

INSTRUCTIONS = (
    "Look up BMW, MINI, Rolls-Royce and BMW Motorrad OEM parts on RealOEM.com. Every RealOEM "
    "request is rate limited and cached, so call tools only for what the user asked, and include "
    "the source_urls from results when answering."
)


def build_server(services: Services) -> MCPServer:
    app = MCPServer("realoem", instructions=INSTRUCTIONS, version=__version__)
    package = realoem_mcp.tools
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(app, services)
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/tools -q`
Expected: PASS (`4 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/tools server/src/realoem_mcp/server.py server/tests/tools/test_admin.py server/tests/tools/test_server.py
git commit -m "feat(server): add MCP server with auto-discovered admin tools" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 18: stdio entry point (`main()`)

`main()` configures logging to **stderr** before anything else (stdout carries the MCP protocol;
`MCPServer` only calls `logging.basicConfig`, which is then a no-op), quiets the `httpx` logger to
WARNING (the client logs every request itself), builds `Settings.from_env()`,
and runs `run_stdio_async()` inside one event loop so `services.aclose()` runs on the same loop that
owns the httpx connections. The test starts the real module in a subprocess over stdio.

**Files:**
- Modify: `server/src/realoem_mcp/server.py`
- Test: `server/tests/tools/test_stdio.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/tools/test_stdio.py`:

```python
"""The real entry point: realoem_mcp.server.main() over stdio in a subprocess."""

import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from realoem_mcp import __version__
from tests.harness import BRANDS_DIR

pytestmark = pytest.mark.anyio


async def test_stdio_server_starts_and_lists_tools(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "realoem_mcp.server"],
        env={
            "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
            "REALOEM_DATA_DIR": str(tmp_path / "data"),
            "REALOEM_BRANDS_DIR": str(BRANDS_DIR),
        },
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        status = await client.call_tool("server_status", {})
    assert {tool.name for tool in tools.tools} >= {"server_status", "cache_clear"}
    assert status.structured_content["version"] == __version__
    assert status.structured_content["cache_path"].startswith(str(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/tools/test_stdio.py -q`
Expected: FAIL (`1 failed`): the module exits immediately, so the client's connection is closed before initialization.

- [ ] **Step 3: Write minimal implementation**

Replace the whole of `server/src/realoem_mcp/server.py` with:

```python
"""MCP server entry point: build_server(services) and main() (stdio)."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import sys

from mcp.server.mcpserver import MCPServer

import realoem_mcp.tools
from realoem_mcp import __version__
from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services

INSTRUCTIONS = (
    "Look up BMW, MINI, Rolls-Royce and BMW Motorrad OEM parts on RealOEM.com. Every RealOEM "
    "request is rate limited and cached, so call tools only for what the user asked, and include "
    "the source_urls from results when answering."
)


def build_server(services: Services) -> MCPServer:
    app = MCPServer("realoem", instructions=INSTRUCTIONS, version=__version__)
    package = realoem_mcp.tools
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(app, services)
    return app


async def _serve(settings: Settings) -> None:
    services = create_services(settings)
    try:
        await build_server(services).run_stdio_async()
    finally:
        await services.aclose()


def main() -> None:
    # stdout carries the MCP protocol; all logging goes to stderr.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the client logs each request itself
    asyncio.run(_serve(Settings.from_env()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/tools -q`
Expected: PASS (`5 passed`)

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/src/realoem_mcp/server.py server/tests/tools/test_stdio.py
git commit -m "feat(server): add stdio entry point" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 19: `capture_page.py`

ARD §8 fixture pipeline. Captures one page through `RealOemClient` (same UA, cookie, rate limit and
challenge detection as the server) with `refresh=True`, and writes `<name>.html` plus `<name>.headers`
into `.research-raw/<page-type>/`. The headers file has one block per request sent, labelled
`# attempt N: GET <url>` (a repeated URL is marked `(retry)`). A challenge raises `BotChallenge` and
writes nothing. One page per run; never loop it over many pages.

**Files:**
- Create: `server/scripts/capture_page.py`
- Test: `server/tests/unit/test_capture_page.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_capture_page.py`:

```python
from pathlib import Path

import httpx
import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import BotChallenge
from realoem_mcp.page_types import PageType
from scripts.capture_page import capture, format_headers, parse_params
from tests.harness import BRANDS_DIR, LANDING_URL, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR)


def test_parse_params_keeps_order() -> None:
    assert list(parse_params(["q=11427953129", "series=E90"]).items()) == [
        ("q", "11427953129"),
        ("series", "E90"),
    ]
    with pytest.raises(ValueError, match="key=value"):
        parse_params(["q"])


def test_format_headers_labels_each_attempt() -> None:
    request = httpx.Request("GET", "https://www.realoem.com/bmw/enUS/partgrp?id=VB13")
    moved = httpx.Response(301, headers={"Location": "/bmw/", "X-RO-UI": "v2"}, request=request)
    busy = httpx.Response(503, request=request)
    assert format_headers([moved, busy]) == (
        "# attempt 1: GET https://www.realoem.com/bmw/enUS/partgrp?id=VB13\n"
        "HTTP/1.1 301 Moved Permanently\nlocation: /bmw/\nx-ro-ui: v2\n"
        "\n"
        "# attempt 2: GET https://www.realoem.com/bmw/enUS/partgrp?id=VB13 (retry)\n"
        "HTTP/1.1 503 Service Unavailable\n"
    )


async def test_capture_writes_html_and_headers(tmp_path: Path) -> None:
    target = url("partgrp", id="VB13")
    redirect = Route(redirect_to=LANDING_URL, headers={"X-RO-UI": "v2"})
    transport = FixtureTransport({target: redirect})
    html_path, headers_path = await capture(
        PageType.PARTGRP,
        "typecode_only",
        {"id": "VB13"},
        settings=_settings(tmp_path),
        out_dir=tmp_path / "raw",
        transport=transport,
    )
    assert html_path == tmp_path / "raw" / "partgrp" / "typecode_only.html"
    assert html_path.read_text(encoding="utf-8") == ""
    headers = headers_path.read_text(encoding="utf-8")
    assert headers.startswith(f"# attempt 1: GET {target}\nHTTP/1.1 301 Moved Permanently\n")
    assert "location: https://www.realoem.com/bmw/" in headers
    assert "\n\n# attempt 2: GET https://www.realoem.com/bmw/\nHTTP/1.1 200 OK\n" in headers
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]


async def test_capture_refuses_challenge_pages(tmp_path: Path) -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport(
        {target: Route("common/cloudflare_challenge.html", 403, {"cf-mitigated": "challenge"})}
    )
    with pytest.raises(BotChallenge):
        await capture(
            PageType.PARTXREF,
            "blocked",
            {"q": "11427953129"},
            settings=_settings(tmp_path),
            out_dir=tmp_path / "raw",
            transport=transport,
        )
    assert not (tmp_path / "raw").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_capture_page.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.capture_page'`

- [ ] **Step 3: Write minimal implementation**

Create `server/scripts/capture_page.py`:

```python
"""Politely capture one RealOEM page (raw HTML + response headers) into .research-raw/.

One page per run; do not loop this script over many pages.

Goes through RealOemClient, so the user agent, cookie, rate limit and challenge detection are the
same as the server's. Raw captures are git-ignored; turn them into fixtures with trim_fixture.py.

Usage (from server/):
    uv run python scripts/capture_page.py partxref oil_filter_series q=11427953129 series=E90
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.services import create_services

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / ".research-raw"


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wraps a transport and keeps every response (redirect hops included) for the headers file."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.responses: list[httpx.Response] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        self.responses.append(response)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def parse_params(pairs: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        params[key] = value
    return params


def format_headers(responses: Sequence[httpx.Response]) -> str:
    """One block per request sent; redirect hops and retried attempts each get their own."""
    blocks = []
    seen: set[str] = set()
    for number, response in enumerate(responses, start=1):
        url = str(response.request.url)
        label = f"# attempt {number}: GET {url}" + (" (retry)" if url in seen else "")
        seen.add(url)
        lines = [label, f"HTTP/1.1 {response.status_code} {response.reason_phrase}"]
        lines += [f"{name}: {value}" for name, value in response.headers.multi_items()]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


async def capture(
    page_type: PageType,
    name: str,
    params: Mapping[str, str],
    *,
    settings: Settings,
    out_dir: Path = DEFAULT_OUT_DIR,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[Path, Path]:
    recorder = RecordingTransport(transport)
    services = create_services(settings, transport=recorder)
    try:
        page = await services.client.fetch(page_type, page_type.value, params, refresh=True)
    finally:
        await services.aclose()
    folder = out_dir / page_type.value
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{name}.html"
    headers_path = folder / f"{name}.headers"
    html_path.write_text(page.html, encoding="utf-8", newline="\n")
    headers_path.write_text(format_headers(recorder.responses), encoding="utf-8", newline="\n")
    return html_path, headers_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture one RealOEM page into .research-raw/. One page per run; do not loop."
    )
    parser.add_argument("page_type", choices=[p.value for p in PageType])
    parser.add_argument("name", help="file name without extension, e.g. oil_filter_series")
    parser.add_argument("params", nargs="*", help="query parameters as key=value, in send order")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    try:
        html_path, headers_path = asyncio.run(
            capture(
                PageType(args.page_type),
                args.name,
                parse_params(args.params),
                settings=Settings.from_env(),
                out_dir=args.out_dir,
            )
        )
    except (RealOemError, ValueError) as err:
        print(f"capture failed: {err}", file=sys.stderr)
        return 1
    print(f"wrote {html_path} and {headers_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_capture_page.py -q`
Expected: PASS (`4 passed`)

Run: `uv run --directory server python scripts/capture_page.py --help`
Expected: PASS; usage text starting `usage: capture_page.py [-h] [--out-dir OUT_DIR]` and the line
`One page per run; do not loop.` (no request is made).

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/scripts/capture_page.py server/tests/unit/test_capture_page.py
git commit -m "feat(scripts): add polite capture_page script" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 20: Opt-in live smoke test

ARD §8: live tests carry `@pytest.mark.live`, are deselected by default (`-m "not live"` in
`addopts`) and skipped unless `REALOEM_LIVE=1` (conftest hook). This one makes exactly one request
and proves the honest User-Agent receives the v2 page (AD13). Do **not** run it with
`REALOEM_LIVE=1` while implementing; CI never runs it.

**Files:**
- Test: `server/tests/live/test_live_client.py`

- [ ] **Step 1: Write the test**

Create `server/tests/live/test_live_client.py`:

```python
"""Opt-in live smoke test (1 request): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_honest_user_agent_gets_the_v2_page(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        page = await services.client.fetch(PageType.PARTXREF, "partxref", {"q": "11427953129"})
    finally:
        await services.aclose()
    assert page.status == 200
    assert not page.redirected_away
    assert "11427953129" in page.html
```

- [ ] **Step 2: Verify it is deselected by default**

Run: `uv run --directory server pytest tests/live -q; echo "exit=$?"`
Expected: PASS (`1 deselected`, `exit=5`: pytest exits with 5 when every collected test is deselected)

- [ ] **Step 3: Verify it is skipped without `REALOEM_LIVE=1`**

Run: `uv run --directory server pytest tests/live -q -m live`
Expected: PASS (`1 skipped`)

- [ ] **Step 4: Lint**

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: PASS (`All checks passed!`)

- [ ] **Step 5: Commit**

```bash
git add server/tests/live/test_live_client.py
git commit -m "test(live): add opt-in live smoke test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Chunk 8: Plugin packaging, docs, CI, delivery

### Task 21: Plugin and marketplace manifests

ARD §5.1. `plugin.json` is exactly the ARD manifest. `marketplace.json` lists this repository as its
only plugin (`"source": "."`); it also carries a top-level `description`, which
`claude plugin validate --strict` requires. A test keeps the versions equal everywhere and pins the
MCP launch command to the console script.

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Test: `server/tests/unit/test_manifests.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/unit/test_manifests.py`:

```python
"""Plugin manifests, pyproject and __version__ stay consistent (ARD sections 5.1 and 7)."""

import json
import tomllib

from realoem_mcp import __version__
from tests.harness import REPO_ROOT

PLUGIN = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MARKETPLACE = json.loads(
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
)
PYPROJECT = tomllib.loads((REPO_ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8"))


def test_versions_are_equal_everywhere() -> None:
    (entry,) = MARKETPLACE["plugins"]
    assert PLUGIN["version"] == entry["version"] == PYPROJECT["project"]["version"] == __version__


def test_marketplace_lists_this_repo_as_the_plugin() -> None:
    assert MARKETPLACE["name"] == "realoem-searcher"
    assert MARKETPLACE["owner"] == {"name": "Cadtastic"}
    (entry,) = MARKETPLACE["plugins"]
    assert (entry["name"], entry["source"]) == ("realoem-searcher", ".")


def test_mcp_server_launches_the_console_script_with_uv() -> None:
    server = PLUGIN["mcpServers"]["realoem"]
    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--quiet",
        "--directory",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "realoem-mcp",
    ]
    assert server["env"] == {"REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands"}
    assert PYPROJECT["project"]["scripts"]["realoem-mcp"] == "realoem_mcp.server:main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --directory server pytest tests/unit/test_manifests.py -q`
Expected: FAIL with `FileNotFoundError` (no such file: `plugin.json`)

- [ ] **Step 3: Write minimal implementation**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "realoem-searcher",
  "version": "0.1.0",
  "description": "Search and cross-reference BMW, MINI, Rolls-Royce and BMW Motorrad OEM part numbers on RealOEM.com",
  "author": { "name": "Cadtastic" },
  "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
  "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
  "license": "MIT",
  "mcpServers": {
    "realoem": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "${CLAUDE_PLUGIN_ROOT}/server", "realoem-mcp"],
      "env": { "REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands" }
    }
  }
}
```

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "realoem-searcher",
  "owner": {
    "name": "Cadtastic"
  },
  "description": "RealOEM Searcher: BMW Group OEM parts lookups on RealOEM.com for Claude",
  "plugins": [
    {
      "name": "realoem-searcher",
      "source": ".",
      "description": "Search and cross-reference BMW, MINI, Rolls-Royce and BMW Motorrad OEM part numbers on RealOEM.com",
      "version": "0.1.0",
      "author": {
        "name": "Cadtastic"
      },
      "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
      "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
      "license": "MIT"
    }
  ]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --directory server pytest tests/unit/test_manifests.py -q`
Expected: PASS (`3 passed`)

Run: `claude plugin validate . --strict && claude plugin validate .claude-plugin/plugin.json --strict`
Expected: `✔ Validation passed` twice. If `claude` is not on `PATH` (e.g. only the desktop app is
installed), use its bundled CLI, for example on Windows
`"$APPDATA/Claude/claude-code/<version>/claude.exe" plugin validate . --strict`, or skip this check
and note it in the PR.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json server/tests/unit/test_manifests.py
git commit -m "feat(plugin): add plugin and marketplace manifests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 22: README and LICENSE

**Files:**
- Create: `README.md`, `LICENSE`

- [ ] **Step 1: Write the license**

Create `LICENSE`:

```text
MIT License

Copyright (c) 2026 Cadtastic

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Write the README**

Create `README.md`:

````markdown
# RealOEM Searcher

A Claude Code plugin that answers BMW Group parts questions (BMW, MINI, Rolls-Royce and BMW
Motorrad) from [RealOEM.com](https://www.realoem.com/bmw/enUS/select): part-number lookups,
VIN decoding, parts diagrams, fitment checks and supersession chains. It bundles a small local MCP
server (`server/`) that fetches and parses RealOEM pages on demand, plus skills that teach Claude
how to use it.

## Install

Requirement: [uv](https://docs.astral.sh/uv/getting-started/installation/) on your `PATH`. uv
installs Python and the server's dependencies on first start; nothing else to set up.

In Claude Code:

```
/plugin marketplace add Cadtastic/RealOEM-Searcher
/plugin install realoem-searcher@realoem-searcher
```

## Politeness

RealOEM is a free community resource with no API. This plugin treats it as a reference, not a data
source to mirror:

- At most one request in flight and at least 2 seconds between requests (never less than 1 s).
- Every page is cached locally (1 to 180 days by page type), so repeat questions cost nothing.
- Requests identify themselves honestly:
  `RealOEM-Searcher/<version> (+https://github.com/Cadtastic/RealOEM-Searcher)`.
- No crawling, no background or speculative fetching, no use of RealOEM data for AI training.
- If RealOEM shows a bot challenge, the plugin stops and tells you; it never tries to get around it.

## Configuration

Environment variables read by the server (all optional):

| Variable | Default |
|---|---|
| `REALOEM_MIN_INTERVAL` | `2.0` seconds between requests (values below 1.0 become 1.0) |
| `REALOEM_TIMEOUT` | `20.0` seconds |
| `REALOEM_CACHE_DIR` | the user cache directory for `realoem-searcher` |
| `REALOEM_DATA_DIR` | the user data directory for `realoem-searcher` |
| `REALOEM_BASE_URL` | `https://www.realoem.com` |
| `REALOEM_BRANDS_DIR` | `brands/` in this repository (set by the plugin) |

## Development

```bash
cd server
uv sync                      # create .venv with runtime + dev dependencies
uv run pytest                # offline test suite (live tests are skipped)
uv run ruff check            # lint
uv run ruff format           # format
uv run realoem-mcp           # run the MCP server on stdio (Ctrl+C to stop)
```

Live smoke tests send a few real requests and are opt-in:

```bash
REALOEM_LIVE=1 uv run pytest -m live tests/live
```

Test fixtures are trimmed real pages. Capture a page politely, then trim it:

```bash
uv run python scripts/capture_page.py partxref oil_filter q=11427953129
uv run python scripts/trim_fixture.py ../.research-raw/partxref/oil_filter.html \
    tests/fixtures/partxref/oil_filter.html
```

`.research-raw/` is git-ignored; never commit raw pages.

Design documents: [PRD](docs/PRD.md), [ARD](docs/ARD.md),
[RealOEM site notes](docs/research/realoem-site-notes.md).

## License

[MIT](LICENSE). RealOEM is an independent site not affiliated with this project or with BMW AG.
````

- [ ] **Step 3: Check the commands the README documents**

Run: `uv run --directory server python scripts/trim_fixture.py --help`
Expected: PASS; usage text starting `usage: trim_fixture.py [-h] raw out`.

- [ ] **Step 4: Check links**

Run: `ls docs/PRD.md docs/ARD.md docs/research/realoem-site-notes.md LICENSE`
Expected: PASS; all four paths listed (the README links to them).

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE
git commit -m "docs: add README and MIT license" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 23: CI workflow

ARD §8: `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest -m "not live"` on ubuntu
(Python 3.11 and 3.13) and windows (3.13), working directory `server`. The workflow token is
read-only (`permissions: contents: read`) and a new push cancels the in-progress run for the same
ref (`concurrency`).

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: ${{ matrix.os }} / Python ${{ matrix.python }}
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            python: "3.11"
          - os: ubuntu-latest
            python: "3.13"
          - os: windows-latest
            python: "3.13"
    defaults:
      run:
        working-directory: server
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: ${{ matrix.python }}
          enable-cache: true
          cache-dependency-glob: server/uv.lock
      - name: Install dependencies
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check
      - name: Check formatting
        run: uv run ruff format --check
      - name: Test (offline)
        run: uv run pytest -m "not live"
```

- [ ] **Step 2: Run the CI steps locally**

Run: `uv sync --directory server --locked && uv run --directory server ruff check && uv run --directory server ruff format --check && uv run --directory server pytest -m "not live" -q`
Expected: PASS (`All checks passed!`, `192 passed, 1 deselected`)

- [ ] **Step 3: Lint the workflow (optional)**

Run `actionlint .github/workflows/ci.yml` if actionlint is installed. Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint and offline test workflow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 24: Final verification and pull request

- [ ] **Step 1: Full offline suite and lint from a clean environment**

```bash
rm -rf server/.venv
uv sync --directory server --locked
uv run --directory server pytest -q
uv run --directory server ruff check
uv run --directory server ruff format --check
```

Expected: `192 passed, 1 deselected`, `All checks passed!`, `44 files already formatted`.

- [ ] **Step 2: Smoke-test the exact plugin launch command over stdio**

This starts the server the way Claude Code will (`uv run --quiet --directory <root>/server
realoem-mcp` with `REALOEM_BRANDS_DIR`), lists the tools and calls `server_status`. It makes no
request to RealOEM (it creates an empty cache database in your user cache directory).

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
        status = await client.call_tool("server_status", {})
        print("status:", status.structured_content)


asyncio.run(main())
EOF
```

Expected: `tools: ['cache_clear', 'server_status']` and a `status:` line with `'version': '0.1.0'`,
`'user_agent': 'RealOEM-Searcher/0.1.0 (+https://github.com/Cadtastic/RealOEM-Searcher)'`,
`'min_interval_s': 2.0` and `'requests_made': 0`.

Optional end-to-end check in Claude Code: `/plugin marketplace add <path to this checkout>`, then
`/plugin install realoem-searcher@realoem-searcher`, restart, run `/mcp` and confirm the `realoem`
server is connected with `server_status` and `cache_clear`.

- [ ] **Step 3: Validate the plugin**

Run: `claude plugin validate . --strict && claude plugin validate .claude-plugin/plugin.json --strict`
Expected: `✔ Validation passed` twice (see Task 21 if `claude` is not on `PATH`).

- [ ] **Step 4: Confirm nothing raw, generated or VIN-like is committed**

Run: `git status --short && git ls-files | grep -E '^\.research-raw/|\.sqlite3$|\.venv/' || echo clean`
Expected: no `git status` output and `clean`.

Run: `git grep -nE '[A-HJ-NPR-Z0-9]{17}' -- ':(exclude)server/uv.lock' | grep -vE 'X{10}[A-HJ-NPR-Z0-9]{7}|WBATEST0000000001' || echo "no VIN leaks"`
Expected: `no VIN leaks`. Any other hit must be inspected; a real VIN must be masked or removed
(re-run `trim_fixture.py` for fixtures) before pushing.

- [ ] **Step 5: Push and open the pull request**

```bash
git push -u origin feat/foundation
gh pr create --base main --head feat/foundation --title "feat: foundation (MCP server skeleton, polite client, cache, brands, CI)" --body "$(cat <<'EOF'
## Summary

Implements PRD F0 (foundation) per ARD §3–§8:

- Plugin + single-plugin marketplace manifests (`realoem-searcher`), MIT license, README.
- uv project `server/` (`realoem-mcp` 0.1.0, mcp 2.x `MCPServer`), stdio entry point, logging to stderr.
- `RealOemClient`: one request in flight, ≥ 2 s spacing (never < 1 s), honest User-Agent, only `Cookie: ro_ui=v2`, Cloudflare challenge → `BotChallenge` (never retried), retries on 429/5xx/timeouts, `X-RO-UI` check, redirect-away detection.
- SQLite page cache with per-page-type TTLs, `shorten`, `clear`, `stats`, schema versioning.
- Brand registry (`brands/*/brand.toml` for BMW, MINI, Rolls-Royce, Motorrad), vehicle-id parser, shared models (`ResultMeta`, `VehicleRef.from_id`, `DiagramRef.build`), parser helpers.
- Tools: `server_status`, `cache_clear` (auto-discovered from `realoem_mcp.tools`).
- Offline test harness (`tests/harness.py`, `make_services`), fixture tooling (`trim_fixture.py`, `capture_page.py`), trimmed fixtures, CI on ubuntu 3.11/3.13 and windows 3.13.

## Test plan

- [x] `uv run pytest` (offline) and `uv run ruff check` / `ruff format --check`
- [x] stdio smoke test with the plugin's launch command (`server_status`, `cache_clear` listed)
- [ ] `claude plugin validate . --strict` (tick only if Step 3 ran; otherwise replace this line with "skipped: claude CLI not available")
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the branch is pushed and `gh` prints the pull request URL. Wait for CI to pass before
asking for review.
