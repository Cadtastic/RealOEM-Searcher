# Hosted Server, Plan 1b: Sign-In and the HTTP App Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the shared-mode server of plan 1a behind GitHub sign-in and serve it over streamable HTTP: an OAuth 2.1 authorization server (dynamic client registration, consent before GitHub, PKCE, rotating refresh tokens, bans), the consent and error pages, rate limits, security headers, VIN-free logs, a full-disk guard for the server's own databases, and the `realoem-mcp-http` entry point. Everything is testable offline: tests drive the real ASGI app with a fake GitHub and canned RealOEM pages.

**Architecture:** `http_app.build_http_app(settings)` assembles the hosted server around the existing `build_server()`: the MCP SDK's own OAuth routes and bearer middleware (`RealOemAuthProvider` supplies the logic), our consent and GitHub routes (`auth/pages.py`), and three ASGI middlewares. Sign-in state lives in `auth.sqlite3` (`auth/store.py`), where tokens and codes are kept only as keyed hashes (`auth/keys.py`); the same database holds plan 1a's usage table. `StorageGuard` decides what a database error means: a full disk frees the page cache and retries once; a second full disk, or a damaged auth database, ends the process so Fly restarts it.

**Tech Stack:** Python ≥ 3.11, mcp 2.2 (`OAuthAuthorizationServerProvider`, `AuthSettings`, `streamable_http_app`), Starlette and uvicorn (now direct dependencies), httpx, stdlib `sqlite3`, pytest + AnyIO, ruff. Spec: `docs/superpowers/specs/2026-10-01-hosted-server-design.md` (sections 4.1 to 4.10, 5, 6, 7). Plan 1a (`docs/superpowers/plans/2026-10-01-hosted-shared-core.md`) must be merged first. Plan 2 deploys to Fly.io and releases 0.2.0.

---

## Before you start

- Plan 1a is merged, and so is this plan, so the worktree has both. Track progress in your task
  list, not by committing ticked checkboxes: Task 17 checks that nothing under `docs/` changed.
- Work in a git worktree on branch `feat/hosted-sign-in`, created from an up-to-date `origin/main`
  (Task 0). Every command below runs from the **worktree root**. Python commands use
  `uv run --directory server …`; paths after it are relative to `server/`. Shell: Git Bash on
  Windows, or any POSIX shell.
- Read the spec sections 4.1 to 4.10 once, and `server/src/realoem_mcp/shared.py`, `quota.py` and
  `cache.py` from plan 1a. The MCP SDK's server-side OAuth code is in
  `server/.venv/Lib/site-packages/mcp/server/auth/` (Windows; `lib/python3.*/site-packages` on
  Linux); the provider protocol is in `provider.py`, the routes in `routes.py`.
- **No code or test may contact realoem.com or GitHub's OAuth and API endpoints**, and never set
  `REALOEM_LIVE=1`: `FixtureTransport` serves canned RealOEM pages, `tests/fake_github.py` stands
  in for GitHub's sign-in, `httpx.MockTransport` for its API in the client test. The `git` and
  `gh` commands in Tasks 0 and 17 talk to GitHub as usual.
- TDD: write the test, run it and see it fail for the stated reason, then implement, then see it
  pass. The code blocks in this plan were run, task by task, on a clean worktree: with all tasks
  applied the suite is `1252 passed, 6 deselected` and ruff is clean. Copy code exactly. Task 15
  is the exception to test-first: its end-to-end tests pass when written, because they check
  Tasks 5 to 14 working together.
- Commit messages are Conventional Commits, each ending with a blank line and a
  `Co-Authored-By:` trailer naming the model that wrote the code. The commit commands below show
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`:
  **replace the model name with your own**; that is the one thing in this plan not to copy
  literally.
- Do not change versions (they stay `0.1.0` until plan 2) and do not commit anything under `docs/`.
- What this plan leaves to plan 2: the Dockerfile, `fly.toml`, the deploy workflow, the GitHub
  OAuth Apps and Fly secrets, switching `plugin.json` to the hosted URL, the documentation (README
  privacy note and the items listed in plan 1a), the uptime alert, and three checks against the
  live Fly proxy: a forged `Fly-Client-IP` is overwritten, a 50-second call survives the idle
  timeout, and Claude does not refresh a token twice in parallel.

## File structure

New modules (each with one job):

| File | Responsibility |
|---|---|
| `server/src/realoem_mcp/auth/keys.py` | Keys derived from the server secret; keyed hashes; PKCE helpers |
| `server/src/realoem_mcp/auth/records.py` | Row types of the sign-in database |
| `server/src/realoem_mcp/auth/store.py` | `AuthStore`: `auth.sqlite3`, forward-only migrations, every query |
| `server/src/realoem_mcp/auth/redirects.py` | The redirect allow-list (a security invariant) and `ClaudeClient` |
| `server/src/realoem_mcp/auth/github.py` | `GitHubLogin` protocol and the real GitHub OAuth App client |
| `server/src/realoem_mcp/auth/outcomes.py` | What a sign-in step tells the pages to do next |
| `server/src/realoem_mcp/auth/provider.py` | `RealOemAuthProvider`: registration, consent, GitHub's return (Task 8); codes and tokens (Task 9) |
| `server/src/realoem_mcp/auth/html.py` | The consent and error pages |
| `server/src/realoem_mcp/auth/pages.py` | `/consent` and `/oauth/github/callback`: cookies and the CSRF MAC |
| `server/src/realoem_mcp/storage_guard.py` | What a full disk or a damaged database means |
| `server/src/realoem_mcp/rate_limit.py` | `SlidingWindow` |
| `server/src/realoem_mcp/log_privacy.py` | `VinFilter`: no VIN in any log line |
| `server/src/realoem_mcp/http_middleware.py` | Security headers, the request log, the sign-in limits |
| `server/src/realoem_mcp/http_app.py` | `build_http_app()` and `main()` (`realoem-mcp-http`) |
| `server/scripts/admin.py` | Maintainer commands: usage, ban, unban, revoke, prune |

Changed: `config.py` (sign-in settings), `quota.py`, `services.py`, `shared.py`, `vehicle_index.py`
and `tools/vehicles.py` (the storage guard), `pyproject.toml` and `uv.lock`. Test helpers:
`tests/hosted_config.py`, `tests/fake_github.py`, `tests/auth_env.py`, `tests/http_env.py`.

## Chunk 1: Settings, keys and the storage guard

### Task 0: Branch and baseline

- [ ] **Step 1: Create the worktree from an up-to-date main.** The first line keeps `.worktrees/`
  out of `git status` in a fresh clone (a local setting, never committed).

````bash
git check-ignore -q .worktrees/ || echo ".worktrees/" >> .git/info/exclude
git fetch origin
git worktree add .worktrees/hosted-sign-in -b feat/hosted-sign-in --no-track origin/main
cd .worktrees/hosted-sign-in
````

- [ ] **Step 2: Record the baseline**

Run: `uv run --directory server pytest -q`
Expected: `1057 passed, 6 deselected` (plan 1a merged). If not, stop and report.

### Task 1: Sign-in settings

`Settings` gains what only the hosted server needs (hosted design 4.8): its public URL (the OAuth
issuer, and the base of the GitHub callback), the GitHub OAuth App's id and secret, the server
secret, the redirect allow-list, Anthropic's address range, and where `auth.sqlite3` lives. They
are read from the environment like every other setting but checked only by `validate_http()`,
which the HTTP app calls, so the stdio server never needs them: the public URL must be a bare
origin (it is stored in canonical, lower-case form) and every allow-list entry an `https://` URL
with a host and no user info or fragment, because the allow-list is a security invariant (Task
6). Secrets are kept out of `repr`.
`tests/hosted_config.py` holds the settings and constants every later test uses.

**Files:**
- Modify: `server/src/realoem_mcp/config.py`
- Create: `server/tests/hosted_config.py`
- Test: `server/tests/unit/test_config_http.py`

- [ ] **Step 1: Write the test settings** `server/tests/hosted_config.py`:

````python
"""Settings and constants for hosted-server tests (no app import, so any task can use them)."""

from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from realoem_mcp.config import Settings
from tests.harness import BRANDS_DIR

BASE = "http://localhost:8080"
MCP_URL = f"{BASE}/mcp"
SECRET_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def hosted_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Complete hosted-server settings on temporary folders (a loopback public URL)."""
    values: dict[str, object] = {
        "mode": "http",
        "cache_dir": tmp_path / "cache",
        "data_dir": tmp_path / "data",
        "brands_dir": BRANDS_DIR,
        "public_url": BASE,
        "github_client_id": "github-client",
        "github_client_secret": "github-secret",
        "secret_key": SECRET_KEY,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def query_of(url: str) -> dict[str, str]:
    """The query parameters of a URL, one value each."""
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
````

- [ ] **Step 2: Write the failing test** `server/tests/unit/test_config_http.py`:

````python
"""The hosted server's sign-in settings (hosted design 4.8)."""

from pathlib import Path

import pytest

from realoem_mcp.config import CLAUDE_CALLBACK, HOSTED_CLIENT_RANGE, Settings
from tests.hosted_config import SECRET_KEY, hosted_settings


def test_defaults() -> None:
    settings = Settings(data_dir=Path("/srv/data"))
    assert settings.public_url is None
    assert settings.redirect_allowlist == (CLAUDE_CALLBACK,)
    assert settings.hosted_client_range == HOSTED_CLIENT_RANGE == "160.79.104.0/21"
    assert settings.auth_path == Path("/srv/data") / "auth.sqlite3"
    assert Settings(data_dir=Path("/d"), auth_dir=Path("/a")).auth_path == Path("/a/auth.sqlite3")


def test_from_env_reads_the_sign_in_settings() -> None:
    settings = Settings.from_env(
        {
            "REALOEM_PUBLIC_URL": "https://realoem-searcher.fly.dev/",
            "REALOEM_GITHUB_CLIENT_ID": "Iv1.abc",
            "REALOEM_GITHUB_CLIENT_SECRET": "shh",
            "REALOEM_SECRET_KEY": SECRET_KEY,
            "REALOEM_REDIRECT_ALLOWLIST": f"{CLAUDE_CALLBACK}, https://claude.com/cb",
            "REALOEM_HOSTED_CLIENT_RANGE": "10.0.0.0/8",
            "REALOEM_AUTH_DIR": "/auth",
        }
    )
    assert settings.public_url == "https://realoem-searcher.fly.dev"  # no trailing slash
    assert (settings.github_client_id, settings.github_client_secret) == ("Iv1.abc", "shh")
    assert settings.secret_key_bytes == b"0123456789abcdef0123456789abcdef"
    assert settings.redirect_allowlist == (CLAUDE_CALLBACK, "https://claude.com/cb")
    assert settings.hosted_client_range == "10.0.0.0/8"
    assert settings.auth_path == Path("/auth/auth.sqlite3")
    assert settings.mode == "stdio"  # only the entry point sets the mode


@pytest.mark.parametrize(
    "given",
    [
        " HTTPS://Realoem-Searcher.FLY.dev/ ",
        "https://realoem-searcher.fly.dev:443",
        "https://realoem-searcher.fly.dev:",
    ],
)
def test_the_public_url_is_kept_in_canonical_form(tmp_path: Path, given: str) -> None:
    settings = hosted_settings(tmp_path, public_url=given)
    assert settings.public_url == "https://realoem-searcher.fly.dev"
    settings.validate_http()
    assert hosted_settings(tmp_path, public_url="http://LOCALHOST:8080").public_url == (
        "http://localhost:8080"
    )


def test_the_allow_list_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="redirect_allowlist must be a list"):
        Settings(redirect_allowlist="https://claude.ai/api/mcp/auth_callback")  # type: ignore[arg-type]


def test_secrets_never_appear_in_repr(tmp_path: Path) -> None:
    text = repr(hosted_settings(tmp_path))
    for secret in ("github-client", "github-secret", SECRET_KEY):
        assert secret not in text


