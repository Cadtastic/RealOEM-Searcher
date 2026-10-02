# Hosted Server Design

**Status:** approved design, 2026-10-01, revised after two rounds of spec and security review,
and amended by the reviews of implementation plans 1a (cache file, client hooks, quota details)
and 1b (sign-in hardening: allow-list checks, IPv6 rate-limit keys, form limits, token logging).
Supersedes the "local stdio server" distribution of ARD AD1/AD2 for the plugin; the stdio entry
point stays for development and tests.

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
connect it from the plugin's Connectors tab" on every surface. Goal: **installing the plugin is all a
user has to do**, apart from the one-time **Connect** click (chat, Cowork) or `/mcp` sign-in
(Claude Code) that every remote connector needs.

## 2. Decisions

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| H1 | **One hosted HTTP MCP server**; `plugin.json` declares `{"type": "http", "url": "https://<host>/mcp"}` and no local command | Only option that reaches chat, Cowork (local and cloud) and Claude Code; Anthropic's guidance prefers remote servers for distribution | Bundled Python or prebuilt binaries (never run in chat or cloud Cowork); uv bootstrapper (same); two plugins (duplicate tools) |
| H2 | **Users sign in with GitHub**; the server is its own OAuth 2.1 authorization server and delegates login to one GitHub OAuth App | Claude's surfaces need dynamic client registration (DCR), which GitHub lacks; per-user identity gives quotas and bans; no extra vendor; the pinned `mcp` SDK (2.2.0) implements the authorization-server side | Open endpoint (no abuse control: Cowork traffic shares Anthropic's egress range `160.79.104.0/21`); hosted identity provider (extra vendor; Claude-compatible registration unverified) |
| H3 | **Fly.io, one always-on machine (shared-cpu-1x, 512 MB), one 1 GB volume**, deployed with `--ha=false` and `auto_stop_machines = "off"` | One process keeps the global politeness rule exact; about $3–5 a month; HTTPS and a shared IPv4 included (hosted connectors are IPv4-only) | VPS (own OS, TLS, backups); Azure Container Apps (SQLite on network storage) |
| H4 | **Per-user quota of cache-miss page fetches per UTC day** (default 300; 30 for GitHub accounts younger than 30 days); a **server-wide daily cap exists but is off by default** | Owner's choice; the server-wide cap is a backstop if RealOEM asks (`fly secrets set`, which restarts the server once) | Server-wide cap on by default (the security review recommends it at launch; owner's call) |
| H5 | **Stateless streamable HTTP with JSON responses**, a per-call deadline, and queue admission limits | Restarts and deploys break nothing; one instance anyway; Claude needs no server push; multi-request tools already support partial, resumable results | Sessions (lost on restart) |
| H6 | **Tokens and codes are 256-bit random values stored as keyed hashes**, each kind under its own derived key; access tokens live 1 hour; refresh tokens rotate on every use with replay detection | OAuth 2.1 and Claude requirements; a copied database (or Fly snapshot) yields no usable credentials; a token of one kind can never pass as another | JWTs (a signing key to protect; no revocation without a list) |
| H7 | The **stdio entry point and the offline test suite stay**; the HTTP app wraps the same `build_server()`; the mode is an explicit setting | Every parser and tool test still runs offline; stdio is the development and test harness; no behaviour is inferred from the absence of a token | Separate server code for HTTP; mode inferred from context |
| H8 | **Consent before GitHub**, on every authorization, bound to the browser with cookies | MCP authorization spec and security best practices (confused deputy): consent for each dynamically registered client **before** the third-party flow; Claude registers a new client per connection, so remembered consent would never apply | Consent after GitHub (violates the MUST); remembered consent |

All existing politeness decisions stay: one request in flight, ≥ 2 s between request starts, honest
User-Agent, `ro_ui=v2` only, no challenge bypass, cached pages, no crawling.

## 3. Architecture

```
Claude (chat / Cowork / Claude Code)
        │  HTTPS, Authorization: Bearer <access token>
        ▼
https://<host>            (Fly.io, one machine, one Python process: uvicorn + the SDK's Starlette app)
  ├─ /mcp ..................... the 13 tools (MCP streamable HTTP, stateless, JSON responses)
  ├─ /.well-known/oauth-protected-resource/mcp, /.well-known/oauth-authorization-server
  ├─ /register /authorize /token /revoke ........ OAuth authorization server (SDK routes)
  ├─ /consent (GET, POST), /oauth/github/callback  consent page and GitHub hand-off (ours)
  └─ /healthz ................. liveness only (constant 200, no database access)
        │
        ├─ RealOemClient (unchanged rules, shared by every user) ──► realoem.com
        └─ Fly volume /data: cache/pages.v2.sqlite3 (page cache, size-capped),
                             data/vehicles.sqlite3 (vehicle index), data/auth.sqlite3 (auth store)
```

The plugin keeps its skills. `plugin.json` changes only `mcpServers`:

```json
"mcpServers": { "realoem": { "type": "http", "url": "https://<host>/mcp" } }
```

No `oauth` block: DCR works on every Claude surface, so the plugin ships no client id or secret.

## 4. Components

New code lives in `server/src/realoem_mcp/`. Existing modules change only where sections 4.7 and
4.8 say so. Every module has one job; HTTP handlers stay thin and all policy lives in testable
classes.

### 4.1 Mode and request context (`current_user.py`)

- `Settings.mode: Literal["stdio", "http"]`, default `"stdio"` (so tests and the maintainer scripts
  that construct `Settings(...)` directly keep working), set to `"http"` only by the
  `realoem-mcp-http` entry point, never inferred. HTTP-only validation (public URL, GitHub
  credentials, secret key) runs only in that entry point. Every behaviour that differs between modes
  checks this flag, so an HTTP code path without a token fails closed rather than falling back to
  stdio behaviour.
