# Hosted Server, Plan 2: Fly.io Deployment and the 0.2.0 Release Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the hosted server of plans 1a and 1b at `https://realoem-searcher.fly.dev` and release 0.2.0, whose plugin connects to it: the container image, `fly.toml`, the deploy and uptime workflows, the owner's one-time setup (GitHub OAuth Apps, the Fly app with its volume and secrets, a deploy token behind a protected environment), checks against the live Fly proxy, the plugin switch, the documentation and the release itself.

**Architecture:** One always-on Fly Machine (`shared-cpu-1x`, 512 MB) in `iad` with one 1 GB volume at `/data`, built from `server/Dockerfile` with the repository root as the build context; `.dockerignore` lets only `server/` and `brands/` in. The entry point hands the volume to the unprivileged `app` user and drops root before the server starts. A `v*` tag runs lint and the offline tests, then deploys with an app-scoped token kept in a GitHub environment that waits for the owner's approval; a scheduled workflow checks `/healthz` every 15 minutes. `plugin.json` changes from a local `uv` command to the hosted URL.

**Tech Stack:** Docker (`python:3.13-slim`, uv 0.11.13), Fly.io (flyctl, Machines, volumes, secrets), GitHub Actions (environments, tag rulesets), GitHub OAuth Apps, pytest + ruff. Spec: `docs/superpowers/specs/2026-10-01-hosted-server-design.md` (sections 4.10, 7, 8 and 10). Plans 1a and 1b (`docs/superpowers/plans/2026-10-01-hosted-shared-core.md` and `2026-10-01-hosted-sign-in.md`) must be merged first.

---

## Before you start

- **Who does what.** Every task heading names who does it:
  - **(agent)**: file changes in a git worktree, test first, as in plans 1a and 1b. A coding agent
    may do them.
  - **(owner)**: steps that need the maintainer's GitHub and Fly.io accounts, create or handle
    credentials, cost money or make something public. The maintainer does them. Claude (the
    controller) may explain a step, read its output and, when the owner asks, run `curl` checks
    against the hosted server. The owner runs `fly status` and `fly logs` and shares the output:
    Claude never runs flyctl on the owner's login (see **Fly account safety**). It never creates
    an account or an app, sees or types a secret, approves a deployment, merges a pull request or
    pushes a tag.
  - **(controller)**: the security review in Task 5, done by a reviewer the controller dispatches.
- **Fly account safety.**
  - `fly auth login` only for an owner step that needs it, and `fly auth logout` once that
    sitting's flyctl work is done (at the latest after Task 11 Step 2, and again after every later
    step that logs in), so no full-access Fly login stays on a machine where Claude runs commands.
  - Never `fly launch` (it writes its own `fly.toml` and can create resources; Tasks 2 and 7 do
    this by hand), `fly secrets set NAME=value` (the value lands in the shell history and any
    transcript; Task 7 imports the secrets from prompts), or `fly mcp server --claude` (it hands
    Claude flyctl on the owner's login). No organization-scoped tokens and no tokens without an
    expiry: the one token in this plan (Task 11) deploys only this app and expires in a year.
  - Fly's agent setup prompt is not used (reviewed 2026-10-02): it does the things above. These
    steps replace it.
- **RealOEM requests.** Only Tasks 8, 10 and 16 send requests to realoem.com, a few dozen at most,
  and only once the owner approves them at that step. Nothing else may, and `REALOEM_LIVE=1` is
  never set.
- **Order matters.** The server goes live and is checked (Chunk 2) before the plugin points at it
  (Chunk 3): until then, an install from this repository's marketplace would connect to a server
  that does not answer. The pull request of Chunk 1 is merged only in Task 11, once the server
  answers, so the uptime check never runs against a server that does not exist yet.
- Commands run from the **root of the worktree** the task names (Tasks 0 and 12 create them)
  unless a step says otherwise. Shell: Git Bash on Windows, or any POSIX shell. `fly` is flyctl
  (`fly version` 0.4 or later).
- TDD for the agent tasks: write the test, run it and see it fail for the stated reason, then
  implement and see it pass. The code blocks were run, task by task, on a clean worktree: with
  every agent task applied the suite is `1263 passed, 6 deselected` and ruff is clean. Copy code
  exactly. Tasks 13 and 14 change documentation only and have no tests.
- Commit messages are Conventional Commits, each ending with a blank line and a
  `Co-Authored-By:` trailer naming the model that wrote the change. The commit commands below show
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`:
  **replace the model name with your own**; that is the one thing in this plan not to copy
  literally. The owner's own commits need no trailer.
- Do not commit anything under `docs/superpowers/`. Versions stay `0.1.0` until Task 12.

## File structure

| File | Responsibility |
|---|---|
| `.dockerignore` | Only `server/` and `brands/` reach a build (never `.research-raw/`) |
| `server/Dockerfile` | The image: Python 3.13, the locked dependencies, `realoem-mcp-http` |
| `server/docker-entrypoint.sh` | Hands the volume to the `app` user, then drops root |
| `fly.toml` | One always-on machine, one volume, the health check, the restart policy |
| `.github/workflows/deploy.yml` | A `v*` tag: lint, offline tests, then a deploy the owner approves |
| `.github/workflows/uptime.yml` | `GET /healthz` every 15 minutes; a failure emails the owner |

Tests: `server/tests/unit/test_container.py`, `test_fly_config.py` and `test_workflows.py` (they
read the files as text; no Docker or YAML parser needed). Changed in Chunks 3 and 4:
`.claude-plugin/plugin.json` and `marketplace.json`, the version in `server/pyproject.toml`,
`server/uv.lock` and `realoem_mcp/__init__.py`, `test_manifests.py`, `test_package.py`,
`README.md`, `CHANGELOG.md`, `skills/vehicle-index/SKILL.md`, `skills/vin-decode/SKILL.md`,
`docs/ARD.md` and `docs/PRD.md`.

Outside the repository (owner, Chunk 2): two GitHub OAuth Apps, the Fly app `realoem-searcher` with
its volume `realoem_data` and four secrets, a Fly deploy token in the GitHub environment
`production`, and a tag ruleset for `v*`.

## Chunk 1: The image, Fly configuration and workflows

### Task 0: Branch and baseline (agent)

- [ ] **Step 1: Create the worktree from an up-to-date main.** The first line keeps `.worktrees/`
  out of `git status` in a fresh clone (a local setting, never committed).

````bash
git check-ignore -q .worktrees/ || echo ".worktrees/" >> .git/info/exclude
git fetch origin
git worktree add .worktrees/hosted-deploy -b feat/hosted-deploy --no-track origin/main
cd .worktrees/hosted-deploy
````

- [ ] **Step 2: Record the baseline**

Run: `uv run --directory server pytest -q`
Expected: `1257 passed, 6 deselected` (plans 1a and 1b merged). If not, stop and report.

### Task 1: The container image (agent)

The build context is the repository root, so `.dockerignore` decides what any build can see: it
starts from "nothing" and lets in only `server/` and `brands/`, minus the virtual environment, the
tests, caches, database files and `.env` files. Raw RealOEM captures in `.research-raw/` and local
secrets therefore never leave the maintainer's machine, even with a local `fly deploy` (hosted
design 4.10). The image installs the locked dependencies first (a layer that code changes reuse),
then the project, keeps no uv download cache, and creates the `app` user (uid 10001, no login
shell). It starts as root only because Fly mounts the volume owned
by root: `docker-entrypoint.sh` creates `/data/cache` and `/data/data`, hands `/data` to `app`
(files an earlier run or a root shell left behind included) and replaces itself with the server
running as `app` (`setpriv` is part of the base image). The repository's `.gitattributes` keeps
the script's line endings LF on Windows too, which a shell script needs inside Linux; the test
checks the bytes. The owner builds and runs the image in Task 8.

**Files:**
- Create: `.dockerignore`, `server/Dockerfile`, `server/docker-entrypoint.sh`
- Test: `server/tests/unit/test_container.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_container.py`:

````python
"""The hosted server's image: what goes in, and how it runs (hosted design 4.10)."""

from tests.harness import REPO_ROOT

DOCKERFILE = (REPO_ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "server" / "docker-entrypoint.sh").read_text(encoding="utf-8")
DOCKERIGNORE = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_only_server_and_brands_reach_the_image() -> None:
    lines = [line for line in _lines(DOCKERIGNORE) if not line.startswith("#")]
    assert lines[0] == "*"  # everything is left out unless listed below
    assert [line for line in lines if line.startswith("!")] == ["!server/", "!brands/"]
    assert {"server/.venv/", "server/tests/", "**/.env*"} <= set(lines)


def test_the_image_runs_the_http_server_as_the_app_user() -> None:
    lines = [line for line in _lines(DOCKERFILE) if not line.startswith("#")]
    assert lines[0] == "FROM python:3.13-slim"
    assert "COPY server/ ./" in lines and "COPY brands/ /app/brands/" in lines
    assert "RUN uv sync --frozen --no-dev --no-install-project" in lines
    assert 'ENTRYPOINT ["/app/server/docker-entrypoint.sh"]' in lines
    assert lines[-1] == 'CMD ["realoem-mcp-http"]'
    assert "USER root" not in lines
    assert ENTRYPOINT.startswith("#!/bin/sh\n")
    # read_text() hides CRLF line endings, which would break the script inside Linux.
    assert b"\r" not in (REPO_ROOT / "server" / "docker-entrypoint.sh").read_bytes()
    assert _lines(ENTRYPOINT)[-1] == 'exec setpriv --reuid=app --regid=app --init-groups -- "$@"'
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_container.py`
Expected: FAIL during collection: `FileNotFoundError` (there is no `server/Dockerfile` yet).

- [ ] **Step 3: Write** `.dockerignore`:

````text
# Only server/ and brands/ go into the image (hosted design 4.10). Everything else, raw RealOEM
# captures in .research-raw/ above all, stays out of every build context, local or remote.
*
!server/
!brands/
server/.venv/
server/tests/
**/__pycache__/
**/.pytest_cache/
**/.ruff_cache/
**/*.sqlite3*
**/*.db
**/.env*
````

- [ ] **Step 4: Write** `server/Dockerfile`:

````dockerfile
# The hosted RealOEM Searcher server (hosted design 4.10). Build from the repository root:
#   docker build -f server/Dockerfile -t realoem-searcher .
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app/server
# Dependencies first, so a code change reuses this layer.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./
COPY brands/ /app/brands/
RUN uv sync --frozen --no-dev \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && chmod 0755 /app/server/docker-entrypoint.sh

ENV PATH="/app/server/.venv/bin:$PATH" \
    REALOEM_BRANDS_DIR=/app/brands \
    REALOEM_CACHE_DIR=/data/cache \
    REALOEM_DATA_DIR=/data/data
EXPOSE 8080
# Starts as root only to hand the volume to the app user, then drops root for good.
ENTRYPOINT ["/app/server/docker-entrypoint.sh"]
CMD ["realoem-mcp-http"]
````

- [ ] **Step 5: Write** `server/docker-entrypoint.sh`:

````sh
#!/bin/sh
# Fly mounts the volume at /data owned by root. Give it to the app user (files an earlier run or
# a root shell left behind included), then run the server as that user, never as root.
set -eu
mkdir -p /data/cache /data/data
chown -R app:app /data
exec setpriv --reuid=app --regid=app --init-groups -- "$@"
````

- [ ] **Step 6: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_container.py`
Expected: `2 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1259 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add .dockerignore server/Dockerfile server/docker-entrypoint.sh server/tests/unit/test_container.py
git commit -m "feat(deploy): container image for the hosted server" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 2: Fly configuration (agent)

`fly.toml` at the repository root describes one always-on machine (hosted design H3, 4.10):
`auto_stop_machines = "off"` and `min_machines_running = 1`, because tokens, pending sign-ins and
the RealOEM request lock live in one process and on one volume; request concurrency 100 soft and
200 hard; a `/healthz` check, which only tells Fly's proxy where to route and never heals anything;
and `on-failure` restarts, at most 10. After that a crash loop leaves the machine stopped, and
`auto_start_machines = false` keeps it stopped (otherwise the next request, the uptime check's
included, would start it again), so the uptime check (Task 3) notices. A deploy does not start it
either: once the cause is fixed, the owner runs `fly machine start`. A tool call answers with
one JSON body at its end, so its connection stays quiet for up to the 50-second call limit plus one
slow RealOEM response; `idle_timeout = 180` keeps Fly's proxy from closing it (its default is 60
seconds). The volume `realoem_data` is mounted at `/data`. `REALOEM_PUBLIC_URL` is set here rather
than as a secret: it is not secret, and since it is the OAuth issuer (changing it signs everyone
out), a change to it should go through review. The test checks the `[env]` entries by inclusion,
so another (a different call limit, say) can join them. The four secrets are set by the owner
(Task 7). Every deploy passes `--ha=false`, which keeps the app at one machine.

**Files:**
- Create: `fly.toml`
- Test: `server/tests/unit/test_fly_config.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_fly_config.py`:

````python
"""fly.toml: one always-on machine with one volume (hosted design H3, 4.10)."""

import tomllib

from tests.harness import REPO_ROOT

FLY = tomllib.loads((REPO_ROOT / "fly.toml").read_text(encoding="utf-8"))


def test_one_always_on_machine_with_one_volume() -> None:
    assert FLY["app"] == "realoem-searcher"
    service = FLY["http_service"]
    assert (service["internal_port"], service["force_https"]) == (8080, True)
    assert (service["auto_stop_machines"], service["min_machines_running"]) == ("off", 1)
    assert service["auto_start_machines"] is False  # a crash-looped machine stays stopped
    assert service["http_options"] == {"idle_timeout": 180}  # past a 50 s call and a slow fetch
    assert service["concurrency"] == {"type": "requests", "soft_limit": 100, "hard_limit": 200}
    (check,) = service["checks"]
    assert (check["method"], check["path"]) == ("GET", "/healthz")
    assert FLY["mounts"] == [{"source": "realoem_data", "destination": "/data"}]
    assert FLY["restart"] == [{"policy": "on-failure", "retries": 10}]
    assert FLY["vm"] == [{"size": "shared-cpu-1x", "memory": "512mb"}]
    assert FLY["build"] == {"dockerfile": "server/Dockerfile"}


def test_the_server_keeps_its_data_on_the_volume() -> None:
    # Other settings (a different call limit, say) may join these.
    assert (
        FLY["env"].items()
        >= {
            "REALOEM_PUBLIC_URL": "https://realoem-searcher.fly.dev",
            "REALOEM_CACHE_DIR": "/data/cache",
            "REALOEM_DATA_DIR": "/data/data",
            "REALOEM_BRANDS_DIR": "/app/brands",
        }.items()
    )
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_fly_config.py`
Expected: FAIL during collection: `FileNotFoundError` (there is no `fly.toml` yet).

- [ ] **Step 3: Write** `fly.toml`:

````toml
# The hosted RealOEM Searcher server on Fly.io (hosted design H3, 4.10): one always-on machine with
# one volume. Deploy from the repository root, always as one machine:
#   flyctl deploy --ha=false
app = "realoem-searcher"
primary_region = "iad"

[build]
  dockerfile = "server/Dockerfile"

[env]
  REALOEM_PUBLIC_URL = "https://realoem-searcher.fly.dev"
  REALOEM_CACHE_DIR = "/data/cache"
  REALOEM_DATA_DIR = "/data/data"
  REALOEM_BRANDS_DIR = "/app/brands"

[[mounts]]
  source = "realoem_data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  # Always on. A crash loop that uses up the restarts below leaves the machine stopped, and
  # neither a request nor a deploy starts it again, so the uptime check notices. Once the cause is
  # fixed: fly machine start <id> --app realoem-searcher
  auto_stop_machines = "off"
  auto_start_machines = false
  min_machines_running = 1

  # A tool call answers with one JSON body at its end: up to the 50 s call limit plus one slow
  # RealOEM response (20 s timeout, retried). Keep such a quiet connection open well past that.
  [http_service.http_options]
    idle_timeout = 180

  [http_service.concurrency]
    type = "requests"
    soft_limit = 100
    hard_limit = 200

  [[http_service.checks]]
    method = "GET"
    path = "/healthz"
    interval = "30s"
    timeout = "5s"
    grace_period = "10s"

[[restart]]
  policy = "on-failure"
  retries = 10

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
````

- [ ] **Step 4: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_fly_config.py`
Expected: `2 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1261 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add fly.toml server/tests/unit/test_fly_config.py
git commit -m "feat(deploy): fly.toml for one always-on machine with one volume" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 3: The deploy and uptime workflows (agent)

`deploy.yml` runs on a `v*` tag. CI (`ci.yml`) does not run on tags, so the workflow repeats lint
and the offline tests (Ubuntu, Python 3.13) before it deploys. The deploy job uses the `production`
environment, which holds `FLY_API_TOKEN` (a deploy token for this one app) and waits for the
owner's approval (Task 11). `flyctl` comes from `superfly/flyctl-actions/setup-flyctl`, pinned to
the commit of its release 1.6, and the action installs flyctl 0.4.111, not the latest: the job
holds a deploy token. `--remote-only` builds on Fly's builder and `--ha=false` keeps one machine.
Deploys never overlap: a running deploy finishes, and of several waiting tags the newest deploys.
The test also checks that the workflow's `on:` block is a push of a `v*` tag and nothing else.

`uptime.yml` fetches `/healthz` every 15 minutes, with retries so a deploy's restart does not count
as an outage. When a run fails, GitHub emails the account that last changed the schedule. It needs
no permissions. GitHub disables scheduled workflows in a public repository after 60 days without
activity in the repository; `gh workflow enable uptime.yml` turns it back on.

**Files:**
- Create: `.github/workflows/deploy.yml`, `.github/workflows/uptime.yml`
- Test: `server/tests/unit/test_workflows.py`

- [ ] **Step 1: Write the failing test** `server/tests/unit/test_workflows.py`:

````python
"""The deploy and uptime workflows (hosted design 4.10).

Checked line by line: no YAML parser is a dependency, and GitHub validates the syntax when a
workflow runs.
"""

import re

from tests.harness import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _lines(name: str) -> list[str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_a_tag_deploys_after_the_offline_tests() -> None:
    lines = _lines("deploy.yml")
    assert 'tags: ["v*"]' in lines
    for step in ("run: uv run ruff check", "run: uv run ruff format --check"):
        assert step in lines
    assert 'run: uv run pytest -m "not live"' in lines
    assert "needs: test" in lines and "environment: production" in lines
    assert "run: flyctl deploy --remote-only --ha=false" in lines
    assert "FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}" in lines
    setup = next(line for line in lines if "setup-flyctl@" in line)
    assert len(setup.split("@")[1].split()[0]) == 40  # pinned to a commit
    assert any(re.fullmatch(r"version: \d+\.\d+\.\d+", line) for line in lines)  # and flyctl
    # Only a pushed v* tag deploys: no other trigger, and no branch filter.
    assert lines[lines.index("on:") + 1 : lines.index("permissions:")] == ["push:", 'tags: ["v*"]']


def test_an_uptime_check_watches_the_health_endpoint() -> None:
    lines = _lines("uptime.yml")
    assert '- cron: "*/15 * * * *"' in lines
    assert "https://realoem-searcher.fly.dev/healthz" in lines
````

- [ ] **Step 2: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_workflows.py`
Expected: FAIL: both tests, with `FileNotFoundError` (no workflow files yet).