def test_complete_hosted_settings_pass(tmp_path: Path) -> None:
    hosted_settings(tmp_path).validate_http()
    hosted_settings(tmp_path, public_url="https://realoem-searcher.fly.dev").validate_http()


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"public_url": None}, "REALOEM_PUBLIC_URL is required"),
        ({"public_url": "http://realoem-searcher.fly.dev"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com/mcp"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com?x=1"}, "REALOEM_PUBLIC_URL must be"),
        ({"github_client_id": None}, "REALOEM_GITHUB_CLIENT_ID is required"),
        ({"github_client_secret": ""}, "REALOEM_GITHUB_CLIENT_SECRET is required"),
        ({"secret_key": None}, "REALOEM_SECRET_KEY is required"),
        ({"secret_key": "not base64!"}, "REALOEM_SECRET_KEY must be base64"),
        ({"secret_key": "c2hvcnQ="}, "at least 32 random bytes"),
        ({"redirect_allowlist": ()}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("http://evil.example/cb",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("claude.ai/api/mcp/auth_callback",)}, "REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://claude.ai/cb#frag",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://user@claude.ai/cb",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://claude.ai/" + "a" * 512,)}, "REDIRECT_ALLOWLIST"),
        ({"public_url": "https://exa mple.com"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com#"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com?"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com:abc"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com:99999"}, "REALOEM_PUBLIC_URL must be"),
        ({"hosted_client_range": "not a network"}, "REALOEM_HOSTED_CLIENT_RANGE"),
    ],
)
def test_a_missing_or_malformed_value_stops_the_server(
    tmp_path: Path, overrides: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match="The hosted server cannot start") as refused:
        hosted_settings(tmp_path, **overrides).validate_http()
    assert problem in str(refused.value)


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as refused:
        Settings(mode="http").validate_http()
    for name in ("PUBLIC_URL", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "SECRET_KEY"):
        assert f"REALOEM_{name}" in str(refused.value)
````

- [ ] **Step 3: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_config_http.py`
Expected: FAIL with `ImportError: cannot import name 'CLAUDE_CALLBACK'`.

- [ ] **Step 4: Implement.** In `server/src/realoem_mcp/config.py`:

Edit 1. Find:

````python

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import platformdirs

````

Replace with:

````python

from __future__ import annotations

import base64
import binascii
import ipaddress
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit

import platformdirs

````

Edit 2. Find:

````python
MIN_INTERVAL_FLOOR_S = 1.0
HTTP_CACHE_MAX_MB = 400  # at most 40 % of the hosted server's 1 GB volume
CACHE_MIN_FREE_MB = 100  # hosted server: below this much free disk, stop caching
# src/realoem_mcp/config.py -> parents[3] is the repository root that holds brands/.
DEFAULT_BRANDS_DIR = Path(__file__).resolve().parents[3] / "brands"

````

Replace with:

````python
MIN_INTERVAL_FLOOR_S = 1.0
HTTP_CACHE_MAX_MB = 400  # at most 40 % of the hosted server's 1 GB volume
CACHE_MIN_FREE_MB = 100  # hosted server: below this much free disk, stop caching
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
HOSTED_CLIENT_RANGE = "160.79.104.0/21"  # Anthropic's egress range (hosted Claude, Cowork)
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")
MIN_SECRET_KEY_BYTES = 32
MAX_REDIRECT_URL = 512
_HOSTNAME = re.compile(r"[a-z0-9.-]+")
_DEFAULT_PORTS = {"https": 443, "http": 80}
# src/realoem_mcp/config.py -> parents[3] is the repository root that holds brands/.
DEFAULT_BRANDS_DIR = Path(__file__).resolve().parents[3] / "brands"

````

Edit 3. Find:

````python
    global_daily_limit: int = 0  # server-wide cap on the same count; 0 = off
    call_deadline_s: float = 50.0  # a tool call older than this starts no new RealOEM request
    cache_max_mb: int | None = None  # None = HTTP_CACHE_MAX_MB in http mode, no cap in stdio
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

````

Replace with:

````python
    global_daily_limit: int = 0  # server-wide cap on the same count; 0 = off
    call_deadline_s: float = 50.0  # a tool call older than this starts no new RealOEM request
    cache_max_mb: int | None = None  # None = HTTP_CACHE_MAX_MB in http mode, no cap in stdio
    # Hosted server only; required values are checked by validate_http(), not here.
    public_url: str | None = None  # e.g. https://realoem-searcher.fly.dev: the OAuth issuer
    github_client_id: str | None = field(default=None, repr=False)
    github_client_secret: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)  # base64 of >= 32 random bytes
    redirect_allowlist: tuple[str, ...] = (CLAUDE_CALLBACK,)
    hosted_client_range: str = HOSTED_CLIENT_RANGE
    auth_dir: Path | None = None  # None = data_dir
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

````

Edit 4. Find:

````python
        ):
            raise ValueError(f"admins must be a set of 'github:<id>' subjects, got {self.admins!r}")
        object.__setattr__(self, "admins", frozenset(self.admins))

    @property
    def cache_max_bytes(self) -> int:
````

Replace with:

````python
        ):
            raise ValueError(f"admins must be a set of 'github:<id>' subjects, got {self.admins!r}")
        object.__setattr__(self, "admins", frozenset(self.admins))
        if isinstance(self.redirect_allowlist, str):
            raise ValueError(
                f"redirect_allowlist must be a list of URLs, got {self.redirect_allowlist!r}"
            )
        object.__setattr__(self, "redirect_allowlist", tuple(self.redirect_allowlist))
        if self.public_url is not None:
            object.__setattr__(self, "public_url", _origin(self.public_url))
        if self.auth_dir is not None:
            object.__setattr__(self, "auth_dir", Path(self.auth_dir).expanduser())

    @property
    def cache_max_bytes(self) -> int:
````

Edit 5. Find:

````python
        """Free disk space below which new pages are not cached; 0 = no floor (stdio)."""
        return CACHE_MIN_FREE_MB * 1024 * 1024 if self.mode == "http" else 0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
````

Replace with:

````python
        """Free disk space below which new pages are not cached; 0 = no floor (stdio)."""
        return CACHE_MIN_FREE_MB * 1024 * 1024 if self.mode == "http" else 0

    @property
    def auth_path(self) -> Path:
        """The hosted server's sign-in database (clients, tokens, users, usage)."""
        return (self.auth_dir or self.data_dir) / "auth.sqlite3"

    @property
    def is_local(self) -> bool:
        """True when the public URL is a loopback address (a development run)."""
        return urlsplit(self.public_url or "").hostname in LOOPBACK_HOSTS

    @property
    def secret_key_bytes(self) -> bytes:
        """The decoded server secret; validate_http() has checked it."""
        return base64.b64decode(self.secret_key or "", validate=True)

    def validate_http(self) -> None:
        """Refuse to run the hosted server without its required values (hosted design 4.8)."""
        problems: list[str] = []
        url = urlsplit(self.public_url or "")
        if not self.public_url:
            problems.append("REALOEM_PUBLIC_URL is required")
        elif (
            not (url.scheme == "https" or (url.scheme == "http" and self.is_local))
            or not _HOSTNAME.fullmatch(url.hostname or "")
            or url.username is not None
            or url.path not in ("", "/")
            or "?" in self.public_url
            or "#" in self.public_url
            or not _has_valid_port(url)
        ):
            problems.append(
                "REALOEM_PUBLIC_URL must be an https:// origin such as "
                "https://realoem-searcher.fly.dev (http:// only for localhost)"
            )
        if not self.github_client_id:
            problems.append("REALOEM_GITHUB_CLIENT_ID is required")
        if not self.github_client_secret:
            problems.append("REALOEM_GITHUB_CLIENT_SECRET is required")
        if not self.secret_key:
            problems.append("REALOEM_SECRET_KEY is required")
        else:
            try:
                key = self.secret_key_bytes
            except (binascii.Error, ValueError):
                key = b""
            if len(key) < MIN_SECRET_KEY_BYTES:
                problems.append(
                    f"REALOEM_SECRET_KEY must be base64 of at least {MIN_SECRET_KEY_BYTES} random "
                    "bytes (openssl rand -base64 32)"
                )
        if not self.redirect_allowlist:
            problems.append("REALOEM_REDIRECT_ALLOWLIST must name at least one URL")
        for entry in self.redirect_allowlist:
            if not _is_https_callback(entry):
                problems.append(
                    f"REALOEM_REDIRECT_ALLOWLIST entries must be https:// URLs with a host, no "
                    f"user info or fragment, at most {MAX_REDIRECT_URL} characters: {entry!r}"
                )
        try:
            ipaddress.ip_network(self.hosted_client_range)
        except ValueError:
            problems.append(
                f"REALOEM_HOSTED_CLIENT_RANGE is not a network: {self.hosted_client_range!r}"
            )
        if problems:
            raise ValueError("The hosted server cannot start: " + "; ".join(problems) + ".")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
````

Edit 6. Find:

````python
            if deadline <= 0:
                raise ValueError(f"REALOEM_CALL_DEADLINE_S must be greater than 0, got {value!r}")
            kwargs["call_deadline_s"] = deadline
        return cls(**kwargs)  # type: ignore[arg-type]


````

Replace with:

````python
            if deadline <= 0:
                raise ValueError(f"REALOEM_CALL_DEADLINE_S must be greater than 0, got {value!r}")
            kwargs["call_deadline_s"] = deadline
        for env_name, field_name in _TEXT_ENV.items():
            if value := env.get(env_name, "").strip():
                kwargs[field_name] = value
        if value := env.get("REALOEM_REDIRECT_ALLOWLIST"):
            kwargs["redirect_allowlist"] = tuple(
                part.strip() for part in value.split(",") if part.strip()
            )
        if value := env.get("REALOEM_AUTH_DIR"):
            kwargs["auth_dir"] = Path(value).expanduser()
        return cls(**kwargs)  # type: ignore[arg-type]


````

Edit 7. Find:

````python
    "REALOEM_CACHE_MAX_MB": "cache_max_mb",
}
_COUNT_FIELDS = tuple(_COUNT_ENV.values())


def _to_count(name: str, value: str) -> int:
````

Replace with:

````python
    "REALOEM_CACHE_MAX_MB": "cache_max_mb",
}
_COUNT_FIELDS = tuple(_COUNT_ENV.values())
_TEXT_ENV = {
    "REALOEM_PUBLIC_URL": "public_url",
    "REALOEM_GITHUB_CLIENT_ID": "github_client_id",
    "REALOEM_GITHUB_CLIENT_SECRET": "github_client_secret",
    "REALOEM_SECRET_KEY": "secret_key",
    "REALOEM_HOSTED_CLIENT_RANGE": "hosted_client_range",
}


def _origin(raw: str) -> str:
    """A well-formed origin in canonical form: lower-case scheme and host, no default or empty
    port, no trailing slash (the form the SDK itself uses for the issuer). Anything else is kept
    as given, for validate_http() to report."""
    text = raw.strip().rstrip("/")
    parts = urlsplit(text)
    if (
        not (parts.scheme and parts.netloc)
        or parts.path
        or "?" in text
        or "#" in text
        or "@" in parts.netloc
        or not _HOSTNAME.fullmatch(parts.hostname or "")
        or not _has_valid_port(parts)
    ):
        return text
    scheme = parts.scheme.lower()
    port = parts.port
    suffix = f":{port}" if port is not None and port != _DEFAULT_PORTS.get(scheme) else ""
    return f"{scheme}://{parts.hostname}{suffix}"


def _has_valid_port(url: SplitResult) -> bool:
    try:
        url.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    return True


def _is_https_callback(entry: str) -> bool:
    url = urlsplit(entry)
    return (
        url.scheme == "https"
        and bool(url.hostname)
        and url.username is None
        and "#" not in entry
        and len(entry) <= MAX_REDIRECT_URL
        and _has_valid_port(url)
    )


def _to_count(name: str, value: str) -> int:
````

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_config_http.py tests/unit/test_config.py tests/unit/test_config_hosted.py`
Expected: `74 passed` (30 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1087 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/config.py server/tests/hosted_config.py server/tests/unit/test_config_http.py
git commit -m "feat(hosted): sign-in settings (public URL, GitHub app, secret key, allow-list)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 2: Keys

Every credential the server issues is a 256-bit random value stored only as a keyed hash, each
kind under its own key derived from the server secret (hosted design 4.4, H6): a copied database
yields nothing usable, and a value of one kind can never match a row of another. The module also
holds the base64url and PKCE helpers the provider uses.

**Files:**
- Create: `server/src/realoem_mcp/auth/__init__.py`, `server/src/realoem_mcp/auth/keys.py`
- Test: `server/tests/unit/test_auth_keys.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_keys.py`:

````python
"""Keys derived from the server secret (hosted design 4.4)."""

import hashlib
import hmac

import pytest

from realoem_mcp.auth.keys import LABELS, Keys, b64url, new_secret, pkce_challenge

SECRET = b"0123456789abcdef0123456789abcdef"


def test_each_purpose_has_its_own_key() -> None:
    keys = Keys(SECRET)
    assert len({keys.key(label) for label in LABELS}) == len(LABELS)
    assert len({keys.hash(label, "same value") for label in LABELS}) == len(LABELS)


def test_the_derivation_is_the_designed_one() -> None:
    # Spec 4.4. Changing this voids every stored token, code and cache owner on upgrade.
    key = hmac.new(SECRET, b"realoem/v1/access", hashlib.sha256).digest()
    assert Keys(SECRET).key("access") == key
    assert Keys(SECRET).hash("access", "t") == hmac.new(key, b"t", hashlib.sha256).hexdigest()


def test_hashes_depend_on_the_secret() -> None:
    assert Keys(SECRET).hash("access", "t") != Keys(SECRET[::-1]).hash("access", "t")
    assert Keys(SECRET).hash("access", "t") == Keys(SECRET).hash("access", "t")


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Keys(b"too short")


def test_new_secrets_are_256_bit_and_url_safe() -> None:
    values = {new_secret() for _ in range(100)}
    assert len(values) == 100
    assert all(len(value) == 43 and "=" not in value for value in values)


def test_pkce_challenge_matches_rfc_7636() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert b64url(b"\xff\xff") == "__8"
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_keys.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth'`.

- [ ] **Step 3: Create the package** `server/src/realoem_mcp/auth/__init__.py`:

````python
"""Sign-in for the hosted server: an OAuth 2.1 authorization server that delegates login to GitHub.

Nothing here is used by the stdio server.
"""
````

- [ ] **Step 4: Implement** `server/src/realoem_mcp/auth/keys.py`:

````python
"""Keys derived from the server secret, one per purpose (hosted design 4.4).

Tokens and codes are stored only as keyed hashes, each kind under its own key: a copied database
yields no usable credential, and a value of one kind can never match a row of another kind.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from realoem_mcp.config import MIN_SECRET_KEY_BYTES

LABELS = ("access", "refresh", "code", "github", "github-pkce", "consent", "cache-owner")


def new_secret() -> str:
    """A fresh 256-bit random value, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def b64url(raw: bytes) -> str:
    """base64url without padding (RFC 7636 appendix A)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge of a PKCE verifier."""
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


class Keys:
    """k_label = HMAC-SHA256(secret, "realoem/v1/" + label) for each label in LABELS."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < MIN_SECRET_KEY_BYTES:
            raise ValueError(f"the server secret must be at least {MIN_SECRET_KEY_BYTES} bytes")
        self._keys = {
            label: hmac.new(secret, f"realoem/v1/{label}".encode(), hashlib.sha256).digest()
            for label in LABELS
        }

    def key(self, label: str) -> bytes:
        return self._keys[label]

    def digest(self, label: str, value: str) -> bytes:
        return hmac.new(self._keys[label], value.encode("utf-8"), hashlib.sha256).digest()

    def hash(self, label: str, value: str) -> str:
        """H_label(value) as stored in the database: hex HMAC-SHA256 under k_label."""
        return self.digest(label, value).hex()
````

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_keys.py`
Expected: `6 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1093 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/__init__.py server/src/realoem_mcp/auth/keys.py server/tests/unit/test_auth_keys.py
git commit -m "feat(auth): keys derived from the server secret, keyed hashes and PKCE helpers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 3: The storage guard

A full disk is the failure a one-volume server meets first (hosted design 4.10). The page cache is
disposable, so when the auth database or the vehicle index finds the disk full, the guard deletes
the cache files (the one action that frees space without needing any) and retries the operation
once. A second full disk, or a damaged auth database (`CORRUPT`, `IOERR`, `NOTADB`), ends the
process with `os._exit(1)` after flushing the logs, so Fly restarts it; a `SystemExit` raised
inside a request handler could be swallowed. Any other error, such as a database kept busy by the
admin script, is raised as usual: killing the server for it would be worse. Every operation
given to the guard must be one whole transaction, so running it twice is safe. `run_directly` is
the do-nothing version for stdio, tests and the admin script.

**Files:**
- Create: `server/src/realoem_mcp/storage_guard.py`
- Test: `server/tests/unit/test_storage_guard.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_storage_guard.py`:

````python
"""What the hosted server does when its own databases fail (hosted design 4.10)."""

import sqlite3

import pytest

from realoem_mcp.errors import RealOemError
from realoem_mcp.storage_guard import AUTH, VEHICLES, StorageGuard, run_directly


def _error(
    code: int, message: str = "simulated", kind: type[sqlite3.Error] = sqlite3.OperationalError
) -> sqlite3.Error:
    error = kind(message)
    error.sqlite_errorcode = code  # what SQLite sets on a real failure
    return error


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def free_space(self) -> None:
        self.events.append("cache deleted")

    def exit(self, status: int) -> None:
        self.events.append(f"exit {status}")


def _failing(*errors: BaseException):
    """An operation that raises the given errors in turn, then returns 'done'."""
    remaining = list(errors)

    def operation() -> str:
        if remaining:
            raise remaining.pop(0)
        return "done"

    return operation


def test_a_full_disk_deletes_the_page_cache_and_retries_once() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    assert guard.run(AUTH, _failing(_error(sqlite3.SQLITE_FULL))) == "done"
    assert recorder.events == ["cache deleted"]


def test_a_second_full_disk_ends_the_process() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    full = _error(sqlite3.SQLITE_FULL)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(VEHICLES, _failing(full, _error(sqlite3.SQLITE_FULL)))
    assert recorder.events == ["cache deleted", "exit 1"]


@pytest.mark.parametrize(
    "code", [sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_IOERR | (3 << 8)]
)
def test_a_damaged_auth_database_ends_the_process(code: int) -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(AUTH, _failing(_error(code)))
    assert recorder.events == ["exit 1"]


@pytest.mark.parametrize(
    ("store", "second", "events"),
    [
        (AUTH, _error(sqlite3.SQLITE_BUSY), ["cache deleted"]),
        (VEHICLES, _error(sqlite3.SQLITE_CORRUPT), ["cache deleted"]),
        (
            AUTH,
            _error(sqlite3.SQLITE_CORRUPT, kind=sqlite3.DatabaseError),
            ["cache deleted", "exit 1"],
        ),
    ],
    ids=["busy-after-full", "corrupt-index-after-full", "corrupt-auth-after-full"],
)
def test_only_a_second_full_disk_or_a_damaged_auth_database_is_fatal(
    store: str, second: sqlite3.Error, events: list[str]
) -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.Error):
        guard.run(store, _failing(_error(sqlite3.SQLITE_FULL), second))
    assert recorder.events == events


def test_a_file_that_is_not_a_database_ends_the_process() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.DatabaseError):  # what SQLite raises for NOTADB and CORRUPT
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_NOTADB, kind=sqlite3.DatabaseError)))
    assert recorder.events == ["exit 1"]


def test_other_errors_pass_through() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    with pytest.raises(sqlite3.OperationalError):
        guard.run(VEHICLES, _failing(_error(sqlite3.SQLITE_CORRUPT)))  # not the auth database
    with pytest.raises(sqlite3.OperationalError):
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_BUSY)))
    with pytest.raises(ValueError):
        guard.run(AUTH, _failing(ValueError("not a database error")))
    assert recorder.events == []


def test_a_wrapped_full_disk_is_recognised() -> None:
    recorder = Recorder()
    guard = StorageGuard(recorder.free_space, exit=recorder.exit)
    wrapped = RealOemError("The vehicle index could not be opened")
    wrapped.__cause__ = _error(sqlite3.SQLITE_FULL)
    assert guard.run(VEHICLES, _failing(wrapped)) == "done"
    assert recorder.events == ["cache deleted"]


def test_a_failure_to_free_space_ends_the_process() -> None:
    recorder = Recorder()

    def broken() -> None:
        raise OSError("cannot delete")

    guard = StorageGuard(broken, exit=recorder.exit)
    with pytest.raises(OSError):
        guard.run(AUTH, _failing(_error(sqlite3.SQLITE_FULL)))
    assert recorder.events == ["exit 1"]


def test_run_directly_adds_nothing() -> None:
    assert run_directly(AUTH, lambda: 42) == 42
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_storage_guard.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.storage_guard'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/storage_guard.py`:

````python
"""What the hosted server does when one of its own databases fails (hosted design 4.10).

The page cache is disposable; the auth database and the vehicle index are not. When either finds
the disk full, deleting the cache files is the one action that frees space without needing any,
so the guard does that and retries the operation once. A second full disk, or a damaged auth
database, ends the process so that Fly restarts it: /healthz never heals anything by itself.
Any other error (a busy database, say) is raised as usual.

Every operation passed to a Runner must be safe to run again: one whole transaction.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from typing import NoReturn, Protocol, TypeVar

from realoem_mcp.cache import is_full

T = TypeVar("T")

AUTH = "auth"
VEHICLES = "vehicle index"
_BROKEN = (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_NOTADB)

log = logging.getLogger(__name__)


class Runner(Protocol):
    def __call__(self, store: str, operation: Callable[[], T], /) -> T: ...


def run_directly(store: str, operation: Callable[[], T]) -> T:
    """The Runner that adds nothing: stdio, tests and the admin script."""
    return operation()


def sqlite_error(error: BaseException) -> sqlite3.Error | None:
    """The SQLite error behind error: itself, or the cause a wrapper (RealOemError) kept."""
    for candidate in (error, error.__cause__):
        if isinstance(candidate, sqlite3.Error):
            return candidate
    return None


def _is_broken(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) in _BROKEN


def hard_exit(status: int) -> NoReturn:
    """End the process at once, even from inside a request handler (where SystemExit may be
    swallowed), after flushing the logs that os._exit would skip."""
    logging.shutdown()
    os._exit(status)


class StorageGuard:
    """A Runner for the hosted server. free_space deletes the page cache files; the HTTP app
    points it at PageCache.reset once the cache is open."""

    def __init__(
        self, free_space: Callable[[], None], *, exit: Callable[[int], object] = hard_exit
    ) -> None:
        self.free_space = free_space
        self._exit = exit

    def run(self, store: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except Exception as error:
            cause = sqlite_error(error)
            if cause is None:
                raise
            if not is_full(cause):
                if store == AUTH and _is_broken(cause):
                    self._fatal(store, cause)
                raise
        log.error("the %s database found the disk full; deleting the page cache, retrying", store)
        try:
            self.free_space()
        except Exception as error:
            self._fatal("page cache", error)
            raise
        try:
            return operation()
        except Exception as error:
            cause = sqlite_error(error)
            if cause is not None and (is_full(cause) or (store == AUTH and _is_broken(cause))):
                self._fatal(store, cause)
            raise

    def _fatal(self, store: str, error: BaseException) -> None:
        log.critical("the %s database failed (%s); exiting so the server restarts", store, error)
        self._exit(1)  # never returns, except for a test double
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_storage_guard.py`
Expected: `13 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1106 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/storage_guard.py server/tests/unit/test_storage_guard.py
git commit -m "feat(hosted): storage guard for a full disk and a damaged auth database" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 2: The sign-in database

### Task 4: The sign-in database

`AuthStore` owns `auth.sqlite3` (hosted design 4.4): WAL mode, forward-only numbered migrations
(never drop and recreate: bans, consents and usage survive upgrades), and every query the
provider, the pages and the admin script need. Two refinements of the spec's table list: a
`families` table carries each sign-in's absolute expiry and its revocation, so revoking a family
is one `UPDATE`; and the first migration creates plan 1a's `usage` table (the same DDL as
`quota.USAGE_SCHEMA`, written out: a migration's text never changes once released), so the
quota counts in this database. Each migration reads the version again under the write lock,
because the admin script may open the database while the server starts. State changes that must
happen once are single conditional `UPDATE` statements: a pending sign-in moves forward once
(`UPDATE ... RETURNING` the row), a code is used once and a refresh token rotates once (checked by
the row count). The hourly purge keeps rotated refresh tokens until their family expires, because
they detect a replayed token.

**Files:**
- Create: `server/src/realoem_mcp/auth/records.py`, `server/src/realoem_mcp/auth/store.py`
- Test: `server/tests/unit/test_auth_store.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_store.py`:

````python
"""The sign-in database (hosted design 4.4, 4.9)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from realoem_mcp.auth.records import (
    AWAITING_CONSENT,
    CONSENTED,
    GITHUB_RETURNED,
    ClientRecord,
    CodeRecord,
    PendingRequest,
)
from realoem_mcp.auth.store import MIGRATIONS, AuthStore, migrate

NOW = 1_800_000_000  # 2027-01-15
HOUR, DAY = 3_600, 86_400


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AuthStore]:
    opened = AuthStore.open(tmp_path / "auth.sqlite3")
    yield opened
    opened.close()


def _pending(request_id: str = "req1", expires_at: int = NOW + 600) -> PendingRequest:
    return PendingRequest(
        id=request_id,
        client_id="client1",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_explicit=True,
        client_state="s",
        code_challenge="c" * 43,
        resource="https://x/mcp",
        scopes=("realoem",),
        status=AWAITING_CONSENT,
        expires_at=expires_at,
    )


def test_a_new_database_is_migrated_and_reopening_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    AuthStore.open(path).close()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    expected = {"clients", "pending", "authorization_codes", "families", "tokens", "users"}
    assert expected | {"consents", "usage"} <= tables
    AuthStore.open(path).close()  # already migrated: nothing to do


def test_a_migration_another_process_applied_meanwhile_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    AuthStore.open(path).close()  # the other process migrated first
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        real_execute = conn.execute
        reads = iter([0])  # what this process read before it took the lock

        class StaleFirstRead:
            def execute(self, sql: str, *args: object):
                if sql == "PRAGMA user_version" and (stale := next(reads, None)) is not None:
                    return real_execute("SELECT ?", (stale,))
                return real_execute(sql, *args)

            def __getattr__(self, name: str) -> object:
                return getattr(conn, name)

        migrate(StaleFirstRead())  # type: ignore[arg-type]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_a_database_from_a_newer_server_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer than this server"):
        AuthStore.open(path)


def test_atomic_rolls_back_everything_on_error(store: AuthStore) -> None:
    def work() -> None:
        store.add_pending(_pending())
        raise ValueError("boom")

    with pytest.raises(ValueError):
        store.atomic(work)
    assert store.pending("req1", NOW) is None
    assert store.conn.in_transaction is False


def test_a_pending_request_moves_forward_once(store: AuthStore) -> None:
    store.add_pending(_pending())
    assert store.pending("req1", NOW) is not None
    consented = store.consent("req1", "statehash", NOW)
    assert consented is not None and consented.status == CONSENTED
    assert store.consent("req1", "statehash", NOW) is None  # a second answer
    assert store.deny("req1", NOW) is None
    assert store.pending("req1", NOW) is None  # no longer waiting for consent
    returned = store.return_from_github("statehash", NOW)
    assert returned is not None and returned.status == GITHUB_RETURNED
    assert store.return_from_github("statehash", NOW) is None  # the state works once


def test_an_expired_request_cannot_be_answered(store: AuthStore) -> None:
    store.add_pending(_pending(expires_at=NOW))
    assert store.pending("req1", NOW) is None
    assert store.consent("req1", "h", NOW) is None
    assert store.deny("req1", NOW) is None


def test_a_code_can_be_used_once(store: AuthStore) -> None:
    store.add_code(
        CodeRecord(
            "codehash",
            "fam",
            "client1",
            "https://r",
            True,
            "c" * 43,
            "https://x/mcp",
            ("realoem",),
            "github:1",
            NOW + 600,
            None,
        )
    )
    assert store.use_code("codehash", NOW) is True
    assert store.use_code("codehash", NOW) is False
    assert store.code("codehash").used_at == NOW


def _family_with_tokens(store: AuthStore, family: str = "fam", subject: str = "github:1") -> None:
    store.add_family(family, subject, "client1", NOW, NOW + 90 * DAY)
    store.add_token(
        f"{family}-a", "access", family, subject, "client1", ["realoem"], "r", NOW + HOUR
    )
    store.add_token(
        f"{family}-r", "refresh", family, subject, "client1", ["realoem"], "r", NOW + 30 * DAY
    )


def test_tokens_are_found_only_with_their_own_kind(store: AuthStore) -> None:
    _family_with_tokens(store)
    access = store.token("fam-a", "access")
    assert access is not None and (access.subject, access.family_revoked) == ("github:1", False)
    assert store.token("fam-a", "refresh") is None
    assert store.token("fam-r", "access") is None


def test_rotation_happens_once_and_never_on_a_revoked_family(store: AuthStore) -> None:
    _family_with_tokens(store)
    assert store.rotate("fam-a", NOW) is False  # only a refresh token rotates
    assert store.rotate("fam-r", NOW) is True
    assert store.rotate("fam-r", NOW) is False
    _family_with_tokens(store, "fam2")
    store.revoke_family("fam2")
    assert store.rotate("fam2-r", NOW) is False
    assert store.token("fam2-a", "access").family_revoked is True


def test_active_families_are_listed_oldest_first(store: AuthStore) -> None:
    for number in range(3):
        store.add_family(f"f{number}", "github:1", "c", NOW + number, NOW + DAY)
    store.add_family("other", "github:2", "c", NOW, NOW + DAY)
    store.add_family("ended", "github:1", "c", NOW, NOW)
    store.revoke_family("f1")
    assert store.active_families("github:1", NOW) == ["f0", "f2"]


def test_a_ban_revokes_every_token_and_shows_on_lookup(store: AuthStore) -> None:
    store.upsert_user("github:1", "octocat", datetime(2011, 1, 25, tzinfo=UTC), NOW)
    _family_with_tokens(store)
    store.ban("github:1", "abuse", NOW)
    assert store.is_banned("github:1")
    assert store.token("fam-a", "access").banned is True
    assert store.token("fam-a", "access").family_revoked is True
    assert store.unban("github:1") is True
    assert not store.is_banned("github:1")
    store.ban("github:9", "never seen", NOW)  # an id that never signed in can be banned too
    assert store.is_banned("github:9")


def test_users_keep_their_account_age(store: AuthStore) -> None:
    created = datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC)
    store.upsert_user("github:1", "octocat", created, NOW)
    store.upsert_user("github:1", "octocat-renamed", None, NOW + DAY)
    user = store.user("github:1")
    assert (user.github_login, user.github_created_at, user.first_seen) == (
        "octocat-renamed",
        created,
        NOW,
    )
    assert store.github_created_at("github:1") == created
    assert store.github_created_at("github:2") is None


def _code_record(code_hash: str, expires_at: int) -> CodeRecord:
    return CodeRecord(
        code_hash,
        "fam",
        "client1",
        "https://r",
        True,
        "c" * 43,
        "r",
        ("realoem",),
        "github:1",
        expires_at,
        None,
    )


def test_purge_removes_what_is_no_longer_needed(store: AuthStore) -> None:
    store.add_pending(_pending("stale", expires_at=NOW - 1))
    store.add_pending(_pending("live"))
    assert store.live_pending_count(NOW) == 1
    store.add_code(_code_record("old-code", NOW - 1))
    store.add_code(_code_record("live-code", NOW + 600))
    store.add_client(ClientRecord("unused", None, {}, NOW - 25 * HOUR, None))
    store.add_client(ClientRecord("new", None, {}, NOW - HOUR, None))
    store.add_client(ClientRecord("idle", None, {}, NOW - 200 * DAY, NOW - 91 * DAY))
    store.add_client(ClientRecord("active", None, {}, NOW - 200 * DAY, NOW - DAY))
    _family_with_tokens(store)
    store.add_token("old-a", "access", "fam", "github:1", "client1", ["realoem"], "r", NOW - 1)
    store.add_token("rotated", "refresh", "fam", "github:1", "client1", ["realoem"], "r", NOW - 1)
    store.rotate("rotated", NOW - 2)
    store.add_family("ended", "github:1", "client1", NOW - 91 * DAY, NOW - 1)
    store.add_token("ended-r", "refresh", "ended", "github:1", "client1", ["realoem"], "r", NOW + 1)
    store.add_consent("github:1", "client1", "https://r", NOW - 91 * DAY)
    store.add_consent("github:1", "client1", "https://r", NOW - DAY)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2026-10-01', 5)")
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-14', 5)")
    removed = store.purge(NOW)
    assert removed == {
        "pending": 1,
        "authorization_codes": 1,
        "tokens": 2,  # the expired access token and the ended family's token
        "families": 1,
        "clients": 2,
        "usage": 1,
        "consents": 1,
    }
    assert store.token("rotated", "refresh") is not None  # kept: it detects a replay
    # Everything still needed survives: a purge that deleted the wrong rows reports the same counts.
    assert store.pending("live", NOW) is not None
    assert store.code("live-code") is not None
    assert store.token("fam-r", "refresh") is not None  # the live family's tokens
    assert store.client("new") is not None and store.client("active") is not None
    assert store.usage("2027-01-14") == [("github:1", None, 5)]
    assert store.conn.execute("SELECT COUNT(*) FROM consents").fetchone() == (1,)


def test_usage_report_names_users(store: AuthStore) -> None:
    store.upsert_user("github:1", "octocat", None, NOW)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-15', 7)")
    store.conn.execute("INSERT INTO usage VALUES ('*', '2027-01-15', 9)")
    store.conn.execute("INSERT INTO usage VALUES ('github:2', '2027-01-15', 2)")
    assert store.usage("2027-01-15") == [
        ("*", None, 9),
        ("github:1", "octocat", 7),
        ("github:2", None, 2),
    ]
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_store.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth.records'`.

- [ ] **Step 3: Implement the row types** `server/src/realoem_mcp/auth/records.py`:

````python
"""Rows of the sign-in database (hosted design 4.4). Times are integer epoch seconds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# A pending request's status moves forward only: awaiting_consent -> consented -> github_returned,
# or awaiting_consent -> denied.
AWAITING_CONSENT = "awaiting_consent"
CONSENTED = "consented"
GITHUB_RETURNED = "github_returned"
DENIED = "denied"


@dataclass(frozen=True)
class ClientRecord:
    client_id: str
    client_secret: str | None  # in clear: the SDK compares it directly
    metadata: dict[str, Any]  # the kept registration fields
    created_at: int
    last_issued_at: int | None


@dataclass(frozen=True)
class PendingRequest:
    """An /authorize request waiting for consent and the GitHub sign-in."""

    id: str
    client_id: str
    redirect_uri: str
    redirect_uri_explicit: bool
    client_state: str | None
    code_challenge: str
    resource: str
    scopes: tuple[str, ...]
    status: str
    expires_at: int
    subject: str | None = None


@dataclass(frozen=True)
class CodeRecord:
    hash: str
    family: str  # the token family the code's exchange creates (revoked if the code is replayed)
    client_id: str
    redirect_uri: str
    redirect_uri_explicit: bool
    code_challenge: str
    resource: str
    scopes: tuple[str, ...]
    subject: str
    expires_at: int
    used_at: int | None


@dataclass(frozen=True)
class TokenRecord:
    """An access or refresh token, with the state of its family and its user."""

    hash: str
    kind: str  # "access" or "refresh"
    family: str
    subject: str
    client_id: str
    scopes: tuple[str, ...]
    resource: str
    expires_at: int
    rotated_at: int | None
    family_revoked: bool
    family_expires_at: int
    banned: bool


@dataclass(frozen=True)
class UserRecord:
    subject: str  # "github:<numeric id>"
    github_login: str
    github_created_at: datetime | None
    first_seen: int
    banned_at: int | None
    banned_reason: str | None
````

- [ ] **Step 4: Implement the store** `server/src/realoem_mcp/auth/store.py`:

````python
"""The hosted server's sign-in database, auth.sqlite3 (hosted design 4.4).

Stdlib sqlite3 in WAL mode, migrated forward only (never dropped and recreated: bans, consents
and usage survive upgrades). Tokens and codes are stored as keyed hashes (auth/keys.py). Every
statement runs through the Runner, so on the hosted server a full disk frees the page cache and
retries once, and a damaged database ends the process (storage_guard.py).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from realoem_mcp.auth.records import (
    AWAITING_CONSENT,
    CONSENTED,
    DENIED,
    GITHUB_RETURNED,
    ClientRecord,
    CodeRecord,
    PendingRequest,
    TokenRecord,
    UserRecord,
)
from realoem_mcp.storage_guard import AUTH, Runner, run_directly

T = TypeVar("T")

JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024
BUSY_TIMEOUT_MS = 5_000  # the admin script may hold the write lock for a moment
UNUSED_CLIENT_AGE = timedelta(hours=24)  # a client that never completed a sign-in
IDLE_CLIENT_AGE = timedelta(days=90)  # a client with no token issued for this long
RETENTION = timedelta(days=90)  # usage rows and the consent audit

# Forward-only migrations: MIGRATIONS[n] takes the database from user_version n to n + 1.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE clients (
          client_id TEXT PRIMARY KEY, client_secret TEXT, metadata TEXT NOT NULL,
          created_at INTEGER NOT NULL, last_issued_at INTEGER)""",
        """CREATE TABLE pending (
          id TEXT PRIMARY KEY, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
          redirect_uri_explicit INTEGER NOT NULL, client_state TEXT, code_challenge TEXT NOT NULL,
          resource TEXT NOT NULL, scopes TEXT NOT NULL, status TEXT NOT NULL,
          gh_state_hash TEXT UNIQUE, subject TEXT, expires_at INTEGER NOT NULL)""",
        "CREATE INDEX pending_expires_at ON pending (expires_at)",
        """CREATE TABLE authorization_codes (
          hash TEXT PRIMARY KEY, family TEXT NOT NULL, client_id TEXT NOT NULL,
          redirect_uri TEXT NOT NULL, redirect_uri_explicit INTEGER NOT NULL,
          code_challenge TEXT NOT NULL, resource TEXT NOT NULL, scopes TEXT NOT NULL,
          subject TEXT NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER)""",
        """CREATE TABLE families (
          id TEXT PRIMARY KEY, subject TEXT NOT NULL, client_id TEXT NOT NULL,
          created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
          revoked INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX families_subject ON families (subject)",
        """CREATE TABLE tokens (
          hash TEXT PRIMARY KEY, kind TEXT NOT NULL, family TEXT NOT NULL, subject TEXT NOT NULL,
          client_id TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT NOT NULL,
          expires_at INTEGER NOT NULL, rotated_at INTEGER)""",
        "CREATE INDEX tokens_family ON tokens (family)",
        """CREATE TABLE users (
          subject TEXT PRIMARY KEY, github_login TEXT NOT NULL, github_created_at TEXT,
          first_seen INTEGER NOT NULL, banned_at INTEGER, banned_reason TEXT)""",
        """CREATE TABLE consents (
          subject TEXT NOT NULL, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
          granted_at INTEGER NOT NULL)""",
        "CREATE INDEX consents_granted_at ON consents (granted_at)",
        # The table Quota counts in (quota.USAGE_SCHEMA); a migration's text never changes.
        """CREATE TABLE IF NOT EXISTS usage (
          subject TEXT NOT NULL, day TEXT NOT NULL, requests INTEGER NOT NULL,
          PRIMARY KEY (subject, day))""",
    ),
)

_PENDING = (
    "id, client_id, redirect_uri, redirect_uri_explicit, client_state, code_challenge, resource, "
    "scopes, status, expires_at, subject"
)
_CODE = (
    "hash, family, client_id, redirect_uri, redirect_uri_explicit, code_challenge, resource, "
    "scopes, subject, expires_at, used_at"
)


def _version(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise RuntimeError(
            f"auth database version {version} is newer than this server ({len(MIGRATIONS)})"
        )
    return version


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the database to the newest version; each migration is one transaction.

    The version is read again under the write lock: another process (the admin script while
    the server restarts) may have applied the same migration in the meantime.
    """
    while _version(conn) < len(MIGRATIONS):
        conn.execute("BEGIN IMMEDIATE")
        try:
            number = _version(conn)
            if number < len(MIGRATIONS):
                for statement in MIGRATIONS[number]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {number + 1}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def _scopes(text: str) -> tuple[str, ...]:
    return tuple(text.split())


def _pending(row: Sequence[Any]) -> PendingRequest:
    return PendingRequest(
        id=row[0],
        client_id=row[1],
        redirect_uri=row[2],
        redirect_uri_explicit=bool(row[3]),
        client_state=row[4],
        code_challenge=row[5],
        resource=row[6],
        scopes=_scopes(row[7]),
        status=row[8],
        expires_at=row[9],
        subject=row[10],
    )


def _code(row: Sequence[Any]) -> CodeRecord:
    return CodeRecord(
        hash=row[0],
        family=row[1],
        client_id=row[2],
        redirect_uri=row[3],
        redirect_uri_explicit=bool(row[4]),
        code_challenge=row[5],
        resource=row[6],
        scopes=_scopes(row[7]),
        subject=row[8],
        expires_at=row[9],
        used_at=row[10],
    )


def _datetime(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class AuthStore:
    def __init__(self, conn: sqlite3.Connection, *, run: Runner = run_directly) -> None:
        self._conn = conn
        self._run = run

    @classmethod
    def open(cls, path: Path, *, run: Runner = run_directly) -> AuthStore:
        def connect() -> sqlite3.Connection:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit; one connection, used only from the event-loop thread.
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")
                conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
                migrate(conn)
            except BaseException:
                conn.close()
                raise
            return conn

        return cls(run(AUTH, connect), run=run)

    @property
    def conn(self) -> sqlite3.Connection:
        """The connection, for Quota: the usage table lives in this database."""
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # --- plumbing -----------------------------------------------------------------------------

    def atomic(self, work: Callable[[], T]) -> T:
        """Run work as one write transaction; inside another one it simply joins it."""
        if self._conn.in_transaction:
            return work()

        def transaction() -> T:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                result = work()
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            return result

        return self._run(AUTH, transaction)

    def _guarded(self, operation: Callable[[], T]) -> T:
        return operation() if self._conn.in_transaction else self._run(AUTH, operation)

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._guarded(lambda: self._conn.execute(sql, params).fetchone())

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        return self._guarded(lambda: self._conn.execute(sql, params).fetchall())

    def _write(self, sql: str, params: Sequence[Any] = ()) -> int:
        return self._guarded(lambda: self._conn.execute(sql, params).rowcount)

    # --- clients ------------------------------------------------------------------------------

    def add_client(self, record: ClientRecord) -> None:
        self._write(
            "INSERT INTO clients (client_id, client_secret, metadata, created_at, last_issued_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.client_id,
                record.client_secret,
                json.dumps(record.metadata, sort_keys=True),
                record.created_at,
                record.last_issued_at,
            ),
        )

    def client(self, client_id: str) -> ClientRecord | None:
        row = self._one(
            "SELECT client_id, client_secret, metadata, created_at, last_issued_at FROM clients "
            "WHERE client_id = ?",
            (client_id,),
        )
        if row is None:
            return None
        return ClientRecord(row[0], row[1], json.loads(row[2]), row[3], row[4])

    def touch_client(self, client_id: str, now: int) -> None:
        self._write("UPDATE clients SET last_issued_at = ? WHERE client_id = ?", (now, client_id))

    # --- pending sign-ins ---------------------------------------------------------------------

    def add_pending(self, request: PendingRequest) -> None:
        self._write(
            f"INSERT INTO pending ({_PENDING}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.client_id,
                request.redirect_uri,
                int(request.redirect_uri_explicit),
                request.client_state,
                request.code_challenge,
                request.resource,
                " ".join(request.scopes),
                request.status,
                request.expires_at,
                request.subject,
            ),
        )

    def pending(self, request_id: str, now: int) -> PendingRequest | None:
        """The request, if it is still waiting for consent."""
        row = self._one(
            f"SELECT {_PENDING} FROM pending WHERE id = ? AND status = ? AND expires_at > ?",
            (request_id, AWAITING_CONSENT, now),
        )
        return _pending(row) if row else None

    def _advance(self, sql: str, params: Sequence[Any]) -> PendingRequest | None:
        rows = self._all(f"{sql} RETURNING {_PENDING}", params)
        return _pending(rows[0]) if rows else None

    def consent(self, request_id: str, gh_state_hash: str, now: int) -> PendingRequest | None:
        """awaiting_consent -> consented, once; None when stale, used or unknown."""
        return self._advance(
            "UPDATE pending SET status = ?, gh_state_hash = ? "
            "WHERE id = ? AND status = ? AND expires_at > ?",
            (CONSENTED, gh_state_hash, request_id, AWAITING_CONSENT, now),
        )

    def deny(self, request_id: str, now: int) -> PendingRequest | None:
        return self._advance(
            "UPDATE pending SET status = ? WHERE id = ? AND status = ? AND expires_at > ?",
            (DENIED, request_id, AWAITING_CONSENT, now),
        )

    def return_from_github(self, gh_state_hash: str, now: int) -> PendingRequest | None:
        """consented -> github_returned for the request with this GitHub state, once."""
        return self._advance(
            "UPDATE pending SET status = ?, gh_state_hash = NULL "
            "WHERE gh_state_hash = ? AND status = ? AND expires_at > ?",
            (GITHUB_RETURNED, gh_state_hash, CONSENTED, now),
        )

    def record_subject(self, request_id: str, subject: str) -> None:
        """Note who signed in for this request, once GitHub has said so."""
        self._write("UPDATE pending SET subject = ? WHERE id = ?", (subject, request_id))

    def live_pending_count(self, now: int) -> int:
        return self._one("SELECT COUNT(*) FROM pending WHERE expires_at > ?", (now,))[0]

    # --- authorization codes ------------------------------------------------------------------

    def add_code(self, code: CodeRecord) -> None:
        self._write(
            f"INSERT INTO authorization_codes ({_CODE}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code.hash,
                code.family,
                code.client_id,
                code.redirect_uri,
                int(code.redirect_uri_explicit),
                code.code_challenge,
                code.resource,
                " ".join(code.scopes),
                code.subject,
                code.expires_at,
                code.used_at,
            ),
        )

    def code(self, code_hash: str) -> CodeRecord | None:
        row = self._one(f"SELECT {_CODE} FROM authorization_codes WHERE hash = ?", (code_hash,))
        return _code(row) if row else None

    def use_code(self, code_hash: str, now: int) -> bool:
        """Mark the code used; False when it already was (or does not exist)."""
        return (
            self._write(
                "UPDATE authorization_codes SET used_at = ? WHERE hash = ? AND used_at IS NULL",
                (now, code_hash),
            )
            == 1
        )

    # --- token families and tokens ------------------------------------------------------------

    def add_family(
        self, family: str, subject: str, client_id: str, now: int, expires_at: int
    ) -> None:
        self._write(
            "INSERT INTO families (id, subject, client_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (family, subject, client_id, now, expires_at),
        )

    def active_families(self, subject: str, now: int) -> list[str]:
        """The subject's live families, oldest first."""
        rows = self._all(
            "SELECT id FROM families WHERE subject = ? AND revoked = 0 AND expires_at > ? "
            "ORDER BY created_at, rowid",
            (subject, now),
        )
        return [row[0] for row in rows]

    def revoke_family(self, family: str) -> None:
        self._write("UPDATE families SET revoked = 1 WHERE id = ?", (family,))

    def revoke_subject(self, subject: str) -> int:
        """Revoke every family of the subject; returns how many were live."""
        return self._write(
            "UPDATE families SET revoked = 1 WHERE subject = ? AND revoked = 0", (subject,)
        )

    def add_token(
        self,
        token_hash: str,
        kind: str,
        family: str,
        subject: str,
        client_id: str,
        scopes: Sequence[str],
        resource: str,
        expires_at: int,
    ) -> None:
        self._write(
            "INSERT INTO tokens (hash, kind, family, subject, client_id, scopes, resource, "
            "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token_hash, kind, family, subject, client_id, " ".join(scopes), resource, expires_at),
        )

    def token(self, token_hash: str, kind: str) -> TokenRecord | None:
        """The token of this kind with this hash, whatever its state; None if there is none."""
        row = self._one(
            "SELECT t.hash, t.kind, t.family, t.subject, t.client_id, t.scopes, t.resource, "
            "t.expires_at, t.rotated_at, f.revoked, f.expires_at, u.banned_at IS NOT NULL "
            "FROM tokens t JOIN families f ON f.id = t.family "
            "LEFT JOIN users u ON u.subject = t.subject "
            "WHERE t.hash = ? AND t.kind = ?",
            (token_hash, kind),
        )
        if row is None:
            return None
        return TokenRecord(
            hash=row[0],
            kind=row[1],
            family=row[2],
            subject=row[3],
            client_id=row[4],
            scopes=_scopes(row[5]),
            resource=row[6],
            expires_at=row[7],
            rotated_at=row[8],
            family_revoked=bool(row[9]),
            family_expires_at=row[10],
            banned=bool(row[11]),
        )

    def rotate(self, token_hash: str, now: int) -> bool:
        """Mark a live refresh token rotated; False when it already was, or is revoked."""
        return (
            self._write(
                "UPDATE tokens SET rotated_at = ? WHERE hash = ? AND kind = 'refresh' "
                "AND rotated_at IS NULL "
                "AND NOT EXISTS "
                "(SELECT 1 FROM families f WHERE f.id = tokens.family AND f.revoked = 1)",
                (now, token_hash),
            )
            == 1
        )

    # --- users and consents -------------------------------------------------------------------

    def upsert_user(
        self, subject: str, github_login: str, github_created_at: datetime | None, now: int
    ) -> None:
        created = github_created_at.isoformat() if github_created_at else None
        self._write(
            "INSERT INTO users (subject, github_login, github_created_at, first_seen) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (subject) DO UPDATE SET "
            "github_login = excluded.github_login, "
            "github_created_at = COALESCE(excluded.github_created_at, github_created_at)",
            (subject, github_login, created, now),
        )

    def user(self, subject: str) -> UserRecord | None:
        row = self._one(
            "SELECT subject, github_login, github_created_at, first_seen, banned_at, "
            "banned_reason FROM users WHERE subject = ?",
            (subject,),
        )
        if row is None:
            return None
        return UserRecord(row[0], row[1], _datetime(row[2]), row[3], row[4], row[5])

    def github_created_at(self, subject: str) -> datetime | None:
        """For Quota: when the subject's GitHub account was created (None when unknown)."""
        user = self.user(subject)
        return user.github_created_at if user else None

    def is_banned(self, subject: str) -> bool:
        user = self.user(subject)
        return user is not None and user.banned_at is not None

    def ban(self, subject: str, reason: str, now: int) -> None:
        """Ban the subject (known or not yet seen) and revoke all of its tokens."""

        def work() -> None:
            self._conn.execute(
                "INSERT INTO users (subject, github_login, first_seen, banned_at, banned_reason) "
                "VALUES (?, '', ?, ?, ?) ON CONFLICT (subject) DO UPDATE SET "
                "banned_at = excluded.banned_at, banned_reason = excluded.banned_reason",
                (subject, now, now, reason),
            )
            self.revoke_subject(subject)

        self.atomic(work)

    def unban(self, subject: str) -> bool:
        return (
            self._write(
                "UPDATE users SET banned_at = NULL, banned_reason = NULL "
                "WHERE subject = ? AND banned_at IS NOT NULL",
                (subject,),
            )
            == 1
        )

    def add_consent(self, subject: str, client_id: str, redirect_uri: str, now: int) -> None:
        self._write(
            "INSERT INTO consents (subject, client_id, redirect_uri, granted_at) "
            "VALUES (?, ?, ?, ?)",
            (subject, client_id, redirect_uri, now),
        )

    def usage(self, day: str) -> list[tuple[str, str | None, int]]:
        """(subject, GitHub login, requests) for one UTC day, busiest first; "*" is everyone."""
        rows = self._all(
            "SELECT u.subject, users.github_login, u.requests FROM usage u "
            "LEFT JOIN users ON users.subject = u.subject WHERE u.day = ? "
            "ORDER BY u.requests DESC, u.subject",
            (day,),
        )
        return [(row[0], row[1], row[2]) for row in rows]

    # --- housekeeping -------------------------------------------------------------------------

    def purge(self, now: int) -> dict[str, int]:
        """Delete what is no longer needed (hosted design 4.9); returns the rows removed per
        table. Rotated refresh tokens stay until their family expires: they detect replays."""
        retention_cutoff = now - int(RETENTION.total_seconds())
        oldest_day = datetime.fromtimestamp(retention_cutoff, UTC).date().isoformat()
        statements = {
            "pending": ("DELETE FROM pending WHERE expires_at <= ?", (now,)),
            "authorization_codes": (
                "DELETE FROM authorization_codes WHERE expires_at <= ?",
                (now,),
            ),
            "tokens": (
                "DELETE FROM tokens WHERE (expires_at <= ? AND rotated_at IS NULL) "
                "OR family IN (SELECT id FROM families WHERE expires_at <= ?)",
                (now, now),
            ),
            "families": ("DELETE FROM families WHERE expires_at <= ?", (now,)),
            "clients": (
                "DELETE FROM clients WHERE (last_issued_at IS NULL AND created_at <= ?) "
                "OR last_issued_at <= ?",
                (
                    now - int(UNUSED_CLIENT_AGE.total_seconds()),
                    now - int(IDLE_CLIENT_AGE.total_seconds()),
                ),
            ),
            "usage": ("DELETE FROM usage WHERE day < ?", (oldest_day,)),
            "consents": ("DELETE FROM consents WHERE granted_at <= ?", (retention_cutoff,)),
        }

        def work() -> dict[str, int]:
            return {
                table: self._conn.execute(sql, params).rowcount
                for table, (sql, params) in statements.items()
            }

        return self.atomic(work)
````

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_store.py`
Expected: `14 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1120 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/records.py server/src/realoem_mcp/auth/store.py server/tests/unit/test_auth_store.py
git commit -m "feat(auth): sign-in database with forward-only migrations and the hourly purge" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 3: Every database through the guard

### Task 5: Every database through the guard

The quota's usage table lives in the auth database, and the vehicle index is the server's other
durable database, so both now run their statements through the guard: `Quota` and
`VehicleIndex.open` take a `run` argument (default `run_directly`), `Services` carries the
hosted server's guard as `run_storage`, and `build_shared` passes it along. The vehicle index's
transaction now rolls back only when SQLite has not already done so: after a full disk SQLite has
rolled back itself, and a second `ROLLBACK` would raise "no transaction is active" and hide the
real error (the test below fails without that change). The index also gets
`journal_size_limit` like the other two databases, so its WAL file does not keep its peak size on
the shared volume. The tests make SQLite report `SQLITE_FULL` with `PRAGMA max_page_count`, which
fails when a page is allocated; a real full disk in WAL mode usually fails at `COMMIT`, which is
why every transaction runs its `COMMIT` inside the `try`.

**Files:**
- Modify: `server/src/realoem_mcp/quota.py`, `server/src/realoem_mcp/services.py`,
  `server/src/realoem_mcp/shared.py`, `server/src/realoem_mcp/vehicle_index.py`,
  `server/src/realoem_mcp/tools/vehicles.py`
- Test: `server/tests/unit/test_storage_guard_wiring.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_storage_guard_wiring.py`:

````python
"""A full disk in the auth database, the quota or the vehicle index (hosted design 4.10).

SQLite's max_page_count makes a database report SQLITE_FULL with the same error a full disk
gives, when a page is allocated. A real full disk in WAL mode usually fails at COMMIT instead (the
WAL append), which is why every transaction here runs COMMIT inside its try. The guard's
free_space (deleting the page cache in production) lifts the limit.
"""

import dataclasses
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest

from realoem_mcp.auth.records import ClientRecord
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import Quota
from realoem_mcp.shared import build_shared
from realoem_mcp.storage_guard import AUTH, VEHICLES, StorageGuard
from realoem_mcp.tools.vehicles import get_index
from realoem_mcp.vehicle_index import VehicleIndex
from tests.auth_helpers import signed_in
from tests.harness import FakeClock, FixtureTransport, url
from tests.vehicle_data import numbered
from tests.vehicle_env import install_baseline, settings_for

T = TypeVar("T")


class FullDisk:
    """Fills a connection's database to its current size, and frees it on demand."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.conn: sqlite3.Connection | None = None
        self.refill = False  # fill the disk again right after freeing it

    def fill(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count = {pages}")

    def free_space(self) -> None:
        self.events.append("cache deleted")
        assert self.conn is not None
        if not self.refill:
            self.conn.execute("PRAGMA max_page_count = 1000000")

    def exit(self, status: int) -> None:
        self.events.append(f"exit {status}")


def _clients(count: int) -> list[ClientRecord]:
    return [ClientRecord(f"client-{n}", "x" * 500, {"n": n}, 0, None) for n in range(count)]


def test_a_full_auth_database_frees_the_cache_and_retries(tmp_path: Path) -> None:
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        disk.fill(store.conn)
        store.atomic(lambda: [store.add_client(client) for client in _clients(50)])
        assert disk.events == ["cache deleted"]
        assert store.client("client-49") is not None
    finally:
        store.close()


def test_a_second_full_disk_ends_the_process(tmp_path: Path) -> None:
    disk = FullDisk()
    disk.refill = True
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        disk.fill(store.conn)
        with pytest.raises(sqlite3.OperationalError):  # raised after the (recorded) exit
            store.atomic(lambda: [store.add_client(client) for client in _clients(50)])
        assert disk.events == ["cache deleted", "exit 1"]
        assert store.conn.in_transaction is False
    finally:
        store.close()


def test_the_quota_is_counted_through_the_guard(tmp_path: Path) -> None:
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    store = AuthStore.open(tmp_path / "auth.sqlite3", run=guard.run)
    try:
        quota = Quota(
            store.conn,
            Settings(mode="http"),
            account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),
            now=lambda: datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
            run=guard.run,
        )
        disk.fill(store.conn)
        for n in range(200):  # enough new usage rows to need another page
            quota.charge(f"github:{n}")
        assert disk.events == ["cache deleted"]
        assert quota.used_by_everyone_today() == 200  # the retried charge counted once
    finally:
        store.close()


def test_a_full_vehicle_index_frees_the_cache_and_retries(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    rows = numbered(400)
    install_baseline(settings, rows[:10])
    disk = FullDisk()
    guard = StorageGuard(disk.free_space, exit=disk.exit)
    index = VehicleIndex.open(settings, BrandRegistry.load(settings.brands_dir), run=guard.run)
    try:
        disk.fill(index._conn)
        assert index.add_local(rows[10:]) == 390
        assert disk.events == ["cache deleted"]
        assert index.count() == 400
    finally:
        index.close()


def test_the_vehicle_index_limits_its_wal_file(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    install_baseline(settings, numbered(3))
    index = VehicleIndex.open(settings, BrandRegistry.load(settings.brands_dir))
    try:
        limit = index._conn.execute("PRAGMA journal_size_limit").fetchone()[0]
        assert limit == 64 * 1024 * 1024  # as on the cache and the auth database
    finally:
        index.close()


@pytest.mark.anyio
async def test_build_shared_runs_the_quota_and_the_index_through_its_guard(
    tmp_path: Path,
) -> None:
    stores: list[str] = []

    def recorder(store: str, operation: Callable[[], T]) -> T:
        stores.append(store)
        return operation()

    settings = dataclasses.replace(settings_for(tmp_path), mode="http")
    install_baseline(settings, numbered(3))
    part = url("partxref", q="11427953129")
    clock = FakeClock()
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        shared = build_shared(
            settings,
            conn,
            owner_key=b"key",
            account_created_at=lambda subject: datetime(2015, 1, 1, tzinfo=UTC),
            transport=FixtureTransport({part: "partxref/oil_filter_11427953129.html"}),
            clock=clock,
            sleep=clock.sleep,
            run=recorder,
        )
        try:
            with signed_in("github:1"):
                await shared.services.client.fetch(
                    PageType.PARTXREF,
                    "partxref",
                    {"q": "11427953129"},
                )
            get_index(shared.services)
        finally:
            await shared.services.aclose()
    assert AUTH in stores and VEHICLES in stores
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_storage_guard_wiring.py`
Expected: FAIL: 4 failed, 2 passed. The quota test, the full-vehicle-index test and the build_shared test fail with `TypeError` (`unexpected keyword argument 'run'`); `test_the_vehicle_index_limits_its_wal_file` fails with `assert -1 == ((64 * 1024) * 1024)` (SQLite's default: no limit); the two auth-database tests already pass (the store took a guard in Task 4).

- [ ] **Step 3: The quota.** In `server/src/realoem_mcp/quota.py`:

Edit 1. Find:

````python

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
````

Replace with:

````python

from realoem_mcp.config import Settings
from realoem_mcp.errors import QuotaExceeded
from realoem_mcp.storage_guard import AUTH, Runner, run_directly

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
````

Edit 2. Find:

````python
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
````

Replace with:

````python
        *,
        account_created_at: Callable[[str], datetime | None],
        now: Callable[[], datetime] = _utc_now,
        run: Runner = run_directly,
    ) -> None:
        """account_created_at returns the subject's GitHub account creation time, timezone-aware,
        or None when unknown; an unknown age gets the new-account limit (fail closed). run is
        the hosted server's storage guard: the usage table lives in the auth database."""
        self._conn = conn
        self._settings = settings
        self._account_created_at = account_created_at
        self._now = now
        self._run = run
        conn.execute(USAGE_SCHEMA)

    def _day(self) -> str:
````

Edit 3. Find:

````python
        return self._settings.user_daily_limit

    def _used(self, subject: str, day: str) -> int:
        row = self._conn.execute(
            "SELECT requests FROM usage WHERE subject = ? AND day = ?", (subject, day)
        ).fetchone()
        return row[0] if row else 0

    def refusal(self, subject: str) -> QuotaExceeded | None:
````

Replace with:

````python
        return self._settings.user_daily_limit

    def _used(self, subject: str, day: str) -> int:
        row = self._run(
            AUTH,
            lambda: self._conn.execute(
                "SELECT requests FROM usage WHERE subject = ? AND day = ?", (subject, day)
            ).fetchone(),
        )
        return row[0] if row else 0

    def refusal(self, subject: str) -> QuotaExceeded | None:
````

Edit 4. Find:

````python
        day = self._day()
        limit = self.limit_for(subject)
        cap = self._settings.global_daily_limit
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if not self._bump(subject, day, limit):
````

Replace with:

````python
        day = self._day()
        limit = self.limit_for(subject)
        cap = self._settings.global_daily_limit
        self._run(AUTH, lambda: self._charge(subject, day, limit, cap))

    def _charge(self, subject: str, day: str, limit: int, cap: int) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if not self._bump(subject, day, limit):
````

- [ ] **Step 4: Services and build_shared.** In `server/src/realoem_mcp/services.py`:

Edit 1. Find:

````python
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Admit, Charge, Owner, RealOemClient


@dataclass
````

Replace with:

````python
from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.http_client import Admit, Charge, Owner, RealOemClient
from realoem_mcp.storage_guard import Runner, run_directly


@dataclass
````

Edit 2. Find:

````python
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)  # branch-owned singletons

    async def aclose(self) -> None:
        """Close every extra, then the client, then the cache; re-raise the first error.
````

Replace with:

````python
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)  # branch-owned singletons
    run_storage: Runner = run_directly  # hosted server: the storage guard (storage_guard.py)

    async def aclose(self) -> None:
        """Close every extra, then the client, then the cache; re-raise the first error.
