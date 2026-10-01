# Hosted Server Design

**Status:** approved design, 2026-10-01. Supersedes the "local stdio server" distribution decided in
ARD AD1 and AD2 for the plugin; the stdio entry point stays for development and tests.

## 1. Problem

RealOEM Searcher 0.1.0 ships its MCP server as a local process that Claude starts with
`uv run … realoem-mcp`. That works in Claude Code on a machine with `uv`, and nowhere else:

- Cowork starts plugin servers inside its own Linux VM, which has no `uv`, so the server never
  starts (observed 2026-10-01; the other uv-based plugin on the same machine never connected either).
- Claude's [platform support table](https://claude.com/docs/plugins/platform-support.md) says a local
  MCP server is **ignored** in chat and loads in Cowork only "when the Cowork session runs on your
  computer".
- From **2026-10-06**, new Cowork tasks on Pro and Max plans run in the cloud, and the
  "Only on your computer" option is removed
  ([Cowork on web, desktop and mobile](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile)).

No way of packaging a local server fixes chat or cloud Cowork. A remote `http` MCP server "loads;
connect it from the plugin's Connectors tab" on every surface. The goal of this change: **installing
the plugin is all a user has to do**, apart from the one-time **Connect** click that every remote
connector needs.

## 2. Decisions

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| H1 | **One hosted HTTP MCP server**; `plugin.json` declares `{"type": "http", "url": "https://<host>/mcp"}` and no local command | Only option that reaches chat, Cowork (local and cloud) and Claude Code; Anthropic's own guidance prefers remote servers for distribution | Bundled Python or prebuilt binaries (never run in chat or cloud Cowork); uv bootstrapper (same); two plugins (duplicate tools) |
| H2 | **Users sign in with GitHub**; the server is its own OAuth authorization server and delegates login to one GitHub OAuth App | Claude's surfaces need dynamic client registration, which GitHub lacks; per-user identity gives quotas and bans; no extra vendor; the pinned `mcp` SDK (2.2) implements the authorization-server side | Open endpoint (no abuse control: Cowork traffic shares Anthropic's IPs); hosted identity provider (extra vendor, Claude-compatible registration unverified) |
| H3 | **Fly.io, one always-on machine (shared-cpu-1x, 512 MB), one 1 GB volume**, deployed with `--ha=false` and `auto_stop_machines = "off"` | One process keeps the global politeness rule exact; about $3–5 a month; HTTPS and a shared IPv4 included (hosted connectors need IPv4) | VPS (own OS, TLS, backups); Azure Container Apps (SQLite on network storage) |
| H4 | **Per-user quota of RealOEM network requests per day** (default 300, UTC day); cache hits are free; a **server-wide daily cap exists but is off by default** | Owner's choice; the server-wide cap is a one-command backstop if RealOEM asks, without a redeploy | Server-wide cap on by default |
| H5 | **Stateless streamable HTTP with JSON responses** | Restarts and deploys break nothing; one instance anyway; Claude needs no server push | Sessions (lost on restart) |
| H6 | **Tokens are opaque random values stored as SHA-256 hashes**; access tokens live 1 hour; refresh tokens rotate on every use | Spec and Claude requirements; a leaked database leaks no usable tokens | JWTs (a signing key to protect; no revocation without a list) |
| H7 | The **stdio entry point and the offline test suite stay**; the HTTP app wraps the same `build_server()` | Every parser and tool test still runs offline and unchanged | Separate server code for HTTP |

All existing politeness decisions stay: one request in flight, ≥ 2 s between request starts, honest
User-Agent, `ro_ui=v2` only, no challenge bypass, cached pages, no crawling.

## 3. Architecture

```
Claude (chat / Cowork / Claude Code)
        │  HTTPS, Authorization: Bearer <access token>
        ▼
https://<host>            (Fly.io, one machine, one Python process: uvicorn + Starlette)
  ├─ /mcp ..................... the 13 tools (MCP streamable HTTP, stateless, JSON)
  ├─ /.well-known/oauth-protected-resource/mcp, /.well-known/oauth-authorization-server
  ├─ /register /authorize /token /revoke ........ OAuth authorization server (SDK routes)
  ├─ /consent, /oauth/github/callback .......... consent page, GitHub login hand-off (ours)
  └─ /healthz
        │
        ├─ RealOemClient (unchanged rules, shared by every user) ──► realoem.com
        └─ Fly volume /data: pages.sqlite3 (page cache), vehicles.sqlite3 (vehicle index),
                             auth.sqlite3 (clients, codes, tokens, users, bans, usage)
```

The plugin keeps its skills. `plugin.json` changes only `mcpServers`:

```json
"mcpServers": { "realoem": { "type": "http", "url": "https://<host>/mcp" } }
```