- `CurrentUser(subject: str, is_admin: bool)`; `current_user(settings) -> CurrentUser | None` reads
  the SDK's `get_access_token()` (set per request by the SDK's bearer middleware; in stateless mode
  each request runs in its own task with its own context) and checks `subject` against
  `settings.admins`. Returns `None` when no token is present.
- `require_user(settings) -> CurrentUser` raises `RealOemError("not signed in")` when `None`. In
  HTTP mode, tools and hooks call `require_user`; nothing imports `http_app`.
- `call_started_at: ContextVar[float]` is set by `CallClock`, a `ServerMiddleware`
  (`mcp.server.context`) passed as `MCPServer(middleware=[CallClock()])`, at every inbound message.
  The per-call deadline (4.7) reads it.

### 4.2 `http_app.py` and the `realoem-mcp-http` entry point

- `build_http_app(settings) -> Starlette` raises unless `settings.mode == "http"` and runs the
  HTTP-only validation itself (so a uvicorn app-factory launch or a test with default settings can
  never build an HTTP app in stdio mode); `main()` only sets the mode and calls it. It creates the
  `AuthStore`, `Quota`, `FetchGate`,
  `GitHubLogin` and `RealOemAuthProvider`; the client hooks are no-argument closures that resolve
  the caller: `admit = lambda: gate.admit(require_user(settings).subject)` and `charge = lambda:
  quota.charge(require_user(settings).subject)`; `services = create_services(settings, admit=admit,
  charge=charge)`; `server = build_server(services, auth_server_provider=provider,
  auth=auth_settings, middleware=[CallClock()])`; custom routes via `server.custom_route` **before**
  `app = server.streamable_http_app(stateless_http=True, json_response=True,
  transport_security=...)`, so the SDK's app stays the root and its lifespan (session manager)
  runs. Our lifespan wraps `app.router.lifespan_context`: on startup it starts the hourly purge
  task; on shutdown it cancels it and closes `Services` and the auth store.
- `build_server(services, *, auth_server_provider=None, auth=None, middleware=None)` is the existing
  function with three pass-through keyword arguments (stdio passes none).
- `AuthSettings`: `issuer_url = public URL`, `resource_server_url = <public URL>/mcp`,
  `validate_token_resource = True`, `required_scopes = ["realoem"]`,
  `client_registration_options = ClientRegistrationOptions(enabled=True, valid_scopes=["realoem"],
  default_scopes=["realoem"])`, `revocation_options = RevocationOptions(enabled=True)`.
- `TransportSecuritySettings`: in production `enable_dns_rebinding_protection=False` (bearer
  tokens make DNS rebinding useless, and the SDK would answer any request carrying an `Origin`
  header with a `403` that Claude treats as final); in development (`public_url` on loopback)
  `allowed_hosts=["localhost:*", "127.0.0.1:*"]` (a port is then required in the Host header, so
  in-memory tests use a base URL with a port; MCP Inspector is used in proxy mode).
- ASGI middleware (outermost first): security headers on every response (`Strict-Transport-Security`
  on all; the HTML headers of 4.6 on HTML); request log (method, path **without query string**,
  status, duration, `github:<id>` when known); rate limits and the pending-request cap of 4.9 on
  `/register` and `/authorize`.
- `main()`: validates settings (4.8), runs uvicorn on `0.0.0.0:8080` with `access_log=False`,
  logging to stderr as today. `[project.scripts]` gains `realoem-mcp-http =
  "realoem_mcp.http_app:main"`; `realoem-mcp` (stdio) stays. `uvicorn` and `starlette` become
  direct dependencies in `pyproject.toml`.

### 4.3 `auth/provider.py`

`RealOemAuthProvider(OAuthAuthorizationServerProvider)`: pure logic over `AuthStore`, `GitHubLogin`,
`Keys` (4.4) and a clock; no Starlette imports. **The redirect allow-list is a security invariant**:
the SDK redirects some `/authorize` errors to the registered URI before anyone signs in, which is
safe only because registration admits nothing but Claude's callbacks.