````

In `server/src/realoem_mcp/shared.py`:

Edit 1. Find:

````python
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY, Quota
from realoem_mcp.services import Services, create_services


@dataclass
````

Replace with:

````python
from realoem_mcp.page_types import PageType
from realoem_mcp.quota import QUOTA_KEY, Quota
from realoem_mcp.services import Services, create_services
from realoem_mcp.storage_guard import Runner, run_directly


@dataclass
````

Edit 2. Find:

````python
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
````

Replace with:

````python
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], datetime] | None = None,
    run: Runner = run_directly,
) -> Shared:
    """Services for the hosted server: every cache-miss fetch is admitted, charged to the
    signed-in caller and, for VIN pages, cached for that caller only.

    usage_conn is an autocommit SQLite connection that holds the `usage` table. run is the
    storage guard the quota and the vehicle index use (the HTTP app passes StorageGuard.run).
    """
    if settings.mode != "http":
        raise ValueError("build_shared needs Settings(mode='http')")
````

Edit 3. Find:

````python
        usage_conn,
        settings,
        account_created_at=account_created_at,
        **({"now": now} if now is not None else {}),
    )
    gate = FetchGate(settings, quota, clock=clock or time.monotonic)
````

Replace with:

````python
        usage_conn,
        settings,
        account_created_at=account_created_at,
        run=run,
        **({"now": now} if now is not None else {}),
    )
    gate = FetchGate(settings, quota, clock=clock or time.monotonic)
````

Edit 4. Find:

````python
        charge=lambda: quota.charge(require_user(settings).subject),
        owner=vin_page_owner(settings, owner_key),
    )
    services.extras[QUOTA_KEY] = quota
    services.extras[GATE_KEY] = gate
    return Shared(services=services, quota=quota, gate=gate)
````

Replace with:

````python
        charge=lambda: quota.charge(require_user(settings).subject),
        owner=vin_page_owner(settings, owner_key),
    )
    services.run_storage = run
    services.extras[QUOTA_KEY] = quota
    services.extras[GATE_KEY] = gate
    return Shared(services=services, quota=quota, gate=gate)
````

- [ ] **Step 5: The vehicle index.** In `server/src/realoem_mcp/vehicle_index.py`:

Edit 1. Find:

````python
from typing import Any

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle, IndexMeta
from realoem_mcp.vehicle_ids import VehicleId

DB_FILENAME = "vehicles.sqlite3"
````

Replace with:

````python
from typing import Any

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.cache import JOURNAL_SIZE_LIMIT
from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle, IndexMeta
from realoem_mcp.storage_guard import VEHICLES, Runner, run_directly
from realoem_mcp.vehicle_ids import VehicleId

DB_FILENAME = "vehicles.sqlite3"
````

Edit 2. Find:

````python


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
````

Replace with:

````python


class VehicleIndex:
    def __init__(
        self, conn: sqlite3.Connection, brands: BrandRegistry, *, run: Runner = run_directly
    ) -> None:
        self._conn = conn
        self._segments = brands.brand_segments()
        self._run = run  # hosted server: the storage guard, for every write

    @classmethod
    def open(
        cls, settings: Settings, brands: BrandRegistry, *, run: Runner = run_directly
    ) -> VehicleIndex:
        """Open the store, (re)loading the baseline when the committed files changed.

        Missing baseline files count as an empty baseline, so the index works (empty) before the
        maintainer has built one. Unreadable files raise RealOemError naming the file.
        """
        # Retrying a whole open is safe: it closes its connection before raising, and loading
        # the schema and the baseline twice changes nothing.
        return run(VEHICLES, lambda: cls._open(settings, brands, run))

    @classmethod
    def _open(cls, settings: Settings, brands: BrandRegistry, run: Runner) -> VehicleIndex:
        db_path = settings.data_dir / DB_FILENAME
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        except (OSError, sqlite3.Error) as err:
            raise RealOemError(f"The vehicle index {db_path} could not be opened: {err}") from err
        index = cls(conn, brands, run=run)
        try:
            conn.create_function("fold", 1, _casefold, deterministic=True)
            conn.execute("PRAGMA journal_mode=WAL")  # several server processes may share it
            conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")  # one shared volume
            index._ensure_schema()
            brand_ids = sorted(brand.id for brand in brands)
            files = [settings.brands_dir / brand_id / CSV_FILENAME for brand_id in brand_ids]