No `oauth` block: dynamic client registration works on every Claude surface, so the plugin ships no
client id or secret.

## 4. Components

New code lives in `server/src/realoem_mcp/`. Existing tool modules are untouched except the two
admin tools (section 4.7). Every module has one job; HTTP handlers stay thin.

### 4.1 `http_app.py` and the `realoem-mcp-http` entry point

- `build_http_app(services, auth_settings, provider) -> Starlette`: calls the existing
  `build_server(services)` with `auth_server_provider=provider` and `auth=AuthSettings(...)`, mounts
  the custom routes of section 4.5, adds `/healthz`.
- `AuthSettings`: `issuer_url = public URL`, `resource_server_url = <public URL>/mcp`,
  `validate_token_resource = True`, `required_scopes = ["realoem"]`,
  `client_registration_options = ClientRegistrationOptions(enabled=True, valid_scopes=["realoem"],
  default_scopes=["realoem"])`, `revocation_options = RevocationOptions(enabled=True)`.
- Transport: `streamable_http_app(stateless_http=True, json_response=True,
  transport_security=TransportSecuritySettings(allowed_hosts=[public host, "localhost:*"]))`.
- `main()` runs uvicorn on `0.0.0.0:8080`, logging to stderr as today. The `[project.scripts]` entry
  `realoem-mcp-http = "realoem_mcp.http_app:main"` is added; `realoem-mcp` (stdio) stays.
- A request-scoped **current user** context variable is set from the SDK's `get_access_token()`
  (subject `github:<numeric id>`) by a small middleware before each tool call.

### 4.2 `auth/provider.py`

`RealOemAuthProvider(OAuthAuthorizationServerProvider)`, pure logic over `AuthStore` and a
`GitHubLogin`; no Starlette imports.

| Method | Behaviour |
|---|---|
| `register_client` | Accepts only redirect URIs that are `https://claude.ai/api/mcp/auth_callback` or loopback (`http://localhost/…`, `http://127.0.0.1/…`, any port). Anything else raises `RegistrationError("invalid_redirect_uri")`. Rate limit: at most 30 registrations per hour per source address, else `RegistrationError("too_many_registrations")`. Clients are persisted; clients unused for 90 days are pruned. |
| `get_client` | Returns a `LoopbackAwareClient` whose `validate_redirect_uri` matches loopback URIs ignoring the port (Claude Code uses an ephemeral port) and everything else exactly. |
| `authorize` | Stores the pending request (client, PKCE challenge, redirect URI, `state`, `resource`, scopes) under a random id with a 10-minute expiry and returns the GitHub authorization URL (section 4.4) with its own `state`. |
| GitHub return (called by the callback route) | Verifies the GitHub `state`, exchanges the code, reads the numeric id; refuses banned users; if this user has not yet approved this client, returns the consent page; otherwise issues a one-time authorization code (10-minute expiry) bound to the pending request and redirects to the client's redirect URI with the original `state`. |
| `load_authorization_code`, `exchange_authorization_code` | PKCE verifier checked by the SDK; a code is single-use (deleted on exchange; a second use fails); the issued tokens copy the request's `resource`. |
| `load_access_token` | Hash lookup; returns `AccessToken(subject, scopes, expires_at, resource)` or `None` when unknown, expired or revoked. |
| `load_refresh_token`, `exchange_refresh_token` | Rotation: the old refresh token is deleted and a new pair is issued; reuse of a rotated token revokes the whole token family and fails with `invalid_grant`. |
| `revoke_token` | Deletes the token and, for a refresh token, its family. |

### 4.3 `auth/store.py`

SQLite (`auth.sqlite3`, WAL), stdlib `sqlite3`, schema-versioned like the page cache. Tables:
`clients`, `pending_authorizations`, `authorization_codes`, `tokens` (hash, kind, family, subject,
client_id, scopes, resource, expires_at, revoked), `users` (subject, github_login for display,
first_seen, banned_at, banned_reason), `consents` (subject, client_id, granted_at),
`usage` (subject, day, requests). Secrets never stored in clear: tokens and codes as SHA-256 hashes.

### 4.4 `auth/github.py`

`GitHubLogin` builds the GitHub authorization URL (client id, redirect
`https://<host>/oauth/github/callback`, PKCE S256, `state`, no scopes: public profile only),
exchanges the code at `https://github.com/login/oauth/access_token`, and calls
`https://api.github.com/user` for `id` and `login`. The GitHub token is used once and discarded,
never stored and never passed through. Behind a small protocol so tests use a fake.

### 4.5 `auth/pages.py` and custom routes

- `GET /oauth/github/callback`: hands the query to the provider; renders consent or redirects.
- `POST /consent`: records the decision; **Allow** issues the code and redirects, **Deny** redirects
  to the client with `error=access_denied`.