- [ ] **Step 3: Write** `.github/workflows/deploy.yml`:

````yaml
name: Deploy

# A v* tag deploys the hosted server to Fly.io (hosted design 4.10). CI does not run on tags, so
# this workflow runs the lint and the offline tests itself before deploying.
on:
  push:
    tags: ["v*"]

permissions:
  contents: read

concurrency:
  group: deploy
  cancel-in-progress: false

jobs:
  test:
    name: Lint and offline tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: server
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.13"
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

  deploy:
    name: Deploy to Fly.io
    needs: test
    runs-on: ubuntu-latest
    # The environment holds FLY_API_TOKEN (an app-scoped deploy token) and requires a reviewer.
    environment: production
    steps:
      - uses: actions/checkout@v7
      - uses: superfly/flyctl-actions/setup-flyctl@ed8efb33836e8b2096c7fd3ba1c8afe303ebbff1 # 1.6
        with:
          version: 0.4.111
      - name: Deploy (one machine)
        run: flyctl deploy --remote-only --ha=false
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
````

- [ ] **Step 4: Write** `.github/workflows/uptime.yml`:

````yaml
name: Uptime

# Checks the hosted server every 15 minutes (hosted design 4.10). A failed run emails the owner:
# GitHub notifies the account that last changed this schedule. After 10 restarts in a crash loop
# Fly leaves the machine stopped, and this check is how the owner finds out.
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:

permissions: {}

jobs:
  healthz:
    name: GET /healthz
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - name: The server answers
        run: >-
          curl --fail --silent --show-error --max-time 10
          --retry 3 --retry-delay 20 --retry-all-errors
          https://realoem-searcher.fly.dev/healthz
````

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_workflows.py`
Expected: `2 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1263 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Commit**

````bash
git add .github/workflows/deploy.yml .github/workflows/uptime.yml server/tests/unit/test_workflows.py
git commit -m "ci: deploy on a v* tag after the offline tests, and an uptime check" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 4: Final checks and the pull request (agent)

- [ ] **Step 1: Everything green**

Run: `uv run --directory server pytest -q`
Expected: `1263 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 2: Scope check.** Only the files of Tasks 1 to 3 changed:

````bash
git diff --stat origin/main...HEAD
````

Expected: 9 files: `.dockerignore`, `fly.toml`, the two workflows, `server/Dockerfile`,
`server/docker-entrypoint.sh` and the three test files.

- [ ] **Step 3: Push and open the pull request** (only when the controller asks you to; otherwise
  stop here and report). **Do not merge it**: the owner merges it in Task 11, after the first
  deploy.

````bash
git push -u origin feat/hosted-deploy
gh pr create --base main --head feat/hosted-deploy \
  --title "feat(deploy): container image, fly.toml, deploy and uptime workflows" \
  --body-file - <<'EOF'
## Summary

Plan 2, chunk 1, of the hosted server (spec: docs/superpowers/specs/2026-10-01-hosted-server-design.md,
section 4.10). Merging deploys nothing: a deploy runs only on a v* tag, after the owner approves it.

- .dockerignore lets only server/ and brands/ into a build (never .research-raw/).
- server/Dockerfile and docker-entrypoint.sh: Python 3.13 with the locked dependencies; the server
  runs as an unprivileged user, and the entry point hands the Fly volume to it.
- fly.toml: one always-on machine with one volume, a /healthz check, restart on failure.
- deploy.yml (v* tag: lint, offline tests, then an approved deploy) and uptime.yml (/healthz every
  15 minutes).

## Test plan

- [x] uv run pytest: 1263 passed, 6 deselected (6 new tests)
- [x] ruff check and ruff format --check
- [ ] Owner: image built and run locally (plan 2, Task 8)
- [ ] Owner: first deploy from this branch (plan 2, Task 9), then merge (Task 11)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
````

## Chunk 2: Setup, the first deploy and live checks

### Task 5: Security review before going public (controller)

Spec section 7 asks for a security review of the sign-in code before release. It comes before the
first deploy, because the deploy makes the server reachable. The controller dispatches one
reviewer (model: Opus) on an up-to-date checkout of `main` that has the branch of Chunk 1 merged
into it locally (not pushed), with this prompt:

````text
You are reviewing the hosted RealOEM Searcher server for security defects before it is deployed
publicly at https://realoem-searcher.fly.dev. The checkout is at <path>. Read-only: change no file in the
checkout, and send no request to realoem.com, GitHub or the hosted server.

Scope: server/src/realoem_mcp/auth/ (every file), current_user.py, quota.py, gate.py, cache.py
(VIN pages kept per user), tools/admin.py (cache_clear's admin check), http_middleware.py,
http_app.py, log_privacy.py, storage_guard.py, config.py (the HTTP settings), server/scripts/admin.py,
server/Dockerfile, server/docker-entrypoint.sh, fly.toml, .dockerignore and
.github/workflows/deploy.yml.

Check them against: the spec docs/superpowers/specs/2026-10-01-hosted-server-design.md (sections
4.2 to 4.10, 6 and 7); the Authorization section and the Security Best Practices of the MCP
specification (modelcontextprotocol.io): confused deputy, token passthrough, session hijacking;
OAuth 2.1 (PKCE, exact redirect URI matching, single-use codes, refresh token rotation); and the
OWASP basics for the consent and error pages (CSRF, clickjacking, XSS, open redirects).

Look in particular for: a way to get a token for another user's GitHub identity; a redirect to a
URI outside the allow-list; a token, code, secret or VIN reaching a log line or a page; a limit
(quota, rate limit, body size, pending sign-ins) a client can get around; a database error that
leaves a credential usable or the server in a bad state; a secret in the image or the build
context; anything in the deploy workflow that would let a pull request or a forged tag deploy.

Report each finding as: severity (Critical, High, Medium or Low), file:line, what is wrong, a
concrete exploit or failure scenario, and the fix. Confirm every finding by following the code path
end to end (running the offline tests or a scratch script in a temporary directory if that helps);
report nothing you have not confirmed. End with what you checked and found sound.
````

- [ ] **Step 1: Run the review** and give the owner its findings.
- [ ] **Step 2: Fix before going public.** Each Critical or High finding is fixed before Task 9,
  test first (a test that fails on the defect). A finding in a file of Chunk 1 (`server/Dockerfile`,
  `server/docker-entrypoint.sh`, `fly.toml`, `.dockerignore`, the workflows) is fixed as a commit
  on `feat/hosted-deploy` and pushed to its open pull request; any other finding on its own branch
  from `main`, reviewed and merged like any change. The reviewer then confirms each fix. The owner
  decides about Medium and Low findings: fix now, or open an issue.

### Task 6: GitHub OAuth Apps (owner)

The server signs users in through a GitHub OAuth App (not a GitHub App). It asks for no scope, so it
reads only the public profile, and GitHub's sign-in page shows the app's name and owner. An OAuth
App takes one callback URL, so local runs need a second app (hosted design 4.10).

- [ ] **Step 1: The production app.** Signed in to GitHub as `Cadtastic` (the repository's owner),
  open <https://github.com/settings/developers>, **OAuth Apps**, **New OAuth App**:
  - Application name: `RealOEM Searcher`
  - Homepage URL: `https://github.com/Cadtastic/RealOEM-Searcher`
  - Application description: `Sign in to the hosted RealOEM Searcher server. Only the id, username
    and creation date of your public GitHub profile are read.`
  - Authorization callback URL: `https://realoem-searcher.fly.dev/oauth/github/callback`
  - Enable Device Flow: off

  **Register application**, then **Generate a new client secret**. Leave the page open for Task 7:
  GitHub shows the secret only once. Paste it nowhere else (no chat, file or pull request).

- [ ] **Step 2: The development app**, the same way: name `RealOEM Searcher (dev)`, the same
  homepage, callback `http://localhost:8080/oauth/github/callback`. Generate a secret and keep it,
  with the app's client ID, in your password manager for Task 8 and later local runs.

### Task 7: The Fly app, its volume and secrets (owner)

- [ ] **Step 1: Create the app.** The Fly account needs a payment method (pay as you go; one
  `shared-cpu-1x` machine with 512 MB and a 1 GB volume cost a few dollars a month).

````bash
fly auth login
fly apps create realoem-searcher
````

Expected: `New app created: realoem-searcher`. If the name is taken, stop: the hostname is in the
spec, the OAuth App and `fly.toml`, and choosing another means changing all three.

- [ ] **Step 2: The volume**

````bash
fly volumes create realoem_data --app realoem-searcher --region iad --size 1 --yes
````

Expected: a 1 GB volume `realoem_data` in `iad` with daily snapshots, kept 5 days (Fly's defaults,
the backup the design relies on). `--yes` accepts flyctl's warning that one volume has no
redundancy: one machine with one volume is the design (H3).

- [ ] **Step 3: The secrets.** `--stage` stores them without starting anything; the first deploy
  picks them up. The values never appear on screen or in the shell history: two are typed at
  prompts, the key is generated, and the numeric id of the `Cadtastic` GitHub account
  (`REALOEM_ADMINS`, which may clear the cache) comes from `gh`. Nothing is stored if a value is
  missing.

````bash
read -r -p "Production OAuth App client ID: " GH_ID
read -r -s -p "Production OAuth App client secret: " GH_SECRET; echo
ADMIN_ID="$(gh api users/Cadtastic --jq .id)"
if [ -n "$GH_ID" ] && [ -n "$GH_SECRET" ] && [ -n "$ADMIN_ID" ]; then
  {
    printf 'REALOEM_GITHUB_CLIENT_ID=%s\n' "$GH_ID"
    printf 'REALOEM_GITHUB_CLIENT_SECRET=%s\n' "$GH_SECRET"
    printf 'REALOEM_SECRET_KEY=%s\n' "$(openssl rand -base64 32)"
    printf 'REALOEM_ADMINS=%s\n' "$ADMIN_ID"
  } | fly secrets import --app realoem-searcher --stage
else
  echo "A value is missing; nothing was stored."
fi
unset GH_ID GH_SECRET ADMIN_ID
fly secrets list --app realoem-searcher
````

Expected: the four names, with digests but never values. Nobody needs the secret key again:
changing it later signs every user out.

### Task 8: Build and run the image locally (owner)

Needs Docker Desktop. The build downloads the `python:3.13-slim` and uv images and the locked
Python packages. Step 4 sends one or two RealOEM requests, once the owner approves. Work in the
worktree of Task 0, after Task 4. The first line below keeps Git Bash from rewriting paths such as
`/data` before Docker sees them (it changes nothing elsewhere).

- [ ] **Step 1: Build, and look inside**

````bash
export MSYS_NO_PATHCONV=1
docker build -f server/Dockerfile -t realoem-searcher:dev .
docker run --rm --entrypoint sh realoem-searcher:dev -c "ls -A /app /app/server; id app"
````

Expected: the build succeeds; `/app` holds only `brands` and `server`; `/app/server` holds
`.venv`, `Dockerfile`, `docker-entrypoint.sh`, `pyproject.toml`, `scripts`, `src` and `uv.lock`
(no `tests`); `id` shows `uid=10001(app)`.

- [ ] **Step 2: Run it with the development OAuth App.** In the same terminal (the client ID and
  secret are typed at prompts):

````bash
read -r -p "Dev OAuth App client ID: " REALOEM_GITHUB_CLIENT_ID
read -r -s -p "Dev OAuth App client secret: " REALOEM_GITHUB_CLIENT_SECRET; echo
REALOEM_SECRET_KEY="$(openssl rand -base64 32)"
export REALOEM_GITHUB_CLIENT_ID REALOEM_GITHUB_CLIENT_SECRET REALOEM_SECRET_KEY
docker run --rm --name realoem-dev -p 8080:8080 -v realoem-dev-data:/data \
  -e REALOEM_PUBLIC_URL=http://localhost:8080 -e REALOEM_GITHUB_CLIENT_ID \
  -e REALOEM_GITHUB_CLIENT_SECRET -e REALOEM_SECRET_KEY realoem-searcher:dev
````

Expected: the server starts on port 8080 without errors.

- [ ] **Step 3: Look at it** from another terminal:

````bash
curl -s http://localhost:8080/healthz; echo
curl -s http://localhost:8080/.well-known/oauth-authorization-server; echo
docker top realoem-dev
````

Expected: `ok`; the discovery JSON with `"scopes_supported":["realoem"]`; the server process runs
as UID 10001, not root.

- [ ] **Step 4: Sign in from Claude Code and make one lookup** (one or two RealOEM requests: the
  owner approves them now). If the 0.1.0 plugin is installed, disable it in `/plugin` for Tasks 8
  and 10, so Claude cannot use its local server by mistake. Then, in the worktree of Task 0:

````bash
claude mcp add --transport http realoem-dev http://localhost:8080/mcp
````

Start a **new** Claude Code session in that same directory (a server added this way belongs to the
directory, and a session already running does not see it), then `/mcp`, `realoem-dev`,
**Authenticate**. The consent page names "A program on this computer" and shows Claude Code's
loopback redirect URI; **Allow** leads to GitHub's page for "RealOEM Searcher (dev)" and back. Ask
Claude to run realoem-dev's `server_status`, and to look up part 11427953129 with realoem-dev.
Expected: `server_status` shows `cache_path` null and your daily quota; the lookup answers with its
source URL; the container log shows one line per request, with `github:<your id>` on the `/mcp`
lines and no query strings or tokens.

- [ ] **Step 5: MCP Inspector in proxy mode** (spec section 7).
  `npx @modelcontextprotocol/inspector` downloads and starts it. In its page: transport
  **Streamable HTTP**, URL `http://localhost:8080/mcp`, connection type **Via Proxy**, **Connect**,
  and sign in again. Expected: **List Tools** shows 13 tools, and `server_status` runs.

- [ ] **Step 6: Clean up.** Stop the inspector and the container (Ctrl+C). In the container's
  terminal, forget the development secrets, then remove the test connection and the volume:

````bash
unset REALOEM_GITHUB_CLIENT_ID REALOEM_GITHUB_CLIENT_SECRET REALOEM_SECRET_KEY MSYS_NO_PATHCONV
claude mcp remove realoem-dev
docker volume rm realoem-dev-data
````

### Task 9: The first deploy (owner)

After Task 5's Critical and High findings are fixed. Work in the worktree of Task 0. It must be
clean (`git status --short` prints nothing; `.dockerignore` keeps ignored local files such as
`.env` out of the build), the pull request's CI green, and the branch must contain every fix. If a
fix was merged into `main` after Task 4:

````bash
git fetch origin
git merge --no-edit origin/main
git push
git log --oneline -10
````

Expected: the log shows each fix commit. Wait for the pull request's CI to pass again before
Step 1.

- [ ] **Step 1: Deploy**