````

Edit 3. Find:

````python
        self._conn.execute("BEGIN IMMEDIATE")  # take the write lock up front
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _ensure_schema(self) -> None:
        """Create the tables; on a schema-version change rebuild them, keeping local rows if the
````

Replace with:

````python
        self._conn.execute("BEGIN IMMEDIATE")  # take the write lock up front
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            # SQLite has already rolled back after some errors (a full disk is one); a second
            # ROLLBACK would raise and hide the real error.
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _ensure_schema(self) -> None:
        """Create the tables; on a schema-version change rebuild them, keeping local rows if the
````

Edit 4. Find:

````python
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
````

Replace with:

````python
    def add_local(self, rows: Sequence[IndexedVehicle]) -> int:
        """Insert rows found by an update; existing keys are ignored. Returns rows inserted."""
        added_at = _now()

        def insert() -> int:
            inserted = 0
            with self._transaction():
                for row in rows:
                    values = _db_values(csv_record(row), row.brand, "local")
                    inserted += self._conn.execute(_INSERT_NEW, (*values, added_at)).rowcount
            return inserted

        return self._run(VEHICLES, insert)

    def last_remote_total(self) -> int | None:
        """RealOEM's vehicle count seen by the last update check, if any."""
````

Edit 5. Find:

````python

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
````

Replace with:

````python

    def record_check(self, *, remote_total: int, resume: tuple[str | None, int] | None) -> None:
        """Store the outcome of an update check: time, RealOEM's total, and where to resume."""
        checked_at = _now()

        def store() -> None:
            with self._transaction():
                self._set_meta("last_update_at", checked_at)
                self._set_meta("last_remote_total", str(remote_total))
                if resume is None:
                    self._conn.execute(
                        "DELETE FROM meta WHERE key IN ('resume_start', 'resume_page')"
                    )
                else:
                    self._set_meta("resume_start", resume[0] or "")
                    self._set_meta("resume_page", str(resume[1]))

        self._run(VEHICLES, store)

    def meta(self) -> IndexMeta:
        built_at = self._get_meta("built_at")
````

In `server/src/realoem_mcp/tools/vehicles.py`:

Edit 1. Find:

````python
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands)
        services.extras[INDEX_KEY] = index
    return index

````

Replace with:

````python
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands, run=services.run_storage)
        services.extras[INDEX_KEY] = index
    return index

````

- [ ] **Step 6: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_storage_guard_wiring.py tests/unit/test_quota.py tests/unit/test_vehicle_index.py tests/tools/test_shared_wiring.py`
Expected: `41 passed` (6 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1126 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/quota.py server/src/realoem_mcp/services.py server/src/realoem_mcp/shared.py server/src/realoem_mcp/vehicle_index.py server/src/realoem_mcp/tools/vehicles.py server/tests/unit/test_storage_guard_wiring.py
git commit -m "feat(hosted): quota and vehicle index run through the storage guard" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 4: Redirects and GitHub

### Task 6: The redirect allow-list

Registration admits exactly Claude's callback (`https://claude.ai/api/mcp/auth_callback`, a string
match; more can be configured) and programs on the user's computer: `http://localhost` or
`http://127.0.0.1`, any port, no user info, no fragment, at most 512 characters (hosted design
4.3). This is a security invariant: the SDK redirects some `/authorize` errors to the registered
URI before anyone signs in. `ClaudeClient` is the SDK's client record with one change: a loopback
redirect matches on everything but the port, because a local program listens on whatever port is
free, and the requested URI (with its port) is returned so the SDK's `/token` check passes. An
empty path counts as `/`: the SDK stores `http://127.0.0.1:33418` as registered but normalises
the same URI in an `/authorize` request to `http://127.0.0.1:33418/`.

**Files:**
- Create: `server/src/realoem_mcp/auth/redirects.py`
- Test: `server/tests/unit/test_auth_redirects.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_redirects.py`:

````python
"""The redirect allow-list, a security invariant (hosted design 4.3)."""

import pytest
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl

from realoem_mcp.auth.redirects import ClaudeClient, is_allowed, is_loopback
from realoem_mcp.config import CLAUDE_CALLBACK

ALLOWLIST = (CLAUDE_CALLBACK,)


@pytest.mark.parametrize(
    "uri",
    [
        CLAUDE_CALLBACK,
        "http://localhost:33418/callback",
        "http://127.0.0.1:8765/oauth/callback?x=1",
        "http://localhost/callback",
    ],
)
def test_claude_and_loopback_redirects_are_allowed(uri: str) -> None:
    assert is_allowed(uri, ALLOWLIST)


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback/",  # not the exact string
        "https://evil.example/callback",
        "http://localhost.evil.com/callback",
        "http://localhost@evil.com/callback",
        "http://user@localhost/callback",
        "http://127.0.0.1.nip.io/callback",
        "http://localhost:3000/callback#fragment",
        "https://localhost:3000/callback",  # loopback means plain http
        "http://[::1]:3000/callback",
        "http://localhost:99999/callback",  # a port that cannot exist
        "http://localhost:3000/" + "x" * 491,  # 513 characters
    ],
)
def test_everything_else_is_refused(uri: str) -> None:
    assert not is_allowed(uri, ALLOWLIST)


def test_the_length_limit_is_512() -> None:
    base = "http://localhost:3000/"
    assert is_loopback(base + "x" * (512 - len(base)))
    assert not is_loopback(base + "x" * (513 - len(base)))


def _client(*uris: str) -> ClaudeClient:
    return ClaudeClient(client_id="c", redirect_uris=[AnyUrl(uri) for uri in uris])


def test_a_loopback_redirect_matches_on_any_port() -> None:
    client = _client("http://localhost:3000/callback")
    requested = AnyUrl("http://localhost:41234/callback")
    assert client.validate_redirect_uri(requested) == requested  # keeps the requested port
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://localhost:41234/other"))
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://127.0.0.1:41234/callback"))  # another host
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://localhost:41234/callback?x=1"))  # query


def test_a_loopback_redirect_without_a_path_matches_too() -> None:
    # Registered as the client sent it (the SDK keeps the empty path); requested with "/".
    client = ClaudeClient.model_validate(
        {"client_id": "c", "redirect_uris": ["http://127.0.0.1:33418"]}
    )
    requested = AnyUrl("http://127.0.0.1:40000")
    assert client.validate_redirect_uri(requested) == requested


def test_other_redirects_must_match_exactly() -> None:
    client = _client(CLAUDE_CALLBACK)
    assert client.validate_redirect_uri(AnyUrl(CLAUDE_CALLBACK)) == AnyUrl(CLAUDE_CALLBACK)
    assert client.validate_redirect_uri(None) == AnyUrl(CLAUDE_CALLBACK)  # the only one
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://claude.ai/api/mcp/other"))
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_redirects.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth.redirects'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/auth/redirects.py`:

````python
"""Which redirect URIs a client may use (hosted design 4.3). A security invariant.

The SDK redirects some /authorize errors to the registered URI before anyone signs in. That is
safe only because registration admits nothing but Claude's own callback (an exact string) and
programs on the user's computer (http://localhost or http://127.0.0.1, any port).
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl

from realoem_mcp.config import LOOPBACK_HOSTS

MAX_LOOPBACK_URI = 512


def is_loopback(uri: str) -> bool:
    """http://localhost or http://127.0.0.1, any port, no user info, no fragment, short."""
    if len(uri) > MAX_LOOPBACK_URI or "#" in uri:
        return False
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    return parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS and "@" not in parts.netloc


def is_allowed(uri: str, allowlist: Iterable[str]) -> bool:
    return uri in tuple(allowlist) or is_loopback(uri)


def _same_but_port(registered: str, requested: str) -> bool:
    a, b = urlsplit(registered), urlsplit(requested)
    # An empty path is "/": the SDK keeps a registered "http://127.0.0.1:33418" as it is, but
    # turns the same URI in an /authorize request into "http://127.0.0.1:33418/".
    return (a.scheme, a.hostname, a.path or "/", a.query) == (
        b.scheme,
        b.hostname,
        b.path or "/",
        b.query,
    )


class ClaudeClient(OAuthClientInformationFull):
    """A registered client. A loopback redirect URI matches on everything but the port (a local
    program listens on whatever port is free); every other URI must match exactly."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and is_loopback(str(redirect_uri)):
            for registered in self.redirect_uris or []:
                if is_loopback(str(registered)) and _same_but_port(
                    str(registered), str(redirect_uri)
                ):
                    return redirect_uri  # with its port, so /token's equality check passes
            raise InvalidRedirectUriError(
                f"Redirect URI '{redirect_uri}' not registered for client"
            )
        return super().validate_redirect_uri(redirect_uri)
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_redirects.py`
Expected: `19 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1145 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/redirects.py server/tests/unit/test_auth_redirects.py
git commit -m "feat(auth): redirect allow-list for Claude's callback and loopback programs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 7: GitHub sign-in

`GitHubLogin` is a protocol with the real client here and a fake in the tests (hosted design 4.5).
The real one builds the authorization URL (no scope: the public profile is all the server reads;
PKCE S256), exchanges the code for a token at GitHub, reads `id`, `login` and `created_at` from
`/user`, and drops the GitHub token. Any failure, including GitHub refusing the code, becomes
`GitHubUnavailable`, which the provider turns into an error page. The test uses
`httpx.MockTransport`: nothing reaches GitHub.

**Files:**
- Create: `server/src/realoem_mcp/auth/github.py`
- Test: `server/tests/unit/test_auth_github.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_github.py`:

````python
"""GitHubOAuthApp against a mock GitHub (hosted design 4.5; never the real one)."""

from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from realoem_mcp.auth.github import (
    TOKEN_URL,
    USER_URL,
    GitHubOAuthApp,
    GitHubUnavailable,
    GitHubUser,
)
from tests.hosted_config import query_of

pytestmark = pytest.mark.anyio

CALLBACK = "https://realoem-searcher.fly.dev/oauth/github/callback"
PROFILE = {"id": 583231, "login": "octocat", "created_at": "2011-01-25T18:44:36Z"}


def _github(handler: Callable[[httpx.Request], httpx.Response]) -> GitHubOAuthApp:
    return GitHubOAuthApp(
        "client-id", "client-secret", CALLBACK, transport=httpx.MockTransport(handler)
    )


def test_the_authorization_url_asks_for_the_public_profile_only() -> None:
    url = _github(lambda request: httpx.Response(500)).authorization_url(
        state="s1", code_challenge="c1"
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert query_of(url) == {
        "client_id": "client-id",
        "redirect_uri": CALLBACK,
        "state": "s1",
        "code_challenge": "c1",
        "code_challenge_method": "S256",
        "allow_signup": "true",
    }  # no scope


async def test_fetch_user_exchanges_the_code_then_reads_the_profile() -> None:
    seen: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "gho_temp", "token_type": "bearer"})
        return httpx.Response(200, json=PROFILE)

    app = _github(github)
    try:
        user = await app.fetch_user(code="the-code", code_verifier="the-verifier")
    finally:
        await app.aclose()
    assert user == GitHubUser(583231, "octocat", datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC))
    exchange, profile = seen
    form = {key: values[0] for key, values in parse_qs(exchange.content.decode()).items()}
    assert form == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code": "the-code",
        "redirect_uri": CALLBACK,
        "code_verifier": "the-verifier",
    }
    assert exchange.headers["accept"] == "application/json"
    assert str(profile.url) == USER_URL
    assert profile.headers["authorization"] == "Bearer gho_temp"


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"error": "bad_verification_code"}),
        httpx.Response(502),
        httpx.Response(200, text="<html>not json</html>"),
    ],
    ids=["refused-code", "server-error", "not-json"],
)
async def test_a_failed_exchange_is_reported_as_unavailable(answer: httpx.Response) -> None:
    seen: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    app = _github(github)
    try:
        with pytest.raises(GitHubUnavailable):
            await app.fetch_user(code="c", code_verifier="v")
    finally:
        await app.aclose()
    assert [str(request.url) for request in seen] == [TOKEN_URL]  # /user is never called


async def test_an_unreachable_github_or_an_odd_profile_is_unavailable() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    def no_id(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "gho_temp"})
        return httpx.Response(200, json={"login": "octocat"})

    for handler in (unreachable, no_id):
        app = _github(handler)
        try:
            with pytest.raises(GitHubUnavailable):
                await app.fetch_user(code="c", code_verifier="v")
        finally:
            await app.aclose()
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_github.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth.github'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/auth/github.py`:

````python
"""Sign-in with GitHub: one GitHub OAuth App, public profile only (hosted design 4.5).

The GitHub token is used for the one call that reads the user's id, login and account age, then
discarded: never stored, logged or passed on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode

import httpx

from realoem_mcp import __version__

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
TIMEOUT_S = 10.0


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    created_at: datetime | None  # when the GitHub account was created


class GitHubUnavailable(Exception):
    """GitHub could not complete the sign-in (unreachable, refused the code, odd answer)."""


class GitHubLogin(Protocol):
    def authorization_url(self, *, state: str, code_challenge: str) -> str: ...

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser: ...

    async def aclose(self) -> None: ...


class GitHubOAuthApp:
    """The real GitHubLogin."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        callback_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._callback_url = callback_url
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT_S,
            headers={"User-Agent": f"RealOEM-Searcher/{__version__}"},
        )

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        query = {
            "client_id": self._client_id,
            "redirect_uri": self._callback_url,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "allow_signup": "true",
        }  # no scope: the public profile is all this server reads
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser:
        try:
            exchange = await self._http.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": self._callback_url,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            exchange.raise_for_status()
            token = exchange.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise GitHubUnavailable(f"GitHub refused the code: {exchange.json().get('error')}")
            profile = await self._http.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            profile.raise_for_status()
            data = profile.json()
            created = data.get("created_at")
            return GitHubUser(
                id=int(data["id"]),
                login=str(data["login"]),
                created_at=datetime.fromisoformat(created) if created else None,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise GitHubUnavailable(type(error).__name__) from None

    async def aclose(self) -> None:
        await self._http.aclose()
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_github.py`
Expected: `6 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1151 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/github.py server/tests/unit/test_auth_github.py
git commit -m "feat(auth): GitHub OAuth App client for the public profile" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 5: The sign-in steps

### Task 8: Registration, consent and GitHub's return

`RealOemAuthProvider` implements the SDK's `OAuthAuthorizationServerProvider` (hosted design 4.3):
pure logic over the store, GitHub, the keys and a clock; no Starlette. This task builds the
sign-in half, Task 9 the codes and tokens. What each method does is in the spec's table; the
essentials:

- **Registration** checks every redirect URI against the allow-list, refuses more than 5 or a
  `client_name` over 200 characters, and stores only the fields it needs. Loading a client keeps
  only the URIs today's allow-list admits, so narrowing the allow-list takes effect at once.
- **`/authorize`** validates `state`, the PKCE challenge, `resource` and `scope`, stores a pending
  request (10 minutes) and sends the browser to the consent page. It never contacts GitHub.
- **Consent** moves the request forward once: Allow derives the GitHub PKCE verifier from the
  request id and a fresh state (the verifier is never stored) and starts GitHub; Deny sends
  `access_denied` back to the client. Either answer is final.
- **GitHub's return** needs the state cookie to match before it touches the request (a refused
  attempt does not use it up), then finds the request by the state's hash and advances it once,
  then signs the user in (or shows the banned or GitHub-unavailable page) and issues a one-time
  code (10 minutes).

`tests/fake_github.py` checks the PKCE pair the way GitHub does; `tests/auth_env.py` runs the
provider on a temporary database with a settable clock (its helpers for codes and tokens are used
from Task 9 on).

**Files:**
- Create: `server/src/realoem_mcp/auth/outcomes.py`, `server/src/realoem_mcp/auth/provider.py`
- Create: `server/tests/fake_github.py`, `server/tests/auth_env.py`
- Test: `server/tests/unit/test_auth_provider_sign_in.py`

- [ ] **Step 1: Write the GitHub double** `server/tests/fake_github.py`:

````python
"""A GitHubLogin double: no network, and it checks the PKCE pair like GitHub does."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from realoem_mcp.auth.github import GitHubUnavailable, GitHubUser
from realoem_mcp.auth.keys import pkce_challenge

AUTHORIZE_URL = "https://github.example/login/oauth/authorize"
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)


@dataclass
class FakeGitHub:
    """approve() ties a user to a new code for a state, as GitHub's sign-in page does; fetch_user
    accepts that code once, with the state's PKCE verifier. add_user() only builds a user."""

    users: dict[str, GitHubUser] = field(default_factory=dict)  # code -> user
    challenges: dict[str, str] = field(default_factory=dict)  # state -> code_challenge
    codes: dict[str, str] = field(default_factory=dict)  # code -> state
    available: bool = True
    exchanged: list[str] = field(default_factory=list)  # codes used, in order
    _numbers: itertools.count = field(default_factory=lambda: itertools.count(1))

    def add_user(
        self, user_id: int, login: str | None = None, created_at: datetime | None = OLD_ACCOUNT
    ) -> GitHubUser:
        return GitHubUser(id=user_id, login=login or f"user{user_id}", created_at=created_at)

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        self.challenges[state] = code_challenge
        return f"{AUTHORIZE_URL}?state={state}&code_challenge={code_challenge}"

    def approve(self, authorization_url: str, user: GitHubUser) -> str:
        """What GitHub's redirect back carries after `user` signs in: a code for the state."""
        state = parse_qs(urlsplit(authorization_url).query)["state"][0]
        code = f"code-{next(self._numbers)}"
        self.codes[code] = state
        self.users[code] = user
        return code

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser:
        self.exchanged.append(code)
        if not self.available:
            raise GitHubUnavailable("GitHub is down")
        state = self.codes.pop(code, None)  # a GitHub code works once
        if state is None or pkce_challenge(code_verifier) != self.challenges.get(state):
            raise GitHubUnavailable("bad_verification_code")
        return self.users[code]

    async def aclose(self) -> None:
        pass
````

- [ ] **Step 2: Write the provider test environment** `server/tests/auth_env.py`:

````python
"""RealOemAuthProvider on a temporary database, with a fake GitHub and a settable clock."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from realoem_mcp.auth.keys import Keys
from realoem_mcp.auth.outcomes import RedirectToClient, StartGitHub
from realoem_mcp.auth.provider import IssuedCode, RealOemAuthProvider
from realoem_mcp.auth.redirects import ClaudeClient
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import CLAUDE_CALLBACK, Settings
from tests.fake_github import FakeGitHub
from tests.hosted_config import CHALLENGE, hosted_settings, query_of

PUBLIC_URL = "https://realoem-searcher.fly.dev"
RESOURCE = f"{PUBLIC_URL}/mcp"
START = 1_800_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


@dataclass
class AuthEnv:
    provider: RealOemAuthProvider
    store: AuthStore
    github: FakeGitHub
    clock: Clock
    keys: Keys
    settings: Settings

    async def register(self, *uris: str, name: str | None = "Claude") -> ClaudeClient:
        info = OAuthClientInformationFull(
            client_id=str(uuid.uuid4()),
            client_secret="client-secret",
            redirect_uris=[AnyUrl(uri) for uri in (uris or (CLAUDE_CALLBACK,))],
            client_name=name,
            token_endpoint_auth_method="client_secret_post",
            scope="realoem",
        )
        await self.provider.register_client(info)
        client = await self.provider.get_client(info.client_id)
        assert client is not None
        return client

    def params(self, client: ClaudeClient, **overrides: object) -> AuthorizationParams:
        values: dict[str, object] = {
            "state": "client-state",
            "scopes": ["realoem"],
            "code_challenge": CHALLENGE,
            "redirect_uri": (client.redirect_uris or [])[0],
            "redirect_uri_provided_explicitly": True,
            "resource": RESOURCE,
        }
        values.update(overrides)
        return AuthorizationParams(**values)  # type: ignore[arg-type]

    async def start(self, client: ClaudeClient, **overrides: object) -> str:
        """/authorize, returning the pending request id."""
        consent_url = await self.provider.authorize(client, self.params(client, **overrides))
        return query_of(consent_url)["req"]

    async def allowed(self, client: ClaudeClient) -> tuple[str, StartGitHub]:
        request_id = await self.start(client)
        outcome = self.provider.consent(request_id, "allow")
        assert isinstance(outcome, StartGitHub)
        return request_id, outcome

    async def code_for(self, client: ClaudeClient, user_id: int = 1) -> str:
        """The authorization code the whole sign-in hands back to the client."""
        _, to_github = await self.allowed(client)
        code = self.github.approve(to_github.url, self.github.add_user(user_id))
        outcome = await self.provider.github_return(
            {"code": code, "state": to_github.state}, to_github.state
        )
        assert isinstance(outcome, RedirectToClient), outcome
        return query_of(outcome.url)["code"]

    async def loaded_code(self, client: ClaudeClient, user_id: int = 1) -> IssuedCode:
        code = await self.provider.load_authorization_code(
            client, await self.code_for(client, user_id)
        )
        assert code is not None
        return code

    async def tokens(self, client: ClaudeClient, user_id: int = 1) -> OAuthToken:
        code = await self.loaded_code(client, user_id)
        return await self.provider.exchange_authorization_code(client, code)


@contextmanager
def auth_env(tmp_path: Path) -> Iterator[AuthEnv]:
    settings = hosted_settings(tmp_path, public_url=PUBLIC_URL)
    keys = Keys(settings.secret_key_bytes)
    store = AuthStore.open(settings.auth_path)
    github = FakeGitHub()
    clock = Clock()
    provider = RealOemAuthProvider(settings, store, github, keys, clock=clock)
    try:
        yield AuthEnv(provider, store, github, clock, keys, settings)
    finally:
        store.close()
````

- [ ] **Step 3: Write the failing test** `server/tests/unit/test_auth_provider_sign_in.py`:

````python
"""RealOemAuthProvider: registration, /authorize, consent and GitHub's return (design 4.3)."""

import dataclasses
from pathlib import Path

import pytest
from mcp.server.auth.provider import AuthorizeError, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from realoem_mcp.auth.keys import pkce_challenge
from realoem_mcp.auth.outcomes import ExpiredRequest, RedirectToClient, ShowError
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.auth_env import RESOURCE, AuthEnv, auth_env
from tests.hosted_config import query_of

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(tmp_path: Path):
    with auth_env(tmp_path) as created:
        yield created


# --- registration ---------------------------------------------------------------------------


async def test_claude_and_loopback_clients_can_register(env: AuthEnv) -> None:
    claude = await env.register(CLAUDE_CALLBACK)
    local = await env.register("http://localhost:3000/callback", name="Claude Code")
    assert claude.redirect_uris == [AnyUrl(CLAUDE_CALLBACK)]
    assert local.client_name == "Claude Code"
    assert local.client_secret == "client-secret"  # kept: the SDK compares it at /token
    assert await env.provider.get_client("nobody") is None


@pytest.mark.parametrize(
    ("uris", "name", "error"),
    [
        (["https://evil.example/callback"], "x", "invalid_redirect_uri"),
        ([CLAUDE_CALLBACK, "http://localhost.evil.com/cb"], "x", "invalid_redirect_uri"),
        ([f"http://localhost:{3000 + n}/cb" for n in range(6)], "x", "invalid_redirect_uri"),
        ([CLAUDE_CALLBACK], "x" * 201, "invalid_client_metadata"),
    ],
)
async def test_other_registrations_are_refused(
    env: AuthEnv, uris: list[str], name: str, error: str
) -> None:
    info = OAuthClientInformationFull(
        client_id="bad", redirect_uris=[AnyUrl(uri) for uri in uris], client_name=name
    )
    with pytest.raises(RegistrationError) as refused:
        await env.provider.register_client(info)
    assert refused.value.error == error
    assert await env.provider.get_client("bad") is None


async def test_a_client_loses_redirects_the_allow_list_no_longer_admits(env: AuthEnv) -> None:
    claude = await env.register(CLAUDE_CALLBACK)
    env.provider._settings = dataclasses.replace(
        env.settings, redirect_allowlist=("https://claude.com/api/mcp/auth_callback",)
    )
    assert await env.provider.get_client(claude.client_id) is None


async def test_only_the_needed_metadata_is_stored(env: AuthEnv) -> None:
    info = OAuthClientInformationFull(
        client_id="c1",
        redirect_uris=[AnyUrl(CLAUDE_CALLBACK)],
        client_name="Claude",
        jwks={"keys": []},
        contacts=["someone@example.com"],
        logo_uri="https://example.com/logo.png",
    )
    await env.provider.register_client(info)
    stored = env.store.client("c1").metadata
    assert set(stored) <= {
        "client_name",
        "redirect_uris",
        "grant_types",
        "response_types",
        "token_endpoint_auth_method",
        "scope",
    }
    assert stored["client_name"] == "Claude"


# --- /authorize ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"state": "s" * 513}, "invalid_request"),
        ({"code_challenge": "too-short"}, "invalid_request"),
        ({"code_challenge": "!" * 43}, "invalid_request"),
        ({"resource": "https://x/" + "r" * 250}, "invalid_request"),
        ({"scopes": ["realoem"] * 40}, "invalid_request"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ({"resource": "https://realoem-searcher.fly.dev/other"}, "invalid_target"),
    ],
)
async def test_bad_authorization_requests_are_refused(
    env: AuthEnv, overrides: dict[str, object], error: str
) -> None:
    client = await env.register()
    with pytest.raises(AuthorizeError) as refused:
        await env.provider.authorize(client, env.params(client, **overrides))
    assert refused.value.error == error


async def test_the_resource_defaults_and_compares_as_a_url(env: AuthEnv) -> None:
    client = await env.register()
    for resource in (None, RESOURCE, "HTTPS://Realoem-Searcher.fly.dev/mcp/"):
        request_id = await env.start(client, resource=resource, scopes=None)
        pending = env.store.pending(request_id, int(env.clock.now))
        assert (pending.resource, pending.scopes) == (RESOURCE, ("realoem",))


async def test_authorize_stores_the_request_and_never_contacts_github(env: AuthEnv) -> None:
    client = await env.register()
    consent_url = await env.provider.authorize(client, env.params(client))
    assert consent_url.startswith("https://realoem-searcher.fly.dev/consent?req=")
    assert env.github.challenges == {}
    details = env.provider.describe(query_of(consent_url)["req"])
    assert (details.client_name, details.redirect_uri) == ("Claude", CLAUDE_CALLBACK)


# --- consent ---------------------------------------------------------------------------------