- Consent page shows the client's registered name and redirect host ("*Claude* at claude.ai wants
  to use RealOEM Searcher as you (@login)") with Allow and Deny. Plain HTML, no scripts, no cookies;
  the pending-request id travels in a signed, short-lived form field.
- Error pages: banned ("access to RealOEM Searcher is suspended" + contact link), expired request,
  GitHub unavailable. No stack traces.

### 4.6 `quota.py`

- `Quota.charge(subject) -> None | QuotaExceeded`: increments `usage` for the UTC day and refuses
  when `requests >= user_daily_limit`, or when the global cap is on (> 0) and the day's total has
  reached it. Charged **only** on a cache miss, before the network request.
- Hook point: `RealOemClient` gets an optional `before_request: Callable[[], Awaitable[None]]`
  called inside the lock after the second cache check and before `_get_with_retries`. The HTTP app
  passes a hook that reads the current user and calls `Quota.charge`. The stdio server passes none.
- `QuotaExceeded` is a `RealOemError`, so tools report it as a tool error:
  "You've used your 300 RealOEM lookups for today; the limit resets at 00:00 UTC. Cached results
  remain available." (server-wide wording when the global cap triggered).

### 4.7 Changed settings and tools

New `Settings` fields / env: `public_url` (`REALOEM_PUBLIC_URL`), `user_daily_limit`
(`REALOEM_USER_DAILY_LIMIT`, 300), `global_daily_limit` (`REALOEM_GLOBAL_DAILY_LIMIT`, 0 = off),
`admins` (`REALOEM_ADMINS`, comma-separated GitHub numeric ids), `github_client_id` /
`github_client_secret` (`REALOEM_GITHUB_CLIENT_ID` / `REALOEM_GITHUB_CLIENT_SECRET`),
`auth_dir` (`REALOEM_AUTH_DIR`, defaults to `data_dir`). All validated at startup; the HTTP entry
point refuses to start without `public_url` and the GitHub credentials.

- `cache_clear`: admins only; others get a tool error naming the restriction.
- `server_status`: no file paths; adds `quota: {used_today, limit, resets_at}` for the caller and
  `global_limit` when on.
- `update_vehicle_index`: unchanged, and its requests count against the caller's quota.
- `scripts/admin.py` (run via `fly ssh console`): `usage [--day]`, `ban <id> --reason`, `unban`,
  `revoke <id>`, `prune`.

### 4.8 Deployment

- `server/Dockerfile`: `python:3.13-slim`, `uv sync --frozen --no-dev`, non-root user, `CMD
  realoem-mcp-http`. `fly.toml`: one process, internal port 8080, `force_https = true`,
  `auto_stop_machines = "off"`, `min_machines_running = 1`, volume `realoem_data` at `/data`, HTTP
  health check on `/healthz`, env `REALOEM_CACHE_DIR=/data/cache`, `REALOEM_DATA_DIR=/data/data`.
- Secrets via `fly secrets set`: `REALOEM_PUBLIC_URL`, `REALOEM_GITHUB_CLIENT_ID`,
  `REALOEM_GITHUB_CLIENT_SECRET`, `REALOEM_ADMINS`, `REALOEM_CONSENT_SIGNING_KEY`.
- GitHub Actions `deploy.yml`: on a `v*` tag, after CI passes, `flyctl deploy --remote-only --ha=false`
  with `FLY_API_TOKEN` from repository secrets.
- Backups: Fly daily volume snapshots (5-day retention) plus a weekly `scripts/backup.py` that
  copies the three SQLite files to a Fly-hosted object bucket is **out of scope for 0.2.0**; the
  vehicle index can always be rebuilt from the committed baseline, the cache is disposable, and
  losing `auth.sqlite3` only means users click Connect again.

## 5. Data flow

**Sign-in (once per surface; chat and Cowork share one, Claude Code has its own):**

1. The user installs the plugin and clicks **Connect** on its Connectors tab (chat, Cowork) or
   runs `/mcp` (Claude Code).
2. Claude calls `/mcp` without a token → `401` with `WWW-Authenticate: Bearer
   resource_metadata="https://<host>/.well-known/oauth-protected-resource/mcp"`.
3. Claude reads the metadata, registers at `/register` (redirect URI checked), gets a client id.
4. Claude opens `/authorize` (PKCE S256, `resource=https://<host>/mcp`, `scope=realoem`) in the
   user's browser; the server stores the pending request and redirects to GitHub.
5. GitHub returns to `/oauth/github/callback`; the server checks `state`, exchanges the code,
   reads the numeric id. Banned → error page.
6. First time for this client: consent page; **Allow** is remembered per (user, client).
7. The server redirects to Claude's redirect URI with a one-time code and the original `state`;
   Claude exchanges it at `/token` for a 1-hour access token and a refresh token.

