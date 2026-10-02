# Hosted Server, Plan 1a: Shared-Mode Core Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the existing MCP server a "shared" (hosted) mode that many signed-in users can use at once: per-user daily quotas, queue admission and a per-call deadline in front of the one polite RealOEM client, VIN pages cached per user, a size-capped shared cache that copes with a full disk, and the tool changes that a shared server needs. Everything is testable offline through the in-memory MCP client; there is no HTTP server, sign-in or deployment yet.

**Architecture:** `Settings.mode` ("stdio" by default, "http" only for the hosted server) switches every shared-mode behaviour, so the stdio plugin and its 942 tests keep passing. The caller is read from the access token the MCP SDK puts in its auth context (`current_user.py`); tests set that context directly (`tests/auth_helpers.py`). `RealOemClient` gains three optional hooks (`admit` before waiting for the request lock, `charge` inside it on a cache miss, `owner` for per-user cache entries); `shared.build_shared()` wires them to `Quota` (SQLite `usage` table) and `FetchGate`. `PageCache` gains an `owner` column, constant-time size accounting, an LRU cap with incremental vacuum, a free-space floor and a `reset()` for a full disk.

**Tech Stack:** Python ≥ 3.11, mcp 2.2 (`MCPServer`, `ServerMiddleware`, `mcp.server.auth.middleware.auth_context`), httpx, SQLite (stdlib `sqlite3`), pytest + AnyIO, ruff. Spec: `docs/superpowers/specs/2026-10-01-hosted-server-design.md` (sections 4.1, 4.2, 4.7, 4.8). This is plan 1a of three: **1b** adds sign-in (OAuth provider, store, keys, GitHub login, consent pages, middleware) and the `realoem-mcp-http` entry point; **2** deploys to Fly.io and releases 0.2.0.

---

## Before you start

- This plan is merged to `main` before execution starts, so the worktree has it. Track progress in
  your task list, not by committing ticked checkboxes: Task 14 checks that nothing under `docs/`
  changed.
- Work in a git worktree on branch `feat/hosted-shared-core`, created from an up-to-date `origin/main`
  (Task 0). Every command below runs from the **worktree root**. Python commands use
  `uv run --directory server …`; paths after it (like `tests/unit/test_quota.py`) are relative to
  `server/`. `git` paths are relative to the worktree root. Shell: Git Bash on Windows, or any
  POSIX shell.
- Read the spec sections 4.1, 4.2, 4.7 and 4.8 once. Read `server/src/realoem_mcp/http_client.py`,
  `cache.py`, `services.py` and `tools/admin.py` before Tasks 5–11; they change.
- **Never send a request to realoem.com** and never set `REALOEM_LIVE=1`. Every test is offline:
  `FixtureTransport` serves canned pages, `FakeClock` makes the 2-second spacing instant.
- TDD: write the test, run it and see it fail for the stated reason, then implement, then see it
  pass. The code blocks in this plan were run, task by task, on a clean worktree: with all tasks
  applied the suite is `1057 passed, 6 deselected` and ruff is clean. Copy code exactly.
- Commit messages are Conventional Commits. End each with a blank line and a `Co-Authored-By:`
  trailer naming the model that wrote the code. The commit commands below show
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`:
  **replace the model name with your own**; that is the one thing in this plan not to copy
  literally.
- Do not change versions (they stay `0.1.0` until plan 2) and do not commit anything under `docs/`.
- What this plan leaves to plan 1b (the HTTP entry point), so it is written down once: install
  `CallClock` with the clock the gate uses (Task 3); keep the `httpx` logger at WARNING, as
  `server.main()` does, and install a log filter for the SDK's tool-error lines (Task 6); call
  `PageCache.reset()` when another database finds the disk full (Task 5); create the `usage`
  table in the auth database's migrations with `USAGE_SCHEMA` (Task 7); derive `owner_key` from
  the server secret (Task 9).
- What this plan leaves to plan 2's documentation update (the spec is amended in this plan's own
  pull request): the README and ARD name the cache file `pages.v2.sqlite3`; `server_status`
  returns `cache_path: null` on the hosted server rather than omitting it; the client has a
  third hook, `owner`; the server-wide usage row is counted even while its cap is off; an unknown
  GitHub account age gets the new-account limit; the `vehicle-index` skill's wording about the
  index being "stored on this computer".

## File structure

New files (each with one job):

| File | Responsibility |
|---|---|
| `server/src/realoem_mcp/current_user.py` | The signed-in caller (`current_user`, `require_user`) and `CallClock`, the middleware that stamps when each tool call started |
| `server/src/realoem_mcp/quota.py` | `Quota`: per-user daily request counts in a SQLite `usage` table; new-account limit; optional server-wide cap |
| `server/src/realoem_mcp/gate.py` | `FetchGate`: whether a cache-miss fetch may queue for RealOEM, and for how long |
| `server/src/realoem_mcp/shared.py` | `build_shared()`: Services wired with the quota, the gate and per-user VIN cache owners |
| `server/tests/auth_helpers.py` | `signed_in(subject)`: act as a signed-in user in tests |
| `server/tests/shared_env.py` | `shared_services()` and `call_tool()`: offline hosted-mode Services for tool tests |

Changed files: `errors.py` (3 errors), `config.py` (hosted settings), `server.py`
(`build_server` keyword arguments), `cache.py` (owners, size accounting, cap, disk handling),
`http_client.py` (`Page.owner`, hooks, refresh throttle, VIN-free logs), `services.py`
(hooks and cache limits), `tools/vin.py`, `tools/catalog.py`, `tools/parts.py` (cache entries
are shortened in their owner's row), `tools/admin.py`, `tools/fitment.py`, `tools/vehicles.py`,
`models/vehicles.py`, `skills/vehicle-index/SKILL.md` and its test.

## Chunk 1: Foundations

### Task 0: Branch and baseline

- [ ] **Step 1: Create the worktree from an up-to-date main.** The first line keeps `.worktrees/`
  out of `git status` in a fresh clone (a local setting, never committed).

````bash
git check-ignore -q .worktrees/ || echo ".worktrees/" >> .git/info/exclude
git fetch origin
git worktree add .worktrees/hosted-shared-core -b feat/hosted-shared-core --no-track origin/main
cd .worktrees/hosted-shared-core
````

- [ ] **Step 2: Record the baseline**

Run: `uv run --directory server pytest -q`
Expected: `942 passed, 6 deselected`. If not, stop and report: main is not green.

### Task 1: Hosted errors

`QuotaExceeded`, `Busy` and `CallDeadline` are `RealOemError`s, so every tool already turns them
into a user-facing tool error.

**Files:**
- Modify: `server/src/realoem_mcp/errors.py` (append three classes)
- Test: `server/tests/unit/test_errors_hosted.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_errors_hosted.py`:

````python
"""Errors of the hosted server: quota, busy and call-deadline messages (hosted design 4.7)."""

from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded, RealOemError


def test_quota_exceeded_names_the_callers_limit() -> None:
    err = QuotaExceeded(300)
    assert isinstance(err, RealOemError)
    assert (err.limit, err.server_wide) == (300, False)
    assert err.message == (
        "You've used your 300 RealOEM lookups for today; the limit resets at 00:00 UTC. "
        "Cached results remain available."
    )


def test_server_wide_quota_message_names_no_number() -> None:
    err = QuotaExceeded(2000, server_wide=True)
    assert (err.limit, err.server_wide) == (2000, True)
    assert err.message == (
        "RealOEM Searcher has reached its daily request limit; try again after 00:00 UTC."
    )


def test_busy_and_call_deadline_are_user_facing_errors() -> None:
    assert isinstance(Busy(), RealOemError)
    assert isinstance(CallDeadline(), RealOemError)
    assert Busy().message == "RealOEM Searcher is busy; try again in a minute."
    assert CallDeadline().message == (
        "This call took too long; call again to continue (pages already fetched are cached)."
    )
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_errors_hosted.py`
Expected: FAIL with `ImportError: cannot import name 'Busy'`.

- [ ] **Step 3: Implement.** Append to `server/src/realoem_mcp/errors.py` (after `UpstreamError`):

````python
class QuotaExceeded(RealOemError):
    """The caller (or, with server_wide, the whole server) used up the day's RealOEM requests."""

    def __init__(self, limit: int, *, server_wide: bool = False) -> None:
        self.limit = limit
        self.server_wide = server_wide
        if server_wide:
            message = (
                "RealOEM Searcher has reached its daily request limit; try again after 00:00 UTC."
            )
        else:
            message = (
                f"You've used your {limit} RealOEM lookups for today; the limit resets at "
                "00:00 UTC. Cached results remain available."
            )
        super().__init__(message)


class Busy(RealOemError):
    """Too many requests are already waiting for RealOEM; nothing was charged."""

    def __init__(self) -> None:
        super().__init__("RealOEM Searcher is busy; try again in a minute.")


class CallDeadline(RealOemError):
    """The tool call ran out of time before it could make its next RealOEM request."""

    def __init__(self) -> None:
        super().__init__(
            "This call took too long; call again to continue (pages already fetched are cached)."
        )
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_errors_hosted.py`
Expected: `3 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `945 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/errors.py server/tests/unit/test_errors_hosted.py
git commit -m "feat(hosted): add quota, busy and call-deadline errors" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 2: Hosted settings

`Settings` gains the mode and the hosted limits. `mode` is never read from the environment: only the
HTTP entry point (plan 1b) sets it. The cache cap (`cache_max_bytes`) is on in HTTP mode, and in
stdio only when `cache_max_mb` is set; the free-space floor (`cache_min_free_bytes`) is HTTP-only.
Bad values fail at construction: negative or fractional counts, a deadline that is not a positive
finite number, and admins that are not `github:<id>` subjects.

**Files:**
- Modify: `server/src/realoem_mcp/config.py` (replace the whole file)
- Test: `server/tests/unit/test_config_hosted.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_config_hosted.py`:

````python
"""Settings of the hosted ("http") mode (hosted design 4.1, 4.8)."""

import pytest

from realoem_mcp.config import Settings

MB = 1024 * 1024


def test_stdio_defaults_leave_every_hosted_feature_off() -> None:
    settings = Settings()
    assert settings.mode == "stdio"
    assert settings.admins == frozenset()
    assert (settings.user_daily_limit, settings.new_user_daily_limit) == (300, 30)
    assert settings.min_account_age_days == 30
    assert settings.global_daily_limit == 0
    assert settings.call_deadline_s == 50.0
    assert settings.cache_max_mb is None
    assert (settings.cache_max_bytes, settings.cache_min_free_bytes) == (0, 0)


def test_http_mode_turns_on_the_cache_cap_and_the_free_space_floor() -> None:
    settings = Settings(mode="http")
    assert settings.cache_max_bytes == 400 * MB
    assert settings.cache_min_free_bytes == 100 * MB
    assert Settings(mode="http", cache_max_mb=0).cache_max_bytes == 0
    assert Settings(cache_max_mb=5).cache_max_bytes == 5 * MB  # stdio can opt in


def test_from_env_reads_the_hosted_settings_but_never_the_mode() -> None:
    settings = Settings.from_env(
        {
            "REALOEM_MODE": "http",  # not a setting: only the HTTP entry point sets the mode
            "REALOEM_ADMINS": " 123, 456 ,",
            "REALOEM_USER_DAILY_LIMIT": "50",
            "REALOEM_NEW_USER_DAILY_LIMIT": "5",
            "REALOEM_MIN_ACCOUNT_AGE_DAYS": "7",
            "REALOEM_GLOBAL_DAILY_LIMIT": "2000",
            "REALOEM_CALL_DEADLINE_S": "40",
            "REALOEM_CACHE_MAX_MB": "100",
        }
    )
    assert settings.mode == "stdio"
    assert settings.admins == frozenset({"github:123", "github:456"})
    assert (settings.user_daily_limit, settings.new_user_daily_limit) == (50, 5)
    assert (settings.min_account_age_days, settings.global_daily_limit) == (7, 2000)
    assert settings.call_deadline_s == 40.0
    assert settings.cache_max_bytes == 100 * MB


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REALOEM_USER_DAILY_LIMIT", "-1"),
        ("REALOEM_NEW_USER_DAILY_LIMIT", "many"),
        ("REALOEM_MIN_ACCOUNT_AGE_DAYS", "1.5"),
        ("REALOEM_GLOBAL_DAILY_LIMIT", "x"),
        ("REALOEM_CACHE_MAX_MB", "1.5"),
        ("REALOEM_CALL_DEADLINE_S", "0"),
        ("REALOEM_CALL_DEADLINE_S", "soon"),
        ("REALOEM_ADMINS", "octocat"),
    ],
)
def test_a_bad_hosted_value_names_its_variable(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


def test_mode_must_be_stdio_or_http() -> None:
    with pytest.raises(ValueError, match="mode must be 'stdio' or 'http'"):
        Settings(mode="cli")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"user_daily_limit": -1},
        {"global_daily_limit": 1.5},
        {"min_account_age_days": True},
        {"cache_max_mb": -1},
        {"call_deadline_s": 0},
        {"call_deadline_s": float("inf")},
        {"call_deadline_s": True},
        {"admins": "github:1"},  # a string, not a set of subjects
        {"admins": frozenset({"123"})},  # a bare id
    ],
)
def test_bad_direct_values_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=next(iter(kwargs))):
        Settings(**kwargs)  # type: ignore[arg-type]
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_config_hosted.py`
Expected: FAIL: `AttributeError: 'Settings' object has no attribute 'mode'` and similar.

- [ ] **Step 3: Implement.** Replace `server/src/realoem_mcp/config.py` with:

````python
"""Runtime settings. Every field except mode, lang and user_agent can be set by environment."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import platformdirs

from realoem_mcp import __version__

REPO_URL = "https://github.com/Cadtastic/RealOEM-Searcher"
USER_AGENT = f"RealOEM-Searcher/{__version__} (+{REPO_URL})"
MIN_INTERVAL_FLOOR_S = 1.0
HTTP_CACHE_MAX_MB = 400  # at most 40 % of the hosted server's 1 GB volume
CACHE_MIN_FREE_MB = 100  # hosted server: below this much free disk, stop caching
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
    # Hosted ("http") mode. The mode is set by the entry point, never by the environment.
    mode: Literal["stdio", "http"] = "stdio"
    admins: frozenset[str] = frozenset()  # subjects, e.g. "github:1234"
    user_daily_limit: int = 300  # cache-miss page fetches per user per UTC day; 0 = unlimited
    new_user_daily_limit: int = 30  # the same for GitHub accounts younger than the age below
    min_account_age_days: int = 30
    global_daily_limit: int = 0  # server-wide cap on the same count; 0 = off
    call_deadline_s: float = 50.0  # a tool call older than this starts no new RealOEM request
    cache_max_mb: int | None = None  # None = HTTP_CACHE_MAX_MB in http mode, no cap in stdio
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

    def __post_init__(self) -> None:
        for name in ("min_interval_s", "timeout_s"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number, got {getattr(self, name)!r}")
        if float(self.timeout_s) <= 0:
            raise ValueError(f"timeout_s must be greater than 0, got {self.timeout_s!r}")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(
            self, "min_interval_s", max(float(self.min_interval_s), MIN_INTERVAL_FLOOR_S)
        )
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        object.__setattr__(self, "cache_dir", Path(self.cache_dir).expanduser())
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser())
        object.__setattr__(self, "brands_dir", Path(self.brands_dir).expanduser())
        if self.mode not in ("stdio", "http"):
            raise ValueError(f"mode must be 'stdio' or 'http', got {self.mode!r}")
        for name in _COUNT_FIELDS:
            value = getattr(self, name)
            if name == "cache_max_mb" and value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a whole number of 0 or more, got {value!r}")
        deadline = self.call_deadline_s
        if isinstance(deadline, bool) or not math.isfinite(float(deadline)) or float(deadline) <= 0:
            raise ValueError(
                f"call_deadline_s must be a finite number greater than 0, got {deadline!r}"
            )
        object.__setattr__(self, "call_deadline_s", float(deadline))
        if isinstance(self.admins, str) or not all(
            isinstance(subject, str) and subject.startswith("github:") for subject in self.admins
        ):
            raise ValueError(f"admins must be a set of 'github:<id>' subjects, got {self.admins!r}")
        object.__setattr__(self, "admins", frozenset(self.admins))

    @property
    def cache_max_bytes(self) -> int:
        """The page cache's size cap in bytes; 0 = no cap."""
        megabytes = self.cache_max_mb
        if megabytes is None:
            megabytes = HTTP_CACHE_MAX_MB if self.mode == "http" else 0
        return megabytes * 1024 * 1024

    @property
    def cache_min_free_bytes(self) -> int:
        """Free disk space below which new pages are not cached; 0 = no floor (stdio)."""
        return CACHE_MIN_FREE_MB * 1024 * 1024 if self.mode == "http" else 0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        kwargs: dict[str, object] = {}
        if value := env.get("REALOEM_BASE_URL"):
            kwargs["base_url"] = value
        if value := env.get("REALOEM_MIN_INTERVAL"):
            kwargs["min_interval_s"] = _to_float("REALOEM_MIN_INTERVAL", value)
        if value := env.get("REALOEM_TIMEOUT"):
            timeout = _to_float("REALOEM_TIMEOUT", value)
            if timeout <= 0:
                raise ValueError(f"REALOEM_TIMEOUT must be greater than 0, got {value!r}")
            kwargs["timeout_s"] = timeout
        if value := env.get("REALOEM_CACHE_DIR"):
            kwargs["cache_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_DATA_DIR"):
            kwargs["data_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_BRANDS_DIR"):
            kwargs["brands_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_ADMINS"):
            kwargs["admins"] = _to_admins(value)
        for env_name, field_name in _COUNT_ENV.items():
            if value := env.get(env_name):
                kwargs[field_name] = _to_count(env_name, value)
        if value := env.get("REALOEM_CALL_DEADLINE_S"):
            deadline = _to_float("REALOEM_CALL_DEADLINE_S", value)
            if deadline <= 0:
                raise ValueError(f"REALOEM_CALL_DEADLINE_S must be greater than 0, got {value!r}")
            kwargs["call_deadline_s"] = deadline
        return cls(**kwargs)  # type: ignore[arg-type]


_COUNT_ENV = {
    "REALOEM_USER_DAILY_LIMIT": "user_daily_limit",
    "REALOEM_NEW_USER_DAILY_LIMIT": "new_user_daily_limit",
    "REALOEM_MIN_ACCOUNT_AGE_DAYS": "min_account_age_days",
    "REALOEM_GLOBAL_DAILY_LIMIT": "global_daily_limit",
    "REALOEM_CACHE_MAX_MB": "cache_max_mb",
}
_COUNT_FIELDS = tuple(_COUNT_ENV.values())


def _to_count(name: str, value: str) -> int:
    text = value.strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"{name} must be a whole number of 0 or more, got {value!r}")
    return int(text)


def _to_admins(value: str) -> frozenset[str]:
    ids = [part.strip() for part in value.split(",") if part.strip()]
    for part in ids:
        if not (part.isascii() and part.isdigit()):
            raise ValueError(
                f"REALOEM_ADMINS must be comma-separated GitHub numeric ids, got {part!r}"
            )
    return frozenset(f"github:{part}" for part in ids)