async def test_allow_starts_github_with_a_derived_pkce_challenge(env: AuthEnv) -> None:
    client = await env.register()
    request_id, outcome = await env.allowed(client)
    assert outcome.url.startswith("https://github.example/login/oauth/authorize")
    verifier = env.provider._verifier(request_id, outcome.state)
    assert len(verifier) == 43
    assert env.github.challenges[outcome.state] == pkce_challenge(verifier)
    assert env.provider.describe(request_id) is None  # no longer waiting for consent


async def test_deny_sends_access_denied_back_to_the_client(env: AuthEnv) -> None:
    client = await env.register()
    request_id = await env.start(client)
    outcome = env.provider.consent(request_id, "deny")
    assert isinstance(outcome, RedirectToClient)
    assert outcome.url.startswith(CLAUDE_CALLBACK)
    assert query_of(outcome.url) == {"error": "access_denied", "state": "client-state"}


async def test_a_request_is_answered_once_and_only_in_time(env: AuthEnv) -> None:
    client = await env.register()
    request_id = await env.start(client)
    env.provider.consent(request_id, "allow")
    for decision in ("allow", "deny"):
        with pytest.raises(ExpiredRequest):
            env.provider.consent(request_id, decision)
    late = await env.start(client)
    env.clock.now += 601
    with pytest.raises(ExpiredRequest):
        env.provider.consent(late, "allow")
    denied = await env.start(client)
    env.provider.consent(denied, "deny")
    for decision in ("allow", "deny"):  # a denial is final too
        with pytest.raises(ExpiredRequest):
            env.provider.consent(denied, decision)
    with pytest.raises(ExpiredRequest):
        env.provider.consent("unknown", "deny")
    with pytest.raises(ValueError):
        env.provider.consent(await env.start(client), "maybe")


# --- the GitHub callback ---------------------------------------------------------------------


async def test_the_callback_needs_the_matching_state_cookie(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert await env.provider.github_return(query, None) == ShowError("expired")
    assert await env.provider.github_return(query, "another-state") == ShowError("expired")
    assert await env.provider.github_return({"code": code}, to_github.state) == ShowError("expired")
    assert env.github.exchanged == []  # GitHub was never asked
    # The refused attempts did not use up the request: the right cookie still works.
    assert isinstance(await env.provider.github_return(query, to_github.state), RedirectToClient)


async def test_a_callback_works_once_and_never_before_consent(env: AuthEnv) -> None:
    client = await env.register()
    await env.start(client)  # waiting for consent: no GitHub state exists yet
    forged = {"code": "c", "state": "guessed"}
    assert await env.provider.github_return(forged, "guessed") == ShowError("expired")
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert isinstance(await env.provider.github_return(query, to_github.state), RedirectToClient)
    assert await env.provider.github_return(query, to_github.state) == ShowError("expired")


async def test_cancelling_at_github_sends_access_denied(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    query = {"error": "access_denied", "state": to_github.state}
    outcome = await env.provider.github_return(query, to_github.state)
    assert isinstance(outcome, RedirectToClient)
    assert query_of(outcome.url) == {"error": "access_denied", "state": "client-state"}


async def test_github_failures_show_an_error_page(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    env.github.available = False
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert await env.provider.github_return(query, to_github.state) == ShowError(
        "github_unavailable"
    )


async def test_a_wrong_pkce_verifier_is_refused_by_github(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    env.github.challenges[to_github.state] = "something-else"  # as if the verifier changed
    code = env.github.approve(to_github.url, env.github.add_user(1))
    outcome = await env.provider.github_return(
        {"code": code, "state": to_github.state}, to_github.state
    )
    assert outcome == ShowError("github_unavailable")


async def test_a_banned_user_cannot_sign_in(env: AuthEnv) -> None:
    env.store.ban("github:7", "abuse", int(env.clock.now))
    client = await env.register()
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(7))
    outcome = await env.provider.github_return(
        {"code": code, "state": to_github.state}, to_github.state
    )
    assert outcome == ShowError("banned")
    assert env.store.conn.execute("SELECT COUNT(*) FROM authorization_codes").fetchone()[0] == 0


async def test_a_sign_in_records_the_user_and_the_consent(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.code_for(client, user_id=42)
    user = env.store.user("github:42")
    assert user.github_login == "user42"
    consents = env.store.conn.execute("SELECT subject, redirect_uri FROM consents").fetchall()
    assert consents == [("github:42", CLAUDE_CALLBACK)]
    stored = env.store.code(env.keys.hash("code", code))
    assert (stored.subject, stored.resource, stored.scopes) == ("github:42", RESOURCE, ("realoem",))
    assert stored.used_at is None and stored.expires_at == int(env.clock.now) + 600
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_provider_sign_in.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth.outcomes'`.

- [ ] **Step 5: The outcomes** `server/src/realoem_mcp/auth/outcomes.py`:

````python
"""What the sign-in steps tell the pages to do next (hosted design 4.3, 4.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal["expired", "banned", "github_unavailable"]


@dataclass(frozen=True)
class StartGitHub:
    """Consent given: send the browser to GitHub, remembering state in a cookie."""

    url: str
    state: str


@dataclass(frozen=True)
class RedirectToClient:
    """Send the browser back to the client's redirect URI (with a code or an error)."""

    url: str


@dataclass(frozen=True)
class ShowError:
    """Show an error page; never a redirect."""

    kind: ErrorKind


@dataclass(frozen=True)
class ConsentDetails:
    """What the consent page shows; everything trusted stays on the server-side row."""

    request_id: str
    client_name: str | None
    redirect_uri: str
    scopes: tuple[str, ...]


class ExpiredRequest(Exception):
    """The pending sign-in is unknown, already decided, or out of time."""
````

- [ ] **Step 6: Implement the provider's sign-in half** `server/src/realoem_mcp/auth/provider.py`:

````python
"""The OAuth 2.1 authorization server behind the SDK's routes (hosted design 4.3).

Pure logic over the store, GitHub and the keys: no Starlette here (the pages own cookies and the
CSRF MAC). The SDK already enforces PKCE S256 at /token, code binding to client_id and
redirect_uri, refresh-token binding to the client, scope narrowing, 401/403 semantics and the
resource check on bearer tokens; this class adds only what the design table says.
"""

from __future__ import annotations

import hmac
import logging
import re
import time
from collections.abc import Callable, Mapping
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull

from realoem_mcp.auth.github import GitHubLogin, GitHubUnavailable
from realoem_mcp.auth.keys import Keys, b64url, new_secret, pkce_challenge
from realoem_mcp.auth.outcomes import (
    ConsentDetails,
    ExpiredRequest,
    RedirectToClient,
    ShowError,
    StartGitHub,
)
from realoem_mcp.auth.records import AWAITING_CONSENT, ClientRecord, CodeRecord, PendingRequest
from realoem_mcp.auth.redirects import ClaudeClient, is_allowed
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings

SCOPE = "realoem"
PENDING_LIFETIME = timedelta(minutes=10)
CODE_LIFETIME = timedelta(minutes=10)
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_IDLE = timedelta(days=30)  # a refresh token unused this long expires
FAMILY_LIFETIME = timedelta(days=90)  # absolute: a sign-in lasts at most this long
MAX_FAMILIES = 20  # live sign-ins per user; the oldest is revoked first
MAX_REDIRECT_URIS = 5
MAX_CLIENT_NAME = 200
MAX_STATE = 512
MAX_PARAMETER = 256  # resource and scope
KEPT_METADATA = {
    "client_name",
    "redirect_uris",
    "grant_types",
    "response_types",
    "token_endpoint_auth_method",
    "scope",
}  # every other registration field (jwks, contacts, ...) is dropped
_CODE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")

log = logging.getLogger(__name__)


def _seconds(span: timedelta) -> int:
    return int(span.total_seconds())


def _same_resource(given: str, expected: str) -> bool:
    """URL comparison: scheme and host ignore case, a trailing slash is ignored."""
    a, b = urlsplit(given), urlsplit(expected)
    return (a.scheme.lower(), a.netloc.lower(), a.path.rstrip("/"), a.query, a.fragment) == (
        b.scheme.lower(),
        b.netloc.lower(),
        b.path.rstrip("/"),
        b.query,
        b.fragment,
    )


class IssuedCode(AuthorizationCode):
    family: str


class IssuedRefreshToken(RefreshToken):
    family: str
    family_expires_at: int


class IssuedAccessToken(AccessToken):
    family: str


class RealOemAuthProvider(
    OAuthAuthorizationServerProvider[IssuedCode, IssuedRefreshToken, IssuedAccessToken]
):
    def __init__(
        self,
        settings: Settings,
        store: AuthStore,
        github: GitHubLogin,
        keys: Keys,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._store = store
        self._github = github
        self._keys = keys
        self._clock = clock
        self.resource = f"{settings.public_url}/mcp"

    def _now(self) -> int:
        return int(self._clock())

    def _verifier(self, request_id: str, state: str) -> str:
        """The PKCE verifier for GitHub, derived (never stored): 43 base64url characters."""
        return b64url(self._keys.digest("github-pkce", f"{request_id}|{state}"))

    # --- registration -------------------------------------------------------------------------

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(uri) for uri in client_info.redirect_uris or []]
        if not uris or len(uris) > MAX_REDIRECT_URIS:
            raise RegistrationError(
                "invalid_redirect_uri", f"register between 1 and {MAX_REDIRECT_URIS} redirect URIs"
            )
        for uri in uris:
            if not is_allowed(uri, self._settings.redirect_allowlist):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "only Claude's callback and http://localhost or http://127.0.0.1 redirect "
                    "URIs can be registered",
                )
        if client_info.client_name is not None and len(client_info.client_name) > MAX_CLIENT_NAME:
            raise RegistrationError("invalid_client_metadata", "client_name is too long")
        metadata = client_info.model_dump(mode="json", include=KEPT_METADATA, exclude_none=True)
        self._store.add_client(
            ClientRecord(
                client_id=client_info.client_id,
                client_secret=client_info.client_secret,
                metadata=metadata,
                created_at=self._now(),
                last_issued_at=None,
            )
        )

    async def get_client(self, client_id: str) -> ClaudeClient | None:
        """The client, with only the redirect URIs the allow-list admits today (an operator may
        have narrowed it since the client registered); None when none is left."""
        record = self._store.client(client_id)
        if record is None:
            return None
        allowed = [
            uri
            for uri in record.metadata.get("redirect_uris", [])
            if is_allowed(uri, self._settings.redirect_allowlist)
        ]
        if not allowed:
            return None
        return ClaudeClient.model_validate(
            {
                **record.metadata,
                "redirect_uris": allowed,
                "client_id": record.client_id,
                "client_secret": record.client_secret,
            }
        )

    # --- sign-in: /authorize, consent, GitHub -------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Store the request and send the browser to the consent page. Never contacts GitHub."""
        if params.state is not None and len(params.state) > MAX_STATE:
            raise AuthorizeError("invalid_request", "state is too long")
        if not _CODE_CHALLENGE.fullmatch(params.code_challenge):
            raise AuthorizeError("invalid_request", "code_challenge must be an S256 challenge")
        if params.resource is not None and len(params.resource) > MAX_PARAMETER:
            raise AuthorizeError("invalid_request", "resource is too long")
        scopes = params.scopes or [SCOPE]
        if len(" ".join(scopes)) > MAX_PARAMETER:
            raise AuthorizeError("invalid_request", "scope is too long")
        if params.resource is not None and not _same_resource(params.resource, self.resource):
            raise AuthorizeError("invalid_target", f"this server's resource is {self.resource}")
        request = PendingRequest(
            id=new_secret(),
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_explicit=params.redirect_uri_provided_explicitly,
            client_state=params.state,
            code_challenge=params.code_challenge,
            resource=self.resource,
            scopes=tuple(scopes),
            status=AWAITING_CONSENT,
            expires_at=self._now() + _seconds(PENDING_LIFETIME),
        )
        self._store.add_pending(request)
        return f"{self._settings.public_url}/consent?{urlencode({'req': request.id})}"

    def describe(self, request_id: str) -> ConsentDetails | None:
        """What the consent page shows for a request still waiting for consent."""
        pending = self._store.pending(request_id, self._now())
        if pending is None:
            return None
        client = self._store.client(pending.client_id)
        name = client.metadata.get("client_name") if client else None
        return ConsentDetails(pending.id, name, pending.redirect_uri, pending.scopes)

    def consent(self, request_id: str, decision: str) -> StartGitHub | RedirectToClient:
        """The user's answer on the consent page. Each request can be answered once."""
        now = self._now()
        if decision == "allow":
            state = new_secret()
            pending = self._store.consent(request_id, self._keys.hash("github", state), now)
            if pending is None:
                raise ExpiredRequest()
            challenge = pkce_challenge(self._verifier(request_id, state))
            return StartGitHub(
                self._github.authorization_url(state=state, code_challenge=challenge), state
            )
        if decision != "deny":
            raise ValueError(f"decision must be 'allow' or 'deny', got {decision!r}")
        pending = self._store.deny(request_id, now)
        if pending is None:
            raise ExpiredRequest()
        return RedirectToClient(
            construct_redirect_uri(
                pending.redirect_uri, error="access_denied", state=pending.client_state
            )
        )

    async def github_return(
        self, query: Mapping[str, str], state_cookie: str | None
    ) -> RedirectToClient | ShowError:
        """GitHub's callback (code and state only). Errors here are pages, never redirects,
        until the state checks pass."""
        state = query.get("state") or ""
        if (
            not state
            or not state_cookie
            or not hmac.compare_digest(state.encode("utf-8"), state_cookie.encode("utf-8"))
        ):
            return ShowError("expired")
        pending = self._store.return_from_github(self._keys.hash("github", state), self._now())
        if pending is None:
            return ShowError("expired")
        if query.get("error") == "access_denied":  # the user cancelled at GitHub
            return RedirectToClient(
                construct_redirect_uri(
                    pending.redirect_uri, error="access_denied", state=pending.client_state
                )
            )
        code = query.get("code")
        if query.get("error") or not code:
            return ShowError("github_unavailable")
        try:
            user = await self._github.fetch_user(
                code=code, code_verifier=self._verifier(pending.id, state)
            )
        except GitHubUnavailable as error:
            log.warning("GitHub sign-in failed: %s", error)
            return ShowError("github_unavailable")
        subject = f"github:{user.id}"
        if self._store.is_banned(subject):
            log.info("refused the sign-in of banned %s", subject)
            return ShowError("banned")
        issued = new_secret()
        now = self._now()

        def record_sign_in() -> None:
            self._store.upsert_user(subject, user.login, user.created_at, now)
            self._store.add_consent(subject, pending.client_id, pending.redirect_uri, now)
            self._store.record_subject(pending.id, subject)
            self._store.add_code(
                CodeRecord(
                    hash=self._keys.hash("code", issued),
                    family=new_secret(),
                    client_id=pending.client_id,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_explicit=pending.redirect_uri_explicit,
                    code_challenge=pending.code_challenge,
                    resource=pending.resource,
                    scopes=pending.scopes,
                    subject=subject,
                    expires_at=now + _seconds(CODE_LIFETIME),
                    used_at=None,
                )
            )
            self._store.touch_client(pending.client_id, now)

        self._store.atomic(record_sign_in)
        log.info("signed in %s", subject)
        return RedirectToClient(
            construct_redirect_uri(pending.redirect_uri, code=issued, state=pending.client_state)
        )
````

- [ ] **Step 7: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_provider_sign_in.py`
Expected: `26 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1177 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/outcomes.py server/src/realoem_mcp/auth/provider.py server/tests/fake_github.py server/tests/auth_env.py server/tests/unit/test_auth_provider_sign_in.py
git commit -m "feat(auth): OAuth provider registration, consent before GitHub, GitHub sign-in" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 6: Tokens, pages, rate limits and VIN-free logs

### Task 9: Codes and tokens

The provider's second half (hosted design 4.3, H6). A code works once: `exchange` marks it used in
the same transaction that creates the token family, and loading a used or expired code revokes
what it issued (OAuth 2.1 section 4.1.3). Access tokens live an hour; refresh tokens rotate on
every use, and a rotated refresh token presented again revokes its whole family and logs
`refresh_reuse github:<id>` once per incident (a token of a family already revoked, by a ban or
`/revoke`, is refused silently, so the log line stays a clean signal); two concurrent refreshes
therefore end the sign-in (spec section 10 keeps open whether hosted Claude ever does that).
Refresh tokens expire after 30 unused days, and a sign-in ends 90 days after it began. A user
keeps at most 20 sign-ins, the oldest revoked first. Tokens are looked up by the hash of their own
kind, so a refresh token or a code never passes as an access token, and every lookup reads the
database: bans and revocations apply at the next request.

**Files:**
- Modify: `server/src/realoem_mcp/auth/provider.py`
- Test: `server/tests/unit/test_auth_provider_tokens.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_provider_tokens.py`:

````python
"""RealOemAuthProvider: authorization codes, access and refresh tokens (design 4.3)."""

import asyncio
import logging
from pathlib import Path

import pytest
from mcp.server.auth.provider import TokenError

from realoem_mcp.auth.provider import MAX_FAMILIES
from tests.auth_env import RESOURCE, AuthEnv, auth_env

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(tmp_path: Path):
    with auth_env(tmp_path) as created:
        yield created


# --- codes -----------------------------------------------------------------------------------


async def test_a_code_works_once_and_a_replay_revokes_its_tokens(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.loaded_code(client)
    tokens = await env.provider.exchange_authorization_code(client, code)
    assert await env.provider.load_access_token(tokens.access_token) is not None
    with pytest.raises(TokenError) as refused:
        await env.provider.exchange_authorization_code(client, code)
    assert refused.value.error == "invalid_grant"
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_loading_a_used_code_revokes_its_tokens(env: AuthEnv) -> None:
    client = await env.register()
    raw = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw)
    )
    assert await env.provider.load_authorization_code(client, raw) is None
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_two_concurrent_exchanges_of_one_code_issue_one_set(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.loaded_code(client)
    results = await asyncio.gather(
        env.provider.exchange_authorization_code(client, code),
        env.provider.exchange_authorization_code(client, code),
        return_exceptions=True,
    )
    assert sorted(type(result).__name__ for result in results) == ["OAuthToken", "TokenError"]


async def test_an_expired_code_is_refused(env: AuthEnv) -> None:
    client = await env.register()
    raw = await env.code_for(client)
    env.clock.now += 601
    assert await env.provider.load_authorization_code(client, raw) is None


# --- tokens ----------------------------------------------------------------------------------


async def test_access_tokens_carry_the_user_and_expire_after_an_hour(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client, user_id=5)
    assert (tokens.token_type, tokens.expires_in, tokens.scope) == ("Bearer", 3600, "realoem")
    access = await env.provider.load_access_token(tokens.access_token)
    assert (access.subject, access.resource, access.client_id) == (
        "github:5",
        RESOURCE,
        client.client_id,
    )
    env.clock.now += 3600
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_a_token_of_one_kind_never_passes_as_another(env: AuthEnv) -> None:
    client = await env.register()
    raw_code = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw_code)
    )
    assert await env.provider.load_access_token(tokens.refresh_token) is None
    assert await env.provider.load_access_token(raw_code) is None
    assert await env.provider.load_refresh_token(client, tokens.access_token) is None


async def test_refreshing_rotates_and_a_reused_refresh_token_revokes_the_family(
    env: AuthEnv, caplog: pytest.LogCaptureFixture
) -> None:
    client = await env.register()
    first = await env.tokens(client, user_id=3)
    refresh = await env.provider.load_refresh_token(client, first.refresh_token)
    second = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    assert second.refresh_token != first.refresh_token
    assert await env.provider.load_access_token(second.access_token) is not None
    with caplog.at_level(logging.WARNING, logger="realoem_mcp.auth.provider"):
        assert await env.provider.load_refresh_token(client, first.refresh_token) is None
    assert "refresh_reuse github:3" in caplog.text
    assert await env.provider.load_access_token(second.access_token) is None  # all revoked
    assert await env.provider.load_refresh_token(client, second.refresh_token) is None


async def test_two_concurrent_refreshes_revoke_the_family(env: AuthEnv) -> None:
    client = await env.register()
    first = await env.tokens(client)
    refresh = await env.provider.load_refresh_token(client, first.refresh_token)
    results = await asyncio.gather(
        env.provider.exchange_refresh_token(client, refresh, ["realoem"]),
        env.provider.exchange_refresh_token(client, refresh, ["realoem"]),
        return_exceptions=True,
    )
    winner = next(result for result in results if not isinstance(result, Exception))
    assert any(isinstance(result, TokenError) for result in results)
    assert await env.provider.load_access_token(winner.access_token) is None


async def test_revoking_a_token_revokes_its_whole_family(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    access = await env.provider.load_access_token(tokens.access_token)
    await env.provider.revoke_token(access)
    assert await env.provider.load_access_token(tokens.access_token) is None
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_ban_takes_effect_on_the_next_request(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client, user_id=9)
    env.store.conn.execute(
        "UPDATE users SET banned_at = 1 WHERE subject = 'github:9'"
    )  # banned without revoking: tokens are still refused
    assert await env.provider.load_access_token(tokens.access_token) is None
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_user_keeps_at_most_twenty_sign_ins(env: AuthEnv) -> None:
    client = await env.register()
    first = await env.tokens(client, user_id=4)
    for _ in range(MAX_FAMILIES - 1):
        env.clock.now += 1
        await env.tokens(client, user_id=4)
    assert await env.provider.load_access_token(first.access_token) is not None
    env.clock.now += 1
    await env.tokens(client, user_id=4)  # the 21st revokes the oldest
    assert await env.provider.load_access_token(first.access_token) is None
    assert len(env.store.active_families("github:4", int(env.clock.now))) == MAX_FAMILIES


async def test_the_database_holds_only_hashes(env: AuthEnv) -> None:
    client = await env.register()
    raw_code = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw_code)
    )
    dump = "\n".join(env.store.conn.iterdump())
    for secret in (raw_code, tokens.access_token, tokens.refresh_token):
        assert secret not in dump