**Tool call:**

1. `Authorization: Bearer <token>` → SDK middleware validates (exists, unexpired, resource matches
   `/mcp`, scope `realoem`) and exposes the `AccessToken`; our middleware sets the current user.
2. The tool runs as today. On a cache miss, `before_request` charges the quota; over the limit →
   refused before any network request. Otherwise the fetch waits its turn (one in flight, ≥ 2 s).
3. The result returns with `source_urls`. Claude refreshes tokens proactively; each refresh rotates
   the refresh token.

**Shared state:** one page cache and one vehicle index for everyone. A page fetched for one user is
free for all others until its TTL expires.

## 6. Error handling

| Situation | Behaviour | User-facing text |
|---|---|---|
| No or expired token | `401` + resource metadata pointer (SDK); Claude refreshes or starts sign-in | Claude prompts to (re)connect |
| Wrong scope or resource | `403 insufficient_scope` / `401` (SDK) | Claude re-authorizes |
| Daily user limit reached | Refused before any request; cache hits still answered | "You've used your 300 RealOEM lookups for today; the limit resets at 00:00 UTC. Cached results remain available." |
| Server-wide cap on and reached | Same | "RealOEM Searcher has reached its daily request limit; try again after 00:00 UTC." |
| Banned user | Tokens deleted; sign-in refused at the GitHub step | Error page: access suspended, contact link |
| Bot challenge / layout change / upstream error | Unchanged; not cached; counts against quota | Today's messages (ARD §5.3) |
| GitHub unavailable during sign-in | Clean failure, nothing stored | "GitHub sign-in is unavailable right now; try again shortly." |
| Bad registration | `400 invalid_redirect_uri` or `429` | Client-only |
| Restart (deploy, migration) | A few seconds of failed connections; no state lost | Claude retries |
| Disk full / auth DB unreadable | `/healthz` fails → Fly restarts the machine; error logged | Brief outage |

Logs carry `github:<id>`, tool name, page type and outcome; never tokens, codes or GitHub tokens.

## 7. Testing

Offline, in CI, no network (extends the existing 942 tests):

- **Provider unit tests:** redirect allow-list (Claude callback, loopback any port, everything else
  rejected); registration rate limit; PKCE failure; `state` mismatch; code single-use and expiry;
  refresh rotation and reuse-revokes-family; revocation; hashes only in the store; banned user
  refused; consent remembered per client.
- **Fake GitHub:** in-process stand-in for the two GitHub endpoints (`respx`/`httpx.MockTransport`).
- **End-to-end over HTTP** (`httpx.AsyncClient` against the Starlette app, in-memory): discovery
  → register → authorize → fake GitHub → consent → token → `tools/list` → `lookup_part` against
  the existing fixture routes; `401` without a token; `403` for a missing scope; two users share
  the cache (second identical call costs no quota); `cache_clear` refused for a non-admin and
  allowed for an admin.
- **Quota tests:** cache hits free; UTC rollover; refusal makes no request; global cap works when on
  and is inert at 0; `server_status` reports the caller's usage.
- **Settings tests:** HTTP entry point refuses to start without public URL / GitHub credentials.
- **Unchanged:** all stdio, parser and tool tests.

Before release: Opus security review of `auth/` against the MCP security best practices; local
container run checked with `curl` discovery, MCP Inspector and `claude mcp add`; after deploy, sign
in and run the PRD §7 smoke session from Claude Code, a Cowork cloud session and chat, with the
replay check (zero repeat RealOEM requests).

## 8. Rollout

1. Send the RealOEM owner message (drafted 2026-10-01: per-user daily limits, shared cache, honest
   UA, offer to adjust or stop). Hold the public switch until a reply or a reasonable wait.
2. Release **0.2.0**: `plugin.json` → hosted URL; Claude-Plugin-Collection entry → `v0.2.0`;
   README install = "Install, then click Connect"; ARD gains AD17 (hosted server) and marks AD1/AD2
   as development-only; PRD F0.1/F0.2 updated; CHANGELOG entry.
3. 0.1.0 installs are offered the update automatically.

## 9. Out of scope

Google sign-in; an admin web UI; CIMD (dynamic registration works on every surface today; the
2026-07-28 spec deprecates it, so CIMD is a later change); multi-region or replicas; per-user cache
isolation; a Fly-hosted backup bucket (see 4.8).

## 10. Open questions

- Final hostname: `realoem-searcher.fly.dev` or a custom domain (needs an A record; hosted
  connectors are IPv4-only).
- Whether Claude Code honours a plugin `oauth` block is unverified; the design does not need it.
- Whether hosted Claude keeps long-lived HTTP sessions is unverified; stateless mode makes it moot.