````bash
fly deploy --app realoem-searcher --remote-only --ha=false
````

Expected: Fly's builder builds the image, the machine starts, and the output ends with the app's
URL, `https://realoem-searcher.fly.dev/`.

- [ ] **Step 2: From outside** (the controller may run these when asked):

````bash
fly status --app realoem-searcher
curl -s https://realoem-searcher.fly.dev/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://realoem-searcher.fly.dev/healthz
curl -sI https://realoem-searcher.fly.dev/healthz | grep -i strict-transport-security
curl -s https://realoem-searcher.fly.dev/.well-known/oauth-authorization-server; echo
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://realoem-searcher.fly.dev/mcp -H "Content-Type: application/json" -d "{}"
````

Expected: one machine, `started`, its check passing; `ok`; a redirect (`301`) to the `https://`
address; `strict-transport-security: max-age=31536000`; the discovery JSON with
`"authorization_endpoint":"https://realoem-searcher.fly.dev/authorize"` and
`"scopes_supported":["realoem"]`; `401`.

- [ ] **Step 3: From inside**

````bash
fly logs --app realoem-searcher --no-tail | tail -80
fly ssh console --app realoem-searcher -C "ls -ln /data /data/data"
fly ssh console --app realoem-searcher -C "setpriv --reuid=app --regid=app --init-groups -- /app/server/.venv/bin/python /app/server/scripts/admin.py usage"
````

Expected: the log shows the start-up and one line per request above, with no query strings (Fly's
health check adds a `GET /healthz 200` line every 30 seconds); `/data/cache` and `/data/data`
belong to uid 10001, and `/data/data` holds `auth.sqlite3`; the admin script prints
`Auth database: /data/data/auth.sqlite3` and an empty usage table. If it prints
`No auth database at …` instead, the SSH session lacks the app's environment: run it again with
`env REALOEM_DATA_DIR=/data/data` before the Python path, and tell the controller, so Task 13 puts
that form in the README.

### Task 10: Checks against the live proxy (owner)

Three questions spec section 10 leaves open are answered here, and the sign-in is tried from both
kinds of client, before the plugin points at the server. Step 3 sends about 25 RealOEM requests
(about 50 if it has to be repeated): the owner approves them at that step.

- [ ] **Step 1: Sign in from Claude Code.** In the worktree of Task 0 (Step 6 removes the server
  there again):

````bash
claude mcp add --transport http realoem-live https://realoem-searcher.fly.dev/mcp
````

In a **new** Claude Code session in that directory: `/mcp`, `realoem-live`, **Authenticate**,
**Allow**, GitHub's page for "RealOEM Searcher", and back. Ask for realoem-live's `server_status`.
Expected: `cache_path` null and your daily quota, and `POST /mcp 200 … github:<your id>` in
`fly logs`.

- [ ] **Step 2: Sign in from claude.ai**, the path chat and Cowork use (Claude's own callback,
  `https://claude.ai/api/mcp/auth_callback`). In claude.ai: **Customize**, **Connectors**, add a
  custom connector named `RealOEM Searcher (test)` with the URL
  `https://realoem-searcher.fly.dev/mcp`, and **Connect**. Expected: the consent page names "Claude
  (claude.ai)"; after **Allow** and GitHub, the connector shows as connected, and in a new chat
  with it enabled `server_status` answers with your quota.

- [ ] **Step 3: A 50-second call survives Fly's proxy.** The server answers a tool call with one
  JSON body at the end, so the connection carries nothing while the call runs; `fly.toml` raises
  the proxy's idle timeout to 180 seconds for this. In the Claude Code session of Step 1, ask:
  "Make exactly one realoem-live compare_vehicles call with vehicle_a
  VA33-USA-03-2006-E90-BMW-328i, vehicle_b WB73-USA-06-2005-E92-BMW-335i, main group 11 and
  max_requests 60, and do not call compare_vehicles again." (Both ids are in the vehicle index, so
  no lookup is needed.) If Claude starts a second `compare_vehicles` call, stop it (Esc).
  Expected: after 50 to 75 seconds Claude Code gets a partial comparison (`complete` false,
  `stopped_reason` the time-limit message), and
  `fly logs` shows `POST /mcp 200` with a duration of at least 50,000 ms (longer is fine: a
  RealOEM retry near the end can add seconds). A shorter duration means
  the call never reached the limit (its pages were already cached): repeat with main group 61
  (general vehicle electrical system, dozens of diagrams on both cars). If instead the call fails
  (a `502`, a timeout or a closed connection) while the log shows the request finishing later,
  the proxy closed the connection: in the worktree of Task 0, add `REALOEM_CALL_DEADLINE_S = "40"`
  under `[env]` in `fly.toml`, commit it to `feat/hosted-deploy`, push, wait for green CI, run
  `fly deploy --app realoem-searcher --remote-only --ha=false` there, repeat the call that failed
  (most of its diagrams are still uncached) expecting at least 40,000 ms, and tell the
  controller, so Task 13 documents the 40 seconds.

- [ ] **Step 4: Fly overwrites a forged `Fly-Client-IP`**, so the sign-in limits count real
  addresses. Do this last: it uses up your address's registrations for the next hour.

````bash
for i in $(seq 1 31); do
  curl -s -o /dev/null -w "%{http_code} " -X POST https://realoem-searcher.fly.dev/register \
    -H "Content-Type: application/json" -H "Fly-Client-IP: 203.0.113.$i" \
    -d '{"redirect_uris":["http://localhost:33418/callback"],"client_name":"forged address check"}'
done; echo
````

Expected: `201` for each registration your address has left this hour (30 minus those it already
made, Step 1's sign-in included), then only `429`: every request counted against your real
address. If all 31 are `201`, the proxy passes a forged header through and anyone could get around
the per-address limits: stop, do not release, and tell the controller (the limits must then key on
another source of the address, a code change with its own tests). The test clients are deleted by
the hourly purge once they go unused.

- [ ] **Step 5: Each client has its own address.** A missing header would make the server see the
  proxy's address for everyone, which the loop above cannot tell apart. Run this once on the same
  network, then once from a second network (a phone's hotspot, say):

````bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://realoem-searcher.fly.dev/register -H "Content-Type: application/json" \
  -d '{"redirect_uris":["http://localhost:33418/callback"],"client_name":"second address check"}'
````

Expected: `429` on the first network, `201` on the second. If the second network also gets `429`,
the server sees one address for everyone: stop, do not release, and tell the controller.

- [ ] **Step 6: Remove the test connections**: in claude.ai, remove the connector of Step 2; then,
  in the worktree of Task 0:

````bash
claude mcp remove realoem-live
````

and re-enable the 0.1.0 plugin if you disabled it. Whether Claude ever refreshes a token twice at
once (spec section 10) shows only over days of real use; Task 16 watches for it.

### Task 11: The deploy pipeline, the merge and the message to RealOEM (owner)

- [ ] **Step 1: The `production` environment.** In the repository: **Settings**, **Environments**,
  **New environment**, name `production`:
  - **Required reviewers**: yourself. Leave **Prevent self-review** off (you are the only
    reviewer).
  - **Deployment branches and tags**: **Selected branches and tags**, **Add deployment branch or
    tag rule**, ref type **Tag**, name pattern `v*`, **Add rule**.
  - **Save protection rules**.

- [ ] **Step 2: The deploy token**, straight into the environment without being shown. The `case`
  checks that flyctl printed nothing but a token before it is stored.

````bash
TOKEN="$(fly tokens create deploy --app realoem-searcher --name github-actions-deploy --expiry 8760h)"
case "$TOKEN" in
  "FlyV1 "*) printf '%s' "$TOKEN" | gh secret set FLY_API_TOKEN --env production --repo Cadtastic/RealOEM-Searcher ;;
  *) echo "Unexpected output from fly tokens create; nothing stored." ;;
esac
unset TOKEN
gh secret list --env production --repo Cadtastic/RealOEM-Searcher
````

Expected: `FLY_API_TOKEN` in the list. The token can deploy only this app and expires in a year;
renew it the same way (a deploy after it expires fails with an authentication error). If the
`case` reports unexpected output, a token was still created: find it with
`fly tokens list --app realoem-searcher` and revoke it with `fly tokens revoke <id>` before
trying again. The setup is done: sign flyctl out (see **Fly account safety**).

````bash
fly auth logout
````

- [ ] **Step 3: Protect `v*` tags.** **Settings**, **Rules**, **Rulesets**, **New ruleset**, **New
  tag ruleset**:
  - Ruleset name `release tags`, enforcement status **Active**.
  - **Bypass list**: **Add bypass**, **Repository admin**.
  - **Target tags**: **Add target**, **Include by pattern**, `v*`.
  - **Rules**: **Restrict creations**, **Restrict updates**, **Restrict deletions**.
  - **Create**.

  Only repository admins can now create, move or delete a `v*` tag, so only they can start a
  deploy; the environment's approval is the second lock.

- [ ] **Step 4: Merge the pull request of Chunk 1** (squash, once its CI is green). The server
  answers, so the uptime check starts on a live server. Then run the uptime check once by hand:

````bash
gh workflow run uptime.yml --repo Cadtastic/RealOEM-Searcher
gh run list --workflow uptime.yml --repo Cadtastic/RealOEM-Searcher --limit 1 --json status,conclusion --jq '.[0] | .status + " " + .conclusion'
````

Expected: `completed success` (run the second command again while it shows `queued` or
`in_progress`). Then, from the main checkout, remove the worktree of Task 0 and its branch (`-D`,
because the branch was squash-merged):

````bash
git worktree remove .worktrees/hosted-deploy
git branch -D feat/hosted-deploy
````

- [ ] **Step 5: Write to RealOEM's owner** (spec section 8, step 1), now that the server works:
  send the message drafted on 2026-10-01 (per-user daily limits, the shared cache, the honest user
  agent, an offer to adjust or stop) and note the date. Task 16 waits for an answer, or for 7 days
  without one (or the longer wait the owner chooses), so the wait overlaps Chunks 3 and 4.

## Chunk 3: Version 0.2.0, the hosted plugin and the user and product documents

### Task 12: Version 0.2.0 and the hosted plugin (agent)

From here on the plugin connects to the hosted server (hosted design H1, spec section 8): its MCP
server entry becomes
`{"type": "http", "url": "https://realoem-searcher.fly.dev/mcp"}`,
with nothing to install. Claude Code, Cowork and chat all read this entry; the stdio server
`realoem-mcp` stays for development and tests. The descriptions drop "local" from "a local vehicle
finder", because the index now lives on the server. The version becomes 0.2.0 everywhere it
appears (AD15): `plugin.json`, `marketplace.json`, `pyproject.toml`, `uv.lock` and
`realoem_mcp.__version__`.

**Files:**
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `server/pyproject.toml`,
  `server/uv.lock`, `server/src/realoem_mcp/__init__.py`
- Test: `server/tests/unit/test_manifests.py`, `server/tests/unit/test_package.py`

- [ ] **Step 1: Create the worktree from an up-to-date main** (after Task 11, so it has Chunk 1):

````bash
git fetch origin
git worktree add .worktrees/release-0.2.0 -b release/0.2.0 --no-track origin/main
cd .worktrees/release-0.2.0
````

Run: `uv run --directory server pytest -q`
Expected: `1263 passed, 6 deselected`. If not, stop and report.

- [ ] **Step 2: Change the tests first.** In `server/tests/unit/test_manifests.py`:

Edit 1. Find:

````python
    assert (entry["name"], entry["source"]) == ("realoem-searcher", "./")


def test_mcp_server_launches_the_console_script_with_uv() -> None:
    server = PLUGIN["mcpServers"]["realoem"]
    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--quiet",
        "--no-dev",
        "--frozen",
        "--directory",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "realoem-mcp",
    ]
    assert server["env"] == {"REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands"}
    assert PYPROJECT["project"]["scripts"]["realoem-mcp"] == "realoem_mcp.server:main"
````

Replace with:

````python
    assert (entry["name"], entry["source"]) == ("realoem-searcher", "./")


def test_the_plugin_uses_the_hosted_server() -> None:
    # Nothing to install: chat, Cowork and Claude Code connect to the hosted server (hosted H1).
    assert PLUGIN["mcpServers"] == {
        "realoem": {"type": "http", "url": "https://realoem-searcher.fly.dev/mcp"}
    }
    scripts = PYPROJECT["project"]["scripts"]
    assert scripts["realoem-mcp-http"] == "realoem_mcp.http_app:main"
    assert scripts["realoem-mcp"] == "realoem_mcp.server:main"  # stdio: development and tests
````

In `server/tests/unit/test_package.py`:

Edit 1. Find:

````python


def test_version() -> None:
    assert __version__ == "0.1.0"
````

Replace with:

````python


def test_version() -> None:
    assert __version__ == "0.2.0"
````

- [ ] **Step 3: Run them**

Run: `uv run --directory server pytest -q tests/unit/test_manifests.py tests/unit/test_package.py`
Expected: FAIL: `test_the_plugin_uses_the_hosted_server` (the plugin still starts `uv`) and `test_version` (`assert '0.1.0' == '0.2.0'`).

- [ ] **Step 4: Switch the plugin and set the version.** In `.claude-plugin/plugin.json`:

Edit 1. Find:

````json
{
  "name": "realoem-searcher",
  "displayName": "RealOEM Searcher",
  "version": "0.1.0",
  "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a local vehicle finder.",
  "author": { "name": "Cadtastic" },
  "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
  "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
````

Replace with:

````json
{
  "name": "realoem-searcher",
  "displayName": "RealOEM Searcher",
  "version": "0.2.0",
  "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a vehicle finder.",
  "author": { "name": "Cadtastic" },
  "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
  "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
````

Edit 2. Find:

````json
  ],
  "mcpServers": {
    "realoem": {
      "command": "uv",
      "args": [
        "run",
        "--quiet",
        "--no-dev",
        "--frozen",
        "--directory",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "realoem-mcp"
      ],
      "env": { "REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands" }
    }
  }
}
````

Replace with:

````json
  ],
  "mcpServers": {
    "realoem": {
      "type": "http",
      "url": "https://realoem-searcher.fly.dev/mcp"
    }
  }
}
````

In `.claude-plugin/marketplace.json`:

Edit 1. Find:

````json
    {
      "name": "realoem-searcher",
      "source": "./",
      "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a local vehicle finder.",
      "version": "0.1.0",
      "author": {
        "name": "Cadtastic"
      },
````

Replace with:

````json
    {
      "name": "realoem-searcher",
      "source": "./",
      "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a vehicle finder.",
      "version": "0.2.0",
      "author": {
        "name": "Cadtastic"
      },
````

In `server/pyproject.toml`:

Edit 1. Find:

````toml
[project]
name = "realoem-mcp"
version = "0.1.0"
description = "MCP server for looking up BMW Group OEM parts on RealOEM.com"
requires-python = ">=3.11"
license = "MIT"
````

Replace with:

````toml
[project]
name = "realoem-mcp"
version = "0.2.0"
description = "MCP server for looking up BMW Group OEM parts on RealOEM.com"
requires-python = ">=3.11"
license = "MIT"
````

In `server/src/realoem_mcp/__init__.py`:

Edit 1. Find:

````python
"""RealOEM MCP server: polite, cached access to RealOEM.com for Claude."""

__version__ = "0.1.0"
````

Replace with:

````python
"""RealOEM MCP server: polite, cached access to RealOEM.com for Claude."""

__version__ = "0.2.0"
````

Then update the lockfile; only the project's own version line changes:

Run: `uv lock --directory server`
Expected: `Resolved 43 packages`; `git diff --stat server/uv.lock` then shows one line changed.

- [ ] **Step 5: Run it**

Run: `uv run --directory server pytest -q tests/unit/test_manifests.py tests/unit/test_package.py`
Expected: `4 passed`.

- [ ] **Run the whole suite and the linters**

Run: `uv run --directory server pytest -q`
Expected: `1263 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 6: Validate the manifests** with Claude Code's own validator:

````bash
claude plugin validate . --strict
claude plugin validate .claude-plugin/plugin.json --strict
````

Expected: both pass.

- [ ] **Commit**

````bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json server/pyproject.toml server/uv.lock server/src/realoem_mcp/__init__.py server/tests/unit/test_manifests.py server/tests/unit/test_package.py
git commit -m "feat: the plugin connects to the hosted server (0.2.0)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 13: README, CHANGELOG, the skills and the PRD (agent)

The user documentation for the hosted server (spec section 8, step 2). The README is rewritten:
installing is "install, then connect once" (`/mcp` in Claude Code, **Connect** elsewhere) with a
GitHub sign-in; it explains the daily limit, the shared cache and what the server keeps (the
privacy section); the tools table and troubleshooting no longer mention a cache path; and a new
section documents running the server yourself, including the admin script. The CHANGELOG gets the
0.2.0 entry, dated "release day" until the owner dates it in Task 16, with how to upgrade. The
vehicle-index skill no longer calls the index local, and the vin-decode skill gives the hosted
server's cache times. The PRD gets what spec section 8 lists: the requirements F0.1, F0.2, F0.4,
F0.6 and F6.2, a new F0.7 (sign-in and the daily budget), NFR2, NFR5 and NFR7, and the new risk
that every user shares one egress address.

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `skills/vehicle-index/SKILL.md`,
  `skills/vin-decode/SKILL.md`, `docs/PRD.md`

- [ ] **Step 1: Two results from Chunk 2.** Ask the controller what the owner found, and change the
  text below where it says so when you copy it:
  - Task 9, Step 3: if the admin script needed `env REALOEM_DATA_DIR=/data/data`, the README's
    admin command (near the end of "Running the server yourself") becomes
    `fly ssh console -C "setpriv --reuid=app --regid=app --init-groups -- env REALOEM_DATA_DIR=/data/data /app/server/.venv/bin/python /app/server/scripts/admin.py usage"`.
  - Task 10, Step 3: if the call limit was lowered to 40 seconds, write "about 40 seconds" under
    the README's Daily limits and "after 40 s" in the PRD's NFR5. In the README's environment
    table keep 50 as the default of `REALOEM_CALL_DEADLINE_S` (the code's default) and add
    "(`fly.toml` sets 40)" to its notes.

  Otherwise copy everything exactly.

- [ ] **Step 2: Replace `README.md` with:**

````markdown
# RealOEM Searcher

A Claude plugin that answers BMW Group parts questions (BMW, MINI, Rolls-Royce and BMW Motorrad)
from [RealOEM.com](https://www.realoem.com/bmw/enUS/select): part-number lookups, supersession
chains, VIN decoding, parts diagrams, fitment checks, vehicle-to-vehicle part comparison and a
vehicle finder. Its six skills teach Claude when and how to use the RealOEM Searcher server, a
hosted MCP server (`server/` in this repository) that fetches and parses RealOEM pages on demand.

**Status:** v0.2.0 (see [CHANGELOG.md](CHANGELOG.md)). All 13 tools and all 6 skills ship, and the
plugin works in Claude Code, in Cowork and in chat: there is nothing to install on your computer.
CI runs the offline tests on Ubuntu (Python 3.11 and 3.13) and Windows (Python 3.13).

## Install

In Claude Code:

```
/plugin marketplace add Cadtastic/RealOEM-Searcher
/plugin install realoem-searcher@realoem-searcher
```

In chat (claude.ai or the desktop app) and Cowork: **Customize**, **Plugins**, **Add**, **Add
marketplace**, **Add from a repository**, enter `Cadtastic/RealOEM-Searcher`, then install RealOEM
Searcher from **Discover**. A plugin installed on your Claude account also appears in Claude Code
when you sign in there.

Then connect it once:

- **Claude Code:** run `/mcp`, choose `plugin:realoem-searcher:realoem` and **Authenticate**.
- **Chat and Cowork:** open RealOEM Searcher under **Customize**, **Plugins**, and **Connect** it
  on its **Connectors** tab.

Connecting opens a page on `realoem-searcher.fly.dev` that names the app asking (Claude) and what
it gets, then asks you to sign in with GitHub. RealOEM Searcher reads only the id, username and
creation date of your public GitHub profile (the date decides the new-account limit below). It
never sees your GitHub password, asks GitHub only for read access to public data (no scopes), and
uses GitHub's token once, to read those fields, without storing it. Claude refreshes the connection
by itself; a sign-in ends after 30 days without use, or 90 days after it began, and then you
connect again.

## Example questions

Ask in plain language; the skills tell Claude which tools to call.

- "What oil filter does VIN ...PX22770 use?"
- "Is 11427541827 current?" (replaced by 11427953129)
- "Does 11427953129 fit an E90 325i USA 10/2005?"
- "Compare the engine lubrication diagrams of an E90 325i and an E92 335i."
- "Find a 2019 R 1250 GS."

## Skills

| Skill | Tools | Use it for |
|---|---|---|
| `part-lookup` | `lookup_part` | What a part number is, whether it is current, which series use it |
| `supersession` | `trace_supersession` | What replaces a part number today, with the chain and remarks |
| `vin-decode` | `decode_vin` | Identifying a car from its VIN (last 7 or all 17 characters) |
| `diagram-browse` | `select_vehicle`, `list_part_groups`, `list_diagrams`, `get_diagram_parts` | Browsing a vehicle's diagrams and parts lists |
| `fitment` | `check_fitment`, `compare_vehicles` | Whether a part fits a car, and what two cars share in one area |
| `vehicle-index` | `find_vehicle`, `update_vehicle_index` | Finding a vehicle by name, series, year, market or type code |

## Tools

The `realoem` MCP server exposes 13 tools. "Requests" is the number of requests sent to RealOEM
when nothing is cached; a cached page costs none, and the cache is shared by everyone, so a page
another user already looked up is free. Answers built from RealOEM pages carry the `source_urls`
of the pages used.

| Tool | Purpose | Requests |
|---|---|---|
| `lookup_part` | Status (current, ended, not found), description, dates, weight, superseded-by and supersedes lists, and the series using a part; with `series`, its vehicles and diagrams | 1 |
| `trace_supersession` | Follow "superseded by" links to the part that replaces a number today | at most 1 + `max_hops` (1-10, default 5); typically 1-2 |
| `decode_vin` | Vehicle for the last 7 or all 17 VIN characters: brand, series, model, market, production month, engine, type code, vehicle id | 1, or 2 with `include_production` |
| `find_vehicle` | Search the vehicle index by name, series, year, market or type code | none |
| `update_vehicle_index` | Add vehicles RealOEM listed since the baseline was built (at most one completed check an hour for everyone) | 1 when nothing is new, else at most `max_pages` (1-10, default 5); one more if the index is longer than RealOEM's |
| `select_vehicle` | Walk RealOEM's model cascade one level per call until a vehicle id is reached | 1 per call |
| `list_part_groups` | A vehicle's specifications and main groups | 1 |
| `list_diagrams` | The subgroups and diagrams of one main group | 1 |
| `get_diagram_parts` | One diagram's parts list (prices, notes, option-code conditions), image and hotspots | 1 |
| `check_fitment` | Whether a part is used on one vehicle, which number it uses there and in which diagrams | 1 |
| `compare_vehicles` | Part numbers two vehicles use in one main group: in both, only A, only B | 2 + 1 per diagram, capped by `max_requests` (2-60, default 20) |
| `server_status` | Version, base URL, user agent, request interval, cache size, requests sent since start, and your quota for today | none |
| `cache_clear` | Delete cached pages (administrators of the server only) | none |

## Daily limits

RealOEM is a free community site, so each user has a daily budget of RealOEM requests:

- **300 lookups a day** (30 for GitHub accounts younger than 30 days). Only requests that go to
  RealOEM count; anything answered from the cache is free, and cached answers stay available when
  the budget is spent. The budget resets at 00:00 UTC. `server_status` shows how much is left.
- **One request at a time for everyone.** The server sends RealOEM one request at a time, at least
  2 seconds apart, so a busy moment can mean a short wait. A tool call that cannot finish in about
  50 seconds stops and says so; calling it again continues from the cache. `compare_vehicles`
  instead returns the diagrams it compared so far, also when the queue is full or the day's
  lookups run out, and says why.

## Privacy

The server keeps your GitHub id, username, account creation date and when you first signed in,
with no time limit (and, if the maintainer suspends an account, when and why); how many RealOEM
requests you made each day (for 90 days); and the sign-ins you approved (for 90 days). It does not store your
questions. The pages it fetched stay in a shared cache, except pages for a VIN: those are cached
for you alone, for at most 30 days, so nobody else can tell which VINs were looked up. Logs record
each request with your GitHub id, the RealOEM pages fetched or served from the cache (part numbers,
vehicle and diagram ids) and the error message of a failed tool call; they never carry a VIN, a
token or the query string of a sign-in request. Only the last 7 characters of a VIN are ever sent
to RealOEM.

## Vehicle index

`find_vehicle` searches a list of every vehicle in RealOEM's vehicles index, so a vehicle can be
found by name, series, year, market or type code without walking the model cascade and without a
request.

- **Baseline.** `brands/<brand>/vehicles.csv` plus `brands/vehicles.meta.toml`, committed to this
  repository. Built 2026-09-30: 8218 vehicles (bmw 6824, mini 640, motorrad 642, rolls-royce 112).
- **Updates.** `update_vehicle_index` adds vehicles RealOEM has listed since the baseline was built,
  reading as few pages as possible. The index is shared, so one update serves everyone, and a
  completed check is not repeated for an hour (`cooldown`). If RealOEM's list no longer matches,
  it reports `drift` and the maintainer rebuilds the baseline.
- **Rebuild.** A full rebuild is maintainer-only (about 166 requests, about 6 minutes at the default
  rate) and is never run by a tool or in CI:

  ```bash
  uv run --directory server python scripts/rebuild_vehicle_index.py
  ```

- **Dates.** Vehicle ids carry the production-start month, and end dates of models still in
  production are as of the baseline's `built_at` date.

## Politeness

RealOEM is a free community resource with no API. This plugin treats it as a reference, not a data
source to mirror:

- One request in flight at a time and at least 2 seconds between requests, for all users together.
  The spacing also applies between redirect hops and retries.
- Daily limits per user (see above), and pages are cached, so repeat questions cost nothing.
- Requests identify themselves honestly:
  `RealOEM-Searcher/<version> (+https://github.com/Cadtastic/RealOEM-Searcher)`.
- The only cookie sent is `ro_ui=v2`, which pins the page layout the parsers read. Cookies the
  site sets are discarded.
- Only same-origin redirects are followed, at most 3.
- Up to 2 retries on HTTP 429, 5xx or a timeout, waiting for `Retry-After` (capped at 30 s) when
  RealOEM sends one, otherwise 5 s and then 15 s.
- If RealOEM shows a Cloudflare bot challenge, the server stops and tells you; it never retries it
  or tries to get around it.
- No crawling, no background or speculative fetching, no use of RealOEM data for AI training. The
  single exception is the committed vehicle list: a maintainer rebuilds it with one full pass over
  RealOEM's vehicle index (about 166 requests, about 6 minutes).

### Caching

| Page | Used by | Kept for |
|---|---|---|
| `select` (model cascade) | `select_vehicle` | 30 days |
| `select?vin` | `decode_vin` | 30 days if found, 1 day if not; for the user who asked only |
| `production` | `decode_vin` with `include_production` | 30 days; 1 day with no record; for the user who asked only |
| `partgrp` | `list_part_groups`, `list_diagrams`, `compare_vehicles` | 30 days; 1 day for an unknown main group |
| `showparts` | `get_diagram_parts`, `compare_vehicles` | 30 days |
| `partxref` | `lookup_part`, `trace_supersession` | 7 days |
| `partsearch` | `check_fitment` | 7 days |
| `vehicles` | `update_vehicle_index` | 1 day; an update fetches a fresh copy unless the cached one is less than an hour old |

Pages that fail to parse are expired immediately, so the next call fetches them again. Redirects
and error responses are not cached. `refresh=true` on a tool call fetches a fresh copy when the
cached one is more than an hour old. The cache is limited to 400 MB; the least recently used pages
make room for new ones.

## Limitations and troubleshooting

- The catalog is US English (`enUS`) only, and prices are USD as RealOEM shows them.
- RealOEM does not expose a VIN's option codes, paint, upholstery or model year, so neither does
  this plugin. A parts list can show option-code conditions ("only for vehicles with option ..."),
  but RealOEM does not say which options a given VIN has.
- RealOEM picks one vehicle per VIN serial (the last 7 characters), so a decode is RealOEM's best
  match. For a full VIN, a manufacturer prefix that does not match the decoded brand is flagged as
  low confidence.
- Vehicle ids from `lookup_part` rows (the `_` form, e.g. `VB13-USA-02_2004_E90_BMW_325i`) carry a
  nominal date that RealOEM ignores: it treats them as undated, so their parts lists are not
  narrowed to any production month. `find_vehicle` ids carry the vehicle's production-start month,
  and RealOEM filters parts lists by it. Neither is a specific car's build month; for a specific
  car, use `decode_vin` or `select_vehicle`.
- If the tools stop working, reconnect: `/mcp` in Claude Code, or **Connect** on the plugin's
  **Connectors** tab in chat and Cowork.

| Message | What it means | What to do |
|---|---|---|
| "You've used your 300 RealOEM lookups for today ..." | Your daily budget is spent. | Cached answers still work; new lookups work again after 00:00 UTC. |
| "RealOEM Searcher has reached its daily request limit ..." | The server's own daily limit is reached (it is normally off). | Try again after 00:00 UTC. |
| "RealOEM Searcher is busy; try again in a minute." | Many lookups are waiting for their turn. | Try again in a minute. |
| "This call took too long; call again to continue ..." | The call ran out of time; the pages it fetched are cached. | Ask again: it continues from the cache. |
| "You are not signed in to RealOEM Searcher ..." | The connection lost its sign-in. | Reconnect (see above). |
| "This sign-in request has expired. Start again from Claude." | A sign-in page was left open too long, or reloaded. | Start connecting again from Claude. |
| "GitHub sign-in is unavailable right now; try again shortly." | GitHub did not answer during sign-in. | Connect again in a few minutes. |
| "Access to RealOEM Searcher is suspended." | The server's maintainer suspended this GitHub account. | [Open an issue](https://github.com/Cadtastic/RealOEM-Searcher/issues) if you think this is a mistake. |
| "Only an administrator of this RealOEM Searcher server can clear its shared cache. ..." | `cache_clear` is for the server's administrators. | Use `refresh=true` on the lookup instead. |
| "RealOEM is showing a bot challenge (Cloudflare) ..." | RealOEM answered with a Cloudflare challenge instead of the page. The server never retries or works around it. | Try again later. |
| "RealOEM's ... page did not have the expected structure ..." (`LayoutChanged`) | The page did not match what the parser reads, so the server returns an error instead of guessing. | Try again later. If it persists, [open an issue](https://github.com/Cadtastic/RealOEM-Searcher/issues) with the page URL from the message. |
| "RealOEM request failed (...)" | RealOEM returned an error status, timed out or could not be reached (429, 5xx and timeouts are retried twice first). | Try again later. |

## Running the server yourself

The hosted server is `realoem-mcp-http`; it runs on [Fly.io](https://fly.io) from `fly.toml` and
`server/Dockerfile`. It reads these environment variables:

| Variable | Default | Notes |
|---|---|---|
| `REALOEM_PUBLIC_URL` | (required) | The server's own address, e.g. `https://realoem-searcher.fly.dev` |
| `REALOEM_GITHUB_CLIENT_ID`, `REALOEM_GITHUB_CLIENT_SECRET` | (required) | A GitHub OAuth App whose callback is `<public URL>/oauth/github/callback` |
| `REALOEM_SECRET_KEY` | (required) | Base64 of at least 32 random bytes (`openssl rand -base64 32`). Changing it signs everyone out |
| `REALOEM_REDIRECT_ALLOWLIST` | Claude's callback | Comma-separated `https` callbacks a client may register; loopback redirects are always allowed |
| `REALOEM_HOSTED_CLIENT_RANGE` | `160.79.104.0/21` | Anthropic's address range, which gets the higher client-registration limit |
| `REALOEM_ADMINS` | none | Comma-separated GitHub numeric ids that may clear the cache |
| `REALOEM_USER_DAILY_LIMIT`, `REALOEM_NEW_USER_DAILY_LIMIT` | 300, 30 | Daily lookups per user, and per user with a new GitHub account; 0 means unlimited |
| `REALOEM_MIN_ACCOUNT_AGE_DAYS` | 30 | GitHub accounts younger than this many days are new; 0 ends the new-account period (an account whose creation date is unknown still counts as new) |
| `REALOEM_GLOBAL_DAILY_LIMIT` | 0 (off) | Daily lookups for everyone together |
| `REALOEM_CALL_DEADLINE_S` | 50 | Seconds after which a tool call starts no new RealOEM request |
| `REALOEM_CACHE_MAX_MB` | 400 | Page cache size limit |
| `REALOEM_CACHE_DIR`, `REALOEM_DATA_DIR`, `REALOEM_AUTH_DIR` | user cache and data directories | The page cache; the vehicle index; the sign-in database (default: the data directory) |
| `REALOEM_MIN_INTERVAL`, `REALOEM_TIMEOUT` | 2.0 s, 20.0 s | Request spacing (never below 1.0 s) and timeout |
| `REALOEM_BRANDS_DIR` | `brands/` in this repository | Brand registry and vehicle index baseline |

The maintainer manages users on the server with `scripts/admin.py` (`usage`, `ban`, `unban`,
`revoke`, `prune`). It refuses to run as root (SQLite files it created would then belong to
root), so drop to the app user first, as the container's entry point does:

```bash
fly ssh console -C "setpriv --reuid=app --regid=app --init-groups -- /app/server/.venv/bin/python /app/server/scripts/admin.py usage"
```

If the uptime check reports the server down and `fly status` shows its machine stopped, a crash
loop used up Fly's restarts. Neither a request nor a deploy starts it again: fix the cause, deploy
the fix, then run `fly machine start <machine id> --app realoem-searcher`.

## Development

```bash
cd server
uv sync --locked             # create .venv from uv.lock (runtime + dev dependencies)
uv run ruff check            # lint
uv run ruff format --check   # formatting (without --check it reformats)
uv run pytest                # offline test suite; pyproject adds -m "not live"
uv run realoem-mcp           # the server on stdio: no sign-in, no limits (Ctrl+C to stop)
```

CI runs the first four commands (see `.github/workflows/ci.yml`); a `v*` tag deploys the hosted
server (`.github/workflows/deploy.yml`). To run the HTTP server locally, create a second GitHub
OAuth App with the callback `http://localhost:8080/oauth/github/callback`, then:

```bash
export REALOEM_PUBLIC_URL=http://localhost:8080 REALOEM_GITHUB_CLIENT_ID=... REALOEM_GITHUB_CLIENT_SECRET=...
export REALOEM_SECRET_KEY="$(openssl rand -base64 32)"
uv run realoem-mcp-http
```

Validate the marketplace and the plugin manifest from the repository root with:

```bash
claude plugin validate . --strict
claude plugin validate .claude-plugin/plugin.json --strict
```

Live smoke tests send a few real requests to RealOEM and are opt-in. They are never run in CI:

```bash
REALOEM_LIVE=1 uv run pytest -m live tests/live
```

PowerShell:

```powershell
$env:REALOEM_LIVE = "1"; uv run pytest -m live tests/live; Remove-Item Env:REALOEM_LIVE
```

Test fixtures are trimmed real pages. Capture a page politely, then trim it:

```bash
uv run python scripts/capture_page.py partxref oil_filter q=11427953129
uv run python scripts/trim_fixture.py ../.research-raw/partxref/oil_filter.html \
    tests/fixtures/partxref/oil_filter.html
```

`.research-raw/` is git-ignored; never commit raw pages.

Design documents: [PRD](docs/PRD.md), [ARD](docs/ARD.md),
[hosted server design](docs/superpowers/specs/2026-10-01-hosted-server-design.md),
[RealOEM site notes](docs/research/realoem-site-notes.md). Release history:
[CHANGELOG](CHANGELOG.md).

## License

[MIT](LICENSE). RealOEM is an independent site not affiliated with this project or with BMW AG.
````

- [ ] **Step 3: The changelog.** In `CHANGELOG.md`:

Edit 1. Find:

````markdown
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-30

First release. A Claude Code plugin with a local MCP server (`realoem`) and six skills that answer
````

Replace with:

````markdown
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - release day

RealOEM Searcher now runs as a hosted server, so the plugin works in Claude Code, in Cowork (on
your computer or in the cloud) and in chat, with nothing to install. Install the plugin, then
connect it once: `/mcp` in Claude Code, or **Connect** in the plugin's Connectors tab.

### Added

- **Hosted server.** `https://realoem-searcher.fly.dev/mcp`, an MCP server over streamable HTTP
  (`realoem-mcp-http`), deployed to Fly.io from `fly.toml` and `server/Dockerfile` when a `v*` tag
  is pushed.
- **Sign-in with GitHub.** The server is its own OAuth 2.1 authorization server: dynamic client
  registration limited to Claude's callback and programs on your computer, a consent page before
  GitHub, PKCE, one-hour access tokens and rotating refresh tokens. Only the id, username and
  creation date of your public GitHub profile are read.
- **Daily limits.** 300 RealOEM lookups per user per UTC day (30 for GitHub accounts younger than
  30 days); cached answers are free and stay available. An optional server-wide limit exists and
  is off.
- **Shared, careful use of RealOEM.** One request at a time and at least 2 seconds apart for all
  users together, a short queue with a per-call time limit, and a shared page cache (400 MB) so a
  page one user fetched is free for everyone. `compare_vehicles` returns its partial result, with
  a `stopped_reason`, when the time, the queue or the day's lookups run out.
- **Privacy.** VIN pages are cached for the user who asked only, for at most 30 days. Logs never
  carry a VIN, a token or the query string of a sign-in request. See the README's Privacy section.

### Changed

- `plugin.json` connects to the hosted server instead of starting a local one with `uv`; uv and a
  local Python are no longer needed. `realoem-mcp` (stdio) stays for development and tests.
- On the hosted server, `server_status` shows your quota and no longer the cache path, and
  `cache_clear` is for the server's administrators.
- On the hosted server, `refresh=true` fetches a fresh copy only when the cached one is more than an
  hour old.
- On the hosted server, `update_vehicle_index` runs one update at a time for everyone and checks at
  most once an hour; a call in that hour returns the new status `cooldown`.
- The page cache moved to a new file, `pages.v2.sqlite3` (with an owner column, a size limit and
  disk-space handling); a server that opens an existing cache folder deletes the old
  `pages.sqlite3` there.

Marketplace installs of 0.1.0 see 0.2.0 on their next marketplace refresh; Claude Code does not
update third-party marketplaces automatically by default. To upgrade now in Claude Code, update the
marketplace you installed from (`/plugin marketplace update realoem-searcher`, or `cadtastic` for
Claude-Plugin-Collection) and the plugin in `/plugin`, start a new session, then connect with
`/mcp`. The 0.1.0 server's local files (`pages.sqlite3` and `vehicles.sqlite3` in the
`realoem-searcher` user cache and data folders) are no longer used and can be deleted.

## [0.1.0] - 2026-09-30

First release. A Claude Code plugin with a local MCP server (`realoem`) and six skills that answer
````

Edit 2. Find:

````markdown
  live site: five end-to-end questions in 15 requests, and a replay of every call made no further
  request.

[0.1.0]: https://github.com/Cadtastic/RealOEM-Searcher/releases/tag/v0.1.0
````

Replace with:

````markdown
  live site: five end-to-end questions in 15 requests, and a replay of every call made no further
  request.

[0.2.0]: https://github.com/Cadtastic/RealOEM-Searcher/releases/tag/v0.2.0
[0.1.0]: https://github.com/Cadtastic/RealOEM-Searcher/releases/tag/v0.1.0
````

- [ ] **Step 4: The skills.** In `skills/vehicle-index/SKILL.md`:

Edit 1. Find:

````markdown

# Vehicle index

A local list of every vehicle in RealOEM's vehicles index (about 8,200), shipped with the plugin
and stored on this computer. Searching it is free: `find_vehicle` never contacts RealOEM.

## Steps

````

Replace with:

````markdown

# Vehicle index

A list of every vehicle in RealOEM's vehicles index (about 8,200), kept by the RealOEM Searcher
server. Searching it is free: `find_vehicle` never contacts RealOEM.

## Steps

````

In `skills/vin-decode/SKILL.md`:

Edit 1. Find:

````markdown
     were made; it costs one more request. If RealOEM's production page cannot be read, the whole
     call fails; call `decode_vin` again without `include_production` to still get the vehicle.
   - Use `refresh=true` only if the user says the answer looks out of date (found VINs are
     cached for 180 days, not-found results for 1 day).
2. If the tool returns an error about the input, show it and ask for the VIN again. VINs never
   contain the letters I, O or Q; a "0" or "1" typed as a letter is the usual mistake.
3. `status` is `not_found`: RealOEM has no vehicle for that serial. Ask the user to check the last 7
````

Replace with:

````markdown
     were made; it costs one more request. If RealOEM's production page cannot be read, the whole
     call fails; call `decode_vin` again without `include_production` to still get the vehicle.
   - Use `refresh=true` only if the user says the answer looks out of date (found VINs are
     cached for 30 days for the user who asked, not-found results for 1 day; a copy less than an
     hour old is not fetched again).
2. If the tool returns an error about the input, show it and ask for the VIN again. VINs never
   contain the letters I, O or Q; a "0" or "1" typed as a letter is the usual mistake.
3. `status` is `not_found`: RealOEM has no vehicle for that serial. Ask the user to check the last 7
````

- [ ] **Step 5: The PRD.** In `docs/PRD.md`:

Edit 1. Find:

````markdown

| | |
|---|---|
| Status | Implemented (v0.1.0) |
| Owner | Cadtastic |
| Repository | https://github.com/Cadtastic/RealOEM-Searcher |
| Last updated | 2026-09-30 |
| Companion docs | [ARD](ARD.md), [RealOEM site notes](research/realoem-site-notes.md), [implementation plans](superpowers/plans/) |

## 1. Problem

````

Replace with:

````markdown

| | |
|---|---|
| Status | Implemented (v0.2.0: hosted server) |
| Owner | Cadtastic |
| Repository | https://github.com/Cadtastic/RealOEM-Searcher |
| Last updated | 2026-10-01 |
| Companion docs | [ARD](ARD.md), [hosted server design](superpowers/specs/2026-10-01-hosted-server-design.md), [RealOEM site notes](research/realoem-site-notes.md), [implementation plans](superpowers/plans/) |

## 1. Problem

````

Edit 2. Find:

````markdown
- Bypassing Cloudflare or other bot protections (no headless-browser challenge solving).
- Per-VIN factory option (SA) codes, paint, upholstery or model year. RealOEM does not expose them.
- Ordering, price comparison across vendors, or affiliate links.
- Account/login features (RealOEM membership only removes ads).
- Languages other than `enUS`.

## 5. Features

All features ship in v0.1.0, each built on its own branch and pull request. `feat/foundation` was a
prerequisite for all of them.

### F0: Foundation (`feat/foundation`)

````

Replace with:

````markdown
- Bypassing Cloudflare or other bot protections (no headless-browser challenge solving).
- Per-VIN factory option (SA) codes, paint, upholstery or model year. RealOEM does not expose them.
- Ordering, price comparison across vendors, or affiliate links.
- RealOEM account/login features (RealOEM membership only removes ads).
- Languages other than `enUS`.

## 5. Features

All features ship in v0.1.0, each built on its own branch and pull request. `feat/foundation` was a
prerequisite for all of them. v0.2.0 moved the server to a hosted service that every user signs in
to ([hosted server design](superpowers/specs/2026-10-01-hosted-server-design.md)); the features are
unchanged.

### F0: Foundation (`feat/foundation`)

````

Edit 3. Find:

````markdown

**Requirements**

- F0.1 Installable as a Claude Code plugin from this repo (`/plugin marketplace add
  Cadtastic/RealOEM-Searcher`). Listing in `Cadtastic/Claude-Plugin-Collection` happens at the first
  release, not in a feature branch.
- F0.2 The MCP server starts via `uv` from the installed plugin with no manual setup beyond having `uv`.
- F0.3 All RealOEM requests go through one client that enforces a minimum interval between requests
  (default 2 s, configurable; never below 1 s), identifies itself honestly with a
  `RealOEM-Searcher/<version> (+repo URL)` user agent, sends only the `ro_ui=v2` cookie, and never sends
  `dmode=0`.
- F0.4 Responses are cached in SQLite in the user's cache directory with per-page-type TTLs; every tool
  that reads cached pages accepts `refresh=true`; a `cache_clear` tool exists.
- F0.5 A Cloudflare challenge produces a clear error telling the user RealOEM is blocking automated
  requests. The server never retries through or works around a challenge.
- F0.6 A `server_status` tool reports version, cache location/size and request settings.

### F1: Part number lookup (`feat/part-lookup`) — feature A

````

Replace with:

````markdown

**Requirements**

- F0.1 Installable as a Claude plugin from this repo (`/plugin marketplace add
  Cadtastic/RealOEM-Searcher`) or from `Cadtastic/Claude-Plugin-Collection`, and usable in Claude
  Code, Cowork and chat. After installing, the user connects once (`/mcp` in Claude Code, **Connect**
  elsewhere) and signs in with GitHub.
- F0.2 The plugin connects to the hosted RealOEM Searcher server
  (`https://realoem-searcher.fly.dev/mcp`) with nothing to install on the user's computer. The stdio
  server (`realoem-mcp`, started with `uv`) stays for development and tests.
- F0.3 All RealOEM requests go through one client that enforces a minimum interval between requests
  (default 2 s, configurable; never below 1 s), identifies itself honestly with a
  `RealOEM-Searcher/<version> (+repo URL)` user agent, sends only the `ro_ui=v2` cookie, and never sends
  `dmode=0`.
- F0.4 Responses are cached in SQLite on the server with per-page-type TTLs, shared by all users except
  VIN pages, which are cached per user; every tool that reads cached pages accepts `refresh=true` (on
  the hosted server honoured for copies more than an hour old); a `cache_clear` tool exists
  (administrators only on the hosted server).
- F0.5 A Cloudflare challenge produces a clear error telling the user RealOEM is blocking automated
  requests. The server never retries through or works around a challenge.
- F0.6 A `server_status` tool reports version, cache size and request settings, plus the caller's
  daily quota on the hosted server (the cache location only on the stdio server).
- F0.7 On the hosted server users sign in with GitHub (public profile only) through the server's own
  OAuth 2.1 authorization server, and each user has a daily budget of RealOEM requests (300; 30 for
  GitHub accounts younger than 30 days); cached answers are free.

### F1: Part number lookup (`feat/part-lookup`) — feature A

````

Edit 4. Find:

````markdown

- F6.1 A committed baseline `brands/<brand>/vehicles.csv` (one vehicle per line) covering RealOEM's
  vehicles index (~8,200 vehicles), built by a maintainer-only script.
- F6.2 At runtime the baseline is loaded into a SQLite store in the user's data directory (not the
  cache directory); rows added by updates are kept there and survive restarts, cache clears and plugin
  updates. When the baseline changes, baseline rows are reloaded and still-missing local rows are kept.
- F6.3 `find_vehicle` searches the local index (free text over series, model and type code, plus
  filters for brand, series, year, market and type code) and returns vehicle ids usable by F3/F4. It
  makes no network requests.
````

Replace with:

````markdown

- F6.1 A committed baseline `brands/<brand>/vehicles.csv` (one vehicle per line) covering RealOEM's
  vehicles index (~8,200 vehicles), built by a maintainer-only script.
- F6.2 At runtime the baseline is loaded into a SQLite store in the server's data directory (not the
  cache directory), shared by all users of the hosted server; rows added by updates are kept there
  and survive restarts, cache clears and plugin updates. When the baseline changes, baseline rows are
  reloaded and still-missing local rows are kept.
- F6.3 `find_vehicle` searches the local index (free text over series, model and type code, plus
  filters for brand, series, year, market and type code) and returns vehicle ids usable by F3/F4. It
  makes no network requests.
````

Edit 5. Find:

````markdown

| ID | Requirement |
|---|---|
| NFR1 Politeness | ≥ 2 s between requests to RealOEM by default; one request in flight at a time per server process; no background or speculative fetching. |
| NFR2 Caching | Repeat questions within a TTL cause zero requests. TTLs: catalog structure and diagram pages 30 days, part lookups 7 days, VIN results 180 days (VIN misses 1 day), production statistics 180 days; vehicles index pages are stored for 1 day, but `update_vehicle_index` always fetches them fresh. |
| NFR3 Correctness | A parser that finds an unexpected page structure raises `LayoutChanged` instead of returning partial or guessed data. |
| NFR4 Traceability | Every data tool result includes the RealOEM `source_urls` and `fetched_at` (admin tools `server_status`/`cache_clear` and the local-only `find_vehicle` excepted; its result has no `source_urls` or `fetched_at`). |
| NFR5 Latency | Single-lookup tools answer in < 5 s when uncached (dominated by the rate limit). |
| NFR6 Testability | Parsers are tested offline against trimmed real-page fixtures; CI needs no network. Live smoke tests are opt-in. |
| NFR7 Portability | Runs on Windows, macOS and Linux with Python ≥ 3.11 managed by `uv`. |
| NFR8 Transparency | User-facing errors say what happened and what to do (e.g. "RealOEM is showing a bot challenge; try again later or open the URL in a browser"). |

## 7. Success criteria
````

Replace with:

````markdown

| ID | Requirement |
|---|---|
| NFR1 Politeness | ≥ 2 s between requests to RealOEM by default; one request in flight at a time per server process, which on the hosted server means for all users together; per-user daily limits on the hosted server; no background or speculative fetching. |
| NFR2 Caching | Repeat questions within a TTL cause zero requests. TTLs: catalog structure and diagram pages 30 days, part lookups 7 days, VIN results 180 days (VIN misses 1 day), production statistics 180 days; vehicles index pages are stored for 1 day, but `update_vehicle_index` fetches them fresh (on the hosted server, unless the stored copy is less than an hour old). On the hosted server VIN results and production statistics are kept for the user who asked only, for at most 30 days. |
| NFR3 Correctness | A parser that finds an unexpected page structure raises `LayoutChanged` instead of returning partial or guessed data. |
| NFR4 Traceability | Every data tool result includes the RealOEM `source_urls` and `fetched_at` (admin tools `server_status`/`cache_clear` and the local-only `find_vehicle` excepted; its result has no `source_urls` or `fetched_at`). |
| NFR5 Latency | Single-lookup tools answer in < 5 s when uncached and nothing else is queued (dominated by the rate limit). On the hosted server a tool call starts no new request after 50 s and says so; `compare_vehicles` returns its partial result instead. |
| NFR6 Testability | Parsers are tested offline against trimmed real-page fixtures; CI needs no network. Live smoke tests are opt-in. |
| NFR7 Portability | The plugin needs nothing on the user's computer. The server runs on Linux (Fly.io) in production, and on Windows, macOS and Linux with Python ≥ 3.11 managed by `uv` for development. |
| NFR8 Transparency | User-facing errors say what happened and what to do (e.g. "RealOEM is showing a bot challenge; try again later or open the URL in a browser"). |

## 7. Success criteria
````

Edit 6. Find:

````markdown
| Last-7-digit matching returns the wrong part | Wrong answers | Client-side input validation and returned-number verification. |
| Server silently picks one vehicle for an ambiguous VIN serial | Wrong vehicle | WMI cross-check for full VINs; skill labels result as RealOEM's best match. |
| Terms of use / content signals | Legal/ethical exposure | Reference-only use, user-initiated, throttled, cached; no bulk data; fixtures trimmed to data sections. |

## 9. Open questions

````

Replace with:

````markdown
| Last-7-digit matching returns the wrong part | Wrong answers | Client-side input validation and returned-number verification. |
| Server silently picks one vehicle for an ambiguous VIN serial | Wrong vehicle | WMI cross-check for full VINs; skill labels result as RealOEM's best match. |
| Terms of use / content signals | Legal/ethical exposure | Reference-only use, user-initiated, throttled, cached; no bulk data; fixtures trimmed to data sections. |
| All users share one egress IP | One Cloudflare challenge stops every user at once | Per-user daily limits and an optional server-wide cap; shared cache; honest UA; the owner told RealOEM before launch. A static egress IP would help RealOEM identify the traffic. |
| The hosted server is down | Every user loses the tools | Fly restarts it on failure; an uptime check every 15 minutes alerts the owner, who starts a machine a crash loop left stopped (`fly machine start`); nothing is lost on restart (no sessions; tokens and cache on disk). |

## 9. Open questions

````

- [ ] **Commit**

````bash
git add README.md CHANGELOG.md skills/vehicle-index/SKILL.md skills/vin-decode/SKILL.md docs/PRD.md
git commit -m "docs: README, changelog, skills and PRD for the hosted server" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

## Chunk 4: The ARD and the release

### Task 14: The ARD (agent)

The ARD sections spec section 8 lists: the diagram and the decisions (a new AD17 "hosted server";
AD1 and AD2 now hold for development only), the layout, the manifest, the settings, the service
hooks and `run_storage`, the new errors, the cache, the admin tools and `update_vehicle_index`'s
`cooldown` status, security, and CI and deployment.

**Files:**
- Modify: `docs/ARD.md`

- [ ] **Step 1: The ARD.** In `docs/ARD.md`:

Edit 1. Find:

````markdown

| | |
|---|---|
| Status | Implemented (v0.1.0) |
| Last updated | 2026-09-30 |
| Companion docs | [PRD](PRD.md), [RealOEM site notes](research/realoem-site-notes.md), [implementation plans](superpowers/plans/) |

## 1. Context
````

Replace with:

````markdown

| | |
|---|---|
| Status | Implemented (v0.2.0: hosted server) |
| Last updated | 2026-10-01 |
| Companion docs | [PRD](PRD.md), [RealOEM site notes](research/realoem-site-notes.md), [implementation plans](superpowers/plans/) |

## 1. Context
````

Edit 2. Find:

````markdown
behind Cloudflare, with no API. This project is a Claude plugin that answers parts questions by fetching
and parsing RealOEM pages on demand, politely and with aggressive caching. Page structure, URL patterns
and quirks are documented in the [site notes](research/realoem-site-notes.md); this document defines how
the software is built.

## 2. System overview

````

Replace with:

````markdown
behind Cloudflare, with no API. This project is a Claude plugin that answers parts questions by fetching
and parsing RealOEM pages on demand, politely and with aggressive caching. Page structure, URL patterns
and quirks are documented in the [site notes](research/realoem-site-notes.md); this document defines how
the software is built. Since v0.2.0 the MCP server runs as one hosted service that users sign in to;
the [hosted server design](superpowers/specs/2026-10-01-hosted-server-design.md) is the detailed
reference for it, and §5.13 summarises it.

## 2. System overview

````

Edit 3. Find:

````markdown
flowchart LR
    U[User] --> C[Claude]
    C -- reads --> S[Skills<br/>skills/*]
    C -- MCP tool calls (stdio) --> M[realoem MCP server<br/>server/]
    M --> T[Tools layer]
    T --> P[Parsers]
    T --> H[RealOemClient]
````

Replace with:

````markdown
flowchart LR
    U[User] --> C[Claude]
    C -- reads --> S[Skills<br/>skills/*]
    C -- MCP over HTTPS, bearer token --> A[Sign-in and limits<br/>OAuth server, quota, gate]
    U -. signs in with .-> G[GitHub]
    A --> M[realoem MCP server<br/>server/, on Fly.io]
    M --> T[Tools layer]
    T --> P[Parsers]
    T --> H[RealOemClient]
````

Edit 4. Find:

````markdown
- **Skills** carry workflow knowledge: which tools to chain, how to explain BMW-specific concepts, what
  RealOEM cannot answer. They never touch HTML.
- **The MCP server** owns all data access: HTTP, rate limiting, caching, parsing and result shaping.
  Tools return typed, structured results.

## 3. Architecture decisions

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| AD1 | Plugin bundling a local stdio **MCP server** plus **skills** | One long-lived process can enforce a single rate limit and hold cache handles; typed tools isolate fragile HTML parsing; server works in any MCP client; skills add workflow knowledge | Skills + CLI scripts (no shared rate limit, per-call process start); MCP only (no BMW workflow guidance) |
| AD2 | **Python ≥ 3.11**, packaged with **uv**, launched by `uv run --quiet --no-dev --frozen --directory ${CLAUDE_PLUGIN_ROOT}/server realoem-mcp` | Good HTML tooling; uv installs deps on first run; no PyPI release needed | C#/.NET (runtime distribution); TypeScript |
| AD3 | Official **`mcp` SDK 2.x** (`mcp.server.mcpserver.MCPServer`) | Maintained reference SDK; pydantic return types become structured output; in-memory `mcp.Client` for tests | SDK 1.x `FastMCP` (superseded); third-party `fastmcp` |
| AD4 | **httpx** (async) for HTTP, **selectolax** for HTML | Fast, small, typed; `httpx.MockTransport` makes the client testable without extra libraries | requests (sync), BeautifulSoup (slower, looser) |
| AD5 | **Cache raw pages** (not parsed results) in **SQLite**, keyed by request URL, TTL by page type | Parser fixes apply to cached data immediately; one simple table; stdlib `sqlite3`; survives restarts | Caching parsed results (stale on parser change); in-memory only; no cache |
````

Replace with:

````markdown
- **Skills** carry workflow knowledge: which tools to chain, how to explain BMW-specific concepts, what
  RealOEM cannot answer. They never touch HTML.
- **The MCP server** owns all data access: HTTP, rate limiting, caching, parsing and result shaping.
  Tools return typed, structured results. The hosted server (`realoem-mcp-http`) wraps the same
  server in GitHub sign-in, per-user quotas and a request queue; the stdio entry point
  (`realoem-mcp`) runs the same tools locally for development and tests.

## 3. Architecture decisions

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| AD1 | Plugin bundling a local stdio **MCP server** plus **skills** (since v0.2.0 for development and tests only; see AD17) | One long-lived process can enforce a single rate limit and hold cache handles; typed tools isolate fragile HTML parsing; server works in any MCP client; skills add workflow knowledge | Skills + CLI scripts (no shared rate limit, per-call process start); MCP only (no BMW workflow guidance) |
| AD2 | **Python ≥ 3.11**, packaged with **uv**, launched by `uv run --quiet --no-dev --frozen --directory ${CLAUDE_PLUGIN_ROOT}/server realoem-mcp` (since v0.2.0 the launch command is for development only; users connect to the hosted server, AD17) | Good HTML tooling; uv installs deps on first run; no PyPI release needed | C#/.NET (runtime distribution); TypeScript |
| AD3 | Official **`mcp` SDK 2.x** (`mcp.server.mcpserver.MCPServer`) | Maintained reference SDK; pydantic return types become structured output; in-memory `mcp.Client` for tests | SDK 1.x `FastMCP` (superseded); third-party `fastmcp` |
| AD4 | **httpx** (async) for HTTP, **selectolax** for HTML | Fast, small, typed; `httpx.MockTransport` makes the client testable without extra libraries | requests (sync), BeautifulSoup (slower, looser) |
| AD5 | **Cache raw pages** (not parsed results) in **SQLite**, keyed by request URL, TTL by page type | Parser fixes apply to cached data immediately; one simple table; stdlib `sqlite3`; survives restarts | Caching parsed results (stale on parser change); in-memory only; no cache |
````

Edit 5. Find:

````markdown
| AD14 | **No cookie jar**: every request sends exactly `Cookie: ro_ui=v2`; server-set cookies are discarded | Site sends `Vary: Cookie`; cached pages must not depend on hidden state (`pvin`, A/B cookies) | httpx default cookie persistence |
| AD15 | **Tool modules are auto-discovered** (`pkgutil` over `realoem_mcp.tools`); versions are bumped only at release | Feature branches add files instead of editing shared ones, so parallel branches don't conflict | Central registration list; per-PR version bumps |
| AD16 | **Vehicle index = committed per-brand CSV baseline + runtime SQLite store in the user data dir** (`vehicles.sqlite3`, separate from the page cache) | CSV diffs are reviewable and small in git; SQLite gives durable local additions and indexed search; keeping it out of the cache DB means `cache_clear`/schema resets never lose it; shipping the baseline means RealOEM serves the 165 index pages once, not once per user | Committed `.sqlite` (binary, bloats history); JSON (larger, not one-row-per-line); local-only build (165 requests per user); table inside the cache DB |

## 4. Repository layout

````

Replace with:

````markdown
| AD14 | **No cookie jar**: every request sends exactly `Cookie: ro_ui=v2`; server-set cookies are discarded | Site sends `Vary: Cookie`; cached pages must not depend on hidden state (`pvin`, A/B cookies) | httpx default cookie persistence |
| AD15 | **Tool modules are auto-discovered** (`pkgutil` over `realoem_mcp.tools`); versions are bumped only at release | Feature branches add files instead of editing shared ones, so parallel branches don't conflict | Central registration list; per-PR version bumps |
| AD16 | **Vehicle index = committed per-brand CSV baseline + runtime SQLite store in the user data dir** (`vehicles.sqlite3`, separate from the page cache) | CSV diffs are reviewable and small in git; SQLite gives durable local additions and indexed search; keeping it out of the cache DB means `cache_clear`/schema resets never lose it; shipping the baseline means RealOEM serves the 165 index pages once, not once per user | Committed `.sqlite` (binary, bloats history); JSON (larger, not one-row-per-line); local-only build (165 requests per user); table inside the cache DB |
| AD17 | **One hosted MCP server** (`https://realoem-searcher.fly.dev/mcp`, streamable HTTP, stateless) that users reach from the plugin with **GitHub sign-in**; the server is its own OAuth 2.1 authorization server, with per-user daily quotas, a request queue and a per-call deadline in front of the one polite client (hosted design H1-H8) | A local server never runs in chat or cloud Cowork; one process keeps AD6 exact for everyone; per-user identity gives quotas and bans; the shared cache means a page is fetched once for all users | Bundled Python or prebuilt binaries; a uv bootstrapper; an open endpoint; a hosted identity provider |

## 4. Repository layout

````

Edit 6. Find:

````markdown
├─ .claude-plugin/
│  ├─ plugin.json               # manifest; MCP server "realoem"; skills from the default skills/
│  └─ marketplace.json          # single-plugin marketplace (source "./")
├─ .github/workflows/ci.yml     # ruff + pytest (offline)
├─ brands/
│  ├─ bmw/          brand.toml, README.md, vehicles.csv
│  ├─ mini/         brand.toml, README.md, vehicles.csv
````

Replace with:

````markdown
├─ .claude-plugin/
│  ├─ plugin.json               # manifest; MCP server "realoem"; skills from the default skills/
│  └─ marketplace.json          # single-plugin marketplace (source "./")
├─ .github/workflows/
│  ├─ ci.yml                    # ruff + pytest (offline)
│  ├─ deploy.yml                # on a v* tag: ruff + pytest, then flyctl deploy (AD17)
│  └─ uptime.yml                # GET /healthz every 15 minutes
├─ .dockerignore                # only server/ and brands/ reach the image
├─ fly.toml                     # one always-on machine, one volume (AD17)
├─ brands/
│  ├─ bmw/          brand.toml, README.md, vehicles.csv
│  ├─ mini/         brand.toml, README.md, vehicles.csv
````

Edit 7. Find:

````markdown
│  ├─ supersession/SKILL.md      # feature E
│  └─ vehicle-index/SKILL.md     # F6
├─ server/
│  ├─ pyproject.toml            # project "realoem-mcp", script realoem-mcp = realoem_mcp.server:main
│  ├─ uv.lock
│  ├─ scripts/
│  │  ├─ trim_fixture.py        # raw page → trimmed fixture
│  │  ├─ capture_page.py        # polite single-page capture through RealOemClient (raw, uncommitted)
│  │  └─ rebuild_vehicle_index.py  # maintainer-only full rebuild of brands/*/vehicles.csv (F6)
│  ├─ src/realoem_mcp/
│  │  ├─ __init__.py            # __version__
│  │  ├─ server.py              # build_server(services) -> MCPServer; main()
│  │  ├─ services.py            # Services container + create_services(settings)
│  │  ├─ config.py              # Settings (env-overridable)
│  │  ├─ errors.py              # RealOemError hierarchy
````

Replace with:

````markdown
│  ├─ supersession/SKILL.md      # feature E
│  └─ vehicle-index/SKILL.md     # F6
├─ server/
│  ├─ pyproject.toml            # project "realoem-mcp"; scripts realoem-mcp (stdio), realoem-mcp-http
│  ├─ uv.lock
│  ├─ Dockerfile, docker-entrypoint.sh   # the hosted server's image
│  ├─ scripts/
│  │  ├─ admin.py               # hosted server: usage, ban, unban, revoke, prune
│  │  ├─ trim_fixture.py        # raw page → trimmed fixture
│  │  ├─ capture_page.py        # polite single-page capture through RealOemClient (raw, uncommitted)
│  │  └─ rebuild_vehicle_index.py  # maintainer-only full rebuild of brands/*/vehicles.csv (F6)
│  ├─ src/realoem_mcp/
│  │  ├─ __init__.py            # __version__
│  │  ├─ server.py              # build_server(services) -> MCPServer; main() (stdio)
│  │  ├─ http_app.py            # build_http_app(settings); main() (realoem-mcp-http)       (§5.13)
│  │  ├─ http_middleware.py     # security headers, request log, sign-in rate limits      (§5.13)
│  │  ├─ auth/                  # OAuth provider, sign-in store, keys, GitHub, consent pages (§5.13)
│  │  ├─ current_user.py        # the signed-in caller; CallClock (call deadline)         (§5.13)
│  │  ├─ quota.py, gate.py      # daily quotas; queue admission for cache-miss fetches    (§5.13)
│  │  ├─ shared.py              # build_shared(): Services wired for the hosted server    (§5.13)
│  │  ├─ storage_guard.py       # full disk / damaged database handling                   (§5.13)
│  │  ├─ rate_limit.py, log_privacy.py   # sliding windows; VIN-free logs                 (§5.13)
│  │  ├─ services.py            # Services container + create_services(settings)
│  │  ├─ config.py              # Settings (env-overridable)
│  │  ├─ errors.py              # RealOemError hierarchy
````

Edit 8. Find:

````markdown
{
  "name": "realoem-searcher",
  "displayName": "RealOEM Searcher",
  "version": "0.1.0",
  "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a local vehicle finder.",
  "author": { "name": "Cadtastic" },
  "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
  "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
  "license": "MIT",
  "keywords": ["bmw", "mini", "rolls-royce", "motorrad", "realoem", "oem-parts", "part-numbers", "vin-decoder", "parts-diagrams", "mcp"],
  "mcpServers": {
    "realoem": {
      "command": "uv",
      "args": ["run", "--quiet", "--no-dev", "--frozen", "--directory", "${CLAUDE_PLUGIN_ROOT}/server", "realoem-mcp"],
      "env": { "REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands" }
    }
  }
}
```
````

Replace with:

````markdown
{
  "name": "realoem-searcher",
  "displayName": "RealOEM Searcher",
  "version": "0.2.0",
  "description": "Look up BMW, MINI, Rolls-Royce and BMW Motorrad parts on RealOEM.com: part numbers and supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle comparison and a vehicle finder.",
  "author": { "name": "Cadtastic" },
  "homepage": "https://github.com/Cadtastic/RealOEM-Searcher",
  "repository": "https://github.com/Cadtastic/RealOEM-Searcher",
  "license": "MIT",
  "keywords": ["bmw", "mini", "rolls-royce", "motorrad", "realoem", "oem-parts", "part-numbers", "vin-decoder", "parts-diagrams", "mcp"],
  "mcpServers": {
    "realoem": { "type": "http", "url": "https://realoem-searcher.fly.dev/mcp" }
  }
}
```
````

Edit 9. Find:

````markdown
- Skills load from the default `skills/` folder. If a brand-specific skill is ever needed, add
  `"skills": ["./skills", "./brands/<brand>/skills"]` (the field supplements the default folder) in that
  change; do not list folders that don't exist.
- `--no-dev` keeps test/lint tools out of users' plugin environments; `--frozen` runs from the
  committed `uv.lock` without re-locking in the plugin cache.
- Tools are exposed to Claude as `mcp__plugin_realoem-searcher_realoem__<tool>`; skills refer to them by
  short name (`lookup_part`).
- `marketplace.json`: `{"name": "realoem-searcher", "owner": {"name": "Cadtastic"}, "plugins": [{"name":
````

Replace with:

````markdown
- Skills load from the default `skills/` folder. If a brand-specific skill is ever needed, add
  `"skills": ["./skills", "./brands/<brand>/skills"]` (the field supplements the default folder) in that
  change; do not list folders that don't exist.
- Since v0.2.0 the plugin starts nothing on the user's computer: Claude connects to the hosted
  server, and the user signs in once (`/mcp` in Claude Code, **Connect** in chat and Cowork). No
  `oauth` block: dynamic client registration works on every Claude surface. For development, run the
  stdio server with `uv run --directory server realoem-mcp`.
- Tools are exposed to Claude as `mcp__plugin_realoem-searcher_realoem__<tool>`; skills refer to them by
  short name (`lookup_part`).
- `marketplace.json`: `{"name": "realoem-searcher", "owner": {"name": "Cadtastic"}, "plugins": [{"name":
````

Edit 10. Find:

````markdown
| `data_dir` | `REALOEM_DATA_DIR` | `platformdirs.user_data_dir("realoem-searcher")` (durable data: vehicle index store) |
| `brands_dir` | `REALOEM_BRANDS_DIR` | `<repo>/brands` resolved relative to the package |
| `user_agent` | — (not overridable) | `RealOEM-Searcher/<__version__> (+https://github.com/Cadtastic/RealOEM-Searcher)` (AD13) |

### 5.2a Services container (`services.py`)

````

Replace with:

````markdown
| `data_dir` | `REALOEM_DATA_DIR` | `platformdirs.user_data_dir("realoem-searcher")` (durable data: vehicle index store) |
| `brands_dir` | `REALOEM_BRANDS_DIR` | `<repo>/brands` resolved relative to the package |
| `user_agent` | — (not overridable) | `RealOEM-Searcher/<__version__> (+https://github.com/Cadtastic/RealOEM-Searcher)` (AD13) |
| `mode` | — (set by the entry point) | `"stdio"`; `realoem-mcp-http` sets `"http"`, which switches on every hosted behaviour |
| `admins`, `user_daily_limit`, `new_user_daily_limit`, `min_account_age_days`, `global_daily_limit`, `call_deadline_s`, `cache_max_mb` | `REALOEM_ADMINS`, `REALOEM_USER_DAILY_LIMIT`, … | none, 300, 30, 30, 0 (off), 50 s, 400 MB in HTTP mode (0 = off in stdio) |
| `public_url`, `github_client_id`, `github_client_secret`, `secret_key`, `redirect_allowlist`, `hosted_client_range`, `auth_dir` | `REALOEM_PUBLIC_URL`, … | required in HTTP mode (the last three default to Claude's callback, Anthropic's range and `data_dir`); checked by `validate_http()` |

### 5.2a Services container (`services.py`)

````

Edit 11. Find:

````markdown
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)   # branch-owned singletons (e.g. vehicle index)

    async def aclose(self) -> None: ...          # closes client (httpx), cache (sqlite), and any extra with close()

def create_services(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                    clock: Callable[[], float] | None = None,
                    sleep: Callable[[float], Awaitable[None]] | None = None) -> Services: ...
```

Tools and exported fetch helpers receive a `Services` and use only these five attributes; `extras` holds
branch-owned singletons such as the vehicle index (`tools/vehicles.py`).

### 5.3 Errors (`errors.py`)
````

Replace with:

````markdown
    client: RealOemClient
    brands: BrandRegistry
    extras: dict[str, Any] = field(default_factory=dict)   # branch-owned singletons (e.g. vehicle index)
    run_storage: Runner = run_directly   # hosted server: the storage guard (§5.13)

    async def aclose(self) -> None: ...          # closes client (httpx), cache (sqlite), and any extra with close()

def create_services(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                    clock: Callable[[], float] | None = None,
                    sleep: Callable[[float], Awaitable[None]] | None = None,
                    admit=None, charge=None, owner=None) -> Services: ...
```

`admit`, `charge` and `owner` are the hosted server's client hooks (§5.5), set by
`shared.build_shared()`, which also sets `Services.run_storage` (the storage guard, §5.13).

Tools and exported fetch helpers receive a `Services` and use only these attributes; `extras` holds
branch-owned singletons such as the vehicle index (`tools/vehicles.py`).

### 5.3 Errors (`errors.py`)
````

Edit 12. Find:

````markdown
├─ NotFound                        # RealOEM has no such part/vehicle/VIN
├─ BotChallenge                    # Cloudflare challenge; includes the URL to open in a browser
├─ LayoutChanged(page_type, detail, url)   # parser invariant failed
└─ UpstreamError(status, url, detail=None) # non-200 after retries, timeouts, network errors
```

Tools catch `RealOemError` and raise `mcp.server.mcpserver.exceptions.ToolError(err.message)`, which
````

Replace with:

````markdown
├─ NotFound                        # RealOEM has no such part/vehicle/VIN
├─ BotChallenge                    # Cloudflare challenge; includes the URL to open in a browser
├─ LayoutChanged(page_type, detail, url)   # parser invariant failed
├─ UpstreamError(status, url, detail=None) # non-200 after retries, timeouts, network errors
├─ QuotaExceeded(limit, server_wide=False) # hosted: the daily budget is spent
├─ Busy                                    # hosted: too many fetches waiting
└─ CallDeadline                            # hosted: the tool call is out of time
```

Tools catch `RealOemError` and raise `mcp.server.mcpserver.exceptions.ToolError(err.message)`, which
````

Edit 13. Find:

````markdown
`"partxref"`, `"partsearch"`, `"part"`, `"vehicles"`); `cache_clear(page_type=...)` accepts these values.
`client.fetch(..., ttl=...)` may override the default. The TTL is applied when a page is **written**
(stored as `expires_at`). A tool that parses a negative result (e.g. VIN miss) calls
`cache.shorten(url, ttl)` to cap that entry's lifetime.

### 5.5 HTTP client (`http_client.py`)

````

Replace with:

````markdown
`"partxref"`, `"partsearch"`, `"part"`, `"vehicles"`); `cache_clear(page_type=...)` accepts these values.
`client.fetch(..., ttl=...)` may override the default. The TTL is applied when a page is **written**
(stored as `expires_at`). A tool that parses a negative result (e.g. VIN miss) calls
`cache.shorten(url, ttl, owner=page.owner)` to cap that entry's lifetime. On the hosted server,
`select?vin=` and `production` pages belong to the user who asked (a keyed hash of the user, never
the id) and live at most 30 days.

### 5.5 HTTP client (`http_client.py`)

````

Edit 14. Find:

````markdown
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool

class RealOemClient:
    def __init__(self, settings, cache: PageCache, *, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep): ...
    def build_url(self, path: str, params: Mapping[str, str]) -> str: ...
    async def fetch(self, page_type: PageType, path: str, params: Mapping[str, str], *,
                    refresh: bool = False, ttl: timedelta | None = None) -> Page: ...
````

Replace with:

````markdown
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool
    owner: str = ""     # "" = shared; else the cache owner of a VIN page (hosted)

class RealOemClient:
    def __init__(self, settings, cache: PageCache, *, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 admit=None, charge=None, owner=None): ...
    def build_url(self, path: str, params: Mapping[str, str]) -> str: ...
    async def fetch(self, page_type: PageType, path: str, params: Mapping[str, str], *,
                    refresh: bool = False, ttl: timedelta | None = None) -> Page: ...
````

Edit 15. Find:

````markdown
7. Only HTTP 200 pages are cached. The redirect-to-landing case (final URL path `/bmw/` or `/bmw/enUS/`
   without the requested path) is returned uncached with `final_url` set; callers turn it into
   `NotFound`. Helper: `page.redirected_away` (final path does not end with the requested path).
8. Two different counts: the client's process-wide `requests_made` (shown by `server_status`) counts
   **every HTTP request actually sent**, including retries, redirect hops, challenges and failures.
   A tool call's `ResultMeta.requests_made` counts **pages** it used with `from_cache=False` (a page that
   needed retries or a redirect still counts once); tools compute it from their pages, never from the
````

Replace with:

````markdown
7. Only HTTP 200 pages are cached. The redirect-to-landing case (final URL path `/bmw/` or `/bmw/enUS/`
   without the requested path) is returned uncached with `final_url` set; callers turn it into
   `NotFound`. Helper: `page.redirected_away` (final path does not end with the requested path).
8. Hosted server only (the three hooks are `None` in stdio): `owner(page_type, params)` picks the
   cache owner of a page; a cache miss enters `admit()` **before** waiting for the lock, then waits
   at most as long as the admission allows (`asyncio.timeout`; `Busy` or `CallDeadline`); `charge()`
   runs inside the lock after the second cache check misses, so a page another call fetched while
   this one waited is free; `refresh=true` is honoured only for copies older than an hour; log
   lines show `select` and `production` URLs with their query values masked.
9. Two different counts: the client's process-wide `requests_made` (shown by `server_status`) counts
   **every HTTP request actually sent**, including retries, redirect hops, challenges and failures.
   A tool call's `ResultMeta.requests_made` counts **pages** it used with `from_cache=False` (a page that
   needed retries or a redirect still counts once); tools compute it from their pages, never from the
````

Edit 16. Find:

````markdown

### 5.6 Cache (`cache.py`)

SQLite database `pages.sqlite3` in `cache_dir`, WAL mode:

```sql
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, page_type TEXT NOT NULL, final_url TEXT NOT NULL, status INTEGER NOT NULL,
  html TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version
```

API: `get(url) -> Page | None` (unexpired only), `put(page, ttl)`, `shorten(url, ttl)` (sets
`expires_at = min(expires_at, fetched_at + ttl)`), `clear(page_type: PageType | None = None) -> int`,
`stats() -> CacheStats(entries, bytes, path)`. Synchronous `sqlite3` calls (sub-millisecond at this
volume; a single connection with `check_same_thread=False`, used only from the event loop thread). A
schema-version mismatch drops and recreates the tables. Timestamps are stored as UTC ISO-8601 strings.

### 5.7 Brand registry (`brands.py`, `brands/*/brand.toml`)

````

Replace with:

````markdown

### 5.6 Cache (`cache.py`)

SQLite database `pages.v2.sqlite3` in `cache_dir` (schema version 2; the version 1 file
`pages.sqlite3` is deleted when possible), WAL mode, `auto_vacuum=INCREMENTAL`:

```sql
CREATE TABLE IF NOT EXISTS pages (
  owner TEXT NOT NULL, url TEXT NOT NULL, page_type TEXT NOT NULL, final_url TEXT NOT NULL,
  status INTEGER NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  last_used INTEGER NOT NULL, size_bytes INTEGER NOT NULL, html TEXT NOT NULL,  -- html last
  PRIMARY KEY (owner, url));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version, total_bytes
```

API: `get(url, *, owner="") -> Page | None` (unexpired only), `put(page, ttl) -> bool` (stores under
`page.owner`; `False` when the page was served uncached), `shorten(url, ttl, *, owner="")` (sets
`expires_at = min(expires_at, fetched_at + ttl)`), `clear(page_type: PageType | None = None) -> int`,
`purge_expired()`, `reset()`, `stats() -> CacheStats(entries, bytes, path)`. A running byte total in
`meta`, updated in the same transaction as every write, keeps `stats()` and the size cap
constant-time; `html` is the last column, so no bookkeeping query reads page bodies. With a cap
(400 MB on the hosted server) `put` evicts the least recently used pages to 90 % of it and vacuums
in chunks, each followed by a `TRUNCATE` checkpoint, so the freed space really leaves the disk; below
100 MB of free disk it evicts to half the cap and otherwise serves pages uncached, and a full disk
never fails a tool call. Synchronous `sqlite3` calls (a single connection with
`check_same_thread=False`, used only from the event loop thread). Timestamps are stored as UTC
ISO-8601 strings.

### 5.7 Brand registry (`brands.py`, `brands/*/brand.toml`)

````

Edit 17. Find:

````markdown
  back), catch `RealOemError` → `ToolError`, and return pydantic models.