async def test_an_unused_refresh_token_expires_after_30_days(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    env.clock.now += 30 * 86_400
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_sign_in_ends_90_days_after_it_began(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    for _ in range(3):  # refreshed every 29 days: 87 days so far
        env.clock.now += 29 * 86_400
        refresh = await env.provider.load_refresh_token(client, tokens.refresh_token)
        assert refresh is not None
        tokens = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    env.clock.now += 3 * 86_400 - 1_800  # half an hour before day 90: one last refresh
    refresh = await env.provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None
    tokens = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    env.clock.now += 1_800  # day 90, while the new access token's hour has not run out
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None
    assert await env.provider.load_access_token(tokens.access_token) is None
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_provider_tokens.py`
Expected: FAIL: the provider cannot load codes or issue tokens yet (the protocol's empty methods return `None`).

- [ ] **Step 3: Implement.** In `server/src/realoem_mcp/auth/provider.py`:

Edit 1. Find:

````python
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull

from realoem_mcp.auth.github import GitHubLogin, GitHubUnavailable
from realoem_mcp.auth.keys import Keys, b64url, new_secret, pkce_challenge
````

Replace with:

````python
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from realoem_mcp.auth.github import GitHubLogin, GitHubUnavailable
from realoem_mcp.auth.keys import Keys, b64url, new_secret, pkce_challenge
````

Edit 2. Find:

````python
        return RedirectToClient(
            construct_redirect_uri(pending.redirect_uri, code=issued, state=pending.client_state)
        )
````

Replace with:

````python
        return RedirectToClient(
            construct_redirect_uri(pending.redirect_uri, code=issued, state=pending.client_state)
        )

    # --- codes and tokens ---------------------------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> IssuedCode | None:
        record = self._store.code(self._keys.hash("code", authorization_code))
        if record is None:
            return None
        if record.used_at is not None or record.expires_at <= self._now():
            # OAuth 2.1 section 4.1.3: a replayed code revokes the tokens issued from it.
            self._store.revoke_family(record.family)
            return None
        return IssuedCode(
            code=authorization_code,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            client_id=record.client_id,
            code_challenge=record.code_challenge,
            redirect_uri=AnyUrl(record.redirect_uri),
            redirect_uri_provided_explicitly=record.redirect_uri_explicit,
            resource=record.resource,
            subject=record.subject,
            family=record.family,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: IssuedCode
    ) -> OAuthToken:
        now = self._now()
        subject = authorization_code.subject or ""
        family = authorization_code.family

        def exchange() -> OAuthToken | None:
            if not self._store.use_code(self._keys.hash("code", authorization_code.code), now):
                return None  # the other of two concurrent exchanges won
            live = self._store.active_families(subject, now)
            for oldest in live[: max(0, len(live) - MAX_FAMILIES + 1)]:
                self._store.revoke_family(oldest)
            expires_at = now + _seconds(FAMILY_LIFETIME)
            self._store.add_family(family, subject, client.client_id, now, expires_at)
            return self._issue(
                family,
                subject,
                client.client_id,
                authorization_code.scopes,
                authorization_code.resource or self.resource,
                now,
                expires_at,
            )

        tokens = self._store.atomic(exchange)
        if tokens is None:
            self._store.revoke_family(family)
            raise TokenError("invalid_grant", "authorization code was already used")
        return tokens

    def _issue(
        self,
        family: str,
        subject: str,
        client_id: str,
        scopes: list[str],
        resource: str,
        now: int,
        family_expires_at: int,
    ) -> OAuthToken:
        access, refresh = new_secret(), new_secret()
        access_expires = now + _seconds(ACCESS_LIFETIME)
        refresh_expires = min(now + _seconds(REFRESH_IDLE), family_expires_at)
        for value, kind, expires_at in (
            (access, "access", access_expires),
            (refresh, "refresh", refresh_expires),
        ):
            self._store.add_token(
                self._keys.hash(kind, value),
                kind,
                family,
                subject,
                client_id,
                scopes,
                resource,
                expires_at,
            )
        self._store.touch_client(client_id, now)
        return OAuthToken(
            access_token=access,
            expires_in=_seconds(ACCESS_LIFETIME),
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> IssuedAccessToken | None:
        """Only an unexpired, unrevoked access token of a user who is not banned. Read from the
        database on every request: no cached tokens or bans."""
        record = self._store.token(self._keys.hash("access", token), "access")
        now = self._now()
        if (
            record is None
            or record.family_revoked
            or record.banned
            or record.expires_at <= now
            or record.family_expires_at <= now
        ):
            return None
        return IssuedAccessToken(
            token=token,
            client_id=record.client_id,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            resource=record.resource,
            subject=record.subject,
            family=record.family,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> IssuedRefreshToken | None:
        record = self._store.token(self._keys.hash("refresh", refresh_token), "refresh")
        if record is None:
            return None
        if record.rotated_at is not None:  # a refresh token used twice: someone has a copy
            if not record.family_revoked:
                self._store.revoke_family(record.family)
                log.warning("refresh_reuse %s", record.subject)
            return None
        now = self._now()
        if (
            record.family_revoked
            or record.banned
            or record.expires_at <= now
            or record.family_expires_at <= now
        ):
            return None
        return IssuedRefreshToken(
            token=refresh_token,
            client_id=record.client_id,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            resource=record.resource,
            subject=record.subject,
            family=record.family,
            family_expires_at=record.family_expires_at,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: IssuedRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        now = self._now()

        def rotate() -> OAuthToken | None:
            if not self._store.rotate(self._keys.hash("refresh", refresh_token.token), now):
                return None  # the other of two concurrent refreshes won
            return self._issue(
                refresh_token.family,
                refresh_token.subject or "",
                client.client_id,
                scopes,
                refresh_token.resource or self.resource,
                now,
                refresh_token.family_expires_at,
            )

        tokens = self._store.atomic(rotate)
        if tokens is None:
            self._store.revoke_family(refresh_token.family)
            log.warning("refresh_reuse %s", refresh_token.subject)
            raise TokenError("invalid_grant", "refresh token was already used")
        return tokens

    async def revoke_token(self, token: IssuedAccessToken | IssuedRefreshToken) -> None:
        """Revokes the token and every token issued with it (its whole family)."""
        self._store.revoke_family(token.family)
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_provider_sign_in.py tests/unit/test_auth_provider_tokens.py`
Expected: `40 passed` (14 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1191 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/provider.py server/tests/unit/test_auth_provider_tokens.py
git commit -m "feat(auth): one-time codes, rotating refresh tokens and token families" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 10: The consent and error pages

Plain HTML, no scripts, every value escaped (hosted design 4.6). The consent page names the
requester by where the answer goes, never by a name the client chose: Claude's callback is
"Claude (claude.ai)"; a loopback redirect is "A program on this computer" plus its self-asserted
name, cleaned of control and bidirectional-override characters, cut to 64 characters and escaped.
It always shows the full redirect URI and what is granted. Error pages never echo the request.

**Files:**
- Create: `server/src/realoem_mcp/auth/html.py`
- Test: `server/tests/unit/test_auth_html.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_auth_html.py`:

````python
"""The consent and error pages (hosted design 4.6)."""

from realoem_mcp.auth.html import (
    CONTINUE_ONLY,
    GRANTED,
    consent_page,
    error_page,
    requester,
    shown_name,
)
from realoem_mcp.auth.outcomes import ConsentDetails
from realoem_mcp.config import CLAUDE_CALLBACK

ALLOWLIST = (CLAUDE_CALLBACK, "https://claude.com/api/mcp/auth_callback")


def _details(redirect_uri: str, name: str | None = "Claude") -> ConsentDetails:
    return ConsentDetails("req-1", name, redirect_uri, ("realoem",))


def test_client_names_are_cleaned_shortened_and_escaped() -> None:
    assert shown_name("<b>Evil</b>") == "&lt;b&gt;Evil&lt;/b&gt;"
    assert shown_name("Claude\u202eedoC\x07") == "ClaudeedoC"  # bidi override and BEL removed
    assert shown_name("x" * 100) == "x" * 64
    assert shown_name(None) == ""


def test_the_requester_is_named_by_where_the_answer_goes() -> None:
    assert requester(_details(CLAUDE_CALLBACK, "Totally Not Claude"), ALLOWLIST) == (
        "Claude (claude.ai)"
    )
    assert requester(_details("https://claude.com/api/mcp/auth_callback"), ALLOWLIST) == (
        "Claude (claude.com)"
    )
    local = requester(_details("http://localhost:3000/cb", "<i>Claude Code</i>"), ALLOWLIST)
    assert local == (
        "A program on this computer (<code>http://localhost:3000/cb</code>) that calls itself "
        "&#8216;&lt;i&gt;Claude Code&lt;/i&gt;&#8217;"
    )


def test_the_consent_page_says_what_is_granted_and_where_it_goes() -> None:
    page = consent_page(
        _details("http://localhost:3000/cb?x=<1>"), csrf="mac", expires_at=123, allowlist=ALLOWLIST
    )
    assert CONTINUE_ONLY in page and GRANTED in page
    assert "http://localhost:3000/cb?x=&lt;1&gt;" in page  # the full redirect URI, escaped
    for hidden in ('name="req" value="req-1"', 'name="exp" value="123"', 'name="csrf" value="mac"'):
        assert hidden in page
    assert 'value="allow">Allow</button>' in page and 'value="deny">Deny</button>' in page
    assert "<script" not in page


def test_error_pages_have_a_status_and_no_echo() -> None:
    assert error_page("expired")[0] == 400
    assert "Start again from Claude" in error_page("expired")[1]
    status, page = error_page("banned")
    assert status == 403 and "suspended" in page and "/issues" in page
    assert error_page("github_unavailable")[0] == 503
    status, page = error_page("busy")
    assert status == 503 and "busy" in page
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_html.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.auth.html'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/auth/html.py`:

````python
"""The sign-in pages: plain HTML, no scripts, every value escaped (hosted design 4.6)."""

from __future__ import annotations

import html
import unicodedata
from collections.abc import Iterable
from urllib.parse import urlsplit

from realoem_mcp.auth.outcomes import ConsentDetails
from realoem_mcp.auth.redirects import is_loopback
from realoem_mcp.config import CLAUDE_CALLBACK, REPO_URL

MAX_SHOWN_NAME = 64
CONTINUE_ONLY = "Continue only if you just connected RealOEM Searcher in Claude."
GRANTED = (
    "RealOEM Searcher tools, counted against your daily quota; reads only the id, username and "
    "creation date of your public GitHub profile"
)
ERRORS = {  # kind -> (status, message)
    "expired": (400, "This sign-in request has expired. Start again from Claude."),
    "banned": (403, "Access to RealOEM Searcher is suspended."),
    "github_unavailable": (503, "GitHub sign-in is unavailable right now; try again shortly."),
    "busy": (503, "RealOEM Searcher is busy; try again in a minute."),
}
_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;"
    "line-height:1.5}code{word-break:break-all}button{font-size:1rem;padding:.5rem 1.25rem;"
    "margin-right:.5rem}"
)


def shown_name(name: str | None) -> str:
    """A self-asserted client name made safe to show: no control or bidi-override characters,
    at most 64 characters, HTML-escaped."""
    if not name:
        return ""
    kept = "".join(char for char in name if unicodedata.category(char) not in ("Cc", "Cf"))
    return html.escape(kept[:MAX_SHOWN_NAME], quote=True)


def requester(details: ConsentDetails, allowlist: Iterable[str]) -> str:
    """Who is asking, named by where the answer goes, never by the name the client chose."""
    uri = details.redirect_uri
    if uri == CLAUDE_CALLBACK:
        return "Claude (claude.ai)"
    if is_loopback(uri):
        name = shown_name(details.client_name)
        calls_itself = f" that calls itself &#8216;{name}&#8217;" if name else ""
        return f"A program on this computer (<code>{html.escape(uri)}</code>){calls_itself}"
    if uri in tuple(allowlist):
        return f"Claude ({html.escape(urlsplit(uri).hostname or uri)})"
    return html.escape(uri)  # registration admits nothing else; shown plainly if it ever did


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def consent_page(
    details: ConsentDetails, *, csrf: str, expires_at: int, allowlist: Iterable[str]
) -> str:
    fields = {"req": details.request_id, "exp": str(expires_at), "csrf": csrf}
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(value, quote=True)}">'
        for name, value in fields.items()
    )
    return _page(
        "Connect RealOEM Searcher",
        "<h1>Connect RealOEM Searcher?</h1>"
        f"<p><strong>{requester(details, allowlist)}</strong> wants to use RealOEM Searcher "
        "with your GitHub account.</p>"
        f"<p>{CONTINUE_ONLY}</p>"
        f"<p>It gets: {GRANTED}.</p>"
        f"<p>You will be sent back to <code>{html.escape(details.redirect_uri)}</code>.</p>"
        f'<form method="post" action="/consent">{hidden}'
        '<button type="submit" name="decision" value="allow">Allow</button>'
        '<button type="submit" name="decision" value="deny">Deny</button></form>',
    )


def error_page(kind: str) -> tuple[int, str]:
    """(status, HTML) for an error kind. No stack traces and no echo of the request."""
    status, message = ERRORS[kind]
    contact = (
        f'<p>If you think this is a mistake, <a href="{REPO_URL}/issues">open an issue</a>.</p>'
        if kind == "banned"
        else ""
    )
    return status, _page("RealOEM Searcher", f"<h1>RealOEM Searcher</h1><p>{message}</p>{contact}")
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_auth_html.py`
Expected: `4 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1195 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/html.py server/tests/unit/test_auth_html.py
git commit -m "feat(auth): consent and error pages" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 11: The rate limiter

`SlidingWindow` allows at most `limit` events per window for each key, kept in memory (one server
process). A refusal records nothing, so a client that keeps knocking is not punished further, and
keys with no recent events are forgotten (when looked up, and in a periodic sweep) so many
addresses cannot grow memory without bound.

**Files:**
- Create: `server/src/realoem_mcp/rate_limit.py`
- Test: `server/tests/unit/test_rate_limit.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_rate_limit.py`:

````python
"""SlidingWindow (hosted design 4.9)."""

from realoem_mcp.rate_limit import SWEEP_EVERY, SlidingWindow


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_allows_the_limit_then_says_when_to_retry() -> None:
    clock = Clock()
    window = SlidingWindow(2, 60.0, clock=clock)
    for _ in range(2):
        assert window.retry_after("a") is None
        window.record("a")
        clock.now += 10
    assert window.retry_after("a") == 40.0  # the first event leaves the window in 40 s
    assert window.retry_after("b") is None  # other keys are counted separately
    clock.now += 40
    assert window.retry_after("a") is None


def test_a_refusal_records_nothing() -> None:
    clock = Clock()
    window = SlidingWindow(1, 60.0, clock=clock)
    window.record("a")
    for _ in range(5):
        assert window.retry_after("a") is not None
    clock.now += 60
    assert window.retry_after("a") is None


def test_idle_keys_are_forgotten() -> None:
    clock = Clock()
    window = SlidingWindow(5, 60.0, clock=clock)
    window.record("old")
    clock.now += 61
    for i in range(SWEEP_EVERY):
        window.record(f"new{i % 3}")
    assert "old" not in window._events


def test_a_key_emptied_by_a_lookup_is_forgotten_and_never_breaks_the_sweep() -> None:
    clock = Clock()
    window = SlidingWindow(5, 60.0, clock=clock)
    window.record("a")
    clock.now += 61
    assert window.retry_after("a") is None  # its only event left the window
    for i in range(SWEEP_EVERY):  # the sweep runs once in here
        window.record(f"other{i % 3}")
    assert "a" not in window._events
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_rate_limit.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.rate_limit'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/rate_limit.py`:

````python
"""Sliding-window rate limits, kept in memory (one server process; hosted design 4.9)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

SWEEP_EVERY = 1_000  # records between sweeps of idle keys


class SlidingWindow:
    """At most `limit` events per `window_s` seconds for each key."""

    def __init__(
        self, limit: int, window_s: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._records = 0

    def retry_after(self, key: str) -> float | None:
        """None when one more event is allowed now; else seconds until one is. Records nothing."""
        now = self._clock()
        events = self._events.get(key)
        if events is None:
            return None
        while events and events[0] <= now - self._window_s:
            events.popleft()
        if not events:
            del self._events[key]  # nothing recent: forget the key
            return None
        if len(events) < self._limit:
            return None
        return events[0] + self._window_s - now

    def record(self, key: str) -> None:
        now = self._clock()
        self._events.setdefault(key, deque()).append(now)
        self._records += 1
        if self._records % SWEEP_EVERY == 0:  # forget keys with no recent events
            cutoff = now - self._window_s
            for idle in [
                k for k, events in self._events.items() if not events or events[-1] <= cutoff
            ]:
                del self._events[idle]
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_rate_limit.py`
Expected: `4 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1199 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/rate_limit.py server/tests/unit/test_rate_limit.py
git commit -m "feat(hosted): sliding-window rate limiter" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 12: VIN-free logs

Plan 1a's client masks the URLs it logs itself. Two other log lines can still carry a VIN: the MCP
SDK logs every failed tool call at INFO with the error text (which can quote the user's input or
a VIN URL), and `httpx` logs every request URL at INFO. `VinFilter` covers every log line: `vin=`
query values are masked anywhere, tracebacks included, and the SDK's line for a failed
`decode_vin` keeps only the tool name. It never raises: a malformed log call still reaches
logging's own error report, which prints the raw message and arguments, so those are masked
instead. It also masks a traceback another handler formatted first. The entry point (Task 13)
installs it on the root logger's handlers and keeps `httpx` at WARNING, as the stdio server does.

**Files:**
- Create: `server/src/realoem_mcp/log_privacy.py`
- Test: `server/tests/unit/test_log_privacy.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_log_privacy.py`:

````python
"""The VIN log filter (hosted design 4.9)."""

import logging

import pytest

from realoem_mcp.log_privacy import WITHHELD, VinFilter, install_vin_filter, mask_vins


def _record(name: str, msg: str, *args: object, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, exc_info)


def _formatted(record: logging.LogRecord) -> str:
    assert VinFilter().filter(record) is True  # the filter changes records, never drops them
    return logging.Formatter("%(message)s").format(record)


def test_vin_query_values_are_masked() -> None:
    assert (
        mask_vins("GET https://www.realoem.com/bmw/enUS/select?vin=PX22770&x=1 failed")
        == "GET https://www.realoem.com/bmw/enUS/select?vin=***&x=1 failed"
    )
    assert mask_vins("production?VIN=WBA12345678901234'") == "production?VIN=***'"
    assert mask_vins("no vins here") == "no vins here"


def test_any_logger_s_vin_urls_are_masked() -> None:
    record = _record("httpx", "HTTP Request: GET %s", "https://x/select?vin=PX22770")
    assert _formatted(record) == "HTTP Request: GET https://x/select?vin=***"


def test_a_failed_decode_vin_keeps_only_the_tool_name() -> None:
    sdk = "mcp.server.mcpserver.server"
    failed = _record(sdk, "Tool %r failed: %r", "decode_vin", "'PX2277' is not a VIN")
    assert _formatted(failed) == f"Tool 'decode_vin' failed: '{WITHHELD}'"
    other = _record(sdk, "Tool %r failed: %r", "lookup_part", "no such part 123")
    assert _formatted(other) == "Tool 'lookup_part' failed: 'no such part 123'"


def test_tracebacks_are_masked_too() -> None:
    try:
        raise RuntimeError("fetching https://x/production?vin=PX22770 broke")
    except RuntimeError:
        import sys

        record = _record("realoem_mcp", "boom", exc_info=sys.exc_info())
    text = _formatted(record)
    assert "PX22770" not in text and "production?vin=***" in text


def test_a_traceback_formatted_earlier_is_masked_too() -> None:
    record = _record("realoem_mcp", "boom")
    record.exc_text = "Traceback ...\nRuntimeError: https://x/select?vin=PX22770"
    assert "PX22770" not in _formatted(record)


def test_a_malformed_log_call_still_passes_the_filter() -> None:
    record = _record("realoem_mcp", "fetch %s %s for vin=PX22770", "https://x/select?vin=PX22770")
    assert VinFilter().filter(record) is True  # logging itself reports the bad call later
    # ... printing the raw message and arguments, so those are masked too
    assert record.msg == "fetch %s %s for vin=***"
    assert record.args == ("https://x/select?vin=***",)


def test_install_adds_the_filter_to_every_root_handler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test_log_privacy")
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    try:
        install_vin_filter(logger)
        assert any(isinstance(f, VinFilter) for f in handler.filters)
    finally:
        logger.removeHandler(handler)
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_log_privacy.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'realoem_mcp.log_privacy'`.

- [ ] **Step 3: Implement** `server/src/realoem_mcp/log_privacy.py`:

````python
"""Keeps VINs out of the hosted server's logs (hosted design 4.9).

The client masks the URLs it logs itself; this filter covers every other log line: vin= query
values are masked anywhere (tracebacks included), and the MCP SDK's line for a failed decode_vin
call loses its message, which can quote the user's input.
"""

from __future__ import annotations

import contextlib
import logging
import re

SDK_TOOL_LOGGER = "mcp.server.mcpserver.server"
SDK_TOOL_FAILED = "Tool %r failed: %r"
VIN_TOOLS = frozenset({"decode_vin"})
WITHHELD = "<withheld: it may contain a VIN>"
_VIN_VALUE = re.compile(r"(?i)\b(vin=)[^&#\s'\"]+")


def mask_vins(text: str) -> str:
    return _VIN_VALUE.sub(r"\1***", text)


class VinFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # A malformed log call must still reach logging's own error report, never raise here.
        with contextlib.suppress(Exception):
            self._mask(record)
        return True

    @staticmethod
    def _mask(record: logging.LogRecord) -> None:
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:  # also a traceback another handler formatted first
            record.exc_text = mask_vins(record.exc_text)
        if (
            record.name == SDK_TOOL_LOGGER
            and record.msg == SDK_TOOL_FAILED
            and isinstance(record.args, tuple)
            and record.args[:1]
            and record.args[0] in VIN_TOOLS
        ):
            record.args = (record.args[0], WITHHELD)
        try:
            message = record.getMessage()
        except Exception:
            # A malformed call: logging's error report prints the raw message and arguments.
            record.msg = mask_vins(str(record.msg))
            if isinstance(record.args, tuple):
                record.args = tuple(mask_vins(str(arg)) for arg in record.args)
            return
        masked = mask_vins(message)
        if masked != message:
            record.msg, record.args = masked, ()


def install_vin_filter(logger: logging.Logger | None = None) -> None:
    """Add the filter to every handler of the root logger (where all records end up)."""
    for handler in (logger or logging.getLogger()).handlers:
        handler.addFilter(VinFilter())
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_log_privacy.py`
Expected: `7 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1206 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/log_privacy.py server/tests/unit/test_log_privacy.py
git commit -m "feat(hosted): log filter that keeps VINs out of every log line" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 7: The HTTP app

### Task 13: The HTTP app and the sign-in pages

`build_http_app(settings)` refuses stdio settings and missing values, then assembles the server
(hosted design 4.2): the auth store and plan 1a's shared Services, both behind the storage guard
(whose `free_space` starts as "delete the cache files" and becomes `PageCache.reset` once the cache
is open); the provider; `build_server()` with the SDK's `AuthSettings` and `CallClock` on the
gate's clock; our routes (`/consent`, `/oauth/github/callback`, `/healthz`) registered **before**
`streamable_http_app(stateless_http=True, json_response=True)`, so the SDK's app stays the root
and its lifespan runs; and a lifespan that runs the purge at startup and then hourly (a server
that restarts often still purges) and closes everything on shutdown. In development (a loopback
public URL) the SDK's DNS-rebinding protection allows only loopback hosts; in production it is
off, because bearer tokens make DNS rebinding useless.
`main()` configures logging, installs the VIN filter and runs uvicorn on port 8080 without access
logs. The middleware comes in Task 14.

`auth/pages.py` owns the cookies and the CSRF MAC (hosted design 4.6). `GET /consent` sets a
`__Host-ro_csrf` cookie (Strict) and puts `HMAC(k_consent, "consent|req|cookie|exp")` in the form;
`POST /consent` reads at most 8 short fields (a bigger form is refused before it is buffered),
needs the cookie, a valid MAC and an unexpired form (`exp` must be plain ASCII digits), then
calls the provider. Allow sets the `__Host-ro_gh_state` cookie (Lax, because GitHub's return is a
cross-site top-level GET) and redirects to GitHub. The callback clears that cookie and either
redirects to the client or shows an error page, never both.

`tests/http_env.py` drives the real app over ASGI: a fake GitHub, canned RealOEM pages, a fake
clock, and helpers that perform each sign-in step as Claude and the browser would. Cookies are
passed by hand, because an `http://` client never sends back the `Secure` cookies the pages set.

**Files:**
- Create: `server/src/realoem_mcp/auth/pages.py`, `server/src/realoem_mcp/http_app.py`
- Modify: `server/pyproject.toml` (uvicorn and starlette become direct dependencies; the
  `realoem-mcp-http` script), `server/uv.lock`
- Create: `server/tests/http_env.py`
- Test: `server/tests/http/test_sign_in_flow.py`, `server/tests/http/test_sign_in_pages.py`,
  `server/tests/http/test_http_app.py`

- [ ] **Step 1: Write the HTTP test environment** `server/tests/http_env.py`:

````python
"""The hosted server in-process: build_http_app over ASGI, a fake GitHub, canned RealOEM pages.

Requests go to http://localhost:8080 (a loopback public URL, so the app runs in development
mode, which needs a port in the Host header). Cookies are passed by hand: an http:// client
never sends back the Secure cookies the sign-in pages set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from realoem_mcp.auth.github import GitHubUser
from realoem_mcp.config import CLAUDE_CALLBACK, Settings
from realoem_mcp.http_app import build_http_app
from tests.fake_github import FakeGitHub
from tests.harness import FakeClock, FixtureTransport, Route
from tests.hosted_config import BASE, CHALLENGE, MCP_URL, VERIFIER, hosted_settings, query_of


def cookies_of(response: httpx.Response) -> dict[str, str]:
    """name -> value of every Set-Cookie on the response."""
    jar: dict[str, str] = {}
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        jar.update({name: morsel.value for name, morsel in cookie.items()})
    return jar


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str


@dataclass
class HostedEnv:
    app: Starlette
    http: httpx.AsyncClient
    github: FakeGitHub
    transport: FixtureTransport
    settings: Settings
    exits: list[int] = field(default_factory=list)

    async def register(self, redirect_uri: str = CLAUDE_CALLBACK, **extra: object) -> dict:
        body = {"redirect_uris": [redirect_uri], "client_name": "Claude", **extra}
        response = await self.http.post("/register", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    async def authorize(self, client: dict, *, state: str = "client-state") -> httpx.Response:
        return await self.http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": client["redirect_uris"][0],
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "state": state,
                "scope": "realoem",
                "resource": MCP_URL,
            },
        )

    async def consent(self, consent_url: str, decision: str = "allow") -> httpx.Response:
        """Load the consent page, then submit it with its cookie."""
        page = await self.http.get(consent_url)
        assert page.status_code == 200, page.text
        form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
        return await self.http.post(
            "/consent",
            data={**form, "decision": decision},
            headers={"Cookie": f"__Host-ro_csrf={cookies_of(page)['__Host-ro_csrf']}"},
        )

    async def github_returns(self, to_github: httpx.Response, user: GitHubUser) -> httpx.Response:
        """GitHub signs `user` in and redirects back with the state cookie the browser kept."""
        location = to_github.headers["location"]
        code = self.github.approve(location, user)
        state = query_of(location)["state"]
        return await self.http.get(
            "/oauth/github/callback",
            params={"code": code, "state": state},
            headers={"Cookie": f"__Host-ro_gh_state={cookies_of(to_github)['__Host-ro_gh_state']}"},
        )

    async def token(self, client: dict, back_to_client: httpx.Response) -> httpx.Response:
        code = query_of(back_to_client.headers["location"])["code"]
        return await self.http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": client["redirect_uris"][0],
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "code_verifier": VERIFIER,
                "resource": MCP_URL,
            },
        )

    async def sign_in(self, user_id: int, **user: object) -> Tokens:
        """The whole sign-in as Claude and the user's browser perform it."""
        client = await self.register()
        consent = await self.authorize(client)
        to_github = await self.consent(consent.headers["location"])
        back = await self.github_returns(to_github, self.github.add_user(user_id, **user))
        issued = await self.token(client, back)
        assert issued.status_code == 200, issued.text
        body = issued.json()
        return Tokens(
            body["access_token"],
            body["refresh_token"],
            client["client_id"],
            client["client_secret"],
        )

    def mcp(self, access_token: str | None) -> Client:
        """An MCP client over streamable HTTP to this app, with this bearer token."""
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=BASE, headers=headers
        )
        return Client(streamable_http_client(MCP_URL, http_client=http))


def hidden_field(page: str, name: str) -> str:
    """The value of a hidden form field on a sign-in page."""
    marker = f'name="{name}" value="'
    start = page.index(marker) + len(marker)
    return page[start : page.index('"', start)]


@asynccontextmanager
async def hosted_app(
    tmp_path: Path,
    routes: Mapping[str, Route | str] | None = None,
    **overrides: object,
) -> AsyncIterator[HostedEnv]:
    settings = hosted_settings(tmp_path, **overrides)
    github = FakeGitHub()
    transport = FixtureTransport(routes or {})
    clock = FakeClock()
    exits: list[int] = []
    app = build_http_app(
        settings,
        github=github,
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        exit=exits.append,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http,
    ):
        yield HostedEnv(app, http, github, transport, settings, exits)
    assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"
````

- [ ] **Step 2: Write the failing end-to-end test** `server/tests/http/test_sign_in_flow.py`:

````python
"""The whole hosted server over HTTP: discovery, sign-in with GitHub, tools (hosted design 5, 7)."""

from pathlib import Path

import pytest

from tests.harness import url
from tests.hosted_config import MCP_URL
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
ROUTES = {OIL_FILTER: "partxref/oil_filter_11427953129.html"}


async def test_discovery_points_claude_at_the_sign_in(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        unauthorized = await env.http.post("/mcp", json={})
        assert unauthorized.status_code == 401
        assert (
            'resource_metadata="http://localhost:8080/.well-known/oauth-protected-resource/mcp"'
            in unauthorized.headers["www-authenticate"]
        )
        resource = (await env.http.get("/.well-known/oauth-protected-resource/mcp")).json()
        assert resource["resource"] == MCP_URL
        assert resource["authorization_servers"] == ["http://localhost:8080"]
        server = (await env.http.get("/.well-known/oauth-authorization-server")).json()
        assert server["registration_endpoint"] == "http://localhost:8080/register"
        assert server["scopes_supported"] == ["realoem"]
        assert server["code_challenge_methods_supported"] == ["S256"]


async def test_a_signed_in_user_can_call_a_tool(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1001)
        async with env.mcp(tokens.access_token) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            result = await client.call_tool("lookup_part", {"part_number": "11427953129"})
        assert "lookup_part" in names
        assert result.is_error is False, result.content
        assert [str(request.url) for request in env.transport.requests] == [OIL_FILTER]
````

- [ ] **Step 3: Write the failing page tests** `server/tests/http/test_sign_in_pages.py`:

````python
"""The consent page, the GitHub callback, cookies and headers over HTTP (hosted design 4.6)."""

import base64
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from realoem_mcp.auth.keys import Keys
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.hosted_config import SECRET_KEY, query_of
from tests.http_env import HostedEnv, cookies_of, hidden_field, hosted_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def env(tmp_path: Path):
    async with hosted_app(tmp_path) as created:
        yield created


async def _consent_url(env: HostedEnv, **client: object) -> str:
    registered = await env.register(**client)
    response = await env.authorize(registered)
    assert response.status_code == 302
    return response.headers["location"]


def _set_cookie(response, name: str) -> str:
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))