def _to_float(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of seconds, got {value!r}")
    return number
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_config_hosted.py tests/unit/test_config.py`
Expected: `44 passed` (21 new, 23 existing).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `966 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/config.py server/tests/unit/test_config_hosted.py
git commit -m "feat(hosted): add hosted-mode settings (mode, quotas, deadline, cache cap)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 3: The caller and the call clock

Over HTTP, the MCP SDK's bearer middleware validates the access token and stores it in a context
variable that `get_access_token()` reads; tool handlers see it. `require_user()` is what every
hosted-mode code path calls, so a call without a token fails closed. `CallClock` is an MCP
`ServerMiddleware` that records when each inbound message started, for the per-call deadline;
`time_left()` turns that into the seconds left. The HTTP server (plan 1b) must install `CallClock`
with the same clock the gate uses, or no deadline ever applies. `tests/auth_helpers.signed_in()` sets the same context variable the SDK sets, so tests run through
the in-memory client exactly as a signed-in HTTP call would.

**Files:**
- Create: `server/src/realoem_mcp/current_user.py`, `server/tests/auth_helpers.py`
- Test: `server/tests/unit/test_current_user.py`

- [ ] **Step 1: Write the test helper** `server/tests/auth_helpers.py`:

````python
"""Test helper: act as a signed-in user, the way the SDK's bearer middleware does over HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken


@contextmanager
def signed_in(subject: str | None, *, scopes: tuple[str, ...] = ("realoem",)) -> Iterator[None]:
    """Inside the block get_access_token() returns a token for `subject`; tools called through
    the in-memory mcp.Client see it too."""
    token = AccessToken(
        token="test-token", client_id="test-client", scopes=list(scopes), subject=subject
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)
````

- [ ] **Step 2: Write the failing test** `server/tests/unit/test_current_user.py`:

````python
"""current_user / require_user and the CallClock middleware (hosted design 4.1)."""

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.current_user import (
    CallClock,
    CurrentUser,
    call_started_at,
    current_user,
    require_user,
    time_left,
)
from realoem_mcp.errors import RealOemError
from tests.auth_helpers import signed_in

SETTINGS = Settings(mode="http", admins=frozenset({"github:1"}))


def test_without_a_token_there_is_no_user() -> None:
    assert current_user(SETTINGS) is None
    with pytest.raises(RealOemError, match="not signed in"):
        require_user(SETTINGS)


def test_the_subject_and_the_admin_flag_come_from_the_token() -> None:
    with signed_in("github:1"):
        assert current_user(SETTINGS) == CurrentUser("github:1", True)
    with signed_in("github:2"):
        assert require_user(SETTINGS) == CurrentUser("github:2", False)
    assert current_user(SETTINGS) is None  # the helper restores the previous state


def test_a_token_without_a_subject_is_not_a_user() -> None:
    with signed_in(None):
        assert current_user(SETTINGS) is None
    with signed_in(""):
        assert current_user(SETTINGS) is None


def test_time_left_counts_down_from_the_start_of_the_call() -> None:
    settings = Settings(mode="http", call_deadline_s=50.0)
    assert time_left(settings, lambda: 100.0) is None  # outside a tool call
    token = call_started_at.set(90.0)
    try:
        assert time_left(settings, lambda: 100.0) == 40.0
        assert time_left(settings, lambda: 150.0) == -10.0
    finally:
        call_started_at.reset(token)


@pytest.mark.anyio
async def test_call_clock_stamps_each_message_and_resets_afterwards() -> None:
    ticks = iter([10.0, 20.0])
    clock = CallClock(lambda: next(ticks))
    seen: list[float | None] = []

    async def call_next(ctx: object) -> str:
        seen.append(call_started_at.get())
        return "result"

    assert await clock(object(), call_next) == "result"  # type: ignore[arg-type]
    await clock(object(), call_next)  # type: ignore[arg-type]
    assert seen == [10.0, 20.0]
    assert call_started_at.get() is None


@pytest.mark.anyio
async def test_call_clock_resets_even_when_the_handler_fails() -> None:
    async def call_next(ctx: object) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await CallClock(lambda: 5.0)(object(), call_next)  # type: ignore[arg-type]
    assert call_started_at.get() is None
````

- [ ] **Step 3: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_current_user.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.current_user'`.

- [ ] **Step 4: Implement** `server/src/realoem_mcp/current_user.py`:

````python
"""Who is calling (hosted mode) and when the current tool call started (hosted design 4.1)."""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.auth.middleware.auth_context import get_access_token

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

NOT_SIGNED_IN = "You are not signed in to RealOEM Searcher; connect it in Claude and try again."

# Start of the tool call being handled (monotonic seconds); None outside a call. The HTTP server
# must install CallClock, or no deadline ever applies.
call_started_at: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "realoem_call_started_at", default=None
)


@dataclass(frozen=True)
class CurrentUser:
    subject: str  # "github:<numeric id>"
    is_admin: bool


def current_user(settings: Settings) -> CurrentUser | None:
    """The signed-in caller, from the access token the SDK validated for this request."""
    token = get_access_token()
    if token is None or not token.subject:
        return None
    return CurrentUser(subject=token.subject, is_admin=token.subject in settings.admins)


def time_left(settings: Settings, clock: Callable[[], float]) -> float | None:
    """Seconds until the current tool call's deadline; None outside a tool call.

    clock must be the clock CallClock stamps call_started_at with.
    """
    started = call_started_at.get()
    if started is None:
        return None
    return settings.call_deadline_s - (clock() - started)


def require_user(settings: Settings) -> CurrentUser:
    """The signed-in caller; hosted-mode code paths call this so a missing user fails closed."""
    user = current_user(settings)
    if user is None:
        raise RealOemError(NOT_SIGNED_IN)
    return user


class CallClock:
    """ServerMiddleware that records when each inbound message started (for the call deadline)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        token = call_started_at.set(self._clock())
        try:
            return await call_next(ctx)
        finally:
            call_started_at.reset(token)
````

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_current_user.py`
Expected: `6 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `972 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/current_user.py server/tests/auth_helpers.py server/tests/unit/test_current_user.py
git commit -m "feat(hosted): read the signed-in caller and stamp tool-call start times" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 4: `build_server` keyword arguments

The HTTP app (plan 1b) passes the SDK's auth provider, auth settings and middleware; the stdio
server passes none, so nothing changes for it.

**Files:**
- Modify: `server/src/realoem_mcp/server.py` (`build_server` and its imports)
- Test: `server/tests/tools/test_server_hosted.py`

- [ ] **Step 1: Write the failing test** `server/tests/tools/test_server_hosted.py`:

````python
"""build_server's hosted-mode keyword arguments reach the MCP server (hosted design 4.2)."""

import pytest
from mcp import Client
from mcp.server.auth.middleware.auth_context import get_access_token

from realoem_mcp.current_user import CallClock, call_started_at
from realoem_mcp.server import build_server
from tests.auth_helpers import signed_in

pytestmark = pytest.mark.anyio


async def test_middleware_and_the_signed_in_user_reach_a_tool(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services, middleware=[CallClock(lambda: 123.0)])

    @app.tool()
    async def probe() -> str:
        """Test-only tool: what a tool can see about the call and the caller."""
        token = get_access_token()
        return f"{call_started_at.get()}|{token.subject if token else None}"

    async with Client(app) as client:
        anonymous = await client.call_tool("probe", {})
        with signed_in("github:7"):
            alice = await client.call_tool("probe", {})
        with signed_in("github:8"):
            bob = await client.call_tool("probe", {})
    assert anonymous.content[0].text == "123.0|None"
    assert alice.content[0].text == "123.0|github:7"
    assert bob.content[0].text == "123.0|github:8"


async def test_the_auth_arguments_reach_the_mcp_server(make_services) -> None:
    services, _ = make_services({})
    # The SDK itself refuses a provider without auth settings, so this proves it got one.
    with pytest.raises(ValueError, match="without auth settings"):
        build_server(services, auth_server_provider=object())  # type: ignore[arg-type]


async def test_stdio_server_is_built_without_the_hosted_arguments(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services)
    async with Client(app) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"server_status", "cache_clear"} <= names
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_server_hosted.py`
Expected: two tests FAIL with `TypeError: build_server() got an unexpected keyword argument` (`middleware`, `auth_server_provider`); the stdio test passes.

- [ ] **Step 3: Implement.** In `server/src/realoem_mcp/server.py`:

Edit 1. Find:

````python
import logging
import pkgutil
import sys

from mcp.server.mcpserver import MCPServer

````

Replace with:

````python
import logging
import pkgutil
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer

````

Edit 2. Find:

````python
from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services

log = logging.getLogger(__name__)

INSTRUCTIONS = (
````

Replace with:

````python
from realoem_mcp.config import Settings
from realoem_mcp.services import Services, create_services

if TYPE_CHECKING:
    from mcp.server.auth.provider import OAuthAuthorizationServerProvider
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.context import ServerMiddleware

log = logging.getLogger(__name__)

INSTRUCTIONS = (
````

Edit 3. Find:

````python
)


def build_server(services: Services) -> MCPServer:
    app = MCPServer("realoem", instructions=INSTRUCTIONS, version=__version__)
    package = realoem_mcp.tools
    for module_info in pkgutil.iter_modules(package.__path__):
        try:
````

Replace with:

````python
)


def build_server(
    services: Services,
    *,
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
    auth: AuthSettings | None = None,
    middleware: Sequence[ServerMiddleware[Any]] | None = None,
) -> MCPServer:
    """The MCP server with every tool registered. The keyword arguments are for the hosted
    (HTTP) server; the stdio server passes none of them."""
    app = MCPServer(
        "realoem",
        instructions=INSTRUCTIONS,
        version=__version__,
        auth_server_provider=auth_server_provider,
        auth=auth,
        middleware=middleware,
    )
    package = realoem_mcp.tools
    for module_info in pkgutil.iter_modules(package.__path__):
        try:
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_server_hosted.py`
Expected: `3 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `975 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/server.py server/tests/tools/test_server_hosted.py
git commit -m "feat(hosted): let build_server take auth and middleware for the HTTP app" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 2: The shared page cache

### Task 5: Cache owners, size accounting, the cap and disk handling

`PageCache` changes in one step because the schema changes (version 2):

- **Owners.** The primary key becomes `(owner, url)`. `""` is the shared owner; per-user entries
  (VIN pages, wired in Task 9) use a keyed hash of the user. `get`, `put` (via `page.owner`) and
  `shorten` take the owner; `Page` gains `owner` so callers can pass it back.
- **`html` is the last column.** Every other column can then be read without walking a large
  page's overflow chain, so the cap check, eviction, the purge and `stats()` never read page bodies
  (a test proves it with SQLite's trace callback).
- **Size accounting.** Each row stores `size_bytes`; a running total in `meta` is updated in the
  same transaction as every write. `stats()` reads the total instead of summing every page.
- **A new file, `pages.v2.sqlite3`.** Each schema version gets its own file name, so an older
  server still running (in another Claude Code session) keeps its own file instead of fighting
  over one, and the new file can be created with `auto_vacuum=INCREMENTAL`, which can only be set
  before the first table exists. The version 1 file, `pages.sqlite3`, is deleted (on Windows it
  stays while an older server still has it open). The schema is created in one transaction, so a second process starting at the same
  moment sees no table or all of them.
- **The cap.** With `max_bytes` set, `put` evicts least-recently-used rows (`last_used`, updated on
  each hit) down to 90 % of the cap, then returns the freed pages to the filesystem with
  `PRAGMA incremental_vacuum`. In WAL mode the vacuum first writes every page it moves to the
  `-wal` file, so it runs in chunks of 2048 pages with a `TRUNCATE` checkpoint after each: the
  file and its WAL together shrink, and the vacuum never needs more than one chunk of extra disk
  space (a test measures both files). A `TRUNCATE` checkpoint may wait a moment for another
  process's reader, which only a stdio cache given a cap can have; without a cap or a floor
  (stdio) the checkpoint is `PASSIVE` and never waits. The pragma runs through
  `executescript`, because Python's `execute()` steps it once and frees a single page.
- **Disk space.** With `min_free_bytes` set, `put` checks free space first, evicts to half the cap
  if it is low, and serves the page uncached if it is still low. A `SQLITE_FULL` anywhere in
  `put`, eviction included, also serves the page uncached, and `shorten` logs a full disk and
  carries on: a full disk never fails a tool call.
  `put` returns `False` when the page was not stored. `reset()` closes the connection, deletes
  the cache files and reopens empty (on Linux a deleted file frees nothing while it is still
  open); plan 1b calls it when another database reports a full disk.
- **Robustness.** The expired-row purge at startup is skipped (with a warning) on any SQLite
  error, so a busy or full disk never stops the server starting. The cache runs with
  `synchronous=NORMAL` (safe in WAL mode; the cache is disposable). Log lines never carry a cache
  URL, which could hold a VIN.

The stdio server passes neither `max_bytes` nor `min_free_bytes`. What a stdio user notices: the
cache starts empty in the new file `pages.v2.sqlite3` (the old one is removed), and `clear()` now
also vacuums.

**Files:**
- Modify: `server/src/realoem_mcp/http_client.py` (add `Page.owner`)
- Modify: `server/src/realoem_mcp/cache.py` (replace the whole file)
- Test: `server/tests/unit/test_cache_shared.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_cache_shared.py`:

````python
"""PageCache in shared (hosted) mode: owners, size accounting, the cap, disk-space handling."""

import sqlite3
from collections import namedtuple
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp import cache as cache_module
from realoem_mcp.cache import DB_FILENAME, SCHEMA_VERSION, PageCache
from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

XREF = "https://www.realoem.com/bmw/enUS/partxref?q=11427953129"
GRP = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"
VIN = "https://www.realoem.com/bmw/enUS/select?vin=PX22770"
WEEK = timedelta(days=7)
Usage = namedtuple("Usage", "total used free")


def _page(url: str, *, owner: str = "", html: str = "<p>ok</p>", age: timedelta = timedelta(0)):
    return Page(
        page_type=PageType.PARTXREF,
        url=url,
        final_url=url,
        status=200,
        html=html,
        fetched_at=datetime.now(UTC) - age,
        from_cache=False,
        owner=owner,
    )


class Ticker:
    """A clock that advances one second per reading, so last_used values are distinct."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _columns(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(pages)")]


def _write_version_1(path: Path) -> None:
    """A cache file in the version 1 layout, without auto_vacuum."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        conn.execute(
            "CREATE TABLE pages (url TEXT PRIMARY KEY, page_type TEXT NOT NULL, final_url TEXT "
            "NOT NULL, status INTEGER NOT NULL, html TEXT NOT NULL, fetched_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL)"
        )
        conn.commit()


def _full_disk(*args: object) -> None:
    error = sqlite3.OperationalError("database or disk is full")
    error.sqlite_errorcode = sqlite3.SQLITE_FULL  # what SQLite sets on a real full disk
    raise error


# --- owners -------------------------------------------------------------------------------


def test_pages_are_kept_per_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(VIN, owner="alice", html="<p>a</p>"), WEEK)
        cache.put(_page(VIN, owner="bob", html="<p>b</p>"), WEEK)
        assert cache.get(VIN) is None  # nothing shared under this URL
        alice, bob = cache.get(VIN, owner="alice"), cache.get(VIN, owner="bob")
        assert (alice.html, alice.owner, alice.url) == ("<p>a</p>", "alice", VIN)
        assert (bob.html, bob.owner) == ("<p>b</p>", "bob")
        assert cache.stats().entries == 2
    finally:
        cache.close()


def test_shared_pages_have_an_empty_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(XREF), WEEK)
        hit = cache.get(XREF)
        assert hit is not None and hit.owner == ""
        assert cache.get(XREF, owner="alice") is None
    finally:
        cache.close()


def test_shorten_only_touches_the_given_owner(tmp_path: Path) -> None:
    cache = PageCache(tmp_path)
    try:
        cache.put(_page(VIN, owner="alice", age=timedelta(days=2)), timedelta(days=30))
        cache.put(_page(VIN, owner="bob", age=timedelta(days=2)), timedelta(days=30))
        cache.shorten(VIN, timedelta(days=1), owner="alice")
        assert cache.get(VIN, owner="alice") is None
        assert cache.get(VIN, owner="bob") is not None
    finally:
        cache.close()


def test_html_is_the_last_column_and_the_file_can_shrink(tmp_path: Path) -> None:
    PageCache(tmp_path).close()
    path = tmp_path / DB_FILENAME
    assert _columns(path)[-1] == "html"
    assert _columns(path)[:2] == ["owner", "url"]
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)  # INCREMENTAL
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(pages)")}
    assert {"pages_last_used", "pages_expires_at"} <= indexes


def test_an_old_schema_file_is_replaced_by_a_new_file(tmp_path: Path) -> None:
    path = tmp_path / DB_FILENAME
    _write_version_1(path)
    cache = PageCache(tmp_path)
    try:
        assert cache.stats().entries == 0
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert version == (SCHEMA_VERSION,)


def test_the_version_1_cache_is_deleted_unless_it_is_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "pages.sqlite3"
    _write_version_1(legacy)
    (tmp_path / "pages.sqlite3-wal").write_bytes(b"")
    PageCache(tmp_path).close()
    assert not legacy.exists() and not (tmp_path / "pages.sqlite3-wal").exists()
    _write_version_1(legacy)
    real_unlink = Path.unlink

    def in_use(path: Path, missing_ok: bool = False) -> None:  # Windows, while 0.1.0 runs
        if path.name.startswith("pages.sqlite3"):
            raise PermissionError("the file is being used by another process")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", in_use)
    cache = PageCache(tmp_path)  # the new file is separate, so both versions can run
    try:
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
    assert legacy.exists()


# --- size accounting ------------------------------------------------------------------------


def _sum(cache: PageCache) -> int:
    return cache._conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM pages").fetchone()[0]


def test_running_total_follows_put_replace_shorten_clear_and_purge(tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "cache")
    cache.put(_page(XREF, html="ä"), WEEK)  # 2 bytes
    cache.put(_page(GRP, html="abc"), WEEK)  # 3 bytes
    cache.put(_page(VIN, owner="alice", html="12345", age=timedelta(days=10)), WEEK)  # expired
    assert cache.stats().bytes == 10 == _sum(cache)
    cache.put(_page(XREF, html="abcdefg"), WEEK)  # replace: 2 -> 7
    cache.shorten(GRP, timedelta(days=1))  # only the lifetime changes
    assert cache.stats().bytes == 15 == _sum(cache)
    assert cache.clear(PageType.PARTXREF) == 3  # every row here is a partxref page
    assert cache.stats().bytes == 0 == _sum(cache)
    cache.put(_page(XREF, html="abc"), WEEK)
    cache.put(_page(GRP, html="12345", age=timedelta(days=10)), WEEK)
    assert cache.purge_expired() == 1
    assert cache.stats().bytes == 3 == _sum(cache)
    cache.close()
    reopened = PageCache(tmp_path / "cache")
    try:
        assert reopened.stats().bytes == 3
        assert reopened.clear() == 1
        assert reopened.stats().bytes == 0 == _sum(reopened)
    finally:
        reopened.close()


def test_expired_rows_purged_on_open_leave_the_total_right(tmp_path: Path) -> None:
    first = PageCache(tmp_path)
    first.put(_page(XREF, html="abc", age=timedelta(days=10)), WEEK)
    first.put(_page(GRP, html="12345"), WEEK)
    first.close()
    second = PageCache(tmp_path)
    try:
        assert (second.stats().entries, second.stats().bytes) == (1, 5)
    finally:
        second.close()


def test_stats_cap_check_eviction_and_purge_never_read_html(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, max_bytes=1_000, clock=Ticker())
    try:
        for i in range(5):
            cache.put(_page(f"{XREF}{i}", html="x" * 300), WEEK)
        statements: list[str] = []
        cache._conn.set_trace_callback(statements.append)
        cache.stats()
        cache._enforce_cap()
        cache._evict_to(300)
        cache.purge_expired()
        cache._conn.set_trace_callback(None)
        assert statements
        assert not [s for s in statements if "html" in s.lower()]
        assert not [s for s in statements if "*" in s.upper().replace("COUNT(*)", "")]
    finally:
        cache.close()


# --- the cap --------------------------------------------------------------------------------


def test_cap_evicts_least_recently_used_down_to_ninety_percent(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, max_bytes=1_000, clock=Ticker())
    try:
        for name in "abc":
            cache.put(_page(XREF + name, html="x" * 300), WEEK)  # 900 bytes: under the cap
        assert cache.get(XREF + "a") is not None  # a is now the most recently used
        cache.put(_page(XREF + "d", html="x" * 300), WEEK)  # 1200 > 1000: evict to <= 900
        assert cache.get(XREF + "b") is None  # the least recently used went first
        assert [cache.get(XREF + n) is not None for n in "acd"] == [True, True, True]
        assert cache.stats().bytes == 900 == _sum(cache)
    finally:
        cache.close()


def test_no_cap_means_no_eviction_and_no_use_tracking(tmp_path: Path) -> None:
    cache = PageCache(tmp_path, clock=Ticker())
    try:
        for i in range(5):
            cache.put(_page(f"{XREF}{i}", html="x" * 300), WEEK)
        before = cache._conn.execute("SELECT last_used FROM pages WHERE url = ?", (XREF + "0",))
        first = before.fetchone()[0]
        cache.get(XREF + "0")
        after = cache._conn.execute("SELECT last_used FROM pages WHERE url = ?", (XREF + "0",))
        assert after.fetchone()[0] == first
        assert cache.stats().entries == 5
    finally:
        cache.close()


def _on_disk(cache: PageCache) -> int:
    """The cache file and its WAL together: what the filesystem actually holds."""
    files = (cache.path, Path(f"{cache.path}-wal"))
    return sum(path.stat().st_size for path in files if path.exists())


@pytest.mark.parametrize("chunk_pages", [cache_module.VACUUM_CHUNK_PAGES, 50])
def test_eviction_returns_disk_space_to_the_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_pages: int
) -> None:
    monkeypatch.setattr(cache_module, "VACUUM_CHUNK_PAGES", chunk_pages)
    cache = PageCache(tmp_path, max_bytes=8_000_000, clock=Ticker())
    try:
        for i in range(70):  # 70 x 50 KB = 3.5 MB, under the cap
            cache.put(_page(f"{XREF}{i}", html="x" * 50_000), WEEK)
        cache._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = _on_disk(cache)
        assert cache._evict_to(1_750_000) == 35  # half: many live pages have to move
        assert _on_disk(cache) < before - 1_500_000  # freed, not parked in the -wal
        assert cache._conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
    finally:
        cache.close()


# --- disk space -----------------------------------------------------------------------------


def test_low_disk_space_evicts_then_serves_uncached(tmp_path: Path) -> None:
    free = {"bytes": 500}

    def disk_usage(path: Path) -> Usage:
        return Usage(10_000, 10_000 - free["bytes"], free["bytes"])

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=100, disk_usage=disk_usage, clock=Ticker()
    )
    try:
        assert cache.put(_page(XREF + "a", html="x" * 400), WEEK) is True
        assert cache.put(_page(XREF + "b", html="x" * 400), WEEK) is True
        free["bytes"] = 50  # below the floor, and eviction does not help in this fake
        assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is False
        assert cache.get(XREF + "c") is None
        assert cache.stats().bytes <= 500  # it evicted to half the cap before giving up
    finally:
        cache.close()


def test_low_disk_space_evicts_and_caches_when_that_frees_enough(tmp_path: Path) -> None:
    caches: list[PageCache] = []

    def disk_usage(path: Path) -> Usage:  # a 1,000-byte disk that holds only the cache
        used = caches[0].stats().bytes
        return Usage(1_000, used, 1_000 - used)

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=300, disk_usage=disk_usage, clock=Ticker()
    )
    caches.append(cache)
    try:
        assert cache.put(_page(XREF + "a", html="x" * 400), WEEK) is True
        assert cache.put(_page(XREF + "b", html="x" * 400), WEEK) is True  # 200 bytes free now
        assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is True  # a evicted first
        assert cache.get(XREF + "a") is None
        assert cache.get(XREF + "b") is not None and cache.get(XREF + "c") is not None
    finally:
        cache.close()


def test_a_full_disk_during_eviction_never_fails_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    free = {"bytes": 500}

    def disk_usage(path: Path) -> Usage:
        return Usage(10_000, 10_000 - free["bytes"], free["bytes"])

    cache = PageCache(
        tmp_path, max_bytes=1_000, min_free_bytes=100, disk_usage=disk_usage, clock=Ticker()
    )
    try:
        cache.put(_page(XREF + "a", html="x" * 400), WEEK)
        cache.put(_page(XREF + "b", html="x" * 400), WEEK)
        monkeypatch.setattr(PageCache, "_evict_to", _full_disk)
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            free["bytes"] = 50  # low: put evicts before storing, and the eviction fails
            assert cache.put(_page(XREF + "c", html="x" * 100), WEEK) is False
            free["bytes"] = 500  # enough room, but over the cap: the eviction after it fails
            assert cache.put(_page(XREF + "d", html="x" * 400), WEEK) is True
        assert cache.get(XREF + "c") is None
        assert cache.get(XREF + "d") is not None
        assert "disk is full" in caplog.text
    finally:
        cache.close()


def test_a_full_disk_during_put_serves_the_page_uncached(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = PageCache(tmp_path)
    try:
        cache._conn.execute("PRAGMA max_page_count = 20")  # makes SQLite report SQLITE_FULL
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            assert cache.put(_page(XREF, html="x" * 500_000), WEEK) is False
        assert "disk is full" in caplog.text
        assert cache.get(XREF) is None
        assert cache.stats().bytes == 0 == _sum(cache)
    finally:
        cache.close()


class FullOnUpdate:
    """A connection whose UPDATE statements fail as on a full disk."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
        if sql.lstrip().upper().startswith("UPDATE"):
            _full_disk()
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


def test_a_full_disk_during_shorten_never_fails_the_caller(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = PageCache(tmp_path)
    real = cache._conn
    try:
        cache.put(_page(VIN, owner="alice", age=timedelta(days=2)), timedelta(days=30))
        cache._conn = FullOnUpdate(real)  # type: ignore[assignment]
        with caplog.at_level("WARNING", logger="realoem_mcp.cache"):
            cache.shorten(VIN, timedelta(days=1), owner="alice")  # does not raise
        assert "could not shorten" in caplog.text and "PX22770" not in caplog.text
    finally:
        cache._conn = real
        cache.close()


def test_reset_closes_before_deleting_and_reopens_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = PageCache(tmp_path)
    cache.put(_page(XREF), WEEK)
    order: list[str] = []
    old_conn = cache._conn
    real_delete = PageCache._delete_database_files

    def delete(self: PageCache) -> None:
        try:
            old_conn.execute("SELECT 1")
            order.append("deleted while open")
        except sqlite3.ProgrammingError:  # "Cannot operate on a closed database."
            order.append("deleted after close")
        real_delete(self)

    monkeypatch.setattr(PageCache, "_delete_database_files", delete)
    cache.reset()
    try:
        assert order == ["deleted after close"]
        assert (cache.stats().entries, cache.stats().bytes) == (0, 0)
        cache.put(_page(XREF), WEEK)
        assert cache.get(XREF) is not None
    finally:
        cache.close()
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_cache_shared.py`
Expected: FAIL during collection with `AttributeError: module 'realoem_mcp.cache' has no attribute 'VACUUM_CHUNK_PAGES'`.

- [ ] **Step 3: Add `Page.owner`.** In `server/src/realoem_mcp/http_client.py`, in the `Page`
  dataclass, add one field after `from_cache: bool`:

````python
    owner: str = ""  # "" = shared; otherwise the per-user cache owner key (hosted design 4.8)
````

- [ ] **Step 4: Implement.** Replace `server/src/realoem_mcp/cache.py` with:

````python
"""SQLite cache of raw RealOEM pages, keyed by (owner, request URL) (AD5; hosted design 4.8)."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from realoem_mcp.http_client import Page
from realoem_mcp.page_types import PageType

SCHEMA_VERSION = "2"
# A new file name per schema version: an older server still running (another Claude Code session)
# keeps its own file instead of fighting over one.
DB_FILENAME = "pages.v2.sqlite3"
LEGACY_FILENAMES = ("pages.sqlite3",)  # deleted when possible
SHARED = ""  # owner of the pages every user may read
JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024
EVICT_TO = 0.9  # after crossing the cap, evict down to this share of it
EVICT_BATCH = 200
VACUUM_CHUNK_PAGES = 2048  # pages vacuumed between WAL checkpoints (8 MB with 4 KB pages)

logger = logging.getLogger(__name__)

# html is the LAST column: every other column can then be read without walking a large page's
# overflow chain, so the cap check, eviction, the purge and stats() never read page bodies.
_CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
  owner TEXT NOT NULL, url TEXT NOT NULL, page_type TEXT NOT NULL, final_url TEXT NOT NULL,
  status INTEGER NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  last_used INTEGER NOT NULL, size_bytes INTEGER NOT NULL, html TEXT NOT NULL,
  PRIMARY KEY (owner, url))
"""
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS pages_last_used ON pages (last_used)",
    "CREATE INDEX IF NOT EXISTS pages_expires_at ON pages (expires_at)",
)
_CREATE_META = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _iso(value: datetime) -> str:
    # Fixed-width UTC timestamps compare correctly as strings.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _is_corruption(error: sqlite3.DatabaseError) -> bool:
    """True only for a damaged or non-SQLite file (OperationalError covers locks and I/O)."""
    if isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)