- **Never keep an unparseable page cached:** pages are cached by the client before parsing, so when a
  parser raises `LayoutChanged` for a fetched page, the calling tool/helper runs
  `services.cache.shorten(page.url, timedelta(0))` (expires it immediately) before re-raising. Each
  feature tests this (serve a broken page twice → two requests).
- Every **data** tool result extends `ResultMeta` (admin tools `server_status` and `cache_clear`, and the
  local-only `find_vehicle`, whose result has no `ResultMeta`, are exempt):
````

Replace with:

````markdown
  back), catch `RealOemError` → `ToolError`, and return pydantic models.
- **Never keep an unparseable page cached:** pages are cached by the client before parsing, so when a
  parser raises `LayoutChanged` for a fetched page, the calling tool/helper runs
  `services.cache.shorten(page.url, timedelta(0), owner=page.owner)` (expires that entry immediately;
  on the hosted server a VIN page belongs to one user) before re-raising. Each
  feature tests this (serve a broken page twice → two requests).
- Every **data** tool result extends `ResultMeta` (admin tools `server_status` and `cache_clear`, and the
  local-only `find_vehicle`, whose result has no `ResultMeta`, are exempt):
````

Edit 18. Find:

````markdown
    source_urls: list[str]
    fetched_at: datetime        # oldest fetched_at among pages used (UTC)
    from_cache: bool            # True only if every page came from cache
    requests_made: int          # pages this call fetched from the network (§5.5 rule 8)

    @classmethod
    def from_pages(cls, pages: Sequence[Page], **fields) -> Self: ...   # fills the four fields