async def test_the_consent_page_sets_a_strict_host_only_cookie(env: HostedEnv) -> None:
    page = await env.http.get(await _consent_url(env))
    assert page.status_code == 200
    cookie = _set_cookie(page, "__Host-ro_csrf").lower()
    for attribute in ("secure", "httponly", "samesite=strict", "path=/", "max-age=600"):
        assert attribute in cookie
    assert "domain=" not in cookie
    assert "Claude (claude.ai)" in page.text and CLAUDE_CALLBACK in page.text


async def test_a_loopback_client_is_named_as_a_local_program(env: HostedEnv) -> None:
    url = await _consent_url(
        env, redirect_uri="http://localhost:3000/cb", client_name="<b>Claude Code</b>"
    )
    page = await env.http.get(url)
    assert "A program on this computer" in page.text
    assert "&lt;b&gt;Claude Code&lt;/b&gt;" in page.text and "<b>Claude" not in page.text


async def test_allow_hands_over_to_github_with_a_lax_state_cookie(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    assert to_github.status_code == 302
    assert to_github.headers["location"].startswith("https://github.example/")
    cookie = _set_cookie(to_github, "__Host-ro_gh_state").lower()
    for attribute in ("secure", "httponly", "samesite=lax", "path=/", "max-age=600"):
        assert attribute in cookie


async def test_deny_returns_to_claude_with_access_denied(env: HostedEnv) -> None:
    back = await env.consent(await _consent_url(env), decision="deny")
    assert back.status_code == 302
    assert back.headers["location"].startswith(CLAUDE_CALLBACK)
    assert query_of(back.headers["location"]) == {"error": "access_denied", "state": "client-state"}


@pytest.mark.parametrize(
    "tamper", ["no-cookie", "other-cookie", "bad-mac", "expired", "exp-unicode", "replay"]
)
async def test_a_tampered_or_stale_consent_shows_an_error_never_a_redirect(
    env: HostedEnv, tamper: str
) -> None:
    page = await env.http.get(await _consent_url(env))
    form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
    cookie = cookies_of(page)["__Host-ro_csrf"]
    if tamper == "replay":
        first = await env.http.post(
            "/consent",
            data={**form, "decision": "allow"},
            headers={"Cookie": f"__Host-ro_csrf={cookie}"},
        )
        assert first.status_code == 302
    if tamper == "bad-mac":
        form["csrf"] = "0" * 64
    if tamper == "expired":  # correctly signed, but its time is up
        form["exp"] = "1"
        form["csrf"] = Keys(base64.b64decode(SECRET_KEY)).hash(
            "consent", f"consent|{form['req']}|{cookie}|1"
        )
    if tamper == "exp-unicode":  # "²" passes str.isdigit() but int() refuses it
        form["exp"] = "\u00b2"
    headers = {
        "no-cookie": {},
        "other-cookie": {"Cookie": "__Host-ro_csrf=someone-else"},
    }.get(tamper, {"Cookie": f"__Host-ro_csrf={cookie}"})
    response = await env.http.post("/consent", data={**form, "decision": "allow"}, headers=headers)
    assert response.status_code == 400
    assert "location" not in response.headers
    assert "This sign-in request has expired" in response.text


async def test_an_oversized_consent_form_is_refused_unread(env: HostedEnv) -> None:
    page = await env.http.get(await _consent_url(env))
    form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
    cookie = {"Cookie": f"__Host-ro_csrf={cookies_of(page)['__Host-ro_csrf']}"}
    for oversized in ({**form, "req": "x" * 2_000}, {**form, **{f"f{n}": "1" for n in range(20)}}):
        response = await env.http.post("/consent", data=oversized, headers=cookie)
        assert response.status_code == 400 and "location" not in response.headers
        assert "expired" not in response.text  # refused by the form parser, before our checks


async def test_the_callback_without_its_cookie_shows_an_error(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    code = env.github.approve(to_github.headers["location"], env.github.add_user(1))
    state = query_of(to_github.headers["location"])["state"]
    response = await env.http.get("/oauth/github/callback", params={"code": code, "state": state})
    assert response.status_code == 400 and "location" not in response.headers
    assert "__Host-ro_gh_state=" in response.headers["set-cookie"]  # cleared either way


async def test_the_callback_clears_its_cookie_and_returns_a_code(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    back = await env.github_returns(to_github, env.github.add_user(1))
    assert back.status_code == 302
    assert set(query_of(back.headers["location"])) == {"code", "state"}
    cleared = _set_cookie(back, "__Host-ro_gh_state").lower()
    assert "max-age=0" in cleared


async def test_a_banned_user_sees_the_suspended_page(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    with closing(sqlite3.connect(env.settings.auth_path)) as conn:
        conn.execute(
            "INSERT INTO users (subject, github_login, first_seen, banned_at) "
            "VALUES ('github:66', 'x', 0, 1)"
        )
        conn.commit()
    response = await env.github_returns(to_github, env.github.add_user(66))
    assert response.status_code == 403 and "location" not in response.headers
    assert "suspended" in response.text
````

- [ ] **Step 4: Write the failing app tests** `server/tests/http/test_http_app.py`:

````python
"""build_http_app and the realoem-mcp-http entry point (hosted design 4.2, 4.9)."""

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest
from starlette.applications import Starlette

from realoem_mcp import http_app
from realoem_mcp.auth.records import AWAITING_CONSENT, PendingRequest
from realoem_mcp.config import Settings
from realoem_mcp.http_app import build_http_app, purge_once
from tests.fake_github import FakeGitHub
from tests.harness import url
from tests.hosted_config import BASE, SECRET_KEY, hosted_settings
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
COMPARE_ROUTES = {
    url("partgrp", id=E90, mg="11"): "partgrp/e90_325i_mg11.html",
    url("partgrp", id=R56, mg="11"): "partgrp/r56_cooper_s_mg11.html",
    url("showparts", id=E90, diagId="11_3733"): "showparts/e90_325i_11_3733.html",
}
COMPARE = {
    "vehicle_a": E90,
    "vehicle_b": R56,
    "main_group": "11",
    "diag_ids": ["11_3733", "11_3910"],
}


def _expired_pending(request_id: str) -> PendingRequest:
    return PendingRequest(
        request_id, "c", "https://r", True, None, "c" * 43, "r", ("realoem",), AWAITING_CONSENT, 0
    )


def test_stdio_settings_and_missing_values_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode='http'"):
        build_http_app(Settings(cache_dir=tmp_path, data_dir=tmp_path))
    with pytest.raises(ValueError, match="REALOEM_GITHUB_CLIENT_ID is required"):
        build_http_app(hosted_settings(tmp_path, github_client_id=None))


async def test_shutdown_closes_the_databases(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        store = env.app.state.store
        assert store.live_pending_count(0) == 0
    with pytest.raises(sqlite3.ProgrammingError):  # closed
        store.conn.execute("SELECT 1")


async def test_the_purge_runs_on_its_interval(tmp_path: Path) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub(), purge_interval_s=0.01)
    async with app.router.lifespan_context(app):
        # The purge at startup takes the first row; only a repeat on the interval takes the second.
        for request_id in ("first", "second"):
            app.state.store.add_pending(_expired_pending(request_id))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if app.state.store.conn.execute("SELECT COUNT(*) FROM pending").fetchone() == (0,):
                    break
            else:
                pytest.fail(f"the purge never removed {request_id}")


async def test_the_purge_also_runs_at_startup(tmp_path: Path) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub())
    app.state.store.add_pending(_expired_pending("stale"))  # before the server starts
    async with app.router.lifespan_context(app):
        for _ in range(100):
            await asyncio.sleep(0.01)
            if app.state.store.conn.execute("SELECT COUNT(*) FROM pending").fetchone() == (0,):
                break
        else:
            pytest.fail("no purge at startup")


def test_purge_once_reports_what_it_removed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = build_http_app(hosted_settings(tmp_path), github=FakeGitHub())
    store, cache = app.state.store, app.state.services.cache
    try:
        store.add_pending(_expired_pending("a"))
        store.add_pending(_expired_pending("b"))
        with caplog.at_level(logging.INFO, logger="realoem_mcp.http_app"):
            purge_once(store, cache, 1_800_000_000)
        assert "purge: 2 pending; 0 expired pages" in caplog.text
    finally:
        store.close()
        cache.close()


async def test_the_call_deadline_applies_over_http(tmp_path: Path) -> None:
    """CallClock runs on the gate's clock: three requests take 4 s of the fake clock."""
    async with hosted_app(tmp_path, COMPARE_ROUTES, call_deadline_s=3.0) as env:
        tokens = await env.sign_in(1)
        async with env.mcp(tokens.access_token) as client:
            result = await client.call_tool("compare_vehicles", COMPARE)
        data = result.structured_content
        assert (data["complete"], data["unfetched_b"]) == (False, ["11_3910"])


def test_main_reports_a_bad_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(http_app, "install_vin_filter", lambda: None)  # keep pytest's handlers
    for name in ("REALOEM_PUBLIC_URL", "REALOEM_GITHUB_CLIENT_ID", "REALOEM_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REALOEM_DATA_DIR", str(tmp_path))
    httpx_level = logging.getLogger("httpx").level
    try:
        with pytest.raises(SystemExit) as stopped:
            http_app.main()
    finally:
        logging.getLogger("httpx").setLevel(httpx_level)  # main() changes it
    assert stopped.value.code == 2
    assert "The hosted server cannot start" in capsys.readouterr().err


def test_main_serves_on_port_8080(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[bool] = []
    served: list[tuple[object, dict]] = []
    monkeypatch.setattr(http_app, "install_vin_filter", lambda: installed.append(True))
    monkeypatch.setattr(http_app.uvicorn, "run", lambda app, **kw: served.append((app, kw)))
    environment = {
        "REALOEM_PUBLIC_URL": BASE,
        "REALOEM_GITHUB_CLIENT_ID": "id",
        "REALOEM_GITHUB_CLIENT_SECRET": "secret",
        "REALOEM_SECRET_KEY": SECRET_KEY,
        "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
        "REALOEM_DATA_DIR": str(tmp_path / "data"),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    httpx_level = logging.getLogger("httpx").level
    try:
        http_app.main()
    finally:
        logging.getLogger("httpx").setLevel(httpx_level)
    ((app, options),) = served
    assert isinstance(app, Starlette) and installed == [True]
    assert options == {"host": "0.0.0.0", "port": 8080, "access_log": False, "log_config": None}
    app.state.store.close()
    app.state.services.cache.close()
````

- [ ] **Step 5: Run them**

Run: `uv run --directory server pytest -q tests/http`
Expected: FAIL during collection: the module `realoem_mcp.http_app` does not exist yet.

- [ ] **Step 6: Implement the pages** `server/src/realoem_mcp/auth/pages.py`:

````python
"""The consent page and the GitHub hand-off (hosted design 4.6).

These handlers own the cookies and the CSRF MAC; the provider never sees them. Consent is asked
on every sign-in, before GitHub, and bound to the browser that loaded the consent page.
"""

from __future__ import annotations

import hmac
import re
import time
from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from realoem_mcp.auth.html import consent_page, error_page
from realoem_mcp.auth.keys import Keys, new_secret
from realoem_mcp.auth.outcomes import ExpiredRequest, ShowError, StartGitHub
from realoem_mcp.auth.provider import RealOemAuthProvider
from realoem_mcp.config import Settings

CSRF_COOKIE = "__Host-ro_csrf"
STATE_COOKIE = "__Host-ro_gh_state"
COOKIE_MAX_AGE = 600  # seconds: as long as a pending sign-in lives
DECISIONS = ("allow", "deny")
# The consent form has four short fields: anything bigger is refused before it is buffered.
FORM_LIMITS = {"max_files": 0, "max_fields": 8, "max_part_size": 1024}
_EXPIRES = re.compile(r"[0-9]{1,12}")  # ASCII digits only: int() accepts more than isdigit()


def error_response(kind: str) -> HTMLResponse:
    status, body = error_page(kind)
    headers = {"Retry-After": "60"} if kind == "busy" else None
    return HTMLResponse(body, status_code=status, headers=headers)


def _set_cookie(response: Response, name: str, value: str, same_site: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        path="/",
        secure=True,
        httponly=True,
        samesite=same_site,  # type: ignore[arg-type]
    )


class SignInPages:
    def __init__(
        self,
        provider: RealOemAuthProvider,
        keys: Keys,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._keys = keys
        self._settings = settings
        self._clock = clock

    def _mac(self, request_id: str, cookie: str, expires_at: str) -> str:
        return self._keys.hash("consent", f"consent|{request_id}|{cookie}|{expires_at}")

    async def show_consent(self, request: Request) -> Response:
        """GET /consent?req=<id>: the consent form, bound to a fresh cookie."""
        details = self._provider.describe(request.query_params.get("req", ""))
        if details is None:
            return error_response("expired")
        cookie = new_secret()
        expires_at = str(int(self._clock()) + COOKIE_MAX_AGE)
        page = consent_page(
            details,
            csrf=self._mac(details.request_id, cookie, expires_at),
            expires_at=int(expires_at),
            allowlist=self._settings.redirect_allowlist,
        )
        response = HTMLResponse(page)
        _set_cookie(response, CSRF_COOKIE, cookie, "strict")
        return response

    async def submit_consent(self, request: Request) -> Response:
        """POST /consent: needs the cookie, a valid MAC and an unexpired form."""
        form = await request.form(**FORM_LIMITS)
        request_id, expires_at, mac, decision = (
            str(form.get(name) or "") for name in ("req", "exp", "csrf", "decision")
        )
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not (
            cookie
            and _EXPIRES.fullmatch(expires_at)
            and int(expires_at) > self._clock()
            and decision in DECISIONS
            and hmac.compare_digest(
                mac.encode("utf-8"), self._mac(request_id, cookie, expires_at).encode("utf-8")
            )
        ):
            return error_response("expired")
        try:
            outcome = self._provider.consent(request_id, decision)
        except ExpiredRequest:
            return error_response("expired")
        response = RedirectResponse(outcome.url, status_code=302)
        if isinstance(outcome, StartGitHub):
            # Lax: GitHub's return is a cross-site top-level GET that must carry this cookie.
            _set_cookie(response, STATE_COOKIE, outcome.state, "lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    async def github_callback(self, request: Request) -> Response:
        """GET /oauth/github/callback: an error page or a redirect to the client, never both."""
        outcome = await self._provider.github_return(
            dict(request.query_params), request.cookies.get(STATE_COOKIE)
        )
        if isinstance(outcome, ShowError):
            response: Response = error_response(outcome.kind)
        else:
            response = RedirectResponse(outcome.url, status_code=302)
        response.delete_cookie(STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response
````

- [ ] **Step 7: Implement the app** `server/src/realoem_mcp/http_app.py`:

````python
"""The hosted server: the MCP tools over streamable HTTP behind GitHub sign-in (hosted design 4.2).

build_http_app() assembles everything and is what tests use; main() is the realoem-mcp-http
entry point. The stdio server (server.py) is unchanged and shares build_server().
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from realoem_mcp.auth.github import GitHubLogin, GitHubOAuthApp
from realoem_mcp.auth.keys import Keys
from realoem_mcp.auth.pages import SignInPages
from realoem_mcp.auth.provider import SCOPE, RealOemAuthProvider
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.cache import DB_FILENAME, PageCache
from realoem_mcp.config import Settings
from realoem_mcp.current_user import CallClock
from realoem_mcp.log_privacy import install_vin_filter
from realoem_mcp.server import build_server
from realoem_mcp.shared import build_shared
from realoem_mcp.storage_guard import StorageGuard, hard_exit

PORT = 8080
PURGE_INTERVAL_S = 3600.0

log = logging.getLogger(__name__)


def _cache_file_deleter(cache_dir: Path) -> Callable[[], None]:
    """Frees disk space before the page cache is open (a full disk found at startup)."""

    def delete() -> None:
        for suffix in ("", "-wal", "-shm"):
            (cache_dir / f"{DB_FILENAME}{suffix}").unlink(missing_ok=True)

    return delete


def _auth_settings(settings: Settings) -> AuthSettings:
    return AuthSettings(
        issuer_url=settings.public_url,  # type: ignore[arg-type]
        resource_server_url=f"{settings.public_url}/mcp",  # type: ignore[arg-type]
        validate_token_resource=True,
        required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    if settings.is_local:  # a development run: only loopback Host headers (a port is required)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*", "127.0.0.1:*"],
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
        )
    # Bearer tokens make DNS rebinding useless, and the SDK would answer any request with an
    # Origin header with a 403 that Claude treats as final.
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def purge_once(store: AuthStore, cache: PageCache, now: float) -> None:
    """The hourly housekeeping (hosted design 4.9)."""
    removed = store.purge(int(now))
    expired_pages = cache.purge_expired()
    log.info(
        "purge: %s; %d expired pages",
        ", ".join(f"{count} {table}" for table, count in removed.items() if count) or "nothing",
        expired_pages,
    )


async def _purge_hourly(store: AuthStore, cache: PageCache, interval_s: float) -> None:
    """Purge at startup, then every interval: a server restarted often still purges."""
    while True:
        try:
            purge_once(store, cache, time.time())
        except Exception:
            log.exception("the hourly purge failed")
        await asyncio.sleep(interval_s)


async def _healthz(request: Request) -> PlainTextResponse:
    """Liveness only: a constant answer, no database access."""
    return PlainTextResponse("ok")


def build_http_app(
    settings: Settings,
    *,
    github: GitHubLogin | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], datetime] | None = None,
    exit: Callable[[int], object] = hard_exit,
    purge_interval_s: float = PURGE_INTERVAL_S,
) -> Starlette:
    """The ASGI app of the hosted server. Refuses stdio settings and missing HTTP-only values.

    github, transport, clock, sleep, now and exit are for tests (a fake GitHub, canned RealOEM
    pages, a fake clock, a recorded exit).
    """
    if settings.mode != "http":
        raise ValueError("build_http_app needs Settings(mode='http'); run realoem-mcp-http")
    settings.validate_http()
    keys = Keys(settings.secret_key_bytes)
    guard = StorageGuard(free_space=_cache_file_deleter(settings.cache_dir), exit=exit)
    store = AuthStore.open(settings.auth_path, run=guard.run)
    shared = build_shared(
        settings,
        store.conn,
        owner_key=keys.key("cache-owner"),
        account_created_at=store.github_created_at,
        transport=transport,
        clock=clock,
        sleep=sleep,
        now=now,
        run=guard.run,
    )
    services = shared.services
    guard.free_space = services.cache.reset
    github = github or GitHubOAuthApp(
        settings.github_client_id or "",
        settings.github_client_secret or "",
        f"{settings.public_url}/oauth/github/callback",
    )
    provider = RealOemAuthProvider(settings, store, github, keys)
    server = build_server(
        services,
        auth_server_provider=provider,
        auth=_auth_settings(settings),
        middleware=[CallClock(clock or time.monotonic)],  # the clock the gate reads
    )
    pages = SignInPages(provider, keys, settings)
    server.custom_route("/consent", methods=["GET"])(pages.show_consent)
    server.custom_route("/consent", methods=["POST"])(pages.submit_consent)
    server.custom_route("/oauth/github/callback", methods=["GET"])(pages.github_callback)
    server.custom_route("/healthz", methods=["GET"])(_healthz)
    # After the custom routes, so the SDK's app stays the root and its lifespan runs.
    app = server.streamable_http_app(
        stateless_http=True, json_response=True, transport_security=_transport_security(settings)
    )
    sdk_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with sdk_lifespan(app):
            purge = asyncio.create_task(_purge_hourly(store, services.cache, purge_interval_s))
            try:
                yield
            finally:
                purge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await purge
                await services.aclose()
                await github.aclose()
                store.close()

    app.router.lifespan_context = lifespan
    app.state.store = store  # for tests and the admin's debugging; nothing else reads these
    app.state.services = services
    return app


def main() -> None:
    # Configure logging before the SDK does (it only configures an unconfigured root logger).
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    install_vin_filter()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the client logs each request itself
    try:
        app = build_http_app(dataclasses.replace(Settings.from_env(), mode="http"))
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(2)
    uvicorn.run(app, host="0.0.0.0", port=PORT, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
````

- [ ] **Step 8: Dependencies and the entry point.** In `server/pyproject.toml`:

Edit 1. Find:

````toml
    "platformdirs>=4",
    "pydantic>=2.11,<3",
    "selectolax>=0.4,<0.5",
]

[project.scripts]
realoem-mcp = "realoem_mcp.server:main"

[dependency-groups]
dev = [
````

Replace with:

````toml
    "platformdirs>=4",
    "pydantic>=2.11,<3",
    "selectolax>=0.4,<0.5",
    "starlette>=1.7,<2",
    "uvicorn>=0.54,<1",
]

[project.scripts]
realoem-mcp = "realoem_mcp.server:main"
realoem-mcp-http = "realoem_mcp.http_app:main"

[dependency-groups]
dev = [
````

Then update the lockfile. The versions are already locked, so only the two new direct
dependencies of `realoem-mcp` appear in `server/uv.lock`:

Run: `uv lock --directory server`
Expected: `Resolved 43 packages`; `git diff --stat` then shows `server/uv.lock | 4 ++++`.

- [ ] **Step 9: Run it**

Run: `uv run --directory server pytest -q tests/http/test_sign_in_flow.py tests/http/test_sign_in_pages.py tests/http/test_http_app.py`
Expected: `24 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1230 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/auth/pages.py server/src/realoem_mcp/http_app.py server/pyproject.toml server/uv.lock server/tests/http_env.py server/tests/http/test_sign_in_flow.py server/tests/http/test_sign_in_pages.py server/tests/http/test_http_app.py
git commit -m "feat(hosted): HTTP app with GitHub sign-in, consent pages and the realoem-mcp-http entry point" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 8: Middleware, acceptance tests and the admin script

### Task 14: Security headers, the request log and the sign-in limits

Three pure ASGI middlewares, added outermost first (hosted design 4.2, 4.6, 4.9):

- **`SecurityHeaders`**: `Strict-Transport-Security` on every response; on HTML responses also
  the CSP, `X-Frame-Options`, `Referrer-Policy` and `Cache-Control: no-store`.
- **`RequestLog`**: one line per request (method, path without the query string, status,
  duration, and `github:<id>` once the SDK has authenticated the caller); never headers, bodies,
  tokens or codes. The path is escaped, so a request cannot forge a log line.
- **`SignInLimits`**: on `/register`, bodies over 8 KB get `413` (the SDK alone accepts 4 MiB),
  30 registrations an hour per address outside Anthropic's range, 600 an hour across the range
  (hosted Claude registers a new client per connection), and a ceiling of 2,000 a day for all
  addresses outside the range; on `/authorize`, 60 per address per 10 minutes, and the busy page
  (`503`, `Retry-After`) once 100,000 sign-ins are pending. The address is the one Fly's proxy
  reports in `Fly-Client-IP` (plan 2 checks that a forged header is overwritten); an IPv6 client
  counts by its /64, because one host controls a whole /64, and an IPv4-mapped address counts as
  IPv4. Limits answer `429` with `Retry-After`.

**Files:**
- Create: `server/src/realoem_mcp/http_middleware.py`
- Modify: `server/src/realoem_mcp/http_app.py`
- Test: `server/tests/http/test_http_middleware.py`, `server/tests/http/test_sign_in_limits.py`

- [ ] **Step 1: Write the failing middleware tests** `server/tests/http/test_http_middleware.py`:

````python
"""Security headers and the request log (hosted design 4.2, 4.6, 4.9)."""

import logging
from pathlib import Path

import pytest

from tests.harness import url
from tests.http_env import HostedEnv, hosted_app

pytestmark = pytest.mark.anyio

ROUTES = {url("partxref", q="11427953129"): "partxref/oil_filter_11427953129.html"}
PART = {"part_number": "11427953129"}


@pytest.fixture
async def env(tmp_path: Path):
    async with hosted_app(tmp_path, ROUTES) as created:
        yield created


async def test_html_pages_carry_the_security_headers(env: HostedEnv) -> None:
    client = await env.register()
    page = await env.http.get((await env.authorize(client)).headers["location"])
    assert page.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"
    health = await env.http.get("/healthz")
    assert (health.status_code, health.text) == (200, "ok")
    assert health.headers["strict-transport-security"] == "max-age=31536000"
    assert "content-security-policy" not in health.headers


async def test_the_request_log_has_no_query_strings_and_names_the_user(
    env: HostedEnv, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="realoem_mcp.requests"):
        tokens = await env.sign_in(1)
        async with env.mcp(tokens.access_token) as client:
            await client.call_tool("lookup_part", PART)
    lines = [r.getMessage() for r in caplog.records if r.name == "realoem_mcp.requests"]
    assert any(line.startswith("GET /authorize 302") for line in lines)
    assert any(line.startswith("POST /mcp 200") and line.endswith("github:1") for line in lines)
    assert not [line for line in lines if "?" in line or "code=" in line or "state=" in line]


async def test_a_path_cannot_forge_a_log_line(
    env: HostedEnv, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="realoem_mcp.requests"):
        await env.http.get("/x%0AGET%20/forged%20200%201%20ms%20github:99")
    (line,) = [r.getMessage() for r in caplog.records if r.name == "realoem_mcp.requests"]
    assert "\n" not in line and line.startswith("GET /x\\nGET /forged")
````

- [ ] **Step 2: Write the failing limit tests** `server/tests/http/test_sign_in_limits.py`:

````python
"""Rate limits, the /register size limit and the pending cap (hosted design 4.9)."""

from pathlib import Path

import pytest

from realoem_mcp import http_middleware
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.http_env import HostedEnv, hosted_app

pytestmark = pytest.mark.anyio

HOSTED = "160.79.104.10"  # inside Anthropic's range
OUTSIDE = "203.0.113.7"
REGISTRATION = {"redirect_uris": [CLAUDE_CALLBACK], "client_name": "Claude"}


async def _register(env: HostedEnv, address: str) -> int:
    response = await env.http.post(
        "/register", json=REGISTRATION, headers={"Fly-Client-IP": address}
    )
    return response.status_code


async def test_an_oversized_registration_is_refused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        big = {**REGISTRATION, "client_name": "x" * 9_000}
        response = await env.http.post("/register", json=big)
        assert response.status_code == 413

        async def chunks():  # no Content-Length: the body is counted as it arrives
            yield b"{" + b" " * 5_000
            yield b" " * 5_000 + b"}"

        streamed = await env.http.post(
            "/register", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert streamed.status_code == 413
        assert await _register(env, OUTSIDE) == 201  # a normal one still works


async def test_one_address_outside_the_hosted_range_gets_30_an_hour(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for _ in range(30):
            assert await _register(env, OUTSIDE) == 201
        refused = await env.http.post(
            "/register", json=REGISTRATION, headers={"Fly-Client-IP": OUTSIDE}
        )
        assert refused.status_code == 429
        assert 3500 <= int(refused.headers["retry-after"]) <= 3600
        assert await _register(env, "203.0.113.8") == 201  # another address is not affected
        assert await _register(env, HOSTED) == 201  # nor is the hosted range


async def test_an_ipv6_client_counts_by_its_64_and_mapped_ipv4_as_ipv4(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for number in range(30):  # one host, many addresses in its /64
            assert await _register(env, f"2001:db8:0:1::{number:x}") == 201
        assert await _register(env, "2001:db8:0:1:ffff::1") == 429
        assert await _register(env, "2001:db8:0:2::1") == 201  # another /64
        for _ in range(30):
            assert await _register(env, "::ffff:198.51.100.9") == 201
        assert await _register(env, "198.51.100.9") == 429  # the same client


async def test_the_hosted_range_shares_one_larger_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "REGISTER_HOSTED_RANGE", (40, 3_600.0))
    async with hosted_app(tmp_path) as env:
        for number in range(40):  # more than one outside address could make
            assert await _register(env, f"160.79.104.{number}") == 201
        assert await _register(env, "160.79.111.250") == 429  # anywhere in the /21


async def test_outside_addresses_share_a_daily_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "REGISTER_OUTSIDE_TOTAL", (3, 86_400.0))
    async with hosted_app(tmp_path) as env:
        for number in range(3):
            assert await _register(env, f"198.51.100.{number}") == 201
        assert await _register(env, "198.51.100.200") == 429
        assert await _register(env, HOSTED) == 201  # the ceiling never applies to the range


async def test_authorize_allows_60_per_address_per_10_minutes(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for _ in range(60):
            response = await env.http.get("/authorize", headers={"Fly-Client-IP": OUTSIDE})
            assert response.status_code != 429
        refused = await env.http.get("/authorize", headers={"Fly-Client-IP": OUTSIDE})
        assert refused.status_code == 429 and "retry-after" in refused.headers


async def test_too_many_pending_sign_ins_show_the_busy_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "MAX_PENDING", 1)
    async with hosted_app(tmp_path) as env:
        client = await env.register()
        assert (await env.authorize(client)).status_code == 302  # one pending sign-in
        busy = await env.authorize(client)
        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "60"
        assert "RealOEM Searcher is busy" in busy.text
        assert busy.headers["content-security-policy"].startswith("default-src 'none'")
````

- [ ] **Step 3: Run them, one file at a time**

Run: `uv run --directory server pytest -q tests/http/test_http_middleware.py`
Expected: FAIL: no security headers (`KeyError: 'content-security-policy'`) and no request log lines.

Run: `uv run --directory server pytest -q tests/http/test_sign_in_limits.py`
Expected: FAIL during collection: `cannot import name 'http_middleware'`.

- [ ] **Step 4: Implement** `server/src/realoem_mcp/http_middleware.py`:

````python
"""ASGI middleware of the hosted server (hosted design 4.2, 4.6, 4.9), outermost first:
security headers, the request log, and the limits on the sign-in routes."""

from __future__ import annotations

import ipaddress
import logging
import math
import time
from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from realoem_mcp.auth.html import error_page
from realoem_mcp.config import Settings
from realoem_mcp.rate_limit import SlidingWindow

HSTS = "max-age=31536000"
HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
MAX_REGISTER_BODY = 8 * 1024  # the SDK alone accepts 4 MiB
REGISTER_PER_ADDRESS = (30, 3_600.0)  # per hour, per address outside the hosted range
REGISTER_HOSTED_RANGE = (600, 3_600.0)  # per hour, for the whole hosted range
REGISTER_OUTSIDE_TOTAL = (2_000, 86_400.0)  # per day, all addresses outside the range together
AUTHORIZE_PER_ADDRESS = (60, 600.0)  # per 10 minutes
MAX_PENDING = 100_000  # live pending sign-ins (about 50 MB)
CLIENT_IP_HEADER = "fly-client-ip"  # set by Fly's proxy; the socket peer is the proxy

log = logging.getLogger("realoem_mcp.requests")


class SecurityHeaders:
    """HSTS on every response; CSP and friends on every HTML response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Strict-Transport-Security"] = HSTS
                if headers.get("content-type", "").startswith("text/html"):
                    for name, value in HTML_HEADERS.items():
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestLog:
    """One line per request: method, path (never the query string), status, duration, and the
    signed-in user when there is one. Never headers, bodies, tokens or codes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            token = getattr(scope.get("user"), "access_token", None)  # set by the SDK's auth
            subject = getattr(token, "subject", None)
            log.info(
                "%s %s %d %.0f ms%s",
                scope["method"],
                # Decoded by the server: escape it, so a path cannot forge another log line.
                scope["path"].encode("unicode_escape").decode("ascii"),
                status,
                (time.perf_counter() - started) * 1000,
                f" {subject}" if subject else "",
            )


async def _send_simple(
    send: Send, status: int, body: bytes, content_type: str, retry_after: float | None = None
) -> None:
    headers = [
        (b"content-type", content_type.encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    if retry_after is not None:
        headers.append((b"retry-after", str(max(1, math.ceil(retry_after))).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class SignInLimits:
    """Rate limits and a size limit on /register, rate limits and the pending cap on
    /authorize. Keyed on the address Fly's proxy reports."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        pending_count: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self._hosted = ipaddress.ip_network(settings.hosted_client_range)
        self._pending_count = pending_count
        self._register_each = SlidingWindow(*REGISTER_PER_ADDRESS, clock=clock)
        self._register_hosted = SlidingWindow(*REGISTER_HOSTED_RANGE, clock=clock)
        self._register_outside = SlidingWindow(*REGISTER_OUTSIDE_TOTAL, clock=clock)
        self._authorize_each = SlidingWindow(*AUTHORIZE_PER_ADDRESS, clock=clock)

    def _client(self, scope: Scope) -> tuple[str, bool]:
        """The client's rate-limit key, and whether it is in Anthropic's range. An IPv6 client
        counts by its /64, because one host controls a whole /64."""
        client = scope.get("client")
        raw = (Headers(scope=scope).get(CLIENT_IP_HEADER) or (client[0] if client else "")).strip()
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return raw or "unknown", False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        hosted = address in self._hosted
        if isinstance(address, ipaddress.IPv6Address):
            return str(ipaddress.ip_network(f"{address}/64", strict=False)), hosted
        return str(address), hosted

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in ("/register", "/authorize"):
            await self.app(scope, receive, send)
            return
        address, hosted = self._client(scope)
        if scope["path"] == "/authorize":
            if (wait := self._authorize_each.retry_after(address)) is not None:
                await _send_simple(send, 429, b"Too many sign-in attempts.", "text/plain", wait)
                return
            self._authorize_each.record(address)
            if self._pending_count() >= MAX_PENDING:
                status, page = error_page("busy")
                await _send_simple(send, status, page.encode(), "text/html; charset=utf-8", 60)
                return
            await self.app(scope, receive, send)
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        buckets = (
            [(self._register_hosted, "hosted")]
            if hosted
            else [(self._register_each, address), (self._register_outside, "outside")]
        )
        waits = [wait for bucket, key in buckets if (wait := bucket.retry_after(key)) is not None]
        if waits:
            await _send_simple(send, 429, b"Too many registrations.", "text/plain", max(waits))
            return
        for bucket, key in buckets:
            bucket.record(key)
        body = await self._read_body(scope, receive)
        if body is None:
            await _send_simple(send, 413, b"Registration body too large.", "text/plain")
            return
        await self.app(scope, _replay(body, receive), send)

    @staticmethod
    async def _read_body(scope: Scope, receive: Receive) -> bytes | None:
        """The whole request body, or None once it passes MAX_REGISTER_BODY."""
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REGISTER_BODY:
            return None
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return b"".join(chunks)  # the client went away; the handler will see that
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_REGISTER_BODY:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replayed() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replayed
````

- [ ] **Step 5: Add the middleware to the app.** In `server/src/realoem_mcp/http_app.py`:

Edit 1. Find:

````python
from realoem_mcp.cache import DB_FILENAME, PageCache
from realoem_mcp.config import Settings
from realoem_mcp.current_user import CallClock
from realoem_mcp.log_privacy import install_vin_filter
from realoem_mcp.server import build_server
from realoem_mcp.shared import build_shared
````

Replace with:

````python
from realoem_mcp.cache import DB_FILENAME, PageCache
from realoem_mcp.config import Settings
from realoem_mcp.current_user import CallClock
from realoem_mcp.http_middleware import RequestLog, SecurityHeaders, SignInLimits
from realoem_mcp.log_privacy import install_vin_filter
from realoem_mcp.server import build_server
from realoem_mcp.shared import build_shared
````

Edit 2. Find:

````python
    app.router.lifespan_context = lifespan
    app.state.store = store  # for tests and the admin's debugging; nothing else reads these
    app.state.services = services
    return app


````

Replace with:

````python
    app.router.lifespan_context = lifespan
    app.state.store = store  # for tests and the admin's debugging; nothing else reads these
    app.state.services = services
    # add_middleware puts each one outside the previous: the last added runs first.
    app.add_middleware(
        SignInLimits,
        settings=settings,
        pending_count=lambda: store.live_pending_count(int(time.time())),
    )
    app.add_middleware(RequestLog)
    app.add_middleware(SecurityHeaders)
    return app


````

- [ ] **Step 6: Run it**

Run: `uv run --directory server pytest -q tests/http/test_sign_in_flow.py tests/http/test_sign_in_pages.py tests/http/test_http_app.py tests/http/test_http_middleware.py tests/http/test_sign_in_limits.py`
Expected: `34 passed` (10 new).

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1240 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/src/realoem_mcp/http_middleware.py server/src/realoem_mcp/http_app.py server/tests/http/test_http_middleware.py server/tests/http/test_sign_in_limits.py
git commit -m "feat(hosted): security headers, request log and sign-in rate limits" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 15: The tools over HTTP (acceptance tests)

These tests sign real users in and call tools through the whole stack, checking what spec section
7 lists for the end-to-end run: two users share a part page but not a VIN page, interleaved calls
are charged to the right user, only an administrator clears the cache, a refresh token works once,
a token without the scope or of the wrong kind is refused, and no log line carries a VIN. They
exercise Tasks 5 to 14 together and pass when written. If one fails, the defect is in an earlier
task: fix it there, not here.

**Files:**
- Test: `server/tests/http/test_hosted_tools.py`

- [ ] **Step 1: Write the tests** `server/tests/http/test_hosted_tools.py`:

````python
"""Tools through the hosted server: users, quotas, the shared cache, logs (hosted design 7)."""

import asyncio
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from realoem_mcp.log_privacy import VinFilter
from tests.harness import Route, url
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
VIN = url("select", vin="PX22770")
ROUTES = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    VIN: "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


def _used_today(env, subject: str) -> int:
    with closing(sqlite3.connect(env.settings.auth_path)) as conn:
        row = conn.execute("SELECT SUM(requests) FROM usage WHERE subject = ?", (subject,))
        return row.fetchone()[0] or 0


async def test_users_share_part_pages_but_not_vin_pages(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        alice, bob = await env.sign_in(1), await env.sign_in(2)
        for tokens in (alice, bob):
            async with env.mcp(tokens.access_token) as client:
                part = await client.call_tool("lookup_part", PART)
                vin = await client.call_tool("decode_vin", {"vin": "PX22770"})
            assert part.is_error is False and vin.is_error is False
        sent = [str(request.url) for request in env.transport.requests]
        assert sent == [OIL_FILTER, VIN, VIN]  # the part page once; each user's own VIN page
        assert (_used_today(env, "github:1"), _used_today(env, "github:2")) == (2, 1)


async def test_interleaved_calls_are_charged_to_the_right_user(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        alice, bob = await env.sign_in(1), await env.sign_in(2)
        async with env.mcp(alice.access_token) as a, env.mcp(bob.access_token) as b:
            await asyncio.gather(
                a.call_tool("lookup_part", PART),
                b.call_tool("decode_vin", {"vin": "PX22770"}),
                a.call_tool("decode_vin", {"vin": "PX22770"}),
            )
        charged = (_used_today(env, "github:1"), _used_today(env, "github:2"))
        assert charged == (2, 1)  # alice's two pages and bob's own VIN page
        assert _used_today(env, "*") == 3


async def test_only_an_admin_clears_the_cache(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES, admins=frozenset({"github:1"})) as env:
        admin, user = await env.sign_in(1), await env.sign_in(2)
        async with env.mcp(user.access_token) as client:
            await client.call_tool("lookup_part", PART)
            refused = await client.call_tool("cache_clear", {})
            status = await client.call_tool("server_status", {})
        assert refused.is_error is True and "Only an administrator" in refused.content[0].text
        assert status.structured_content["cache_path"] is None
        assert status.structured_content["quota"]["used_today"] == 1
        async with env.mcp(admin.access_token) as client:
            cleared = await client.call_tool("cache_clear", {})
        assert cleared.structured_content == {"removed": 1}


async def test_requests_without_a_valid_token_or_scope_are_refused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1)
        anonymous = await env.http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert anonymous.status_code == 401
        forged = await env.http.post(
            "/mcp", json={}, headers={"Authorization": "Bearer not-a-token"}
        )
        assert forged.status_code == 401
        refresh_as_bearer = await env.http.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {tokens.refresh_token}"}
        )
        assert refresh_as_bearer.status_code == 401
        with closing(sqlite3.connect(env.settings.auth_path)) as conn:
            conn.execute("UPDATE tokens SET scopes = ''")
            conn.commit()
        no_scope = await env.http.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {tokens.access_token}"}
        )
        assert no_scope.status_code == 403
        assert 'error="insufficient_scope"' in no_scope.headers["www-authenticate"]


async def test_a_refreshed_token_works_and_the_old_one_cannot_be_reused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": tokens.client_id,
            "client_secret": tokens.client_secret,
        }
        refreshed = await env.http.post("/token", data=form)
        assert refreshed.status_code == 200, refreshed.text
        async with env.mcp(refreshed.json()["access_token"]) as client:
            assert (await client.call_tool("lookup_part", PART)).is_error is False
        replayed = await env.http.post("/token", data=form)
        assert (replayed.status_code, replayed.json()["error"]) == (400, "invalid_grant")


async def test_the_logs_never_carry_a_vin(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    routes = {**ROUTES, url("select", vin="AB12345"): Route(status=503)}
    vin_filter = VinFilter()  # main() puts it on every root handler; here, on caplog's
    caplog.handler.addFilter(vin_filter)  # one handler for the whole session: removed below
    try:
        async with hosted_app(tmp_path, routes) as env:
            tokens = await env.sign_in(1)
            with caplog.at_level(logging.INFO):
                async with env.mcp(tokens.access_token) as client:
                    await client.call_tool("decode_vin", {"vin": "PX22770"})
                    failed = await client.call_tool("decode_vin", {"vin": "AB12345"})  # 503
                    invalid = await client.call_tool("decode_vin", {"vin": "QQ1111!"})
    finally:
        caplog.handler.removeFilter(vin_filter)
    assert failed.is_error is True and invalid.is_error is True
    assert "select?vin=AB12345" in failed.content[0].text  # the user still sees it
    for vin in ("PX22770", "AB12345", "QQ1111!"):
        assert vin not in caplog.text
````

- [ ] **Step 2: Run them**

Run: `uv run --directory server pytest -q tests/http/test_hosted_tools.py`
Expected: `6 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1246 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/tests/http/test_hosted_tools.py
git commit -m "test(hosted): end-to-end tool calls by signed-in users over HTTP" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 16: The admin script

The maintainer looks after users from a shell on the server (hosted design 4.8): `usage` for one
UTC day, `ban` (which also revokes every token), `unban`, `revoke` (sign a user out everywhere)
and `prune` (the hourly purge, now). It refuses to run as root, so SQLite's WAL files never
become root-owned, and refuses a database path that does not exist (a ban written to a new, empty
database would do nothing); it prints the path it uses. Plan 2 documents the `fly ssh console`
command.

**Files:**
- Create: `server/scripts/admin.py`
- Test: `server/tests/unit/test_admin_script.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_admin_script.py`:

````python
"""scripts/admin.py against a temporary auth database."""

import io
from pathlib import Path

import pytest

from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings
from scripts import admin

NOW = 1_800_000_000.0  # 2027-01-15


def _run(tmp_path: Path, *argv: str) -> str:
    """The command's output, after the line that names the database."""
    out = io.StringIO()
    settings = Settings(data_dir=tmp_path)
    assert admin.main(list(argv), settings=settings, now=lambda: NOW, out=out) == 0
    first, _, rest = out.getvalue().partition("\n")
    assert first == f"Auth database: {settings.auth_path}"
    return rest


def _store(tmp_path: Path) -> AuthStore:
    return AuthStore.open(Settings(data_dir=tmp_path).auth_path)


def test_usage_lists_the_day_busiest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_user("github:1", "octocat", None, 0)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2027-01-15', 7)")
    store.conn.execute("INSERT INTO usage VALUES ('github:3', '2027-01-15', 5)")
    store.conn.execute("INSERT INTO usage VALUES ('*', '2027-01-15', 12)")
    store.conn.execute("INSERT INTO usage VALUES ('github:2', '2027-01-14', 3)")
    store.close()
    today = _run(tmp_path, "usage")
    assert today.splitlines() == [
        "Requests on 2027-01-15 (UTC):",
        "      12  everyone",
        "       7  github:1 (octocat)",
        "       5  github:3 (?)",
    ]
    assert "github:2 (?)" in _run(tmp_path, "usage", "--day", "2027-01-14")
    assert "none" in _run(tmp_path, "usage", "--day", "2020-01-01")


def test_ban_unban_and_revoke(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_family("fam", "github:5", "client", int(NOW), int(NOW) + 3600)
    store.close()
    assert "Banned github:5" in _run(tmp_path, "ban", "5", "--reason", "abuse")
    store = _store(tmp_path)
    assert store.is_banned("github:5")
    assert store.user("github:5").banned_reason == "abuse"
    assert store.active_families("github:5", int(NOW)) == []
    store.add_family("fam2", "github:5", "client", int(NOW), int(NOW) + 3600)
    store.close()
    assert "Unbanned github:5." in _run(tmp_path, "unban", "5")
    assert "was not banned" in _run(tmp_path, "unban", "5")
    assert "Revoked 1 sign-in(s) of github:5." in _run(tmp_path, "revoke", "5")


def test_prune_runs_the_purge(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.conn.execute("INSERT INTO usage VALUES ('github:1', '2026-01-01', 1)")
    store.close()
    assert _run(tmp_path, "prune") == "Pruned: 1 usage.\n"
    assert _run(tmp_path, "prune") == "Pruned: nothing.\n"


def test_a_missing_database_is_never_created(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "missing")
    assert admin.main(["ban", "5", "--reason", "x"], settings=settings) == 2
    assert not (tmp_path / "missing").exists()


def test_it_refuses_to_run_as_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(tmp_path).close()
    monkeypatch.setattr(admin.os, "geteuid", lambda: 0, raising=False)
    assert admin.main(["usage"], settings=Settings(data_dir=tmp_path)) == 2


def test_a_github_id_must_be_a_number(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        admin.main(["ban", "octocat", "--reason", "x"], settings=Settings(data_dir=tmp_path))
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_admin_script.py`
Expected: FAIL during collection: `cannot import name 'admin'` from `scripts`.

- [ ] **Step 3: Implement** `server/scripts/admin.py`:

````python
"""MAINTAINER ONLY: look after the hosted server's users (hosted design 4.8, 4.9).

Run it on the server as the app user, never as root, so SQLite's WAL files never become
root-owned; it refuses to run as root. On the hosted server use the image's own Python (`uv run`
would install the development tools first):

    /app/server/.venv/bin/python /app/server/scripts/admin.py usage [--day YYYY-MM-DD]
    ... ban <github id> --reason "..."
    ... unban <github id>
    ... revoke <github id>
    ... prune

Locally, from server/: uv run python scripts/admin.py usage

<github id> is the numeric GitHub id (the number in "github:<id>" in the logs).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO

from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings


def _subject(github_id: str) -> str:
    if not (github_id.isascii() and github_id.isdigit()):
        raise argparse.ArgumentTypeError(f"a GitHub id is a number, got {github_id!r}")
    return f"github:{github_id}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    usage = commands.add_parser("usage", help="requests per user for one UTC day")
    usage.add_argument("--day", help="YYYY-MM-DD (default: today, UTC)")
    ban = commands.add_parser("ban", help="refuse a user's sign-ins and tokens")
    ban.add_argument("subject", type=_subject, metavar="github_id")
    ban.add_argument("--reason", required=True)
    for name, text in (("unban", "lift a ban"), ("revoke", "sign a user out everywhere")):
        command = commands.add_parser(name, help=text)
        command.add_argument("subject", type=_subject, metavar="github_id")
    commands.add_parser("prune", help="run the hourly purge now")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], float] = time.time,
    out: TextIO = sys.stdout,
) -> int:
    args = _parser().parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(
            "Run this as the app user, not root: root-owned files stop the server.", file=sys.stderr
        )
        return 2
    path = (settings or Settings.from_env()).auth_path
    if not path.exists():  # never create a new, empty database: a ban there would do nothing
        print(
            f"No auth database at {path}; set REALOEM_DATA_DIR (or REALOEM_AUTH_DIR).",
            file=sys.stderr,
        )
        return 2
    print(f"Auth database: {path}", file=out)
    store = AuthStore.open(path)
    try:
        if args.command == "usage":
            day = args.day or datetime.fromtimestamp(now(), UTC).date().isoformat()
            rows = store.usage(day)
            print(f"Requests on {day} (UTC):", file=out)
            for subject, login, requests in rows:
                name = "everyone" if subject == "*" else f"{subject} ({login or '?'})"
                print(f"  {requests:>6}  {name}", file=out)
            if not rows:
                print("  none", file=out)
        elif args.command == "ban":
            store.ban(args.subject, args.reason, int(now()))
            print(f"Banned {args.subject}; its tokens are revoked.", file=out)
        elif args.command == "unban":
            done = store.unban(args.subject)
            print(
                f"Unbanned {args.subject}." if done else f"{args.subject} was not banned.", file=out
            )
        elif args.command == "revoke":
            count = store.revoke_subject(args.subject)
            print(f"Revoked {count} sign-in(s) of {args.subject}.", file=out)
        else:
            removed = store.purge(int(now()))
            summary = ", ".join(f"{count} {table}" for table, count in removed.items() if count)
            print(f"Pruned: {summary or 'nothing'}.", file=out)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_admin_script.py`
Expected: `6 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1252 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add server/scripts/admin.py server/tests/unit/test_admin_script.py
git commit -m "feat(hosted): admin script for usage, bans, sign-outs and pruning" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 17: Final verification and pull request

- [ ] **Step 1: Everything green**

Run: `uv run --directory server pytest -q`
Expected: `1252 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 2: Scope check.** Only the files listed in this plan changed:

````bash
git diff --stat origin/main...HEAD
````

Expected: 47 files. Under `server/src/realoem_mcp/`: 15 new files (10 in `auth/`, counting its
`__init__.py`, plus `storage_guard.py`, `rate_limit.py`, `log_privacy.py`, `http_middleware.py`
and `http_app.py`) and 6 modified (`config.py`, `quota.py`, `services.py`, `shared.py`,
`vehicle_index.py`, `tools/vehicles.py`); `server/scripts/admin.py`; `server/pyproject.toml` and
`server/uv.lock`; under `server/tests/`, 4 helpers and 19 test files. Nothing under `brands/`,
`docs/`, `skills/` or `.claude-plugin/`; versions unchanged.

- [ ] **Step 3: Run the server locally and look at it.** No request leaves the machine: the
  public URL is loopback and nobody signs in. In one terminal:

````bash
export REALOEM_PUBLIC_URL=http://localhost:8080 REALOEM_GITHUB_CLIENT_ID=dev REALOEM_GITHUB_CLIENT_SECRET=dev
export REALOEM_SECRET_KEY="$(uv run --directory server python -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())')"
export REALOEM_CACHE_DIR="$(mktemp -d)" REALOEM_DATA_DIR="$(mktemp -d)"
uv run --directory server realoem-mcp-http
````

In another terminal (expected: `ok`, the discovery JSON with `"scopes_supported":["realoem"]`, and
`401`), then stop the server with Ctrl+C:

````bash
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/.well-known/oauth-authorization-server
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/mcp -H "Content-Type: application/json" -d "{}"
````

The server's log shows one line per request, such as `GET /healthz 200 1 ms`, and no query
strings.

- [ ] **Step 4: Push and open the pull request** (only when the controller asks you to; otherwise
  stop here and report):

````bash
git push -u origin feat/hosted-sign-in
gh pr create --base main --head feat/hosted-sign-in \
  --title "feat: hosted server sign-in with GitHub and the HTTP app" \
  --body-file - <<'EOF'
## Summary

Plan 1b of the hosted server (spec: docs/superpowers/specs/2026-10-01-hosted-server-design.md).
Puts plan 1a's shared mode behind GitHub sign-in and serves it over streamable HTTP. Nothing is
deployed yet (plan 2); the stdio server is unchanged.

- OAuth 2.1 authorization server on the MCP SDK: dynamic client registration limited to Claude's
  callback and loopback programs, consent before GitHub (CSRF-bound), PKCE, one-time codes,
  rotating refresh tokens with replay detection, at most 20 sign-ins per user, bans.
- auth.sqlite3 with forward-only migrations; tokens and codes stored only as keyed hashes.
- Security headers, a request log without query strings, sign-in rate limits keyed on
  Fly-Client-IP, a pending-sign-in cap, and a log filter that keeps VINs out of every log line.
- A storage guard: a full disk frees the page cache and retries once; a second full disk or a
  damaged auth database exits so Fly restarts the server.
- realoem-mcp-http entry point and scripts/admin.py.

## Test plan

- [x] uv run pytest: 1252 passed, 6 deselected (195 new tests, offline: fake GitHub, canned pages)
- [x] ruff check and ruff format --check
- [x] Local run: /healthz, discovery and a 401 from /mcp
- [ ] CI green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
````