| Method | Behaviour |
|---|---|
| `register_client` | Parses every `redirect_uris` entry with `urllib.parse`. Accepts exactly the URLs in `settings.redirect_allowlist` (default `https://claude.ai/api/mcp/auth_callback`; string match) and loopback URIs: scheme `http`, host exactly `localhost` or `127.0.0.1`, no userinfo, no fragment, any port, at most 512 characters. Anything else, more than 5 redirect URIs, or `client_name` over 200 characters → `RegistrationError("invalid_redirect_uri" / "invalid_client_metadata")` (the SDK's four RFC 7591 codes are the only ones it can return, always as `400`). Persists only `client_id`, the secret, `client_name`, `redirect_uris`, `grant_types`, `response_types`, `token_endpoint_auth_method`, `scope` and `created_at`; every other metadata field (`jwks`, `jwks_uri`, `contacts`, …) is dropped. Body size and rate limits live in middleware (4.9). |
| `get_client` | Returns a `ClaudeClient(OAuthClientInformationFull)` whose `validate_redirect_uri` matches loopback URIs on scheme, host, path (an empty path counts as `/`) and query while ignoring the port, and returns the requested URI (with its port) so the SDK's `/token` equality check passes; everything else is an exact string match. Keeps only the redirect URIs today's allow-list admits (`None` when none is left), so narrowing the allow-list takes effect at once. |
| `authorize` | Rejects `state` over 512 characters, a `code_challenge` that is not 43 base64url characters, and `resource` or `scope` over 256 characters with `AuthorizeError("invalid_request")`. Validates `resource`: absent → `<public URL>/mcp`; present and not equal to it (URL comparison: scheme and host case-insensitive, trailing slash ignored) → `AuthorizeError("invalid_target")`. `scopes` `None` → `["realoem"]`. Stores a pending request `{id (256-bit random), client_id, redirect_uri, client_state, code_challenge, resource, scopes, status="awaiting_consent", expires_at=now+10 min}` and returns `https://<host>/consent?req=<id>`. **Never contacts GitHub.** |
| `consent(req_id, decision)` | `allow`: `UPDATE pending SET status='consented', gh_state_hash=? WHERE id=? AND status='awaiting_consent' AND expires_at > now` (0 rows → `ExpiredRequest`), where the GitHub `state` is 256-bit random and `gh_state_hash = H_github(state)`. The PKCE verifier is **never stored**: `verifier = base64url(HMAC-SHA256(k_github_pkce, req_id + "\|" + state))` (43 characters), recomputed at the callback. Returns `StartGitHub(authorization_url, state)`. `deny`: `UPDATE … SET status='denied' WHERE id=? AND status='awaiting_consent'` (0 rows → `ExpiredRequest`); returns `RedirectToClient(redirect_uri, error="access_denied", state=client_state)`. |
| `github_return(query, state_cookie)` | GitHub's callback carries only `code` and `state`. Requires `state_cookie == query.state` (constant-time); finds the row by `gh_state_hash = H_github(query.state)`; then `UPDATE pending SET status='github_returned', gh_state_hash=NULL WHERE id=? AND status='consented' AND gh_state_hash=? AND expires_at > now` — 0 rows → `ShowError("expired")`, **no redirect**. If the query carries `error=access_denied` (user cancelled at GitHub) → `RedirectToClient(error="access_denied")`. Exchanges the code with the recomputed verifier, reads `id`, `login`, `created_at`. Banned → `ShowError("banned")`. GitHub unreachable → `ShowError("github_unavailable")`. Otherwise upserts the user, writes the consent audit row, issues a one-time authorization code bound to the pending request (`client_id`, `redirect_uri`, `code_challenge`, `resource`, `scopes`, subject, 10-minute expiry) and returns `RedirectToClient(redirect_uri, code=…, state=client_state)`. |
| `load_authorization_code` | Lookup by `H_code`. A used or expired code returns `None` **and** revokes the token family issued from it (OAuth 2.1 §4.1.3). |
| `exchange_authorization_code` | In one transaction: `UPDATE authorization_codes SET used_at=? WHERE hash=? AND used_at IS NULL`; 0 rows → revoke the family and raise `TokenError("invalid_grant")`; else create a new family (at most 20 active families per subject; the oldest is revoked first) and insert the access token (`kind='access'`, 1 h) and refresh token (`kind='refresh'`, idle 30 days, family absolute expiry 90 days) with the code's `resource` and scopes. Used codes are kept until `expires_at`. |
| `load_access_token` | Lookup by `H_access`, restricted to `kind='access'`; returns `AccessToken(token, client_id, scopes, expires_at, resource, subject)` or `None` when unknown, expired, revoked, or the subject has `banned_at` set. No in-process caching of tokens or bans. |
| `load_refresh_token` | Lookup by `H_refresh`, restricted to `kind='refresh'`; any other kind or an unknown hash → `None`. A rotated refresh hash in a live family → revoke every token in the family, log `refresh_reuse github:<id>` (once per incident), return `None` (the SDK then answers `invalid_grant`). A token of a family already revoked (ban, `/revoke`, the 20-family cap) → `None` without a log line, so `refresh_reuse` stays a clean signal for section 10's question. |
| `exchange_refresh_token` | In one transaction: `UPDATE tokens SET rotated_at=? WHERE hash=? AND kind='refresh' AND rotated_at IS NULL AND revoked=0`; 0 rows → revoke the family and raise `TokenError("invalid_grant")`; else issue a new access and refresh token in the same family (scopes may only shrink; the SDK enforces this). Rotated rows are kept until the family's absolute expiry. |
| `revoke_token` | Revokes the token and its whole family. |

The SDK already enforces PKCE S256 on our `/token`, code binding to `client_id` and `redirect_uri`,
refresh-token binding to the client, scope narrowing, `401`/`403` semantics, and the resource check
on bearer tokens. The provider adds only what the table says.

### 4.4 `auth/store.py` and `auth/keys.py`

- `Keys`: `k_label = HMAC-SHA256(secret_key, "realoem/v1/" + label)` for the labels `access`,
  `refresh`, `code`, `github`, `github-pkce`, `consent`, `cache-owner`. `H_x(value) =
  HMAC-SHA256(k_x, value)`. Each token kind is hashed under its own key, so a value of one kind
  can never match a row of another.
- SQLite (`auth.sqlite3`, WAL, `PRAGMA journal_size_limit=67108864`), stdlib `sqlite3`,
  forward-only numbered migrations (never drop-and-recreate: bans, consents and usage survive
  upgrades). Tables: `clients` (id, secret in clear because the SDK compares it directly, metadata,
  created_at, last_issued_at), `pending` (the pending request of 4.3 plus `gh_state_hash` and
  `subject` once known; no verifier), `authorization_codes` (hash, family, pending fields, used_at,
  expires_at), `tokens` (hash, kind, family, subject, client_id, scopes, resource, expires_at,
  rotated_at, revoked), `users` (subject, github_login, github_created_at, first_seen, banned_at,
  banned_reason), `consents` (audit: subject, client_id, redirect_uri, granted_at), `usage`
  (subject, day, requests) plus one row per day for the global total.
- A copied database yields no usable credentials; it does yield GitHub ids, logins, usage and ban
  reasons, which are personal data (retention in 4.9).

### 4.5 `auth/github.py`

`GitHubLogin` (a protocol with a real and a fake implementation): builds the GitHub authorization
URL (client id, redirect `https://<host>/oauth/github/callback`, PKCE S256 challenge of the derived
verifier, `state`, no scopes: public profile only), exchanges the code at
`https://github.com/login/oauth/access_token`, and reads `id`, `login` and `created_at` from
`https://api.github.com/user`. The GitHub token is used for that one call and discarded: never
stored, logged or passed through.

### 4.6 `auth/pages.py` and the custom routes

`pages.py` owns cookies and the CSRF MAC; the provider never sees them.

- `GET /consent?req=<id>`: sets the cookie `__Host-ro_csrf` (256-bit random; `Secure; HttpOnly;
  SameSite=Strict; Path=/; Max-Age=600`) and renders the consent form with hidden fields `req`,
  `exp` and `csrf = HMAC-SHA256(k_consent, "consent|" + req + "|" + cookie + "|" + exp)`. Trusted
  data (client, redirect URI, scopes, resource, PKCE) stays on the server-side row only.
- `POST /consent`: reads at most 8 fields of at most 1 KB and no files (a bigger form is refused
  before it is buffered), requires the cookie, a valid MAC (`hmac.compare_digest`) and an
  unexpired `exp` of plain ASCII digits, then calls `provider.consent(req, decision)`. `StartGitHub` → set `__Host-ro_gh_state=<state>`
  (`Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600`; Lax because GitHub's return is a
  cross-site top-level GET) and `302` to GitHub. `RedirectToClient` → `302`. `ExpiredRequest` →
  error page.
- `GET /oauth/github/callback`: calls `provider.github_return(query, state_cookie)`; clears the
  cookie; `RedirectToClient` → `302`; `ShowError` → error page, **never a redirect**.
- **Consent page content:** heading by redirect target, never by the self-asserted name: Claude's
  callback → "Claude (claude.ai)"; a loopback redirect → "A program on this computer
  (`http://localhost:<port>/callback`) that calls itself '<name>'". Both get the line "Continue only
  if you just connected RealOEM Searcher in Claude." Always shown: the full redirect URI for this
  request, and what is granted ("RealOEM Searcher tools, counted against your daily quota; reads
  only the id, username and creation date of your public GitHub profile"). `client_name` is HTML-escaped, stripped of control and
  bidirectional-override characters, and truncated to 64 characters. Buttons: Allow, Deny.
- **Error pages:** banned ("access to RealOEM Searcher is suspended" + contact link), expired or
  invalid request, GitHub unavailable, busy (from the middleware of 4.9, `503` with `Retry-After`).
  No stack traces, no query echo.
- **Every HTML response** carries `Content-Security-Policy: default-src 'none'; style-src
  'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Plain HTML, no scripts.

### 4.7 `quota.py`, `gate.py`, and the client hooks

`RealOemClient` gains three optional hooks, all `None` in stdio mode (the third, `owner`, decides
which cache entry a page belongs to; see 4.8):

- `admit()`: an async context manager entered **before** waiting for the lock. It refuses
  immediately when the user is already at the day's limit, enforces at most 4 waiting-or-in-flight
  cache-miss fetches per subject and 20 overall, and computes the remaining wait as
  `min(60 s, deadline − now)`; its exit releases the counters. The lock is then acquired inside
  `async with asyncio.timeout(remaining): await self._lock.acquire()` with a `try/finally` release
  (not `asyncio.wait_for`, which can leak the lock on Python 3.11 when the task is cancelled as the
  acquire completes). A timeout raises `CallDeadline` when the deadline was the binding limit, else
  `Busy(RealOemError)` ("RealOEM Searcher is busy; try again in a minute"); either way nothing is
  charged. The deadline check applies to every wait, including the single-flight wait of
  `update_vehicle_index`.
- `charge()`: called **inside** the lock, after the second cache check misses and before the
  network request. `Quota.charge(subject)` runs one transaction: the user's row
  (`UPDATE usage SET requests = requests + 1 WHERE subject=? AND day=? AND requests < ?`, after
  inserting the day's row if missing) and the global row the same way (always counted, so the cap
  can be switched on mid-day; it refuses only when `global_daily_limit > 0`); if either updates 0
  rows the transaction rolls back and `QuotaExceeded(RealOemError)` is raised, so refused
  attempts are never counted. The limit is `new_user_daily_limit` when the user's
  `github_created_at` is younger than `min_account_age_days` or unknown (fail closed), else
  `user_daily_limit`; `0` means unlimited. Admins are not exempt. Charged once per `RealOemClient.fetch` that goes to
  the network; retries and redirect hops are free.
- `create_services(settings, *, admit=None, charge=None, owner=None, transport=None, clock=None,
  sleep=None)` passes the hooks to the client.
- Messages use the configured numbers: "You've used your {limit} RealOEM lookups for today; the
  limit resets at 00:00 UTC. Cached results remain available." / "RealOEM Searcher has reached its
  daily request limit; try again after 00:00 UTC."
- **Per-call deadline** (`REALOEM_CALL_DEADLINE_S`, 50, measured from `call_started_at`): once
  exceeded, `admit()` raises `CallDeadline(RealOemError)` instead of waiting, and the client starts
  no retry whose delay would reach it (`CallDeadline`; the failed attempt stays charged).
  `compare_vehicles` (`tools/fitment.py`) treats `CallDeadline`, `Busy` **and** `QuotaExceeded`
  (while reading diagrams; during the two diagram lists they are tool errors) like an exhausted
  request budget: it switches to cache-only reads, with the error's message in `stopped_reason`,
  and returns `complete=false` (resumable) when diagrams could not be read, never losing the pages
  it already compared or the ones already cached (with `refresh=true` a cached copy older than an
  hour may stand in, so `complete` can still be true). Every other tool reports them as tool
  errors: "This call took too long; call again to continue (pages already fetched are cached)." /
  the busy message. PRD NFR5 (< 5 s
  uncached) holds per request when the queue is empty.
- `server_status` reports the caller's `quota: {used_today, limit, resets_at}` and `global_limit`
  when on.

### 4.8 Settings, changed tools, shared-mode rules

New `Settings` fields (env; defaults): `mode` (set by the entry point, not by env), `public_url`
(`REALOEM_PUBLIC_URL`; required in HTTP mode), `github_client_id` / `github_client_secret`
(`REALOEM_GITHUB_CLIENT_ID` / `REALOEM_GITHUB_CLIENT_SECRET`; required; `repr=False`), `secret_key`
(`REALOEM_SECRET_KEY`; base64 of ≥ 32 random bytes; required; `repr=False`), `admins`
(`REALOEM_ADMINS`, comma-separated GitHub numeric ids), `user_daily_limit`
(`REALOEM_USER_DAILY_LIMIT`, 300), `new_user_daily_limit` (`REALOEM_NEW_USER_DAILY_LIMIT`, 30),
`min_account_age_days` (`REALOEM_MIN_ACCOUNT_AGE_DAYS`, 30), `global_daily_limit`
(`REALOEM_GLOBAL_DAILY_LIMIT`, 0 = off), `call_deadline_s` (`REALOEM_CALL_DEADLINE_S`, 50),
`cache_max_mb` (`REALOEM_CACHE_MAX_MB`, 400 in HTTP mode, 0 = off in stdio), `redirect_allowlist`
(`REALOEM_REDIRECT_ALLOWLIST`, default `https://claude.ai/api/mcp/auth_callback`),
`hosted_client_range` (`REALOEM_HOSTED_CLIENT_RANGE`, `160.79.104.0/21`), `auth_dir`
(`REALOEM_AUTH_DIR`, default `data_dir`). The HTTP entry point refuses to start when a required
value is missing or malformed: the public URL must be a bare origin (stored in canonical,
lower-case form), and every allow-list entry an `https://` URL with a host, no userinfo or
fragment, at most 512 characters. Rotating `secret_key` restarts the server and voids every token and
in-flight sign-in; users reconnect.

- `cache_clear`: in HTTP mode admins only (`require_user`; tool error otherwise); in stdio mode
  unchanged.
- `server_status`: in HTTP mode returns `cache_path` as `null` (a tool's output schema is fixed) and
  adds `quota`; in stdio mode unchanged (PRD F0.6 and the existing tests keep applying to the
  local server).
- `refresh=true` in HTTP mode is honoured only when the cached copy is older than 1 hour;
  otherwise the cached page is returned (`from_cache=true` tells the truth).
- `update_vehicle_index` in HTTP mode is single-flight: an update in progress makes concurrent
  callers wait for its result (within the deadline). A 1-hour server-wide cooldown starts only
  after an `up_to_date` or `updated` result; `partial` and `drift` results, and deadline errors,
  start no cooldown so the documented "call again to continue" still works. A call inside the
  cooldown makes no request and returns the new status `cooldown` with `message` "The index was
  checked at <time>; it is refreshed at most once an hour." (`models/vehicles.py` and the
  `vehicle-index` skill gain the status). Its requests count against the caller who triggered it.
- **VIN pages are not shared:** `PageCache` gains an `owner` column with primary key
  `(owner, url)`: `''` for shared pages, `H_cache_owner(subject)` for `select?vin=` and
  `production?vin=` in HTTP mode. `get`, `put`, `cached` and `shorten` take the owner. `Page` gains
  `owner`, set by the client, and every `shorten` call passes it:
  `services.cache.shorten(page.url, ttl, owner=page.owner)`. `Page.url` stays the RealOEM URL, so
  `source_urls` and `redirected_away` are unaffected. Owner-scoped entries expire after 30 days (the
  shared VIN TTL of 180 days does not apply in HTTP mode; ARD §5.4 and PRD NFR2 record this).
  Reason: a shared entry's `from_cache`/`fetched_at` would reveal whether and when someone else
  decoded a VIN.
- **Cache size accounting:** each row stores `size_bytes INTEGER NOT NULL` (UTF-8 length, set in
  `put`), and a running total in `meta` is updated in the same transaction as `put`, eviction,
  `clear` and the expired-row purge. The cap check and `stats()` read that total, so both are
  constant-time and never read `html` (today's `stats()` sums `LENGTH(CAST(html AS BLOB))`, a full
  scan). **`html` is the last column**: `owner`, `url`, `page_type`, `final_url`, `status`,
  `fetched_at`, `expires_at`, `last_used` (INTEGER epoch seconds, so the per-hit update overwrites
  in place) and `size_bytes` precede it, with indexes on `(last_used)` and `(expires_at)`, so
  eviction and the purge never walk a page's overflow chain either.
- **Cache size cap** (`cache_max_mb`): checked after each `put` against the running total; when
  over, least-recently-used rows (a `last_used` column, updated on hit) are evicted until 10 %
  under the cap. The cache database is created with `PRAGMA auto_vacuum=INCREMENTAL`, which can
  only be set before the first table exists, so the version 2 schema lives in a new file,
  `pages.v2.sqlite3` (the version 1 file `pages.sqlite3` is deleted when possible; the cache is
  disposable). `PRAGMA incremental_vacuum` runs after every eviction, in chunks each followed by a
  `TRUNCATE` checkpoint (in WAL mode the moved pages are first written to the `-wal` file),
  returning freed pages to the filesystem with at most one chunk of extra space, far less than a
  full `VACUUM` needs. No
  scheduled `VACUUM`. `PRAGMA journal_size_limit=67108864` on all three databases. 400 MB is at
  most 40 % of the volume.
- **Free-space floor:** before each `put`, `shutil.disk_usage(cache_dir)` is checked; below 100 MB
  free the cache evicts to half the cap first, and if still below the floor the page is served
  without being cached. A `SQLITE_FULL` raised by the cache's own `put` or `shorten` (for example
  WAL growth despite the floor) is treated the same way: logged, and the page served uncached,
  never a failed tool call.
- `scripts/admin.py` (run via `fly ssh console` as the app user, not root, so SQLite's WAL files
  never become root-owned; it refuses to run as root, and refuses an auth database path that does
  not exist rather than create an empty one): `usage [--day]`, `ban <id> --reason`, `unban <id>`,
  `revoke <id>`, `prune`.

### 4.9 Rate limits, purging, retention

- ASGI middleware rejects `/register` bodies over 8 KB with `413` (the SDK alone accepts 4 MiB).
- ASGI middleware keyed on `Fly-Client-IP` (set by Fly's proxy; the socket peer is the proxy; an
  IPv6 client counts by its /64, since one host controls a whole /64, and an IPv4-mapped address
  as IPv4):
  `/register` 30 per hour per address outside `hosted_client_range` and 600 per hour across that
  range (hosted Claude registers a new client per connection), with a global ceiling of 2,000 a
  day that applies only to addresses **outside** the range; `/authorize` 60 per 10 minutes per
  address. Over a limit → `429` with `Retry-After`.
- `/authorize` middleware refuses new pending requests above 100,000 live rows (about 50 MB) with
  the busy page (`503`, `Retry-After`); the provider does not check this.
- Purge task, at startup and then hourly: expired pending rows, codes and tokens; clients that never completed an
  authorization after 24 hours, other clients 90 days after `last_issued_at`; `usage` rows older
  than 90 days; the consent audit after 90 days.
- Retention and privacy: the server keeps GitHub id and login, daily usage counts and ban records;
  no query content is stored outside the page cache (VIN pages per user for 30 days); logs never
  carry query strings of OAuth routes, `Authorization` headers, form bodies, tokens, codes, GitHub
  tokens or VINs (in HTTP mode RealOEM URLs of page types `select` and `production` are logged with
  query values masked, and a log filter masks `vin=` values and the SDK's error text of a failed
  `decode_vin` in every log line); request paths are logged escaped, so a path cannot forge a log
  line. The README gets a short privacy note.

### 4.10 Deployment

- Build context is the **repository root**. `server/Dockerfile`: `python:3.13-slim`, copies
  `server/` and `brands/`, `uv sync --frozen --no-dev`, non-root user, `CMD realoem-mcp-http`. A
  repo-root `.dockerignore` excludes `.research-raw/`, `.worktrees/`, `.venv/`, `.git/`, caches and
  tests, so a maintainer's local `flyctl deploy` never uploads raw captures.
- `fly.toml` at the repository root: one process, internal port 8080, `force_https = true`,
  `auto_stop_machines = "off"`, `[http_service.concurrency] type = "requests", soft_limit = 100,
  hard_limit = 200`, HTTP check on `/healthz` (routing only), `[[restart]] policy = "on-failure",
  retries = 10`, volume `realoem_data` at `/data`, env `REALOEM_PUBLIC_URL` (not a secret, and
  reviewed with the rest of `fly.toml`), `REALOEM_CACHE_DIR=/data/cache`,
  `REALOEM_DATA_DIR=/data/data`, `REALOEM_BRANDS_DIR=/app/brands`. `flyctl deploy --ha=false` runs
  from the repository root.
- Secrets via `fly secrets set`: `REALOEM_GITHUB_CLIENT_ID`, `REALOEM_GITHUB_CLIENT_SECRET`,
  `REALOEM_SECRET_KEY`, `REALOEM_ADMINS`. Setting a secret restarts the machine (a few seconds of
  downtime).
- GitHub Actions `deploy.yml`: on a `v*` tag it runs lint and the offline tests itself (CI does not
  run on tags), then `flyctl deploy --remote-only --ha=false` with an app-scoped deploy token
  (`fly tokens create deploy`) from a GitHub Environment with a required reviewer; a repository
  ruleset protects `v*` tags.
- A second GitHub OAuth App ("RealOEM Searcher (dev)", callback on `http://localhost:8080`) is used
  for local container runs, since a GitHub OAuth App takes one callback URL.
- Fatal errors: `SQLITE_FULL` from the auth or vehicle store closes the cache connection, deletes
  the three cache files (`pages.v2.sqlite3`, `-wal`, `-shm`; they are disposable, and deleting them is
  the one action that frees filesystem space without needing any; on Linux a deleted file frees
  nothing while it is still open, hence the close first), reopens the cache and retries once;
  `CORRUPT`, `IOERR` or `NOTADB` from the auth store, or a second `FULL`, are logged and the
  process ends with `os._exit(1)` after flushing logs (a `SystemExit` raised inside a
  request handler may be swallowed), so Fly's `on-failure` policy restarts it; `/healthz` never
  heals anything by itself. After `retries = 10` a crash loop leaves the machine stopped, so plan
  2 adds an external uptime check on `/healthz` that alerts the owner.
- Backups: Fly's daily volume snapshots (5-day retention) are relied on; an off-platform backup job
  is out of scope for 0.2.0 (the vehicle index rebuilds from the committed baseline, the cache is
  disposable, and losing `auth.sqlite3` means users reconnect, bans are lost and the day's quotas
  reset).

## 5. Data flow

**Sign-in (chat and Cowork share one; Claude Code has its own):**

1. The user installs the plugin and clicks **Connect** (chat, Cowork) or runs `/mcp` (Claude Code).
2. Claude calls `/mcp` without a token → `401` with `WWW-Authenticate: Bearer
   resource_metadata="https://<host>/.well-known/oauth-protected-resource/mcp"`.
3. Claude reads the metadata, registers at `/register` (redirect URIs checked, middleware rate
   limit), gets a client id.
4. Claude opens `/authorize` (PKCE S256, `resource`, `scope=realoem`, `state`) in the user's
   browser; the server validates the request, stores it pending and redirects to `/consent`.
5. The consent page names the redirect target and what is granted. **Deny** → back to Claude with
   `access_denied`. **Allow** → the server generates the GitHub `state`, derives the PKCE verifier,
   sets the state cookie and redirects to GitHub ("Sign in with GitHub", public profile only).
6. GitHub returns to `/oauth/github/callback`; the server checks the state cookie against the query,
   finds and atomically advances the pending row, exchanges the code with the recomputed verifier,
   reads the numeric id; banned → error page.
7. The server redirects to Claude's redirect URI with a one-time code and the original `state`;
   Claude exchanges it at `/token` for a 1-hour access token and a refresh token.

**Tool call:**

1. `Authorization: Bearer <token>` → the SDK validates (exists, `kind='access'`, unexpired, resource
   is `/mcp`, scope `realoem`, subject not banned) and exposes the token to `current_user()`;
   `CallClock` records the start time.
2. The tool runs as today. On a cache miss, `admit()` applies the quota pre-check, the waiter
   limits and the deadline before waiting; inside the lock, after the second cache check misses,
   `charge()` counts the fetch; then the fetch waits its turn (one in flight, ≥ 2 s).
3. The result returns with `source_urls`. Claude refreshes tokens proactively; each refresh rotates
   the refresh token.

**Shared state:** one page cache (except VIN pages) and one vehicle index for everyone.

## 6. Error handling

| Situation | Behaviour | User-facing text |
|---|---|---|
| No or expired token, or a token of another kind | `401` + resource metadata pointer (SDK); Claude refreshes or signs in | Claude prompts to (re)connect |
| Wrong scope or resource | `403 insufficient_scope` / `401` (SDK) | Claude re-authorizes |
| Oversized or foreign `/authorize` parameters | `invalid_request` / `invalid_target` error redirect (SDK, allow-listed client) | Connection fails with a clear error |
| Daily user limit reached | Refused before waiting; cache hits still answered | Quota message (4.7) |
| Server-wide cap on and reached | Same | Server-wide message (4.7) |
| Queue full, waiter limit, or wait too long | `Busy` tool error, nothing charged | "RealOEM Searcher is busy; try again in a minute." |
| Call deadline reached | `compare_vehicles`: partial, resumable; others: tool error | "This call took too long; call again to continue (pages already fetched are cached)." |
| Too many pending sign-ins | `503` busy page from middleware, `Retry-After` | "RealOEM Searcher is busy; try again in a minute." |
| Banned user | Tokens refused at `load_access_token`; sign-in refused after GitHub | Error page: access suspended, contact link |
| Bot challenge / layout change / upstream error | Unchanged; not cached; counts against quota | Today's messages (ARD §5.3) |
| GitHub unavailable or user cancelled at GitHub | Clean failure, nothing stored (cancel → `access_denied` to Claude only after the state checks pass) | "GitHub sign-in is unavailable right now; try again shortly." |
| Bad registration | `400 invalid_redirect_uri` / `invalid_client_metadata` (provider); `429` (middleware) | Client-only |
| Consent form without its cookie, stale, or replayed; callback with missing or mismatched state | Error page, never a redirect | "This sign-in request has expired. Start again from Claude." |
| Restart (deploy, migration, secret change) | Seconds of failed connections; nothing lost (no sessions; tokens and cache on disk) | Claude retries |
| Disk nearly full | Free-space floor: evict, then serve pages uncached | None (slower repeat questions) |
| Disk full | Page-cache files deleted and one retry; a second full disk exits 1 | Brief outage; a persistent crash loop stops the machine and triggers the uptime alert |
| Fatal auth-store error | Process exits 1 → Fly restarts it | Brief outage |

Logs carry `github:<id>`, tool name, page type and outcome; see 4.9 for what they never carry.

## 7. Testing

Offline, in CI, no network (extends the existing 942 tests; `httpx.MockTransport` per AD4, no new
test dependency):

- **Provider:** redirect allow-list (Claude callback exact; loopback any port; `localhost.evil.com`,
  `localhost@evil.com`, `127.0.0.1.nip.io`, fragments and userinfo rejected); `client_name` and
  redirect-count limits; oversized `state`/`code_challenge`/`resource`/`scope` → `invalid_request`;
  `resource` missing → defaulted, foreign → `invalid_target`; consent state machine (`allow`,
  `deny`, double POST → expired, callback before consent → expired); callback lookup by state hash,
  missing cookie, mismatched cookie, replayed state; the verifier recomputes identically; PKCE
  failure (SDK); code single-use incl. **two concurrent exchanges of one code**; refresh rotation
  incl. **two concurrent refreshes** and reuse-revokes-family; **kind confusion: a refresh token or
  a code presented as a bearer token → `401`, an access token at the refresh grant →
  `invalid_grant`**; revocation; hashes only in the store; banned user refused at callback and at
  token load; 20-family cap at code exchange.
- **Pages and headers:** consent page shows the redirect URI and escapes `client_name`; CSP,
  `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`, HSTS present; both cookies carry `Path=/`;
  error pages never redirect.
- **End-to-end over HTTP** (`httpx.AsyncClient` against the app, in-memory with a port in the base
  URL, fake GitHub): discovery → register → authorize → consent → fake GitHub → token →
  `tools/list` → `lookup_part` against the existing fixture routes; `401` without a token; `403`
  for a missing scope; two users share a `partxref` page (second identical call costs no quota)
  but **not** a VIN page; interleaved calls from two users are charged to the right subject;
  `cache_clear` refused for a non-admin, allowed for an admin; request log lines contain no query
  strings; `select`/`production` URLs are masked in logs.
- **Middleware:** `/register` and `/authorize` return `429` keyed per `Fly-Client-IP`, with the
  hosted-range bucket and the outside-only global ceiling; the pending cap returns the `503` busy
  page.
- **Quota, gate and deadline:** cache hits free; retries and redirect hops free; UTC rollover;
  refusal makes no request and is not counted; a global refusal rolls back the user's increment;
  new-account limit; global cap on/off; per-subject and overall waiter limits; lock wait timeout →
  `Busy`, nothing charged; `CallDeadline` makes `compare_vehicles` partial and resumable and is a
  tool error for `trace_supersession`; `update_vehicle_index` single-flight, cooldown only after
  `up_to_date`/`updated`, `partial` resumes; the `refresh=true` 1-hour throttle.
- **Cache:** owner column (`get`/`put`/`cached`/`shorten` with owner; `Page.owner` round-trips),
  owner-scoped 30-day expiry, LRU eviction under the cap, `last_used` updated on hit, the running
  size total stays equal to `SUM(size_bytes)` after put/evict/clear/purge; `stats()`, the cap
  check, eviction and the purge never read `html` (asserted with a trace callback);
  `incremental_vacuum` after eviction; the free-space floor (injected `disk_usage`); on `FULL`
  from another store the cache connection is closed before the files are unlinked, then reopened
  empty.
- **Mode guard:** `build_http_app(Settings())` raises; it also rejects missing HTTP-only settings.
- **Registration limits:** a 9 KB `/register` body → `413`; a 513-character loopback redirect URI
  and a `jwks` field are rejected or dropped.
- **Mode and settings:** HTTP mode with no token fails closed (`cache_clear`, VIN keying, refresh
  throttle); stdio mode keeps `cache_path` and open `cache_clear`; the HTTP entry point refuses to
  start without each required value; the fatal-error handler calls an injected exit function.
- **Purge:** the hourly purge removes expired rows and stale clients.
- **Unchanged:** all stdio, parser and tool tests.

Before release: Opus security review of `auth/`, `quota.py`, `gate.py` and the middleware against
this spec and the MCP security best practices; local container run checked with `curl` discovery,
MCP Inspector (proxy mode) and `claude mcp add`; after deploy, sign in and run the PRD §7 smoke
session from Claude Code, a Cowork cloud session and chat, with the replay check (zero repeat
RealOEM requests).

## 8. Rollout

Two implementation plans: **(1)** auth, quota, gate, cache changes and the HTTP app, all testable
offline; **(2)** Dockerfile, Fly, the deploy workflow, the GitHub OAuth Apps, the hostname, and the
0.2.0 release.

1. Send the RealOEM owner message (drafted 2026-10-01: per-user daily limits, shared cache, honest
   UA, offer to adjust or stop). Hold the public switch until a reply or a reasonable wait.
2. Release **0.2.0**: `plugin.json` → hosted URL; Claude-Plugin-Collection entry → `v0.2.0`;
   README (install = "Install, then Connect / `/mcp`", tools table and troubleshooting without the
   cache path, privacy note); CHANGELOG. Documents to update: ARD §2 diagram, §3 (new AD17 "hosted
   server", AD1/AD2 marked development-only), §4 layout, §5.1 manifest, §5.2 settings (incl.
   `mode`), §5.2a `create_services(admit=…, charge=…)`, §5.3 (`QuotaExceeded`, `Busy`,
   `CallDeadline`), §5.4 (VIN pages 30 days per user in HTTP mode), §5.5 (the hooks, timed lock,
  `Page.owner`), §5.6 (owner column, size accounting, cap, incremental vacuum), §5.11
   admin-tool contracts and the `cooldown` status, §5.12 vehicle-index skill, §7 security, §8
   CI/deploy; PRD F0.1, F0.2, F0.4, F0.6, F6.2, NFR2, NFR5, NFR7, and a new risk "all users share one
   egress IP: one Cloudflare challenge stops everyone; a static egress IP would help RealOEM
   identify the traffic".
3. Marketplace installs of 0.1.0 see the new version on their next marketplace refresh (Claude Code
   does not auto-update third-party marketplaces by default); the release notes say so.

## 9. Out of scope

Google sign-in; an admin web UI; CIMD (DCR works on every surface today; the 2026-07-28 spec
deprecates it, so CIMD is a later change); multi-region or replicas; an off-platform backup job;
RFC 9207 `iss`; a `scope` hint on the `401` (the SDK omits it and Claude falls back to
`scopes_supported`).

## 10. Open questions

- **Hostname** (must be settled before plan 2; it is the OAuth issuer and the GitHub callback, so
  changing it later makes every user reconnect): `realoem-searcher.fly.dev`, or a custom domain
  with an A record.
- Whether hosted Claude ever refreshes a token in parallel (which rotation-with-replay-detection
  would revoke); if `refresh_reuse` log lines appear for real Claude clients, add a ≤ 30 s grace.
- Fly Proxy's idle timeout for long responses is unverified; plan 2 measures a 50 s `compare_vehicles`
  call end to end before the deadline value is final.
- Whether Fly overwrites a client-supplied `Fly-Client-IP` header is unverified; plan 2 sends a
  forged header and confirms the app sees the real address before the hosted-range bucket is relied
  on.