````

Replace with:

````markdown
    source_urls: list[str]
    fetched_at: datetime        # oldest fetched_at among pages used (UTC)
    from_cache: bool            # True only if every page came from cache
    requests_made: int          # pages this call fetched from the network (§5.5 rule 9)

    @classmethod
    def from_pages(cls, pages: Sequence[Page], **fields) -> Self: ...   # fills the four fields
````

Edit 19. Find:

````markdown

| Tool | Parameters | Result |
|---|---|---|
| `server_status` | — | `version, base_url, user_agent, min_interval_s, cache_path, cache_entries, cache_bytes, requests_made` |
| `cache_clear` | `page_type: str \| None = None` (PageType value) | `removed: int` |

**A: `lookup_part(part_number: str, series: str | None = None)` → `PartLookupResult`** (`tools/parts.py`,
`models/parts.py`). Request: `partxref` with params `q`, then `series` if given.
````

Replace with:

````markdown

| Tool | Parameters | Result |
|---|---|---|
| `server_status` | — | `version, base_url, user_agent, min_interval_s, cache_path, cache_entries, cache_bytes, requests_made, quota, global_limit`; on the hosted server `cache_path` is `null` and `quota` is the caller's `{used_today, limit, resets_at}` (`null` in stdio) |
| `cache_clear` | `page_type: str \| None = None` (PageType value) | `removed: int`; on the hosted server administrators only |