def is_full(error: sqlite3.Error) -> bool:
    """True when SQLite reports that the disk (or the database) is full."""
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) == sqlite3.SQLITE_FULL


def _total(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT value FROM meta WHERE key = 'total_bytes'").fetchone()[0])


def _add_total(conn: sqlite3.Connection, delta: int) -> None:
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) "
        "WHERE key = 'total_bytes'",
        (delta,),
    )


def _schema_complete(conn: sqlite3.Connection) -> bool:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"meta", "pages"} <= tables:
        return False
    keys = {row[0] for row in conn.execute("SELECT key FROM meta")}
    return {"schema_version", "total_bytes"} <= keys


def _rollback(conn: sqlite3.Connection) -> None:
    # SQLite has already rolled back after some errors (a full disk is one); a second ROLLBACK
    # would raise "no transaction is active" and hide the real error.
    if conn.in_transaction:
        conn.execute("ROLLBACK")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int  # total UTF-8 size of the cached HTML
    path: Path


class PageCache:
    """The page cache. One connection, used only from the event-loop thread: the hosted server's
    hourly purge and its full-disk reset() must run there too, never in a worker thread."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        max_bytes: int = 0,
        min_free_bytes: int = 0,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
        clock: Callable[[], float] = time.time,
    ) -> None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / DB_FILENAME
        self._max_bytes = max_bytes  # 0 = no cap
        self._min_free_bytes = min_free_bytes  # 0 = no free-space floor
        self._disk_usage = disk_usage
        self._clock = clock
        try:
            self._conn = self._open()
        except sqlite3.DatabaseError as error:
            if not _is_corruption(error):
                raise  # locked, read-only, disk I/O...: the file is fine, so never delete it
            logger.warning("page cache %s is unusable (%s); recreating it", self.path, error)
            try:
                self._delete_database_files()
            except OSError as os_error:
                error.add_note(f"the corrupt cache {self.path} could not be deleted: {os_error}")
                raise error from os_error
            self._conn = self._open()
        self._remove_legacy_files()

    def _connect(self) -> sqlite3.Connection:
        # Autocommit; one connection used only from the event-loop thread.
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            if conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0:
                # Only possible before the first table exists; lets evictions shrink the file.
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # the cache is disposable; safe in WAL mode
            conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")
        except BaseException:
            conn.close()
            raise
        return conn

    def _open(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            if self._is_outdated(conn):
                # A new schema needs a new file: auto_vacuum cannot be turned on once tables exist.
                conn.close()
                self._delete_database_files()
                conn = self._connect()
            self._ensure_schema(conn)
            self._purge_expired(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _delete_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def _remove_legacy_files(self) -> None:
        """Delete the files of older cache versions. On Windows they stay while another process
        has them open; elsewhere that process keeps its now-unlinked file until it exits."""
        for name in LEGACY_FILENAMES:
            for suffix in ("", "-wal", "-shm"):
                try:
                    (self.path.parent / f"{name}{suffix}").unlink(missing_ok=True)
                except OSError as error:
                    logger.info("left the old page cache %s in place: %s", name, error)
                    break

    @staticmethod
    def _is_outdated(conn: sqlite3.Connection) -> bool:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not tables:
            return False
        if "meta" not in tables:
            return True
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return row is None or row[0] != SCHEMA_VERSION

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        """Create what is missing in one transaction, so a process starting at the same moment
        sees either no table or all of them. An existing cache opens without the write lock."""
        if _schema_complete(conn):
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_CREATE_META)
            conn.execute(_CREATE_PAGES)
            for statement in _CREATE_INDEXES:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) "
                "SELECT 'total_bytes', CAST(COALESCE(SUM(size_bytes), 0) AS TEXT) FROM pages"
            )
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise

    @staticmethod
    def _purge_expired(conn: sqlite3.Connection) -> int:
        now = _iso(datetime.now(UTC))
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                freed, removed = conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0), COUNT(*) FROM pages "
                    "WHERE expires_at <= ?",
                    (now,),
                ).fetchone()
                conn.execute("DELETE FROM pages WHERE expires_at <= ?", (now,))
                _add_total(conn, -freed)
                conn.execute("COMMIT")
            except BaseException:
                _rollback(conn)
                raise
        except sqlite3.OperationalError as error:
            # Housekeeping only: get() ignores expired rows, so a busy or full disk must never
            # stop startup or the hourly purge.
            logger.warning("skipping expired-page purge: %s", error)
            return 0
        return removed

    @contextmanager
    def _tx(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            _rollback(self._conn)
            raise

    def get(self, url: str, *, owner: str = SHARED) -> Page | None:
        row = self._conn.execute(
            "SELECT page_type, final_url, status, fetched_at, html FROM pages "
            "WHERE owner = ? AND url = ? AND expires_at > ?",
            (owner, url, _iso(datetime.now(UTC))),
        ).fetchone()
        if row is None:
            return None
        if self._max_bytes:
            self._touch(owner, url)
        page_type, final_url, status, fetched_at, html = row
        return Page(
            page_type=PageType(page_type),
            url=url,
            final_url=final_url,
            status=status,
            html=html,
            fetched_at=datetime.fromisoformat(fetched_at),
            from_cache=True,
            owner=owner,
        )

    def _touch(self, owner: str, url: str) -> None:
        try:
            self._conn.execute(
                "UPDATE pages SET last_used = ? WHERE owner = ? AND url = ?",
                (int(self._clock()), owner, url),
            )
        except sqlite3.OperationalError as error:  # never fail a read over bookkeeping
            logger.debug("could not record a cache hit: %s", error)  # no URL: it may hold a VIN

    def put(self, page: Page, ttl: timedelta) -> bool:
        """Store the page under (page.owner, page.url). False when it was served uncached.

        A full or nearly full disk never fails the caller: the page is then served uncached.
        """
        size = len(page.html.encode("utf-8"))
        try:
            if not self._has_room():
                logger.warning(
                    "disk space is low; serving %s without caching it", page.page_type.value
                )
                return False
            with self._tx():
                old = self._conn.execute(
                    "SELECT size_bytes FROM pages WHERE owner = ? AND url = ?",
                    (page.owner, page.url),
                ).fetchone()
                self._conn.execute(
                    "INSERT OR REPLACE INTO pages (owner, url, page_type, final_url, status, "
                    "fetched_at, expires_at, last_used, size_bytes, html) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        page.owner,
                        page.url,
                        page.page_type.value,
                        page.final_url,
                        page.status,
                        _iso(page.fetched_at),
                        _iso(page.fetched_at + ttl),
                        int(self._clock()),
                        size,
                        page.html,
                    ),
                )
                _add_total(self._conn, size - (old[0] if old else 0))
        except sqlite3.OperationalError as error:
            if not is_full(error):
                raise
            logger.warning("the disk is full; serving %s without caching it", page.page_type.value)
            return False
        try:
            self._enforce_cap()
        except sqlite3.OperationalError as error:
            if not is_full(error):
                raise
            logger.warning("the disk is full; could not evict cached pages")  # the page is stored
        return True

    def shorten(self, url: str, ttl: timedelta, *, owner: str = SHARED) -> None:
        """Cap an entry's lifetime at fetched_at + ttl (used for negative results)."""
        row = self._conn.execute(
            "SELECT fetched_at, expires_at FROM pages WHERE owner = ? AND url = ?", (owner, url)
        ).fetchone()
        if row is None:
            return
        capped = _iso(datetime.fromisoformat(row[0]) + ttl)
        if capped < row[1]:
            try:
                self._conn.execute(
                    "UPDATE pages SET expires_at = ? WHERE owner = ? AND url = ?",
                    (capped, owner, url),
                )
            except sqlite3.OperationalError as error:
                if not is_full(error):
                    raise
                # No URL in the log: it may hold a VIN. The tool call itself carries on.
                logger.warning("the disk is full; could not shorten a cached page's lifetime")

    def clear(self, page_type: PageType | None = None) -> int:
        """Delete every owner's pages (of one page type, or all). Returns the rows removed."""
        with self._tx():
            if page_type is None:
                removed = self._conn.execute("DELETE FROM pages").rowcount
                self._conn.execute("UPDATE meta SET value = '0' WHERE key = 'total_bytes'")
            else:
                value = PageType(page_type).value
                freed = self._conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0) FROM pages WHERE page_type = ?", (value,)
                ).fetchone()[0]
                removed = self._conn.execute(
                    "DELETE FROM pages WHERE page_type = ?", (value,)
                ).rowcount
                _add_total(self._conn, -freed)
        self._release_free_pages()
        return removed

    def purge_expired(self) -> int:
        """Delete expired rows (the hourly housekeeping of the hosted server)."""
        removed = self._purge_expired(self._conn)
        if removed:
            self._release_free_pages()
        return removed

    def stats(self) -> CacheStats:
        entries = self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        return CacheStats(entries=entries, bytes=_total(self._conn), path=self.path)

    def _enforce_cap(self) -> None:
        if self._max_bytes and _total(self._conn) > self._max_bytes:
            self._evict_to(int(self._max_bytes * EVICT_TO))

    def _evict_to(self, target: int) -> int:
        """Delete least-recently-used rows until the total is at most target bytes."""
        if _total(self._conn) <= target:
            return 0  # take no write lock for nothing (on a full disk even that could fail)
        evicted = 0
        with self._tx():
            total = _total(self._conn)
            while total > target:
                victims = self._conn.execute(
                    "SELECT owner, url, size_bytes FROM pages "
                    "ORDER BY last_used, fetched_at LIMIT ?",
                    (EVICT_BATCH,),
                ).fetchall()
                if not victims:
                    break
                doomed = []
                for owner, url, size in victims:
                    if total <= target:
                        break
                    doomed.append((owner, url))
                    total -= size
                self._conn.executemany("DELETE FROM pages WHERE owner = ? AND url = ?", doomed)
                evicted += len(doomed)
            self._conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'total_bytes'", (str(max(total, 0)),)
            )
        if evicted:
            logger.info("evicted %d cached pages (cache is over its size cap)", evicted)
            self._release_free_pages()
        return evicted

    def _release_free_pages(self) -> None:
        """Hand freed pages back to the filesystem.

        incremental_vacuum moves pages from the end of the file into the free slots, and in WAL
        mode every moved page is first written to the -wal file. So the vacuum runs in chunks
        with a checkpoint after each. With a cap or a free-space floor (the hosted server, which
        has one connection, or a stdio cache given REALOEM_CACHE_MAX_MB) that is a TRUNCATE
        checkpoint, which empties the -wal, so the vacuum needs at most one chunk of extra disk
        space; it may wait a moment for another process's reader. Otherwise (stdio) it is a
        PASSIVE checkpoint, which never waits. executescript, not execute: Python's execute()
        steps the pragma once, which frees a single page.
        """
        mode = "TRUNCATE" if self._max_bytes or self._min_free_bytes else "PASSIVE"
        try:
            remaining = self._free_pages()
            while remaining:
                self._conn.executescript(f"PRAGMA incremental_vacuum({VACUUM_CHUNK_PAGES});")
                self._conn.execute(f"PRAGMA wal_checkpoint({mode})")
                left = self._free_pages()
                if left >= remaining:
                    break  # no progress (another process is busy): the next eviction retries
                remaining = left
        except sqlite3.OperationalError as error:
            logger.warning("could not release free cache pages: %s", error)

    def _free_pages(self) -> int:
        return self._conn.execute("PRAGMA freelist_count").fetchone()[0]

    def _has_room(self) -> bool:
        if not self._min_free_bytes:
            return True
        if self._disk_usage(self.path.parent).free >= self._min_free_bytes:
            return True
        if self._max_bytes:
            self._evict_to(self._max_bytes // 2)
        return self._disk_usage(self.path.parent).free >= self._min_free_bytes

    def reset(self) -> None:
        """Close, delete the cache files and reopen empty: the one way to free disk space at once.

        The connection is closed first: on Linux a deleted file frees nothing while it is open.
        If reopening fails, the cache is unusable; the hosted server then exits and restarts.
        """
        self._conn.close()
        try:
            self._delete_database_files()
        finally:
            self._conn = self._open()

    def close(self) -> None:
        self._conn.close()
````

- [ ] **Step 5: Run the new and the existing cache tests**

Run: `uv run --directory server pytest -q tests/unit/test_cache_shared.py tests/unit/test_cache.py`
Expected: `35 passed` (19 new, 16 existing).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `994 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/cache.py server/src/realoem_mcp/http_client.py server/tests/unit/test_cache_shared.py
git commit -m "feat(cache): per-owner entries, size accounting, LRU cap and disk-full handling" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 3: The client hooks

### Task 6: `RealOemClient` hooks, refresh throttle and VIN-free logs

`fetch()` keeps its contract; in hosted mode it gains:

- `owner(page_type, params)` decides the cache owner of a page; `cached()` and `fetch()` use it.
  Owner-scoped pages expire after at most 30 days.
- `admit()` (an async context manager returning an `Admission`) is entered **before** waiting for
  the request lock; the lock is then taken with a time limit (`asyncio.timeout`, not `wait_for`,
  which can leak the lock on Python 3.11 when a task is cancelled as the acquire completes). A
  timeout raises `CallDeadline` when the call deadline set the limit, else `Busy`. Nothing is
  charged.
- `charge()` runs **inside** the lock, after the second cache check misses and before anything is
  sent; it raises `QuotaExceeded` to refuse. A page another call fetched while this one waited is
  found by that second check and is free. Retries and redirect hops are not charged again. The
  admission is held until the response has arrived, so in-flight fetches count against the
  gate's limits too.
- `refresh=true` in hosted mode is honoured only when the cached copy is older than one hour.
- In hosted mode, the client's own log lines show URLs of `select` and `production` pages (which
  can carry a VIN) with their query values masked, including refused off-site redirects and
  network failures. The MCP SDK separately logs every tool error with its message, which can
  contain such a URL or a user's input, and `httpx` logs every request URL at INFO (which is why
  `server.main()` sets the `httpx` logger to WARNING): plan 1b's entry point does the same and
  installs a log filter, and tests it end to end.

With no hooks (stdio) `fetch()` behaves exactly as before. The tests check the important orderings
by name: a page fetched while waiting is free, redirect hops are free, and the admission is open
while each request is sent.

**Files:**
- Modify: `server/src/realoem_mcp/http_client.py` (replace the whole file)
- Test: `server/tests/unit/test_http_client_hosted.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_http_client_hosted.py`:

````python
"""RealOemClient in hosted mode: cache owners, the admit/charge hooks, refresh throttle, logs."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded, UpstreamError
from realoem_mcp.http_client import Admission, RealOemClient, masked
from realoem_mcp.page_types import PageType
from tests.harness import LANDING_URL, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio

XREF_PARAMS = {"q": "11427953129"}
XREF = url("partxref", **XREF_PARAMS)
VIN_PARAMS = {"vin": "PX22770"}
VIN = url("select", **VIN_PARAMS)
PRODUCTION = url("production", **VIN_PARAMS)
CASCADE_PARAMS = {"product": "P"}
CASCADE = url("select", **CASCADE_PARAMS)


class Hooks:
    """Records what the client asks of the hosted server's gate, quota and owner hooks."""

    def __init__(self) -> None:
        self.user = "alice"
        self.admission = Admission(wait_s=60.0, deadline_bound=False)
        self.admit_error: Exception | None = None
        self.charge_error: Exception | None = None
        self.entered = 0
        self.exited = 0
        self.charged: list[str] = []

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[Admission]:
        if self.admit_error is not None:
            raise self.admit_error
        self.entered += 1
        try:
            yield self.admission
        finally:
            self.exited += 1

    def charge(self) -> None:
        if self.charge_error is not None:
            raise self.charge_error
        self.charged.append(self.user)

    def owner(self, page_type: PageType, params: Mapping[str, str]) -> str:
        private = page_type is PageType.PRODUCTION or (
            page_type is PageType.SELECT and "vin" in params
        )
        return f"owner-{self.user}" if private else ""


class RecordingTransport(FixtureTransport):
    """Also records how many admissions were open while each request was being sent."""

    def __init__(self, routes: Mapping[str, Route | str], hooks: Hooks) -> None:
        super().__init__(routes)
        self.hooks = hooks
        self.admissions_open: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.admissions_open.append(self.hooks.entered - self.hooks.exited)
        return await super().handle_async_request(request)


class Unreachable(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("RealOEM is unreachable", request=request)


@pytest.fixture
async def hosted(tmp_path: Path):
    """factory(routes, mode=, transport=) -> (client, transport, hooks, cache).

    In http mode the client gets the recording hooks; in stdio mode it gets none, as in stdio.
    """
    made: list[tuple[RealOemClient, PageCache, httpx.AsyncBaseTransport]] = []

    def factory(routes=None, *, mode: str = "http", transport=None):
        clock = FakeClock()
        hooks = Hooks()
        transport = transport or RecordingTransport(routes or {}, hooks)
        cache = PageCache(tmp_path / f"cache{len(made)}")
        hook_args = (
            {"admit": hooks.admit, "charge": hooks.charge, "owner": hooks.owner}
            if mode == "http"
            else {}
        )
        client = RealOemClient(
            Settings(cache_dir=tmp_path, mode=mode),  # type: ignore[arg-type]
            cache,
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
            **hook_args,
        )
        made.append((client, cache, transport))
        return client, transport, hooks, cache

    yield factory
    for client, cache, transport in made:
        await client.aclose()
        cache.close()
        if isinstance(transport, FixtureTransport):
            assert transport.unmatched == []


# --- cache owners ---------------------------------------------------------------------------


async def test_vin_pages_are_cached_per_user_and_other_pages_are_shared(hosted) -> None:
    client, transport, hooks, _ = hosted({VIN: Route(), XREF: Route(), PRODUCTION: Route()})
    first = await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    await client.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (first.owner, first.url) == ("owner-alice", VIN)  # the URL stays the RealOEM URL
    hooks.user = "bob"
    again = await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    shared = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (again.from_cache, again.owner) == (False, "owner-bob")  # bob pays for his own copy
    assert (shared.from_cache, shared.owner) == (True, "")
    assert [str(r.url) for r in transport.requests] == [VIN, PRODUCTION, XREF, VIN]
    assert client.cached(PageType.SELECT, "select", VIN_PARAMS).owner == "owner-bob"
    hooks.user = "carol"
    assert client.cached(PageType.SELECT, "select", VIN_PARAMS) is None
    assert client.cached(PageType.PARTXREF, "partxref", XREF_PARAMS) is not None


async def test_the_model_cascade_on_the_select_page_is_shared(hosted) -> None:
    client, transport, hooks, _ = hosted({CASCADE: Route()})
    await client.fetch(PageType.SELECT, "select", CASCADE_PARAMS)
    hooks.user = "bob"
    page = await client.fetch(PageType.SELECT, "select", CASCADE_PARAMS)
    assert (page.from_cache, page.owner) == (True, "")
    assert len(transport.requests) == 1


async def test_a_users_own_pages_expire_after_30_days_at_most(hosted) -> None:
    other_vin = url("select", vin="AB12345")
    client, _, _, cache = hosted({VIN: Route(), other_vin: Route(), XREF: Route()})
    await client.fetch(PageType.SELECT, "select", VIN_PARAMS, ttl=timedelta(days=180))
    await client.fetch(PageType.SELECT, "select", {"vin": "AB12345"}, ttl=timedelta(days=1))
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    rows = dict(cache._conn.execute("SELECT url, fetched_at || '|' || expires_at FROM pages"))

    def lifetime(page_url: str) -> timedelta:
        fetched, expires = (datetime.fromisoformat(part) for part in rows[page_url].split("|"))
        return expires - fetched

    assert lifetime(VIN) == timedelta(days=30)  # capped
    assert lifetime(other_vin) == timedelta(days=1)  # shorter is kept
    assert lifetime(XREF) == timedelta(days=7)  # shared pages keep their own lifetime


# --- refresh --------------------------------------------------------------------------------


async def test_hosted_refresh_is_ignored_for_a_copy_younger_than_an_hour(hosted) -> None:
    client, transport, _, cache = hosted({XREF: Route()})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    young = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert young.from_cache is True
    assert len(transport.requests) == 1
    two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="microseconds")
    cache._conn.execute("UPDATE pages SET fetched_at = ?", (two_hours_ago,))
    old = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert old.from_cache is False
    assert len(transport.requests) == 2


async def test_stdio_refresh_always_fetches(hosted) -> None:
    client, transport, _, _ = hosted({XREF: Route()}, mode="stdio")
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS, refresh=True)
    assert page.from_cache is False
    assert len(transport.requests) == 2


# --- charge ---------------------------------------------------------------------------------


async def test_only_a_network_fetch_is_charged_and_only_once(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route(), VIN: Route(status=503)})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # cache hit: free
    assert hooks.charged == ["alice"]
    with pytest.raises(UpstreamError):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # 503: two retries
    assert len(transport.requests) == 4  # 1 + 3 attempts
    assert hooks.charged == ["alice", "alice"]  # retries are free; the failed fetch still counts


async def test_a_page_fetched_while_waiting_for_the_lock_is_free(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    await client._lock.acquire()  # another fetch is in flight: both calls below wait
    calls = [
        asyncio.create_task(client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS))
        for _ in range(2)
    ]
    for _ in range(3):
        await asyncio.sleep(0)  # both pass the first cache check and queue for the lock
    client._lock.release()
    pages = await asyncio.gather(*calls)
    assert [page.from_cache for page in pages] == [False, True]  # found at the second check
    assert len(transport.requests) == 1
    assert hooks.charged == ["alice"]


async def test_redirect_hops_are_free(hosted) -> None:
    group_params = {"id": "NOT-A-GROUP"}
    group = url("partgrp", **group_params)
    client, transport, hooks, _ = hosted({group: Route(redirect_to=LANDING_URL)})
    page = await client.fetch(PageType.PARTGRP, "partgrp", group_params)
    assert page.redirected_away is True
    assert len(transport.requests) == 2  # the request and the redirect hop
    assert hooks.charged == ["alice"]


async def test_a_refused_charge_sends_nothing_and_releases_the_lock(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    hooks.charge_error = QuotaExceeded(300)
    with pytest.raises(QuotaExceeded):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert transport.requests == []
    assert (hooks.entered, hooks.exited) == (1, 1)
    hooks.charge_error = None
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # lock was released
    assert page.from_cache is False


# --- admit ----------------------------------------------------------------------------------


async def test_the_admission_is_held_until_the_response_arrives(hosted) -> None:
    client, transport, hooks, _ = hosted({XREF: Route(), VIN: Route(status=503)})
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    with pytest.raises(UpstreamError):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # 503: retried twice
    assert transport.admissions_open == [1, 1, 1, 1]  # open while every attempt was sent
    assert (hooks.entered, hooks.exited) == (2, 2)
    await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert (hooks.entered, hooks.exited) == (2, 2)  # cache hits never queue


async def test_a_refused_admission_sends_nothing(hosted) -> None:
    client, transport, hooks, _ = hosted({})
    hooks.admit_error = QuotaExceeded(300)
    with pytest.raises(QuotaExceeded):
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert transport.requests == []
    assert hooks.charged == []


@pytest.mark.parametrize(
    ("deadline_bound", "error"), [(False, Busy), (True, CallDeadline)], ids=["queue", "deadline"]
)
async def test_waiting_too_long_for_a_turn_fails_without_a_charge(
    hosted, deadline_bound: bool, error: type[Exception]
) -> None:
    client, transport, hooks, _ = hosted({XREF: Route()})
    hooks.admission = Admission(wait_s=0.01, deadline_bound=deadline_bound)
    await client._lock.acquire()  # someone else's fetch is in flight
    try:
        async with asyncio.timeout(5):  # a broken time limit fails the test, never hangs it
            with pytest.raises(error):
                await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    finally:
        client._lock.release()
    assert transport.requests == []
    assert hooks.charged == []
    assert (hooks.entered, hooks.exited) == (1, 1)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)  # the lock is usable
    assert page.from_cache is False


async def test_a_free_lock_is_taken_even_with_no_time_to_wait(hosted) -> None:
    client, _, hooks, _ = hosted({XREF: Route()})
    hooks.admission = Admission(wait_s=0.0, deadline_bound=True)
    page = await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert page.from_cache is False


# --- logs -----------------------------------------------------------------------------------


def test_masked_hides_every_query_value() -> None:
    assert masked(VIN) == "https://www.realoem.com/bmw/enUS/select?vin=***"
    assert masked("https://x/y?a=1&b=&c=3") == "https://x/y?a=***&b=***&c=***"
    assert masked("https://x/y") == "https://x/y"


async def test_hosted_logs_never_carry_a_vin(hosted, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _, _ = hosted({VIN: Route(), PRODUCTION: Route(), XREF: Route()})
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # the cache-hit line
        await client.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
        await client.fetch(PageType.PARTXREF, "partxref", XREF_PARAMS)
    assert "PX22770" not in caplog.text
    assert "select?vin=***" in caplog.text
    assert "production?vin=***" in caplog.text
    assert XREF in caplog.text  # other page types are logged in full


async def test_hosted_failure_logs_never_carry_a_vin(
    hosted, caplog: pytest.LogCaptureFixture
) -> None:
    offsite = "https://elsewhere.example/select?vin=PX22770"
    client, _, _, _ = hosted({VIN: Route(redirect_to=offsite)})
    unreachable, _, _, _ = hosted(transport=Unreachable())
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        with pytest.raises(UpstreamError):
            await client.fetch(PageType.SELECT, "select", VIN_PARAMS)  # refused off-site hop
        with pytest.raises(UpstreamError):
            await unreachable.fetch(PageType.PRODUCTION, "production", VIN_PARAMS)
    assert "PX22770" not in caplog.text
    assert "elsewhere.example/select?vin=***" in caplog.text
    assert "production?vin=*** failed: ConnectError" in caplog.text


async def test_stdio_logs_keep_the_full_url(hosted, caplog: pytest.LogCaptureFixture) -> None:
    client, _, _, _ = hosted({VIN: Route()}, mode="stdio")
    with caplog.at_level(logging.INFO, logger="realoem_mcp.http_client"):
        await client.fetch(PageType.SELECT, "select", VIN_PARAMS)
    assert VIN in caplog.text
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_http_client_hosted.py`
Expected: FAIL with `ImportError: cannot import name 'Admission'`.

- [ ] **Step 3: Implement.** Replace `server/src/realoem_mcp/http_client.py` with:

````python
"""The only way the server talks to RealOEM: rate limited, cached, honest (AD6, AD8, AD13, AD14)."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import (
    BotChallenge,
    Busy,
    CallDeadline,
    LayoutChanged,
    UpstreamError,
)
from realoem_mcp.page_types import PageType

if TYPE_CHECKING:
    from realoem_mcp.cache import PageCache

log = logging.getLogger(__name__)

COOKIE = "ro_ui=v2"
MAX_REDIRECTS = 3
RETRY_DELAYS_S = (5.0, 15.0)
MAX_RETRIES = len(RETRY_DELAYS_S)
RETRY_AFTER_CAP_S = 30.0
CHALLENGE_TITLE = "<title>Just a moment...</title>"
OWNER_SCOPED_TTL = timedelta(days=30)  # hosted: a user's own (VIN) pages
REFRESH_MIN_AGE = timedelta(hours=1)  # hosted: refresh=true is ignored for newer copies
PRIVATE_PAGE_TYPES = (PageType.SELECT, PageType.PRODUCTION)  # URLs that can carry a VIN
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
    owner: str = ""  # "" = shared; otherwise the per-user cache owner key (hosted design 4.8)

    @property
    def redirected_away(self) -> bool:
        """True when RealOEM redirected to another page (e.g. /bmw/ for an invalid id)."""
        requested = urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1]
        return not urlsplit(self.final_url).path.rstrip("/").endswith("/" + requested)


@dataclass(frozen=True)
class Admission:
    """What the hosted server's gate grants a cache-miss fetch (hosted design 4.7)."""

    wait_s: float  # how long the fetch may wait for its turn
    deadline_bound: bool  # True when the call deadline, not the queue limit, set wait_s


Admit = Callable[[], AbstractAsyncContextManager[Admission]]
Charge = Callable[[], None]
Owner = Callable[[PageType, Mapping[str, str]], str]


def masked(url: str) -> str:
    """The URL with every query value replaced by ***, for logs that must not carry a VIN."""
    parts = urlsplit(url)
    query = "&".join(f"{key}=***" for key, _ in parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit(parts._replace(query=query))


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
        admit: Admit | None = None,
        charge: Charge | None = None,
        owner: Owner | None = None,
    ) -> None:
        self._settings = settings
        self._hosted = settings.mode == "http"
        self._cache = cache
        self._admit = admit  # hosted: queue admission, entered before waiting for the lock
        self._charge = charge  # hosted: counts one cache-miss fetch against the caller's quota
        self._owner = owner  # hosted: the cache owner of a page ("" = shared)
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
        page = self._cache.get(
            self.build_url(path, params), owner=self._owner_of(page_type, params)
        )
        return page if page is not None and page.page_type == page_type else None

    def _owner_of(self, page_type: PageType, params: Mapping[str, str]) -> str:
        return self._owner(page_type, params) if self._owner is not None else ""

    def _log_url(self, page_type: PageType | str, url: str) -> str:
        return masked(url) if self._hosted and page_type in PRIVATE_PAGE_TYPES else url

    def _cached_answer(
        self, page_type: PageType, url: str, owner: str, refresh: bool
    ) -> Page | None:
        """The cached page that answers this fetch, if any.

        In hosted mode refresh=true is honoured only for copies older than REFRESH_MIN_AGE, so
        one user cannot make the shared server refetch a page over and over.
        """
        if refresh and not self._hosted:
            return None
        hit = self._cache.get(url, owner=owner)
        if hit is None:
            return None
        if refresh and datetime.now(UTC) - hit.fetched_at >= REFRESH_MIN_AGE:
            return None
        log.info("%s %s cache hit", page_type.value, self._log_url(page_type, url))
        return hit

    async def fetch(
        self,
        page_type: PageType,
        path: str,
        params: Mapping[str, str],
        *,
        refresh: bool = False,
        ttl: timedelta | None = None,
    ) -> Page:
        """Return the page for `path`, from the cache or rate-limited from RealOEM.

        A same-host redirect is returned as a redirected page (never cached) regardless of the
        final status; callers turn redirected-away pages into NotFound. Other non-200 responses
        raise UpstreamError.

        On the hosted server a cache miss is first admitted by the gate (which may raise
        QuotaExceeded, CallDeadline or Busy), then waits for its turn at most as long as the
        admission allows (Busy or CallDeadline), then is charged to the caller (QuotaExceeded)
        only if the page is still not cached once its turn comes. Cache hits, retries and
        redirect hops are free; the admission is held until the response has arrived. VIN pages
        are cached for their owner only, and refresh=true is honoured only for copies older than
        an hour.
        """
        url = self.build_url(path, params)
        owner = self._owner_of(page_type, params)
        if (hit := self._cached_answer(page_type, url, owner, refresh)) is not None:
            return hit
        if self._admit is None:
            async with self._lock:
                return await self._fetch_locked(page_type, url, owner, refresh=refresh, ttl=ttl)
        async with self._admit() as admission:
            await self._acquire(admission)
            try:
                return await self._fetch_locked(page_type, url, owner, refresh=refresh, ttl=ttl)
            finally:
                self._lock.release()

    async def _acquire(self, admission: Admission) -> None:
        """Take the request lock, waiting at most admission.wait_s for a turn."""
        try:
            # asyncio.timeout, not wait_for: on Python 3.11 wait_for can leak the lock when the
            # task is cancelled just as the acquire completes.
            async with asyncio.timeout(admission.wait_s):
                await self._lock.acquire()
        except TimeoutError:
            raise (CallDeadline() if admission.deadline_bound else Busy()) from None

    async def _fetch_locked(
        self, page_type: PageType, url: str, owner: str, *, refresh: bool, ttl: timedelta | None
    ) -> Page:
        """The network fetch; the caller holds the request lock."""
        # Another call may have fetched the page while this one waited for the lock.
        if (hit := self._cached_answer(page_type, url, owner, refresh)) is not None:
            return hit
        if self._charge is not None:
            self._charge()  # raises QuotaExceeded before anything is sent
        response = await self._get_with_retries(page_type, url)
        page = Page(
            page_type=page_type,
            url=url,
            final_url=str(response.url),
            status=response.status_code,
            html=response.text,
            fetched_at=datetime.now(UTC),
            from_cache=False,
            owner=owner,
        )
        if page.redirected_away:
            return page
        if page.status != 200:
            raise UpstreamError(page.status, url)
        lifetime = ttl if ttl is not None else page_type.ttl
        if owner:
            lifetime = min(lifetime, OWNER_SCOPED_TTL)
        self._cache.put(page, lifetime)
        return page

    async def _get_with_retries(self, page_type: PageType, url: str) -> httpx.Response:
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
                log.warning(
                    "refused off-site redirect from %s to %s",
                    self._log_url(page_type, url),
                    self._log_url(page_type, exc.target),
                )
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

    async def _send(self, page_type: PageType, url: str) -> httpx.Response:
        try:
            return await self._http.get(url, extensions={_PAGE_TYPE: page_type.value})
        except httpx.RequestError as exc:
            log.info(
                "%s %s failed: %s (cache miss)",
                page_type.value,
                self._log_url(page_type, url),
                type(exc).__name__,
            )
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
        page_type = request.extensions.get(_PAGE_TYPE, "?")
        log.info(
            "%s %s -> %d in %.0f ms (cache miss)",
            page_type,
            self._log_url(page_type, str(request.url)),
            response.status_code,
            elapsed_ms,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _is_challenge(response: httpx.Response) -> bool:
    if (
        response.status_code in (403, 503)
        and response.headers.get("cf-mitigated", "").lower() == "challenge"
    ):
        return True
    return CHALLENGE_TITLE in response.text


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Retry-After (delta-seconds or HTTP-date) capped at RETRY_AFTER_CAP_S, else the backoff."""
    default = RETRY_DELAYS_S[attempt]
    header = response.headers.get("Retry-After", "").strip()
    try:
        seconds = float(header)
    except ValueError:
        try:
            when = parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError):
            return default
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    if not math.isfinite(seconds):
        return default
    return min(max(seconds, 0.0), RETRY_AFTER_CAP_S)
````

- [ ] **Step 4: Run the new and the existing client tests**

Run: `uv run --directory server pytest -q tests/unit/test_http_client_hosted.py tests/unit/test_http_client.py tests/unit/test_http_client_errors.py`
Expected: `56 passed` (18 new, 38 existing).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1012 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/http_client.py server/tests/unit/test_http_client_hosted.py
git commit -m "feat(client): admission, quota and cache-owner hooks; hosted refresh throttle; VIN-free logs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 4: The quota and the gate

### Task 7: `Quota`

Counts cache-miss page fetches per subject per UTC day in a SQLite `usage` table on a connection
the caller owns (plan 1b passes the auth database's connection). `charge()` is one
`BEGIN IMMEDIATE … COMMIT`: the user's row and the server-wide row (subject `*`) are incremented
only if both are under their limits, so a refusal counts nothing. The server-wide row is counted
even while the cap is off, so the cap can be switched on mid-day. `0` means unlimited. An account
whose age is unknown gets the new-account limit (fail closed); `account_created_at` must return
timezone-aware datetimes. Plan 1b's auth database creates the same `usage` table in its
migrations with `USAGE_SCHEMA`, so there is one definition.

**Files:**
- Create: `server/src/realoem_mcp/quota.py`
- Test: `server/tests/unit/test_quota.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_quota.py`:

````python
"""Quota: per-user daily limits, the new-account limit and the server-wide cap (design 4.7)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded
from realoem_mcp.quota import EVERYONE, Quota

NOON = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        yield connection


def _quota(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    created: dict[str, datetime] | None = None,
    **settings: int,
) -> Quota:
    accounts = created or {}
    return Quota(
        conn,
        Settings(mode="http", **settings),  # type: ignore[arg-type]
        account_created_at=lambda subject: accounts.get(subject, OLD_ACCOUNT),
        now=clock or Clock(),
    )


def test_charges_up_to_the_limit_then_refuses_without_counting(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=2)
    quota.charge("github:1")
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:1")
    assert (refused.value.limit, refused.value.server_wide) == (2, False)
    assert quota.status("github:1").used_today == 2  # the refused attempt is not counted
    quota.charge("github:2")  # other users are unaffected
    assert quota.status("github:2").used_today == 1


def test_refusal_reports_without_counting(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=1)
    assert quota.refusal("github:1") is None
    quota.charge("github:1")
    refusal = quota.refusal("github:1")
    assert isinstance(refusal, QuotaExceeded) and refusal.limit == 1
    assert quota.status("github:1").used_today == 1


def test_a_new_utc_day_starts_from_zero(conn: sqlite3.Connection) -> None:
    clock = Clock(datetime(2026, 10, 2, 23, 59, tzinfo=UTC))
    quota = _quota(conn, clock, user_daily_limit=1)
    quota.charge("github:1")
    status = quota.status("github:1")
    assert (status.used_today, status.resets_at) == (1, datetime(2026, 10, 3, tzinfo=UTC))
    clock.now = datetime(2026, 10, 3, 0, 1, tzinfo=UTC)
    quota.charge("github:1")
    assert quota.status("github:1").used_today == 1


def test_young_github_accounts_get_the_new_user_limit(conn: sqlite3.Connection) -> None:
    created = {"github:new": NOON - timedelta(days=29), "github:old": NOON - timedelta(days=30)}
    quota = _quota(conn, created=created, user_daily_limit=300, new_user_daily_limit=1)
    assert (quota.limit_for("github:new"), quota.limit_for("github:old")) == (1, 300)
    quota.charge("github:new")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:new")
    assert refused.value.limit == 1


def test_an_unknown_account_age_gets_the_new_account_limit(conn: sqlite3.Connection) -> None:
    quota = Quota(
        conn,
        Settings(mode="http", user_daily_limit=5, new_user_daily_limit=1),
        account_created_at=lambda subject: None,
        now=Clock(),
    )
    assert quota.limit_for("github:1") == 1  # fail closed


def test_zero_means_unlimited(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=0)
    for _ in range(50):
        quota.charge("github:1")
    status = quota.status("github:1")
    assert (status.used_today, status.limit) == (50, 0)


def test_the_server_wide_cap_refuses_everyone_and_rolls_back_the_users_count(
    conn: sqlite3.Connection,
) -> None:
    quota = _quota(conn, user_daily_limit=10, global_daily_limit=2)
    quota.charge("github:1")
    quota.charge("github:2")
    with pytest.raises(QuotaExceeded) as refused:
        quota.charge("github:3")
    assert (refused.value.limit, refused.value.server_wide) == (2, True)
    assert quota.status("github:3").used_today == 0  # rolled back with the global row
    assert quota.used_by_everyone_today() == 2
    refusal = quota.refusal("github:1")
    assert refusal is not None and (refusal.limit, refusal.server_wide) == (2, True)


def test_everyone_is_counted_while_the_cap_is_off(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, global_daily_limit=0)
    quota.charge("github:1")
    quota.charge("github:2")
    assert quota.used_by_everyone_today() == 2  # ready if the cap is switched on mid-day
    row = conn.execute("SELECT requests FROM usage WHERE subject = ?", (EVERYONE,)).fetchone()
    assert row == (2,)


def test_charge_leaves_no_transaction_open_after_a_refusal(conn: sqlite3.Connection) -> None:
    quota = _quota(conn, user_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded):
        quota.charge("github:1")
    assert conn.in_transaction is False
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_quota.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.quota'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/quota.py`:

````python
"""Daily quota of RealOEM requests per user, plus an optional server-wide cap (design 4.7).

What is counted: cache-miss page fetches, once per fetch that goes to the network. Cache hits,
retries and redirect hops are free. Days are UTC days.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
  subject TEXT NOT NULL, day TEXT NOT NULL, requests INTEGER NOT NULL,
  PRIMARY KEY (subject, day))
"""
EVERYONE = "*"  # the subject of the server-wide row
QUOTA_KEY = "quota"  # services.extras key under which the hosted server keeps its Quota


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QuotaStatus:
    used_today: int
    limit: int  # 0 = unlimited
    resets_at: datetime  # the next 00:00 UTC


class Quota:
    """Counts requests in the `usage` table of the given SQLite connection.

    The connection must be in autocommit mode (isolation_level=None): charge() runs its own
    BEGIN IMMEDIATE ... COMMIT so the check and the increment are one atomic step.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        account_created_at: Callable[[str], datetime | None],
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """account_created_at returns the subject's GitHub account creation time, timezone-aware,
        or None when unknown; an unknown age gets the new-account limit (fail closed)."""
        self._conn = conn
        self._settings = settings
        self._account_created_at = account_created_at
        self._now = now
        conn.execute(USAGE_SCHEMA)

    def _day(self) -> str:
        return self._now().astimezone(UTC).date().isoformat()

    def limit_for(self, subject: str) -> int:
        """The subject's daily limit: lower while its GitHub account is new. 0 = unlimited."""
        created = self._account_created_at(subject)
        young = timedelta(days=self._settings.min_account_age_days)
        if created is None or self._now() - created < young:
            return self._settings.new_user_daily_limit
        return self._settings.user_daily_limit

    def _used(self, subject: str, day: str) -> int:
        row = self._conn.execute(
            "SELECT requests FROM usage WHERE subject = ? AND day = ?", (subject, day)
        ).fetchone()
        return row[0] if row else 0

    def refusal(self, subject: str) -> QuotaExceeded | None:
        """Why a request by subject would be refused right now, without counting anything."""
        day = self._day()
        limit = self.limit_for(subject)
        if limit and self._used(subject, day) >= limit:
            return QuotaExceeded(limit)
        cap = self._settings.global_daily_limit
        if cap and self._used(EVERYONE, day) >= cap:
            return QuotaExceeded(cap, server_wide=True)
        return None

    def charge(self, subject: str) -> None:
        """Count one request, or raise QuotaExceeded and count nothing."""
        day = self._day()
        limit = self.limit_for(subject)
        cap = self._settings.global_daily_limit
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if not self._bump(subject, day, limit):
                raise QuotaExceeded(limit)
            # The server-wide row is always counted, so the cap can be switched on mid-day.
            if not self._bump(EVERYONE, day, cap):
                raise QuotaExceeded(cap, server_wide=True)
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _bump(self, subject: str, day: str, limit: int) -> bool:
        self._conn.execute(
            "INSERT OR IGNORE INTO usage (subject, day, requests) VALUES (?, ?, 0)", (subject, day)
        )
        cursor = self._conn.execute(
            "UPDATE usage SET requests = requests + 1 "
            "WHERE subject = ? AND day = ? AND (? = 0 OR requests < ?)",
            (subject, day, limit, limit),
        )
        return cursor.rowcount == 1

    def status(self, subject: str) -> QuotaStatus:
        now = self._now().astimezone(UTC)
        midnight = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
        return QuotaStatus(
            used_today=self._used(subject, self._day()),
            limit=self.limit_for(subject),
            resets_at=midnight,
        )

    def used_by_everyone_today(self) -> int:
        return self._used(EVERYONE, self._day())
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_quota.py`
Expected: `9 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1021 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/quota.py server/tests/unit/test_quota.py
git commit -m "feat(hosted): daily request quota per user with an optional server-wide cap" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 8: `FetchGate`

Before a cache-miss fetch waits for the request lock, the gate refuses it if the user is already at
the day's limit or the server-wide cap is reached, if the tool call is past its deadline, or if too
many fetches are already waiting (4 per user, 20 overall). Otherwise it yields how long the fetch
may wait: 60 s, or less when the call deadline is closer. `FetchGate.time_left()` is the one place
that reads the deadline with the gate's clock; Task 13 uses it too.

**Files:**
- Create: `server/src/realoem_mcp/gate.py`
- Test: `server/tests/unit/test_gate.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_gate.py`:

````python
"""FetchGate: who may queue for RealOEM, and for how long (design 4.7)."""

import sqlite3
from collections.abc import Iterator
from contextlib import AsyncExitStack, closing
from datetime import UTC, datetime

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.current_user import call_started_at
from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded
from realoem_mcp.gate import MAX_OVERALL, MAX_PER_SUBJECT, MAX_WAIT_S, FetchGate
from realoem_mcp.http_client import Admission
from realoem_mcp.quota import Quota

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as connection:
        yield connection


def _gate(conn: sqlite3.Connection, clock: Clock, **settings: float) -> tuple[FetchGate, Quota]:
    config = Settings(mode="http", **settings)  # type: ignore[arg-type]
    quota = Quota(
        conn,
        config,
        account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),  # established
        now=lambda: datetime(2026, 10, 2, tzinfo=UTC),
    )
    return FetchGate(config, quota, clock=clock), quota


def test_the_limits_are_the_designed_ones() -> None:
    assert (MAX_PER_SUBJECT, MAX_OVERALL, MAX_WAIT_S) == (4, 20, 60.0)


async def test_outside_a_tool_call_the_wait_is_the_queue_limit(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with gate.admit("github:1") as admission:
        assert admission == Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
        assert gate.waiting_or_in_flight == 1
    assert gate.waiting_or_in_flight == 0


async def test_the_call_deadline_shortens_the_wait(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=50.0)
    token = call_started_at.set(clock.now - 20.0)  # the call started 20 s ago
    try:
        async with gate.admit("github:1") as admission:
            assert admission == Admission(wait_s=30.0, deadline_bound=True)
    finally:
        call_started_at.reset(token)


async def test_a_distant_deadline_leaves_the_queue_limit(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=120.0)
    token = call_started_at.set(clock.now - 10.0)  # 110 s left
    try:
        async with gate.admit("github:1") as admission:
            assert admission == Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
    finally:
        call_started_at.reset(token)


async def test_a_failure_inside_the_admission_releases_it(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    with pytest.raises(Busy):
        async with gate.admit("github:1"):
            raise Busy()  # as the client's timed wait for the lock does
    assert gate.waiting_or_in_flight == 0


async def test_a_call_past_its_deadline_is_refused(conn: sqlite3.Connection) -> None:
    clock = Clock()
    gate, _ = _gate(conn, clock, call_deadline_s=50.0)
    token = call_started_at.set(clock.now - 51.0)
    try:
        with pytest.raises(CallDeadline):
            async with gate.admit("github:1"):
                pass
    finally:
        call_started_at.reset(token)
    assert gate.waiting_or_in_flight == 0


async def test_a_user_already_at_the_limit_never_queues(conn: sqlite3.Connection) -> None:
    gate, quota = _gate(conn, Clock(), user_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded):
        async with gate.admit("github:1"):
            pass
    assert gate.waiting_or_in_flight == 0


async def test_nobody_queues_once_the_server_wide_cap_is_reached(
    conn: sqlite3.Connection,
) -> None:
    gate, quota = _gate(conn, Clock(), global_daily_limit=1)
    quota.charge("github:1")
    with pytest.raises(QuotaExceeded) as refused:
        async with gate.admit("github:2"):
            pass
    assert refused.value.server_wide is True


async def test_each_user_may_have_only_a_few_fetches_waiting(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with AsyncExitStack() as stack:
        for _ in range(MAX_PER_SUBJECT):
            await stack.enter_async_context(gate.admit("github:1"))
        with pytest.raises(Busy):
            async with gate.admit("github:1"):
                pass
        assert gate.waiting_or_in_flight == MAX_PER_SUBJECT  # the refusal counted nothing
        async with gate.admit("github:2"):  # another user still gets in
            pass
    async with gate.admit("github:1"):  # released on exit
        pass


async def test_everyone_together_may_have_only_twenty_waiting(conn: sqlite3.Connection) -> None:
    gate, _ = _gate(conn, Clock())
    async with AsyncExitStack() as stack:
        for user in range(MAX_OVERALL):
            await stack.enter_async_context(gate.admit(f"github:{user}"))
        with pytest.raises(Busy):
            async with gate.admit("github:999"):
                pass
    assert gate.waiting_or_in_flight == 0
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_gate.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.gate'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/gate.py`:

````python
"""Queue admission for cache-miss fetches on the hosted server (design 4.7).

Every fetch that has to go to RealOEM waits for the one request lock. The gate decides, before
the wait, whether the fetch may queue at all and for how long: never past the day's quota or the
server-wide cap, never past the tool call's deadline, and only while the queue is short.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from realoem_mcp.config import Settings
from realoem_mcp.current_user import time_left
from realoem_mcp.errors import Busy, CallDeadline
from realoem_mcp.http_client import Admission
from realoem_mcp.quota import Quota

MAX_PER_SUBJECT = 4  # waiting-or-in-flight cache-miss fetches of one user
MAX_OVERALL = 20  # the same, for everyone together
MAX_WAIT_S = 60.0  # longest wait for a turn
GATE_KEY = "gate"  # services.extras key under which the hosted server keeps its FetchGate


class FetchGate:
    def __init__(
        self, settings: Settings, quota: Quota, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._settings = settings
        self._quota = quota
        self._clock = clock  # the same clock CallClock stamps call_started_at with
        self._active: Counter[str] = Counter()

    @property
    def waiting_or_in_flight(self) -> int:
        return sum(self._active.values())

    def time_left(self) -> float | None:
        """Seconds until the current tool call's deadline; None outside a tool call."""
        return time_left(self._settings, self._clock)

    @asynccontextmanager
    async def admit(self, subject: str) -> AsyncIterator[Admission]:
        """Admit one cache-miss fetch by subject, or raise without counting anything.

        Raises QuotaExceeded (the user is already at the day's limit, or the server-wide cap is
        reached), CallDeadline (the tool call is out of time) or Busy (too many fetches are
        already waiting). The counters are released when the context exits, however it exits.
        """
        if (refusal := self._quota.refusal(subject)) is not None:
            raise refusal
        left = self.time_left()
        if left is not None and left <= 0:
            raise CallDeadline()
        if self._active[subject] >= MAX_PER_SUBJECT or self.waiting_or_in_flight >= MAX_OVERALL:
            raise Busy()
        self._active[subject] += 1
        try:
            if left is not None and left < MAX_WAIT_S:
                yield Admission(wait_s=left, deadline_bound=True)
            else:
                yield Admission(wait_s=MAX_WAIT_S, deadline_bound=False)
        finally:
            self._active[subject] -= 1
            if not self._active[subject]:
                del self._active[subject]
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_gate.py`
Expected: `10 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1031 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/gate.py server/tests/unit/test_gate.py
git commit -m "feat(hosted): admit cache-miss fetches by quota, deadline and queue length" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 5: Shared mode

### Task 9: `build_shared` and the services hooks

`create_services` passes the three hooks to the client and gives the cache its cap and free-space
floor from the settings. `build_shared()` (HTTP mode only) builds the quota and the gate and wires
the hooks through `require_user`, so a fetch without a signed-in caller is refused, never charged
to nobody. VIN pages (`select?vin=`, `production`) are owned by
`HMAC-SHA256(owner_key, subject)`, so the cache holds no user ids; plan 1b derives `owner_key` from
the server secret, and an empty key is refused (the owner would then be a plain hash of a
GitHub id, which anyone can reverse). The quota and the gate are kept in `services.extras` (`QUOTA_KEY`, `GATE_KEY`)
for the tools that need them. `tests/shared_env.py` builds these Services offline for the tool
tests; its users have old GitHub accounts unless a test says otherwise.

**Files:**
- Modify: `server/src/realoem_mcp/services.py`
- Create: `server/src/realoem_mcp/shared.py`, `server/tests/shared_env.py`
- Test: `server/tests/tools/test_shared_wiring.py`

- [ ] **Step 1: Write the test environment** `server/tests/shared_env.py`:

````python
"""Offline Services in hosted ("http") mode: quota, gate and per-user VIN pages, fake clock."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from realoem_mcp.shared import Shared, build_shared
from tests.auth_helpers import signed_in
from tests.harness import BRANDS_DIR, FakeClock, FixtureTransport, Route

OWNER_KEY = b"test-owner-key"
TODAY = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)  # the default GitHub account age: established


@asynccontextmanager
async def shared_services(
    tmp_path: Path,
    routes: Mapping[str, Route | str] | httpx.AsyncBaseTransport,
    *,
    created: Mapping[str, datetime] | None = None,
    settings: Callable[[Path], Settings] | None = None,
    clock: FakeClock | None = None,
    **overrides: object,
) -> AsyncIterator[tuple[Shared, httpx.AsyncBaseTransport]]:
    """build_shared() on temporary folders. created maps subjects to GitHub account dates
    (default: an old account). settings builds the Settings instead of the default; clock
    drives request spacing and the call deadline.

    The hosted cache keeps 100 MB of the temporary drive free: with less free space there,
    pages are served uncached and tests that count requests fail.
    """
    transport = routes if isinstance(routes, httpx.AsyncBaseTransport) else FixtureTransport(routes)
    config = (
        settings(tmp_path)
        if settings is not None
        else Settings(
            mode="http",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
            brands_dir=BRANDS_DIR,
            **overrides,  # type: ignore[arg-type]
        )
    )
    clock = clock or FakeClock()
    accounts = dict(created or {})
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        shared = build_shared(
            config,
            conn,
            owner_key=OWNER_KEY,
            account_created_at=lambda subject: accounts.get(subject, OLD_ACCOUNT),
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
            now=lambda: TODAY,
        )
        try:
            yield shared, transport
        finally:
            await shared.services.aclose()
    if isinstance(transport, FixtureTransport):
        assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"


async def call_tool(
    services: Services, subject: str | None, tool: str, arguments: dict[str, object]
) -> CallToolResult:
    """Call one tool through the in-memory MCP client, signed in as subject (None: anonymous)."""
    async with Client(build_server(services)) as client:
        if subject is None:
            return await client.call_tool(tool, arguments)
        with signed_in(subject):
            return await client.call_tool(tool, arguments)
````

- [ ] **Step 2: Write the failing test** `server/tests/tools/test_shared_wiring.py`:

````python
"""build_shared: quotas, per-user VIN pages and the cache cap through the MCP tools (design 4.7)."""

import hashlib
import hmac
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.shared import build_shared, vin_page_owner
from tests.auth_helpers import signed_in
from tests.harness import BRANDS_DIR, url
from tests.shared_env import TODAY, call_tool, shared_services

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
VIN = url("select", vin="PX22770")
ROUTES = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    VIN: "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


async def test_users_share_parts_pages_but_pay_for_their_own_vin_pages(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        services = shared.services
        for subject in ("github:1", "github:2"):
            part = await call_tool(services, subject, "lookup_part", PART)
            vin = await call_tool(services, subject, "decode_vin", {"vin": "PX22770"})
            assert part.is_error is False and vin.is_error is False
        sent = [str(request.url) for request in transport.requests]
        assert sent == [OIL_FILTER, VIN, VIN]  # the part page once, the VIN page per user
        assert shared.quota.status("github:1").used_today == 2
        assert shared.quota.status("github:2").used_today == 1  # the part page was free
        assert services.cache.get(VIN) is None  # no shared copy of a VIN page exists


async def test_a_tool_call_without_a_signed_in_user_fetches_nothing(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        result = await call_tool(shared.services, None, "lookup_part", PART)
        assert result.is_error is True
        assert "not signed in" in result.content[0].text
        assert transport.requests == []


async def test_an_anonymous_refresh_of_an_old_copy_fetches_nothing(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, transport):
        services = shared.services
        await call_tool(services, "github:1", "lookup_part", PART)
        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="microseconds")
        services.cache._conn.execute("UPDATE pages SET fetched_at = ?", (two_hours_ago,))
        result = await call_tool(services, None, "lookup_part", {**PART, "refresh": True})
        assert result.is_error is True
        assert "not signed in" in result.content[0].text
        assert len(transport.requests) == 1


async def test_a_user_over_the_limit_still_gets_cached_answers(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES, user_daily_limit=1) as (shared, transport):
        services = shared.services
        first = await call_tool(services, "github:1", "lookup_part", PART)
        refused = await call_tool(services, "github:1", "decode_vin", {"vin": "PX22770"})
        again = await call_tool(services, "github:1", "lookup_part", PART)
        assert first.is_error is False
        assert refused.is_error is True
        assert refused.content[0].text.endswith(
            "You've used your 1 RealOEM lookups for today; the limit resets at 00:00 UTC. "
            "Cached results remain available."
        )
        assert again.is_error is False and again.structured_content["from_cache"] is True
        assert [str(request.url) for request in transport.requests] == [OIL_FILTER]


async def test_a_young_github_account_gets_the_smaller_limit(tmp_path: Path) -> None:
    created = {"github:new": TODAY - timedelta(days=3)}
    async with shared_services(tmp_path, ROUTES, created=created, new_user_daily_limit=1) as (
        shared,
        _,
    ):
        services = shared.services
        decoded = await call_tool(services, "github:new", "decode_vin", {"vin": "PX22770"})
        assert decoded.is_error is False
        refused = await call_tool(services, "github:new", "lookup_part", PART)
        assert refused.is_error is True
        assert "your 1 RealOEM lookups" in refused.content[0].text


async def test_the_hosted_cache_is_capped(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES) as (shared, _):
        cache = shared.services.cache
        assert cache._max_bytes == 400 * 1024 * 1024
        assert cache._min_free_bytes == 100 * 1024 * 1024


def test_only_pages_that_carry_a_vin_are_owned_by_the_caller() -> None:
    owner = vin_page_owner(Settings(mode="http"), b"key")
    expected = hmac.new(b"key", b"github:1", hashlib.sha256).hexdigest()
    with signed_in("github:1"):
        assert owner(PageType.SELECT, {"vin": "PX22770"}) == expected
        assert owner(PageType.PRODUCTION, {"vin": "PX22770"}) == expected
        assert owner(PageType.SELECT, {"product": "P", "archive": "0"}) == ""  # the model cascade
        assert owner(PageType.PARTXREF, {"q": "11427953129"}) == ""
    with pytest.raises(RealOemError, match="not signed in"):
        owner(PageType.SELECT, {"vin": "PX22770"})


@pytest.mark.parametrize(
    ("mode", "owner_key", "message"),
    [("stdio", b"k", "mode='http'"), ("http", b"", "secret owner_key")],
)
def test_build_shared_needs_http_mode_and_a_key(
    tmp_path: Path, mode: str, owner_key: bytes, message: str
) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        with pytest.raises(ValueError, match=message):
            build_shared(
                Settings(
                    mode=mode,  # type: ignore[arg-type]
                    cache_dir=tmp_path,
                    data_dir=tmp_path,
                    brands_dir=BRANDS_DIR,
                ),
                conn,
                owner_key=owner_key,
                account_created_at=lambda subject: None,
            )
    finally:
        conn.close()
````

- [ ] **Step 3: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_shared_wiring.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.shared'`.

- [ ] **Step 4: Pass the hooks through `create_services`.** In `server/src/realoem_mcp/services.py`:

Edit 1. Find:

````python
from realoem_mcp.brands import BrandRegistry
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import RealOemClient


@dataclass
````

Replace with:

````python
from realoem_mcp.brands import BrandRegistry
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Admit, Charge, Owner, RealOemClient


@dataclass
````

Edit 2. Find:

````python
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Services:
    brands = BrandRegistry.load(settings.brands_dir)
    cache = PageCache(settings.cache_dir)
    try:
        client = RealOemClient(
            settings,
````

Replace with:

````python
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    admit: Admit | None = None,
    charge: Charge | None = None,
    owner: Owner | None = None,
) -> Services:
    """admit, charge and owner are the hosted server's client hooks (see shared.build_shared)."""
    brands = BrandRegistry.load(settings.brands_dir)
    # Only non-zero limits are passed, so a PageCache stand-in that takes just cache_dir (as in
    # tests/unit/test_services.py) keeps working; stdio has no limits unless REALOEM_CACHE_MAX_MB.
    limits: dict[str, int] = {}
    if settings.cache_max_bytes:
        limits["max_bytes"] = settings.cache_max_bytes
    if settings.cache_min_free_bytes:
        limits["min_free_bytes"] = settings.cache_min_free_bytes
    cache = PageCache(settings.cache_dir, **limits)
    try:
        client = RealOemClient(
            settings,
````

Edit 3. Find:

````python
            transport=transport,
            clock=clock or time.monotonic,
            sleep=sleep or asyncio.sleep,
        )
    except BaseException:
        cache.close()
````

Replace with:

````python
            transport=transport,
            clock=clock or time.monotonic,
            sleep=sleep or asyncio.sleep,
            admit=admit,
            charge=charge,
            owner=owner,
        )
    except BaseException:
        cache.close()
````

- [ ] **Step 5: Implement** `server/src/realoem_mcp/shared.py`:

````python
"""Wires the hosted ("http") mode pieces together: quota, gate, cache owners, Services.

The HTTP app builds its Services through build_shared(); nothing here imports the HTTP layer,
so the whole shared mode runs in tests through the in-memory MCP client.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.current_user import require_user
from realoem_mcp.gate import GATE_KEY, FetchGate
from realoem_mcp.http_client import Owner
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY, Quota
from realoem_mcp.services import Services, create_services


@dataclass
class Shared:
    services: Services
    quota: Quota
    gate: FetchGate


def vin_page_owner(settings: Settings, owner_key: bytes) -> Owner:
    """Cache owner of a page: the caller for pages that carry a VIN, "" (shared) otherwise.

    A shared VIN page would tell any user, through from_cache and fetched_at, whether and when
    someone else decoded that VIN. The owner is a keyed hash, so the cache holds no user ids.
    """

    def owner(page_type: PageType, params: Mapping[str, str]) -> str:
        carries_vin = page_type is PageType.PRODUCTION or (
            page_type is PageType.SELECT and "vin" in params
        )
        if not carries_vin:
            return ""
        subject = require_user(settings).subject
        return hmac.new(owner_key, subject.encode("utf-8"), hashlib.sha256).hexdigest()

    return owner


def build_shared(
    settings: Settings,
    usage_conn: sqlite3.Connection,
    *,
    owner_key: bytes,
    account_created_at: Callable[[str], datetime | None],
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Shared:
    """Services for the hosted server: every cache-miss fetch is admitted, charged to the
    signed-in caller and, for VIN pages, cached for that caller only.

    usage_conn is an autocommit SQLite connection that holds the `usage` table.
    """
    if settings.mode != "http":
        raise ValueError("build_shared needs Settings(mode='http')")
    if not owner_key:  # without a key the owner would be a plain hash of the user id
        raise ValueError("build_shared needs a secret owner_key")
    quota = Quota(
        usage_conn,
        settings,
        account_created_at=account_created_at,
        **({"now": now} if now is not None else {}),
    )
    gate = FetchGate(settings, quota, clock=clock or time.monotonic)
    services = create_services(
        settings,
        transport=transport,
        clock=clock,
        sleep=sleep,
        # require_user: a fetch with no signed-in caller is refused, never charged to nobody.
        admit=lambda: gate.admit(require_user(settings).subject),
        charge=lambda: quota.charge(require_user(settings).subject),
        owner=vin_page_owner(settings, owner_key),
    )
    services.extras[QUOTA_KEY] = quota
    services.extras[GATE_KEY] = gate
    return Shared(services=services, quota=quota, gate=gate)
````

- [ ] **Step 6: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_shared_wiring.py`
Expected: `9 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1040 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/services.py server/src/realoem_mcp/shared.py server/tests/shared_env.py server/tests/tools/test_shared_wiring.py
git commit -m "feat(hosted): build_shared wires quota, gate and per-user VIN pages into Services" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 10: Every `shorten` names the page's owner

`decode_vin` shortens a missed VIN to one day and expires unparseable pages. Those calls must name
the page's owner, or they would touch the (empty) shared entry and leave the user's 30-day entry in
place. The other tools' `shorten` calls get `owner=page.owner` too: their pages are shared today,
but a missing owner fails silently, so every call names it.

**Files:**
- Modify: `server/src/realoem_mcp/tools/vin.py` (three `shorten` calls), and one `shorten` line
  each in `tools/catalog.py` (two), `tools/parts.py`, `tools/fitment.py` and `tools/vehicles.py`
  (two)
- Test: `server/tests/tools/test_shared_vin.py`

- [ ] **Step 1: Write the failing test** `server/tests/tools/test_shared_vin.py`:

````python
"""decode_vin on the hosted server: a missed VIN is shortened in its owner's cache entry."""

import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from tests.auth_helpers import signed_in
from tests.harness import url
from tests.shared_env import OWNER_KEY, call_tool, shared_services

pytestmark = pytest.mark.anyio

MISS = url("select", vin="ZZZZZZZ")
MISS_PARAMS = {"vin": "ZZZZZZZ"}
SELECT = url("select", vin="PX22770")
PRODUCTION = url("production", vin="PX22770")
DECODE_WITH_PRODUCTION = {"vin": "PX22770", "include_production": True}


def _owner_of(subject: str) -> str:
    """The cache owner of a user's VIN pages: a keyed hash, so the cache holds no user ids."""
    return hmac.new(OWNER_KEY, subject.encode("utf-8"), hashlib.sha256).hexdigest()


def _lifetime(fetched_at: str, expires_at: str) -> timedelta:
    return datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at)


async def test_a_missed_vin_is_cached_for_one_day_for_its_owner_only(tmp_path: Path) -> None:
    async with shared_services(tmp_path, {MISS: "select/vin_miss_zzzzzzz.html"}) as (shared, _):
        services = shared.services
        result = await call_tool(services, "github:1", "decode_vin", MISS_PARAMS)
        assert result.structured_content["status"] == "not_found"
        ((owner, fetched_at, expires_at),) = services.cache._conn.execute(
            "SELECT owner, fetched_at, expires_at FROM pages WHERE url = ?", (MISS,)
        ).fetchall()
        assert owner == _owner_of("github:1")  # a per-user entry, not a shared one
        assert _lifetime(fetched_at, expires_at) == timedelta(days=1)  # shortened for the owner
        with signed_in("github:1"):
            assert services.client.cached(PageType.SELECT, "select", MISS_PARAMS) is not None
        with signed_in("github:2"):
            assert services.client.cached(PageType.SELECT, "select", MISS_PARAMS) is None
        with pytest.raises(RealOemError, match="not signed in"):  # no caller: fail closed
            services.client.cached(PageType.SELECT, "select", MISS_PARAMS)


async def test_a_production_miss_is_cached_for_one_day_for_its_owner(tmp_path: Path) -> None:
    routes = {
        SELECT: "select/vin_bmw_e93_px22770.html",
        PRODUCTION: "production/vin_miss_zzzzzzz.html",
    }
    async with shared_services(tmp_path, routes) as (shared, _):
        services = shared.services
        result = await call_tool(services, "github:1", "decode_vin", DECODE_WITH_PRODUCTION)
        assert result.is_error is False, result.content
        ((owner, fetched_at, expires_at),) = services.cache._conn.execute(
            "SELECT owner, fetched_at, expires_at FROM pages WHERE url = ?", (PRODUCTION,)
        ).fetchall()
        assert owner == _owner_of("github:1")
        assert _lifetime(fetched_at, expires_at) == timedelta(days=1)


async def test_an_unparseable_production_page_is_not_kept_for_its_owner(tmp_path: Path) -> None:
    routes = {SELECT: "select/vin_bmw_e93_px22770.html", PRODUCTION: "select/vin_miss_zzzzzzz.html"}
    async with shared_services(tmp_path, routes) as (shared, transport):
        for _ in range(2):
            result = await call_tool(
                shared.services, "github:1", "decode_vin", DECODE_WITH_PRODUCTION
            )
            assert result.is_error is True
        sent = [str(request.url) for request in transport.requests]
        assert sent == [SELECT, PRODUCTION, PRODUCTION]  # expired at once, so fetched again
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_shared_vin.py`
Expected: three tests FAIL: both VIN lifetimes are `30 days` instead of `1 day`, and the unparseable production page is not fetched again.

- [ ] **Step 3: Implement.** In `server/src/realoem_mcp/tools/vin.py`:

Edit 1. Find:

````python
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
````

Replace with:

````python
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL, owner=page.owner)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
````

Edit 2. Find:

````python
        with _expire_if_unparseable(services, production_page):
            matches = parse_production(production_page.html, url=production_page.url)
        if not matches:
            services.cache.shorten(production_page.url, VIN_MISS_TTL)
        production, notes = pick_production(matches, vin.serial, select.type_code)
        warnings.extend(notes)
    return VinDecodeResult.from_pages(
````

Replace with:

````python
        with _expire_if_unparseable(services, production_page):
            matches = parse_production(production_page.html, url=production_page.url)
        if not matches:
            services.cache.shorten(production_page.url, VIN_MISS_TTL, owner=production_page.owner)
        production, notes = pick_production(matches, vin.serial, select.type_code)
        warnings.extend(notes)
    return VinDecodeResult.from_pages(
````

Edit 3. Find:

````python
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise


````

Replace with:

````python
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW, owner=page.owner)
        raise


````

- [ ] **Step 4: The other tools.** In `server/src/realoem_mcp/tools/catalog.py`:

Edit 1. Find:

````python
            dedupe_names=brand.dedupe_repeated_names,
        )
    if not subgroups:
        services.cache.shorten(page.url, MISSING_GROUP_TTL)
        raise NotFound(
            f"vehicle {vid} has no main group {main_group}; list_part_groups shows the ones it has."
        )
````

Replace with:

````python
            dedupe_names=brand.dedupe_repeated_names,
        )
    if not subgroups:
        services.cache.shorten(page.url, MISSING_GROUP_TTL, owner=page.owner)
        raise NotFound(
            f"vehicle {vid} has no main group {main_group}; list_part_groups shows the ones it has."
        )
````

Edit 2. Find:

````python
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise
````

Replace with:

````python
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW, owner=page.owner)
        raise
````

In `server/src/realoem_mcp/tools/parts.py`:

Edit 1. Find:

````python
    try:
        xref = _parse(services, page, narrowed="series" in params)
    except LayoutChanged:
        services.cache.shorten(page.url, timedelta(0))  # never keep a page we cannot parse
        raise
    if xref is None or not matches(query, xref.part_number):
        return None, page
````

Replace with:

````python
    try:
        xref = _parse(services, page, narrowed="series" in params)
    except LayoutChanged:
        # Never keep a page we cannot parse.
        services.cache.shorten(page.url, timedelta(0), owner=page.owner)
        raise
    if xref is None or not matches(query, xref.part_number):
        return None, page
````

In `server/src/realoem_mcp/tools/fitment.py`:

Edit 1. Find:

````python
            page.html, url=page.url, client=services.client, vehicle_id=str(vid)
        )
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)  # never keep a page we cannot parse
        raise
    if search is None or not matches(query, search.part_number):
        raise _unknown_part(query)
````

Replace with:

````python
            page.html, url=page.url, client=services.client, vehicle_id=str(vid)
        )
    except LayoutChanged:
        # Never keep a page we cannot parse.
        services.cache.shorten(page.url, EXPIRE_NOW, owner=page.owner)
        raise
    if search is None or not matches(query, search.part_number):
        raise _unknown_part(query)
````

In `server/src/realoem_mcp/tools/vehicles.py`:

Edit 1. Find:

````python
    try:
        return parse_vehicles(page.html, url=page.url, brands=services.brands)
    except LayoutChanged:
        services.cache.shorten(page.url, timedelta(0))  # never keep an unparseable page cached
        raise


````

Replace with:

````python
    try:
        return parse_vehicles(page.html, url=page.url, brands=services.brands)
    except LayoutChanged:
        # Never keep an unparseable page cached.
        services.cache.shorten(page.url, timedelta(0), owner=page.owner)
        raise


````

Edit 2. Find:

````python
    probe_number = max(1, math.ceil(probe_total / PAGE_SIZE))
    probe_page = await _fetch(services, probe_number)
    if probe_number > 1 and is_past_end(probe_page.html):
        services.cache.shorten(probe_page.url, timedelta(0))
        first, first_page = await fetch_vehicles_page(services, 1)
        index.record_check(remote_total=first.total, resume=None)
        return _result(
````

Replace with:

````python
    probe_number = max(1, math.ceil(probe_total / PAGE_SIZE))
    probe_page = await _fetch(services, probe_number)
    if probe_number > 1 and is_past_end(probe_page.html):
        services.cache.shorten(probe_page.url, timedelta(0), owner=probe_page.owner)
        first, first_page = await fetch_vehicles_page(services, 1)
        index.record_check(remote_total=first.total, resume=None)
        return _result(
````

- [ ] **Step 5: Run the new and the existing VIN tests**

Run: `uv run --directory server pytest -q tests/tools/test_shared_vin.py tests/tools/test_vin.py tests/tools/test_vin_cache.py tests/tools/test_vin_production.py`
Expected: `28 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1043 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/tools/vin.py server/src/realoem_mcp/tools/catalog.py server/src/realoem_mcp/tools/parts.py server/src/realoem_mcp/tools/fitment.py server/src/realoem_mcp/tools/vehicles.py server/tests/tools/test_shared_vin.py
git commit -m "fix(tools): shorten and expire cache entries in their owner's row" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 6: Admin tools and the call deadline

### Task 11: Admin tools in hosted mode

On the hosted server `server_status` hides the cache path and shows the caller's quota (and the
server-wide cap when it is on); `cache_clear` is for administrators only, because the cache is
shared. Both require a signed-in caller. In stdio mode both behave as before (PRD F0.6 and the
existing tests still apply); the only visible difference is that `server_status`'s output now
also has `quota` and `global_limit` fields, which are `null` in stdio, and `cache_path` becomes
nullable in the output schema (it is never `null` in stdio). The spec's "omits `cache_path`" is
done as `null` because a tool's output schema is fixed; plan 2's documentation update records it. The other figures (`requests_made`, cache entries and bytes) stay server-wide on purpose:
they describe the shared server, not anyone's lookups.

**Files:**
- Modify: `server/src/realoem_mcp/tools/admin.py` (replace the whole file)
- Test: `server/tests/tools/test_shared_admin.py`

- [ ] **Step 1: Write the failing test** `server/tests/tools/test_shared_admin.py`:

````python
"""server_status and cache_clear on the hosted server (design 4.7, 4.8)."""

from pathlib import Path

import pytest

from tests.harness import url
from tests.shared_env import call_tool, shared_services

pytestmark = pytest.mark.anyio

ROUTES = {
    url("partxref", q="11427953129"): "partxref/oil_filter_11427953129.html",
    url("select", vin="PX22770"): "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


async def test_server_status_shows_the_callers_quota_and_no_path(tmp_path: Path) -> None:
    async with shared_services(tmp_path, ROUTES, global_daily_limit=2000) as (shared, _):
        services = shared.services
        await call_tool(services, "github:2", "decode_vin", {"vin": "PX22770"})  # someone else
        await call_tool(services, "github:1", "lookup_part", PART)
        status = (await call_tool(services, "github:1", "server_status", {})).structured_content
        assert status["cache_path"] is None
        assert (status["quota"]["used_today"], status["quota"]["limit"]) == (1, 300)  # own count
        assert status["quota"]["resets_at"].startswith("2026-10-03T00:00:00")
        assert status["global_limit"] == 2000
        anonymous = await call_tool(services, None, "server_status", {})
        assert anonymous.is_error is True


async def test_only_admins_may_clear_the_shared_cache(tmp_path: Path) -> None:
    admins = frozenset({"github:1"})
    async with shared_services(tmp_path, ROUTES, admins=admins) as (shared, _):
        services = shared.services
        await call_tool(services, "github:2", "lookup_part", PART)
        refused = await call_tool(services, "github:2", "cache_clear", {})
        assert refused.is_error is True
        assert "Only an administrator" in refused.content[0].text
        assert (await call_tool(services, None, "cache_clear", {})).is_error is True
        assert services.cache.stats().entries == 1
        cleared = await call_tool(services, "github:1", "cache_clear", {})
        assert cleared.structured_content == {"removed": 1}
        status = (await call_tool(services, "github:1", "server_status", {})).structured_content
        assert status["global_limit"] is None  # the server-wide cap is off by default
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_shared_admin.py`
Expected: FAIL: `cache_path` is a path, and a non-admin's `cache_clear` succeeds.

- [ ] **Step 3: Implement.** Replace `server/src/realoem_mcp/tools/admin.py` with:

````python
"""Admin tools: server_status, cache_clear (ARD section 5.11). Exempt from ResultMeta."""

from __future__ import annotations

from datetime import datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from realoem_mcp import __version__
from realoem_mcp.current_user import require_user
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY
from realoem_mcp.services import Services

ADMINS_ONLY = (
    "Only an administrator of this RealOEM Searcher server can clear its shared cache. "
    "Use refresh=true on a single lookup instead (it refetches copies older than an hour)."
)


class QuotaInfo(BaseModel):
    used_today: int  # RealOEM requests made for the caller today (cached answers are free)
    limit: int  # 0 = unlimited
    resets_at: datetime  # the next 00:00 UTC


class ServerStatus(BaseModel):
    version: str
    base_url: str
    user_agent: str
    min_interval_s: float
    cache_path: str | None  # None on the hosted server
    cache_entries: int
    cache_bytes: int
    requests_made: int
    quota: QuotaInfo | None = None  # hosted server: the caller's daily quota
    global_limit: int | None = None  # hosted server: the server-wide daily cap, when one is on


class CacheClearResult(BaseModel):
    removed: int


def register(app: MCPServer, services: Services) -> None:
    hosted = services.settings.mode == "http"

    @app.tool()
    async def server_status() -> ServerStatus:
        """Report this RealOEM server's version, request settings and cache size.

        Use it to troubleshoot (for example before telling the user RealOEM is unreachable) or
        when the user asks how the plugin talks to RealOEM. Makes no request to RealOEM.
        Returns version, base_url, user_agent, min_interval_s (seconds between requests),
        cache_path, cache_entries, cache_bytes and requests_made (HTTP requests sent to
        RealOEM since start, counting retries and redirect hops). On the hosted server
        cache_path is null and quota shows the caller's daily RealOEM lookups (used_today,
        limit, resets_at; cached answers are free); global_limit is the server-wide daily cap
        when one is set.
        """
        stats = services.cache.stats()
        status = ServerStatus(
            version=__version__,
            base_url=services.settings.base_url,
            user_agent=services.settings.user_agent,
            min_interval_s=services.settings.min_interval_s,
            cache_path=str(stats.path),
            cache_entries=stats.entries,
            cache_bytes=stats.bytes,
            requests_made=services.client.requests_made,
        )
        if not hosted:
            return status
        try:
            user = require_user(services.settings)
        except RealOemError as err:
            raise ToolError(err.message) from err
        usage = services.extras[QUOTA_KEY].status(user.subject)
        return status.model_copy(
            update={
                "cache_path": None,
                "quota": QuotaInfo(
                    used_today=usage.used_today, limit=usage.limit, resets_at=usage.resets_at
                ),
                "global_limit": services.settings.global_daily_limit or None,
            }
        )

    @app.tool()
    async def cache_clear(page_type: str | None = None) -> CacheClearResult:
        """Delete cached RealOEM pages so the next lookups fetch fresh copies.

        Prefer refresh=true on a single data tool call; use this only when the user asks to clear
        the cache or many answers look stale. page_type limits the clear to one page type:
        select, production, partgrp, showparts, partxref, partsearch, part or vehicles. Omit it
        to clear everything. Returns removed (the number of cached pages deleted). On the hosted
        server the cache is shared by all users, so only its administrators can clear it.
        """
        try:
            if hosted and not require_user(services.settings).is_admin:
                raise RealOemError(ADMINS_ONLY)
            target = PageType.parse(page_type) if page_type is not None else None
        except RealOemError as err:
            raise ToolError(err.message) from err
        return CacheClearResult(removed=services.cache.clear(target))
````

- [ ] **Step 4: Run the new and the existing admin tests**

Run: `uv run --directory server pytest -q tests/tools/test_shared_admin.py tests/tools/test_admin.py tests/tools/test_stdio.py`
Expected: `6 passed` (2 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1045 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/tools/admin.py server/tests/tools/test_shared_admin.py
git commit -m "feat(admin): hosted server_status shows the caller's quota; cache_clear is admin-only" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 12: `compare_vehicles` keeps its partial result at the deadline

A comparison can need many requests. When the hosted server raises `CallDeadline` (the call is out
of time) or `Busy` (the queue is full), `compare_vehicles` treats it like a spent request budget:
it reads the remaining diagrams from the cache only and returns `complete=false` with the
unfetched diagrams listed, so calling again continues from the cache. During the two diagram-list
fetches the same errors stay tool errors: there is nothing to compare without both lists. Every
other tool reports them as tool errors (the last test checks `trace_supersession`).

**Files:**
- Modify: `server/src/realoem_mcp/tools/fitment.py` (`compare` and its imports)
- Test: `server/tests/tools/test_shared_deadline.py`

- [ ] **Step 1: Write the failing test** `server/tests/tools/test_shared_deadline.py`:

````python
"""The per-call deadline on the hosted server (design 4.7)."""

from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
import pytest
from mcp import Client

from realoem_mcp import gate
from realoem_mcp.current_user import CallClock
from realoem_mcp.errors import Busy
from realoem_mcp.page_types import PageType
from realoem_mcp.server import build_server
from tests.auth_helpers import signed_in
from tests.harness import FakeClock, FixtureTransport, Route, url
from tests.shared_env import call_tool, shared_services

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
COMPARE_ROUTES = {
    url("partgrp", id=E90, mg="11"): "partgrp/e90_325i_mg11.html",
    url("partgrp", id=R56, mg="11"): "partgrp/r56_cooper_s_mg11.html",
    url("showparts", id=E90, diagId="11_3733"): "showparts/e90_325i_11_3733.html",
    url("showparts", id=R56, diagId="11_3910"): "showparts/r56_cooper_s_11_3910.html",
}
COMPARE = {
    "vehicle_a": E90,
    "vehicle_b": R56,
    "main_group": "11",
    "diag_ids": ["11_3733", "11_3910"],
}


class AfterRequests(FixtureTransport):
    """Runs then() once `count` requests have been answered."""

    def __init__(
        self, routes: Mapping[str, Route | str], count: int, then: Callable[[], None]
    ) -> None:
        super().__init__(routes)
        self._count = count
        self._then = then

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if len(self.requests) == self._count:
            self._then()
        return response


async def test_compare_vehicles_keeps_its_partial_result_at_the_deadline(tmp_path: Path) -> None:
    clock = FakeClock()  # each request after the first waits 2 s, which advances this clock
    async with shared_services(tmp_path, COMPARE_ROUTES, clock=clock, call_deadline_s=3.0) as (
        shared,
        transport,
    ):
        app = build_server(shared.services, middleware=[CallClock(clock)])
        async with Client(app) as client:
            with signed_in("github:1"):
                result = await client.call_tool("compare_vehicles", COMPARE)
                again = await client.call_tool("compare_vehicles", COMPARE)  # a new call
        assert result.is_error is False, result.content
        data = result.structured_content
        # Fetches are admitted at t=0, 0 and 2 s (the 2-second spacing is waited inside the
        # lock); the fourth is refused at admission at t=4, after the 3-second deadline.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            [],
            ["11_3910"],
        )
        assert again.structured_content["complete"] is True  # resumed from the cache
        assert len(transport.requests) == 4  # the second call fetched only the missing diagram
        assert shared.quota.status("github:1").used_today == 4  # refused fetches cost nothing


async def test_after_a_full_queue_compare_vehicles_reads_only_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with shared_services(tmp_path, COMPARE_ROUTES) as (shared, transport):
        real_admit = shared.gate.admit
        refused: list[str] = []

        def full_once(subject: str):
            if len(transport.requests) == 2 and not refused:  # A's diagram, after both lists
                refused.append(subject)
                raise Busy()
            return real_admit(subject)

        monkeypatch.setattr(shared.gate, "admit", full_once)
        result = await call_tool(shared.services, "github:1", "compare_vehicles", COMPARE)
        assert result.is_error is False, result.content
        data = result.structured_content
        # B's diagram was not even tried: after Busy the call reads only the cache.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            ["11_3733"],
            ["11_3910"],
        )
        assert len(transport.requests) == 2


async def test_compare_vehicles_treats_a_full_queue_like_a_spent_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After the B diagram and both diagram lists are fetched, the queue refuses everything.
    transport = AfterRequests(
        COMPARE_ROUTES, 3, lambda: monkeypatch.setattr(gate, "MAX_PER_SUBJECT", 0)
    )
    async with shared_services(tmp_path, transport) as (shared, _):
        services = shared.services
        with signed_in("github:1"):
            await services.client.fetch(
                PageType.SHOWPARTS, "showparts", {"id": R56, "diagId": "11_3910"}
            )
        result = await call_tool(services, "github:1", "compare_vehicles", COMPARE)
        assert result.is_error is False, result.content
        data = result.structured_content
        # A's diagram hit Busy; B's, after it, was still read from the cache.
        assert (data["complete"], data["unfetched_a"], data["unfetched_b"]) == (
            False,
            ["11_3733"],
            [],
        )
        assert len(transport.requests) == 3


async def test_other_tools_report_the_deadline_as_an_error(tmp_path: Path) -> None:
    clock = FakeClock()
    async with shared_services(tmp_path, {}, clock=clock, call_deadline_s=3.0) as (shared, _):
        started_long_ago = CallClock(lambda: clock.now - 10.0)  # the call began 10 s ago
        app = build_server(shared.services, middleware=[started_long_ago])
        async with Client(app) as client:
            with signed_in("github:1"):
                result = await client.call_tool(
                    "trace_supersession", {"part_number": "11427953129"}
                )
        assert result.is_error is True
        assert result.content[0].text.endswith(
            "This call took too long; call again to continue (pages already fetched are cached)."
        )
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/tools/test_shared_deadline.py`
Expected: the three comparison tests FAIL (`is_error` is true: the error aborted the whole call); the `trace_supersession` test already passes.

- [ ] **Step 3: Implement.** In `server/src/realoem_mcp/tools/fitment.py`:

Edit 1. Find:

````python
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import DiagramListResult, PartRow
from realoem_mcp.models.fitment import (
````

Replace with:

````python
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import (
    Busy,
    CallDeadline,
    InvalidInput,
    LayoutChanged,
    NotFound,
    RealOemError,
)
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import DiagramListResult, PartRow
from realoem_mcp.models.fitment import (
````

Edit 2. Find:

````python

    Budget = network requests (cached pages are free). Both diagram lists come first, then the
    in-scope diagrams alternating A/B in list order; once the budget is spent the rest are read
    from the cache only, and cache misses are reported as unfetched.
    """
    ids = [str(_vehicle_id(services, raw)) for raw in (vehicle_a, vehicle_b)]
    diag_ids = _check_scope(main_group, subgroup, diag_ids, max_requests)
````

Replace with:

````python

    Budget = network requests (cached pages are free). Both diagram lists come first, then the
    in-scope diagrams alternating A/B in list order; once the budget is spent the rest are read
    from the cache only, and cache misses are reported as unfetched. On the hosted server a call
    that runs out of time (CallDeadline) or finds the queue full (Busy) while reading diagrams
    ends the same way, so the diagrams already compared are never lost; during the two diagram
    lists it is a tool error, since there is nothing to compare without both.
    """
    ids = [str(_vehicle_id(services, raw)) for raw in (vehicle_a, vehicle_b)]
    diag_ids = _check_scope(main_group, subgroup, diag_ids, max_requests)
````

Edit 3. Find:

````python
        )
    a, b = (_side(diagrams, subgroup, diag_ids) for diagrams in lists)
    used = sum(not page.from_cache for page in pages)
    for side, diag_id in _alternate(a, b):
        fetched = await fetch_diagram_parts(
            services,
            side.vehicle_id,
            diag_id,
            refresh=refresh,
            cache_only=used >= max_requests,
        )
        if fetched is None:
            side.unfetched.append(diag_id)
            continue
````

Replace with:

````python
        )
    a, b = (_side(diagrams, subgroup, diag_ids) for diagrams in lists)
    used = sum(not page.from_cache for page in pages)
    network_open = True
    for side, diag_id in _alternate(a, b):
        try:
            fetched = await fetch_diagram_parts(
                services,
                side.vehicle_id,
                diag_id,
                refresh=refresh,
                cache_only=not network_open or used >= max_requests,
            )
        except (Busy, CallDeadline):
            network_open = False  # like a spent budget: finish from the cache
            fetched = await fetch_diagram_parts(services, side.vehicle_id, diag_id, cache_only=True)
        if fetched is None:
            side.unfetched.append(diag_id)
            continue
````

- [ ] **Step 4: Run the new and the existing comparison tests**

Run: `uv run --directory server pytest -q tests/tools/test_shared_deadline.py tests/tools/test_compare_vehicles.py`
Expected: `22 passed` (4 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1049 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/tools/fitment.py server/tests/tools/test_shared_deadline.py
git commit -m "feat(fitment): compare_vehicles returns a resumable partial result at the call deadline" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 7: The shared vehicle index and the pull request

### Task 13: `update_vehicle_index` on a shared index

The vehicle index is shared on the hosted server, so its updates are too. `update_index_shared`
runs one update at a time: a caller who arrives during an update waits for it (within the call
deadline, read with the gate's clock) and gets its result with `requests_made` 0, since the
requests were made, and charged, for the caller that ran it. A completed `up_to_date` or `updated`
check starts a one-hour cooldown during which calls return the new status `cooldown` without any
request; `partial`, `drift` and deadline errors start no cooldown, so "call again to continue"
still works. The cooldown lives in memory, so a restart allows one more check. The model, the tool
docstring and the `vehicle-index` skill learn the new status. (The skill's other wording, such as
"stored on this computer", is updated with the rest of the documentation in plan 2.)

**Files:**
- Modify: `server/src/realoem_mcp/tools/vehicles.py`, `server/src/realoem_mcp/models/vehicles.py`,
  `skills/vehicle-index/SKILL.md`, `server/tests/unit/test_skill_vehicle_index.py`
- Test: `server/tests/tools/test_shared_vehicle_index.py`

- [ ] **Step 1: Write the failing test** `server/tests/tools/test_shared_vehicle_index.py`:

````python
"""update_vehicle_index on the hosted server: single-flight with an hourly cooldown (design 4.8)."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.current_user import call_started_at
from realoem_mcp.errors import CallDeadline
from realoem_mcp.server import build_server
from realoem_mcp.tools import vehicles
from realoem_mcp.tools.vehicles import UPDATE_STATE_KEY, _UpdateState, update_index_shared
from tests.auth_helpers import signed_in
from tests.harness import FakeClock
from tests.shared_env import shared_services
from tests.vehicle_data import SyntheticIndex, numbered
from tests.vehicle_env import install_baseline, settings_for

pytestmark = pytest.mark.anyio


def _index_settings(rows: list):
    def build(tmp_path: Path):
        settings = dataclasses.replace(settings_for(tmp_path), mode="http")
        install_baseline(settings, rows)
        return settings

    return build


async def test_an_up_to_date_index_is_not_checked_again_within_the_hour(tmp_path: Path) -> None:
    rows = numbered(120)
    transport = SyntheticIndex(rows)
    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 5)
            second = await update_index_shared(shared.services, 5)
        assert first.status == "up_to_date"
        assert second.status == "cooldown"
        assert second.requests_made == 0
        assert "refreshed at most once an hour" in second.message
        assert len(transport.requests) == 1


async def test_a_partial_update_can_be_continued_at_once(tmp_path: Path) -> None:
    remote = numbered(300)
    transport = SyntheticIndex(remote)
    settings = _index_settings(remote[:100])
    async with shared_services(tmp_path, transport, settings=settings) as (shared, _):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 3)
            second = await update_index_shared(shared.services, 3)
            third = await update_index_shared(shared.services, 3)
        assert (first.status, second.status, third.status) == ("partial", "updated", "cooldown")


class YieldingIndex(SyntheticIndex):
    """Yields to the event loop on every request, as a real network call would."""

    async def handle_async_request(self, request):
        await asyncio.sleep(0)
        return await super().handle_async_request(request)


async def test_concurrent_callers_share_one_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    transport = YieldingIndex(rows)
    runs: list[int] = []
    real_update = vehicles.update_index

    async def counted(services, max_pages: int):
        runs.append(max_pages)
        return await real_update(services, max_pages)

    monkeypatch.setattr(vehicles, "update_index", counted)

    async def update_as(subject: str):
        with signed_in(subject):
            return await update_index_shared(shared.services, 5)

    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        first, second = await asyncio.gather(update_as("github:1"), update_as("github:2"))
        assert runs == [5]  # one update ran; the second caller waited for it
        assert first.status == second.status == "up_to_date"
        assert (first.requests_made, second.requests_made) == (1, 0)
        assert len(transport.requests) == 1
        assert shared.quota.status("github:1").used_today == 1  # charged to who ran it
        assert shared.quota.status("github:2").used_today == 0


async def test_waiting_for_an_update_stops_at_the_call_deadline(tmp_path: Path) -> None:
    rows = numbered(120)
    clock = FakeClock()
    transport = SyntheticIndex(rows)
    settings = _index_settings(rows)
    async with shared_services(tmp_path, transport, settings=settings, clock=clock) as (shared, _):
        state = shared.services.extras[UPDATE_STATE_KEY] = _UpdateState()
        await state.lock.acquire()  # an update is running
        try:
            for seconds_left in (0.05, -1.0):  # a short wait that times out, then none at all
                deadline = call_started_at.set(clock.now - (50.0 - seconds_left))
                try:
                    async with asyncio.timeout(5):  # a broken deadline fails, never hangs
                        with signed_in("github:2"), pytest.raises(CallDeadline):
                            await update_index_shared(shared.services, 5)
                finally:
                    call_started_at.reset(deadline)
            assert state.checked_at is None  # a deadline error starts no cooldown
            assert transport.requests == []
            deadline = call_started_at.set(clock.now - 10.0)  # 40 s left: it waits its turn
            try:
                with signed_in("github:2"):
                    waiting = asyncio.create_task(update_index_shared(shared.services, 5))
                await asyncio.sleep(0.01)
                assert not waiting.done()
            finally:
                call_started_at.reset(deadline)
        finally:
            state.lock.release()
        assert (await waiting).status == "up_to_date"


async def test_a_deadline_error_starts_no_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    real_update = vehicles.update_index
    calls: list[int] = []

    async def out_of_time_once(services, max_pages: int):
        calls.append(max_pages)
        if len(calls) == 1:
            raise CallDeadline()
        return await real_update(services, max_pages)

    monkeypatch.setattr(vehicles, "update_index", out_of_time_once)
    async with shared_services(tmp_path, SyntheticIndex(rows), settings=_index_settings(rows)) as (
        shared,
        _,
    ):
        with signed_in("github:1"):
            with pytest.raises(CallDeadline):
                await update_index_shared(shared.services, 5)
            again = await update_index_shared(shared.services, 5)
        assert again.status == "up_to_date"  # checked for real, not "cooldown"


async def test_the_cooldown_ends_after_an_hour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = numbered(120)
    async with shared_services(tmp_path, SyntheticIndex(rows), settings=_index_settings(rows)) as (
        shared,
        _,
    ):
        with signed_in("github:1"):
            assert (await update_index_shared(shared.services, 5)).status == "up_to_date"
            assert (await update_index_shared(shared.services, 5)).status == "cooldown"
            later = datetime.now(UTC) + timedelta(minutes=61)
            monkeypatch.setattr(vehicles, "_now", lambda: later)
            assert (await update_index_shared(shared.services, 5)).status == "up_to_date"


async def test_drift_starts_no_cooldown(tmp_path: Path) -> None:
    local = numbered(120)
    transport = SyntheticIndex(local[:60])  # RealOEM now lists fewer vehicles than the index
    async with shared_services(tmp_path, transport, settings=_index_settings(local)) as (
        shared,
        _,
    ):
        with signed_in("github:1"):
            first = await update_index_shared(shared.services, 5)
            second = await update_index_shared(shared.services, 5)
        assert first.status == second.status == "drift"


async def test_the_tool_uses_the_shared_update_on_the_hosted_server(tmp_path: Path) -> None:
    rows = numbered(120)
    transport = SyntheticIndex(rows)
    async with shared_services(tmp_path, transport, settings=_index_settings(rows)) as (shared, _):
        async with Client(build_server(shared.services)) as client:
            with signed_in("github:1"):
                first = await client.call_tool("update_vehicle_index", {})
                again = await client.call_tool("update_vehicle_index", {})
        assert first.is_error is False, first.content
        assert again.structured_content["status"] == "cooldown"
````

- [ ] **Step 2: Pin the skill's new status.** In `server/tests/unit/test_skill_vehicle_index.py`:

Edit 1. Find:

````python
        "`updated`",
        "`partial`",
        "`drift`",
        "production START month",
        '"as of `built_at`"',
        "`select_vehicle`",
````

Replace with:

````python
        "`updated`",
        "`partial`",
        "`drift`",
        "`cooldown`",
        "production START month",
        '"as of `built_at`"',
        "`select_vehicle`",
````

- [ ] **Step 3: Run them**

Run: `uv run --directory server pytest -q tests/tools/test_shared_vehicle_index.py tests/unit/test_skill_vehicle_index.py`
Expected: FAIL with `ImportError: cannot import name 'UPDATE_STATE_KEY'`, and the skill test fails on the missing `` `cooldown` ``.

- [ ] **Step 4: Add the status to the model.** In `server/src/realoem_mcp/models/vehicles.py`:

Edit 1. Find:

````python


class VehicleIndexUpdateResult(ResultMeta):
    status: Literal["up_to_date", "updated", "partial", "drift"]
    added: list[IndexedVehicle]
    remote_total: int
    local_total: int
````

Replace with:

````python


class VehicleIndexUpdateResult(ResultMeta):
    # "cooldown": hosted server only; the shared index was checked under an hour ago.
    status: Literal["up_to_date", "updated", "partial", "drift", "cooldown"]
    added: list[IndexedVehicle]
    remote_total: int
    local_total: int
````

- [ ] **Step 5: Implement.** In `server/src/realoem_mcp/tools/vehicles.py`:

Edit 1. Find:

````python

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
````

Replace with:

````python

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import CallDeadline, InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.gate import GATE_KEY
from realoem_mcp.http_client import Page
from realoem_mcp.models.vehicles import (
    IndexedVehicle,
````

Edit 2. Find:

````python
from realoem_mcp.vehicle_index import VehicleIndex, sort_key

INDEX_KEY = "vehicle_index"  # services.extras key
MAX_PAGES_LIMIT = 10
MAX_LIMIT = 100
REBUILD_HINT = "The maintainer should rebuild the baseline with scripts/rebuild_vehicle_index.py."
````

Replace with:

````python
from realoem_mcp.vehicle_index import VehicleIndex, sort_key

INDEX_KEY = "vehicle_index"  # services.extras key
UPDATE_STATE_KEY = "vehicle_index_update"  # services.extras key (hosted server)
COOLDOWN = timedelta(hours=1)  # hosted server: at most one completed check per hour
MAX_PAGES_LIMIT = 10
MAX_LIMIT = 100
REBUILD_HINT = "The maintainer should rebuild the baseline with scripts/rebuild_vehicle_index.py."
````

Edit 3. Find:

````python
    )


async def update_index(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """ARD section 5.11 update algorithm: probe one page, then scan back from the last page
    (or from where an interrupted scan stopped)."""
    if not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise InvalidInput(f"max_pages must be between 1 and {MAX_PAGES_LIMIT}, got {max_pages}.")
    index = get_index(services)
    local_total = index.count()
    if index.meta().built_at is None or local_total == 0:
````

Replace with:

````python
    )


def _check_max_pages(max_pages: int) -> None:
    if not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise InvalidInput(f"max_pages must be between 1 and {MAX_PAGES_LIMIT}, got {max_pages}.")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _UpdateState:
    """Hosted server: the vehicle index is shared, so its updates are too."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    generation: int = 0  # number of updates that have finished
    last_result: VehicleIndexUpdateResult | None = None
    checked_at: datetime | None = None  # end of the last up_to_date/updated check


async def _acquire_within_deadline(services: Services, lock: asyncio.Lock) -> None:
    """Wait for the lock, but not past the tool call's deadline (read with the gate's clock)."""
    gate = services.extras.get(GATE_KEY)
    left = gate.time_left() if gate is not None else None
    if left is None:
        await lock.acquire()
        return
    if left <= 0:
        raise CallDeadline()
    try:
        async with asyncio.timeout(left):
            await lock.acquire()
    except TimeoutError:
        raise CallDeadline() from None


async def update_index_shared(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """update_index for the hosted server: one update at a time, and at most one completed
    check per hour for everyone.

    A caller that arrives while an update runs waits for it (within the call deadline) and gets
    its result, with requests_made 0: the requests were made, and charged, for the caller that
    ran the update. Only an up_to_date or updated result starts the cooldown, so a partial
    update can be continued. The cooldown lives in memory: a restart allows one more check.
    """
    _check_max_pages(max_pages)
    state = services.extras.setdefault(UPDATE_STATE_KEY, _UpdateState())
    seen = state.generation
    await _acquire_within_deadline(services, state.lock)
    try:
        if state.generation != seen and state.last_result is not None:  # the update waited for
            return state.last_result.model_copy(update={"requests_made": 0, "from_cache": True})
        if state.checked_at is not None and _now() - state.checked_at < COOLDOWN:
            index = get_index(services)
            return _result(
                [],
                status="cooldown",
                added=[],
                remote_total=index.last_remote_total() or 0,
                local_total=index.count(),
                message=f"The index was checked at {state.checked_at:%H:%M} UTC; it is refreshed "
                "at most once an hour.",
            )
        result = await update_index(services, max_pages)
        state.generation += 1
        state.last_result = result
        if result.status in ("up_to_date", "updated"):
            state.checked_at = _now()
        return result
    finally:
        state.lock.release()


async def update_index(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """ARD section 5.11 update algorithm: probe one page, then scan back from the last page
    (or from where an interrupted scan stopped)."""
    _check_max_pages(max_pages)
    index = get_index(services)
    local_total = index.count()
    if index.meta().built_at is None or local_total == 0:
````

Edit 4. Find:

````python
        to continue where it stopped; drift = the maintainer should rebuild the baseline, also
        returned without any request when no baseline is installed), added (the new vehicles),
        remote_total, local_total, pages_fetched and message. Never downloads the whole index.
        """
        try:
            return await update_index(services, max_pages)
        except RealOemError as err:
            raise ToolError(err.message) from err
````

Replace with:

````python
        to continue where it stopped; drift = the maintainer should rebuild the baseline, also
        returned without any request when no baseline is installed), added (the new vehicles),
        remote_total, local_total, pages_fetched and message. Never downloads the whole index.
        On the hosted server the index is shared: status cooldown means it was checked less
        than an hour ago and nothing was fetched; search again with find_vehicle.
        """
        try:
            if services.settings.mode == "http":
                return await update_index_shared(services, max_pages)
            return await update_index(services, max_pages)
        except RealOemError as err:
            raise ToolError(err.message) from err
````

- [ ] **Step 6: Teach the skill.** In `skills/vehicle-index/SKILL.md`:

Edit 1. Find:

````markdown
     previous call stopped.
   - `drift`: RealOEM changed older entries. Report the `message`: the maintainer should rebuild
     the index. The vehicles found so far were still added.
   Call `update_vehicle_index` at most once per conversation unless it returned `partial` or the
   user asks again.
   If `index.built_at` is null, no vehicle index baseline is installed: `update_vehicle_index`
````

Replace with:

````markdown
     previous call stopped.
   - `drift`: RealOEM changed older entries. Report the `message`: the maintainer should rebuild
     the index. The vehicles found so far were still added.
   - `cooldown`: the shared index was already checked less than an hour ago, so nothing was
     fetched. Treat it like `up_to_date`.
   Call `update_vehicle_index` at most once per conversation unless it returned `partial` or the
   user asks again.
   If `index.built_at` is null, no vehicle index baseline is installed: `update_vehicle_index`
````

- [ ] **Step 7: Run them**

Run: `uv run --directory server pytest -q tests/tools/test_shared_vehicle_index.py tests/unit/test_skill_vehicle_index.py tests/tools/test_update_vehicle_index.py`
Expected: `24 passed` (8 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1057 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/tools/vehicles.py server/src/realoem_mcp/models/vehicles.py skills/vehicle-index/SKILL.md server/tests/unit/test_skill_vehicle_index.py server/tests/tools/test_shared_vehicle_index.py
git commit -m "feat(vehicles): single-flight shared index updates with an hourly cooldown" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 14: Final verification and pull request

- [ ] **Step 1: Everything green**

Run: `uv run --directory server pytest -q`
Expected: `1057 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 2: Scope check.** Only the files listed in this plan changed:

````bash
git diff --stat origin/main...HEAD
````

Expected: 34 files: 18 under `server/src/realoem_mcp/` and `skills/` (13 modified modules, 4 new
modules, `SKILL.md`) and 16 under `server/tests/` (15 new, 1 modified). Nothing under `brands/`, `docs/`,
`.claude-plugin/`, `server/pyproject.toml` or `server/uv.lock`; versions unchanged.

- [ ] **Step 3: The stdio server is unchanged for users.** Run the existing stdio smoke test:

Run: `uv run --directory server pytest -q tests/tools/test_stdio.py`
Expected: all pass.

- [ ] **Step 4: Push and open the pull request** (only when the controller asks you to; otherwise
  stop here and report):

````bash
git push -u origin feat/hosted-shared-core
gh pr create --base main --head feat/hosted-shared-core \
  --title "feat: hosted shared-mode core (quotas, gate, per-user VIN pages, shared cache)" \
  --body-file - <<'EOF'
## Summary

Plan 1a of the hosted server (spec: docs/superpowers/specs/2026-10-01-hosted-server-design.md).
Adds a shared ("http") mode to the MCP server, testable offline; no HTTP server, sign-in or
deployment yet (plans 1b and 2). The stdio plugin is unchanged.

- Settings.mode plus hosted limits; current_user/require_user read the SDK's auth context;
  CallClock stamps tool-call start times.
- PageCache: per-owner entries (VIN pages per user), constant-time size accounting, LRU cap with
  incremental vacuum, free-space floor, disk-full handling, reset().
- RealOemClient hooks: admit (queue admission before the lock, timed acquire), charge (quota
  inside the lock on a miss), owner; hosted refresh throttle; VIN-free logs.
- Quota (per user per UTC day, new-account limit, optional server-wide cap) and FetchGate.
- Tools: cache shortening per owner, admin tools in hosted mode, compare_vehicles partial at the
  call deadline, single-flight vehicle-index updates with a cooldown status.

## Test plan

- [x] uv run pytest: 1057 passed, 6 deselected (115 new tests)
- [x] ruff check and ruff format --check
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
````