**A: `lookup_part(part_number: str, series: str | None = None)` → `PartLookupResult`** (`tools/parts.py`,
`models/parts.py`). Request: `partxref` with params `q`, then `series` if given.
````

Edit 20. Find:

````markdown
```python
class VehicleIndex:
    @classmethod
    def open(cls, settings: Settings, brands: BrandRegistry) -> "VehicleIndex": ...
        # creates tables; if sha256 of all brands/*/vehicles.csv + vehicles.meta.toml differs from the
        # stored baseline hash: delete source='baseline' rows, load CSVs, delete local rows whose key is
        # now in the baseline, store the new hash
````

Replace with:

````markdown
```python
class VehicleIndex:
    @classmethod
    def open(cls, settings: Settings, brands: BrandRegistry, *, run: Runner = run_directly) -> "VehicleIndex": ...
        # run: the storage guard on the hosted server (§5.13)
        # creates tables; if sha256 of all brands/*/vehicles.csv + vehicles.meta.toml differs from the
        # stored baseline hash: delete source='baseline' rows, load CSVs, delete local rows whose key is
        # now in the baseline, store the new hash
````

Edit 21. Find:

````markdown
```

- `update_vehicle_index(max_pages: int = 5)` → `VehicleIndexUpdateResult(ResultMeta)`: `status:
  Literal["up_to_date", "updated", "partial", "drift"], added: list[IndexedVehicle], remote_total: int,
  local_total: int, pages_fetched: int, message: str`. `max_pages` 1–10. Algorithm (always
  `refresh=True`, `sort=year`):
  0. No baseline to compare with (`built_at` is null or the index is empty) → `drift` with 0 requests and
````

Replace with:

````markdown
```

- `update_vehicle_index(max_pages: int = 5)` → `VehicleIndexUpdateResult(ResultMeta)`: `status:
  Literal["up_to_date", "updated", "partial", "drift", "cooldown"], added: list[IndexedVehicle], remote_total: int,
  local_total: int, pages_fetched: int, message: str`. `max_pages` 1–10. Algorithm (always
  `refresh=True`, `sort=year`):
  0. No baseline to compare with (`built_at` is null or the index is empty) → `drift` with 0 requests and
````

Edit 22. Find:

````markdown
     e.g. after removals), expire it, fetch page 1 to read `remote_total` and return `drift`. Past the
     end, RealOEM answers 200 with either no vehicle rows or, as observed live, the last page's rows
     repeated under an inverted "Showing a–b" range (a > b) (site notes §5.5).
- Note for the skill: index vehicle ids carry the vehicle's **production start** month; parts lists are
  filtered by month, so for a specific car's build month use `select_vehicle` with `prod` or
  `decode_vin`. End dates of vehicles still in production are "as of `built_at`".
````

Replace with:

````markdown
     e.g. after removals), expire it, fetch page 1 to read `remote_total` and return `drift`. Past the
     end, RealOEM answers 200 with either no vehicle rows or, as observed live, the last page's rows
     repeated under an inverted "Showing a–b" range (a > b) (site notes §5.5).
  5. Hosted server only: one update runs at a time for everyone; a call that arrives meanwhile waits
     (within the call limit) and gets its result with `requests_made` 0, the requests having been
     charged to the caller that ran it. After an `up_to_date` or `updated` result, calls within the
     hour return `cooldown` with no request (the cooldown lives in memory, so a restart allows one
     more check); a `partial` result starts no cooldown, so the update can be continued.
- Note for the skill: index vehicle ids carry the vehicle's **production start** month; parts lists are
  filtered by month, so for a specific car's build month use `select_vehicle` with `prod` or
  `decode_vin`. End dates of vehicles still in production are "as of `built_at`".
````

Edit 23. Find:

````markdown
  where relevant.
- Skills never instruct Claude to fetch RealOEM directly (WebFetch is blocked anyway); all access goes
  through the MCP tools.

## 6. Data flows

````

Replace with:

````markdown
  where relevant.
- Skills never instruct Claude to fetch RealOEM directly (WebFetch is blocked anyway); all access goes
  through the MCP tools.
- `vehicle-index` treats the hosted server's `cooldown` status (a completed check less than an hour
  ago) like `up_to_date`.

### 5.13 Hosted server (v0.2.0)

The [hosted server design](superpowers/specs/2026-10-01-hosted-server-design.md) has the details;
in short:

- **Entry point.** `realoem-mcp-http` builds the app with `http_app.build_http_app(settings)`:
  `build_server()` behind the MCP SDK's OAuth routes and bearer middleware, our consent and GitHub
  routes, `/healthz`, and three middlewares (security headers, a request log without query strings,
  sign-in rate limits keyed on `Fly-Client-IP`, IPv6 by /64). Stateless streamable HTTP with JSON
  responses; uvicorn on port 8080.
- **Sign-in.** `auth/provider.py` implements `OAuthAuthorizationServerProvider`: registration only
  for Claude's callback and loopback programs, consent before GitHub (CSRF-bound cookies, PKCE to
  GitHub with a derived verifier), one-time codes, one-hour access tokens, rotating refresh tokens
  with replay detection, at most 20 sign-ins per user, bans. `auth.sqlite3` stores every credential
  as a keyed hash (one key per kind, derived from `REALOEM_SECRET_KEY`).
- **Limits.** `quota.Quota` counts cache-miss fetches per user per UTC day (300; 30 for young GitHub
  accounts; an optional server-wide cap). `gate.FetchGate` admits a fetch to the queue only within
  the quota, the call deadline (`CallClock`, 50 s) and the queue limits (4 per user, 20 in all).
  `compare_vehicles` turns `Busy` and `CallDeadline` into a resumable partial result;
  `update_vehicle_index` runs one update at a time with a one-hour `cooldown`.
- **Storage.** `storage_guard.StorageGuard` handles a full disk in the auth database or the vehicle
  index by deleting the disposable page cache and retrying once; a second full disk or a damaged
  auth database exits the process, and Fly restarts it. A log filter keeps VINs out of every log
  line.
- **Deployment.** One always-on Fly.io machine with one 1 GB volume (`fly.toml`,
  `server/Dockerfile`); `deploy.yml` deploys on a `v*` tag after the offline tests; `uptime.yml`
  checks `/healthz` every 15 minutes. A machine a crash loop left stopped stays stopped (no request
  or deploy starts it) until the maintainer runs `fly machine start`. The maintainer manages users
  with `scripts/admin.py`.

## 6. Data flows

````

Edit 24. Find:

````markdown
| Concern | Approach |
|---|---|
| Politeness | AD6 limiter; no prefetching; request budgets on multi-page tools; cache first |
| Observability | Log to stderr (never stdout: stdio transport) at INFO: one line per network request (page type, URL, status, ms, cache hit/miss) |
| Security | Only GET to the configured base URL; inputs validated before URL building; all params URL-encoded; no secrets |
| Versioning | SemVer in `plugin.json`, `marketplace.json`, `pyproject.toml` and `realoem_mcp.__version__` kept equal. Foundation sets 0.1.0; feature PRs do **not** bump versions; a release commit on `main` bumps them (AD15) and updates `Cadtastic/Claude-Plugin-Collection` |
| Compatibility | Windows/macOS/Linux; paths via `pathlib`; SQLite from stdlib |

````

Replace with:

````markdown
| Concern | Approach |
|---|---|
| Politeness | AD6 limiter; no prefetching; request budgets on multi-page tools; cache first |
| Observability | Log to stderr (never stdout: stdio transport) at INFO: one line per network request (page type, URL, status, ms, cache hit/miss); the hosted server adds one line per HTTP request (method, path without query string, status, ms, `github:<id>`), and never logs a VIN, a token or the query string of a request to the server |
| Security | Only GET to the configured base URL; inputs validated before URL building; all params URL-encoded. Hosted server: OAuth 2.1 with PKCE and consent before GitHub, credentials stored as keyed hashes, a redirect allow-list, rate limits and body limits on the sign-in routes, security headers on every page, secrets only in Fly secrets (§5.13) |
| Versioning | SemVer in `plugin.json`, `marketplace.json`, `pyproject.toml` and `realoem_mcp.__version__` kept equal. Foundation sets 0.1.0; feature PRs do **not** bump versions; a release commit on `main` bumps them (AD15) and updates `Cadtastic/Claude-Plugin-Collection` |
| Compatibility | Windows/macOS/Linux; paths via `pathlib`; SQLite from stdlib |

````

Edit 25. Find:

````markdown
  `XXXXXXXXXX`.
- CI (`.github/workflows/ci.yml`): `uv sync --locked`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pytest -m "not live"` on ubuntu (Python 3.11 and 3.13) and windows (3.13).

## 9. Branch and delivery plan

````

Replace with:

````markdown
  `XXXXXXXXXX`.
- CI (`.github/workflows/ci.yml`): `uv sync --locked`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pytest -m "not live"` on ubuntu (Python 3.11 and 3.13) and windows (3.13).
- Deployment (`.github/workflows/deploy.yml`): a `v*` tag runs the same checks on ubuntu (CI does not
  run on tags), then `flyctl deploy --remote-only --ha=false` from the `production` environment,
  which holds an app-scoped deploy token and requires a reviewer. The hosted server's sign-in, quota,
  gate, middleware and storage guard are tested offline through the real ASGI app with a fake GitHub
  (`tests/http/`, `tests/http_env.py`).

## 9. Branch and delivery plan

````

- [ ] **Commit**

````bash
git add docs/ARD.md
git commit -m "docs: ARD for the hosted server" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
````

### Task 15: Final checks and the release pull request (agent)

- [ ] **Step 1: Everything green**

Run: `uv run --directory server pytest -q`
Expected: `1263 passed, 6 deselected`.

Run: `uv run --directory server ruff check && uv run --directory server ruff format --check`
Expected: `All checks passed!` and every file already formatted.

- [ ] **Step 2: Scope check**

````bash
git diff --stat origin/main...HEAD
````

Expected: 13 files: the 7 of Task 12, the 5 of Task 13 and the ARD (Task 14).

- [ ] **Step 3: Push and open the pull request** (only when the controller asks you to; otherwise
  stop here and report). **Do not merge it**: the owner merges it in Task 16.

````bash
git push -u origin release/0.2.0
gh pr create --base main --head release/0.2.0 \
  --title "release: 0.2.0, the plugin connects to the hosted server" \
  --body-file - <<'EOF'
## Summary

Plan 2, chunks 3 and 4, of the hosted server (spec: docs/superpowers/specs/2026-10-01-hosted-server-design.md,
section 8). The server is already live at https://realoem-searcher.fly.dev (plan 2, chunk 2).

- plugin.json connects to https://realoem-searcher.fly.dev/mcp instead of starting a local server with uv;
  nothing to install in Claude Code, Cowork or chat.
- Version 0.2.0 in plugin.json, marketplace.json, pyproject.toml, uv.lock and __version__.
- README (install, connect and sign in; daily limits; privacy; running the server), CHANGELOG
  0.2.0, the vehicle-index and vin-decode skills, ARD and PRD.

## Test plan

- [x] uv run pytest: 1263 passed, 6 deselected
- [x] ruff check and ruff format --check
- [x] claude plugin validate . --strict, and for .claude-plugin/plugin.json
- [ ] Owner: CHANGELOG dated, then merge, tag v0.2.0 and approve the deploy (plan 2, Task 16)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
````

### Task 16: The release (owner)

- [ ] **Step 1: Preconditions**
  - RealOEM's owner has answered the message of Task 11 without objecting, or 7 days (or the
    longer wait chosen there) have passed without an answer. If they object, stop: do not merge.
    The server can stay up unannounced, or be stopped with
    `fly scale count 0 --app realoem-searcher` and, so the uptime check stops emailing,
    `gh workflow disable uptime.yml --repo Cadtastic/RealOEM-Searcher`.
  - `https://realoem-searcher.fly.dev/healthz` answers `ok`, and the latest Uptime run is green.

- [ ] **Step 2: Date the changelog, then merge.** In the worktree of Task 12 (Git Bash's `sed`;
  on macOS write `sed -i ''`):

````bash
sed -i "s/^## \[0.2.0\] - release day$/## [0.2.0] - $(date -u +%F)/" CHANGELOG.md
git diff
````

Expected: the diff changes only the `## [0.2.0]` heading. Then:

````bash
git commit -m "docs: date the 0.2.0 release" CHANGELOG.md
git push
````

Merge the pull request (squash) once its CI is green. Then, from the main checkout, remove the
worktree of Task 12 and its branch:

````bash
git worktree remove .worktrees/release-0.2.0
git branch -D release/0.2.0
````

- [ ] **Step 3: Tag, approve, watch.** First check that `main` ends with the release:

````bash
git fetch origin
git log -1 --format=%s origin/main
````

Expected: `release: 0.2.0, the plugin connects to the hosted server (#<number>)`. Then tag it:

````bash
git tag -a v0.2.0 origin/main -m "RealOEM Searcher 0.2.0" -m "The plugin now connects to the hosted server at https://realoem-searcher.fly.dev: it works in Claude Code, Cowork and chat with nothing to install. See CHANGELOG.md."
git push origin v0.2.0
````

In GitHub, **Actions**, **Deploy**: the run waits for `production`; **Review deployments**,
**production**, **Approve and deploy**. Then:

````bash
gh run list --workflow deploy.yml --repo Cadtastic/RealOEM-Searcher --limit 1 --json status,conclusion --jq '.[0] | .status + " " + .conclusion'
curl -s https://realoem-searcher.fly.dev/healthz; echo
fly releases --app realoem-searcher | head -3
````

Expected: `completed success` (run the first command again while it shows `queued`, `waiting` or
`in_progress`); `ok`; a new release at the top of the list.

- [ ] **Step 4: The GitHub release**, with the 0.2.0 section of the tagged changelog as its notes:

````bash
git show v0.2.0:CHANGELOG.md | awk '/^## \[0.2.0\]/{on=1; next} /^## \[/{on=0} on' > notes-0.2.0.md
gh release create v0.2.0 --repo Cadtastic/RealOEM-Searcher --verify-tag --title "RealOEM Searcher 0.2.0" --notes-file notes-0.2.0.md
rm notes-0.2.0.md
````

- [ ] **Step 5: Smoke sessions** (PRD section 7; the owner approves their RealOEM requests, a few
  dozen). This repository's marketplace serves 0.2.0 from the merge on, so test from it before
  the plugin collection switches (Step 6). In a second terminal, keep the log while the sessions
  run: `fly logs --app realoem-searcher > smoke.log` (Ctrl+C at the end).
  1. **Claude Code.** Remove the 0.1.0 plugin, which runs the old local server
     (`/plugin uninstall realoem-searcher@cadtastic`), then `/plugin marketplace add
     Cadtastic/RealOEM-Searcher` (or `/plugin marketplace update realoem-searcher` if it is
     there) and `/plugin install realoem-searcher@realoem-searcher`. In a new session check that
     `/plugin` shows 0.2.0 and that `/mcp` lists `plugin:realoem-searcher:realoem` as an HTTP
     server; **Authenticate**, and ask for `server_status`: `cache_path` null and a `quota`.
     Then ask the five questions of PRD section 7.
     Before going on, count the `select` and `production` pages fetched so far (their query values
     are all masked as `***` in the log, so they are counted rather than compared):
     `grep "(cache miss)" smoke.log | grep -c '\*\*\*'`.
  2. **Cowork** (a cloud session) and **chat** (claude.ai): **Customize**, **Plugins**, **Add**,
     **Add marketplace**, **Add from a repository**, `Cadtastic/RealOEM-Searcher`, then install
     RealOEM Searcher from **Discover** and **Connect** it on its **Connectors** tab. Do the same
     `server_status` check, then ask the same five questions in each.

Expected: every answer is right, and no RealOEM page was fetched twice: the same GitHub account
signed in everywhere, so Cowork and chat answer from the pages Claude Code fetched. The count of
masked lines is the same as after the Claude Code part, and this prints nothing:

````bash
grep "(cache miss)" smoke.log | grep -v '\*\*\*' | grep -o "https://www.realoem.com[^ ]*" | sort | uniq -d
````

Reading a mismatch: if Claude in Cowork or chat takes another route (another vehicle variant for
question 3, say), the masked count grows by new `select` pages, which are not repeats; the VIN
page was reused when `decode_vin` there shows `from_cache` true and `requests_made` 0. A URL the
duplicate check prints next to a `failed:` line or a `429` or `5xx` status is a retry, not a
refetch. Then delete `smoke.log`.

- [ ] **Step 6: The plugin collection.** In a checkout of `Cadtastic/Claude-Plugin-Collection`, on
  a new branch, as its `CLAUDE.md` asks for a release:
  - in `.claude-plugin/marketplace.json`, the `realoem-searcher` entry: `"ref"` to `"v0.2.0"`,
    `"version"` to `"0.2.0"`, and in `"description"` "a local vehicle finder" to "a vehicle
    finder" (as in this repository's `marketplace.json`);
  - in `README.md`, the RealOEM Searcher row: version `0.2.0`, "a vehicle finder", and instead of
    "Needs [uv](https://docs.astral.sh/uv/)." the sentence "Connect it once and sign in with
    GitHub; nothing to install.";
  - run `claude plugin validate . --strict` and `python scripts/check_versions.py`, open a pull
    request, and merge it once its CI is green.

  Then check the collection's install in Claude Code: `/plugin marketplace update cadtastic`,
  uninstall `realoem-searcher@realoem-searcher`, install `realoem-searcher@cadtastic`, and in a new
  session `/plugin` shows 0.2.0 and `server_status` answers (**Authenticate** in `/mcp` first if
  it asks).

- [ ] **Step 7: The first week.** Every day or two:
  - Search the app's logs for `refresh_reuse` in Fly's log search (Grafana, linked from the app's
    **Monitoring** page in the Fly dashboard; it keeps several days, while `fly logs` shows only
    what happens while it runs). None are expected. Lines for real Claude clients mean Claude
    refreshed a token twice at once (spec section 10): then the rotation needs a grace period of
    at most 30 seconds, a code change with its own plan.
  - Look at the day's usage with the admin script (Task 9, Step 3); ban abuse with its `ban`
    command.
  - Check that Uptime stays green.
