# Hosted Server Design

**Status:** approved design, 2026-10-01, revised after spec and security review. Supersedes the
"local stdio server" distribution of ARD AD1/AD2 for the plugin; the stdio entry point stays for
development and tests.

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
| H4 | **Per-user quota of cache-miss page fetches per UTC day** (default 300; 30 for GitHub accounts younger than 30 days); a **server-wide daily cap exists but is off by default** | Owner's choice; the server-wide cap is a backstop if RealOEM asks (`fly secrets set`, which restarts the server once) | Server-wide cap on by default (security review recommends it at launch; owner's call) |
| H5 | **Stateless streamable HTTP with JSON responses**, a per-call deadline, and queue admission limits | Restarts and deploys break nothing; one instance anyway; Claude needs no server push; multi-request tools already support partial, resumable results | Sessions (lost on restart) |
| H6 | **Tokens and codes are 256-bit random values stored as keyed hashes** (HMAC-SHA256 with a server secret); access tokens live 1 hour; refresh tokens rotate on every use with replay detection | OAuth 2.1 and Claude requirements; a copied database (or Fly snapshot) yields no usable credentials | JWTs (a signing key to protect; no revocation without a list) |
| H7 | The **stdio entry point and the offline test suite stay**; the HTTP app wraps the same `build_server()` | Every parser and tool test still runs offline; stdio is the development and test harness | Separate server code for HTTP |
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
        └─ Fly volume /data: cache/pages.sqlite3 (page cache, size-capped),
                             data/vehicles.sqlite3 (vehicle index), data/auth.sqlite3 (auth store)
```

The plugin keeps its skills. `plugin.json` changes only `mcpServers`:

```json
"mcpServers": { "realoem": { "type": "http", "url": "https://<host>/mcp" } }
```

No `oauth` block: DCR works on every Claude surface, so the plugin ships no client id or secret.

## 4. Components

New code lives in `server/src/realoem_mcp/`. Existing tool modules change only where section 4.8
says so. Every module has one job; HTTP handlers stay thin and all policy lives in testable classes.

### 4.1 Request context (`current_user.py`)

- `CurrentUser(subject: str, is_admin: bool)` and `current_user() -> CurrentUser | None`, which
  reads the SDK's `get_access_token()` (set per request by the SDK's bearer middleware; in stateless
  mode each request runs in its own task with its own context) and checks `subject` against the
  admin list. Returns `None` when no token is present (stdio).
- `require_user() -> CurrentUser` raises `RealOemError("not signed in")` when `None`.
- Tools and the quota hook import only this module; nothing imports `http_app`.

### 4.2 `http_app.py` and the `realoem-mcp-http` entry point

- `build_http_app(settings) -> Starlette`: creates `Services` (`create_services(settings,
  before_request=hook)`), the `AuthStore`, `Quota`, `GitHubLogin` and `RealOemAuthProvider`, then
  `build_server(services, auth_server_provider=provider, auth=auth_settings)` and
  `app = server.streamable_http_app(stateless_http=True, json_response=True,
  transport_security=...)`. Custom routes are added with `MCPServer.custom_route` **before** the app
  is built, so the SDK's app stays the root and its lifespan (session manager) runs; our lifespan
  wrapper closes `Services` and the auth store on shutdown and runs the hourly purge task.
- `build_server(services, *, auth_server_provider=None, auth=None)` is the existing function with
  two pass-through keyword arguments (stdio passes neither).
- `AuthSettings`: `issuer_url = public URL`, `resource_server_url = <public URL>/mcp`,
  `validate_token_resource = True`, `required_scopes = ["realoem"]`,
  `client_registration_options = ClientRegistrationOptions(enabled=True, valid_scopes=["realoem"],
  default_scopes=["realoem"])`, `revocation_options = RevocationOptions(enabled=True)`.
- `TransportSecuritySettings`: in production `enable_dns_rebinding_protection=False` (bearer
  tokens make DNS rebinding useless, and the SDK would answer any request carrying an `Origin`
  header with a `403` that Claude treats as final); in development (`public_url` on loopback)
  `allowed_hosts=["localhost:*", "127.0.0.1:*"]`.
- ASGI middleware (outermost first): security headers on every response (`Strict-Transport-Security`
  on all; the HTML headers of 4.6 on HTML); request log (method, path **without query string**,
  status, duration, `github:<id>` when known); rate limits of 4.9 on `/register` and `/authorize`.
- `main()`: validates settings (4.8), runs uvicorn on `0.0.0.0:8080` with `access_log=False`,
  logging to stderr as today. `[project.scripts]` gains `realoem-mcp-http =
  "realoem_mcp.http_app:main"`; `realoem-mcp` (stdio) stays. `uvicorn` and `starlette` become
  direct dependencies in `pyproject.toml`.
- The quota hook: `async def hook(): quota.charge(require_user().subject)`. In HTTP mode a fetch
  with no user is refused, never charged to nobody. In stdio mode there is no hook.

### 4.3 `auth/provider.py`

`RealOemAuthProvider(OAuthAuthorizationServerProvider)`: pure logic over `AuthStore`, `GitHubLogin`
and a clock; no Starlette imports. **The redirect allow-list is a security invariant**: the SDK
redirects some `/authorize` errors to the registered URI before anyone signs in, which is safe only
because registration admits nothing but Claude's callbacks.

| Method | Behaviour |
|---|---|
| `register_client` | Parses every `redirect_uris` entry with `urllib.parse`. Accepts exactly `https://claude.ai/api/mcp/auth_callback` (string match; the list is the `REALOEM_REDIRECT_ALLOWLIST` setting, default that one URL) and loopback URIs: scheme `http`, host exactly `localhost` or `127.0.0.1`, no userinfo, no fragment, any port. Anything else, more than 5 redirect URIs, or `client_name` over 200 characters → `RegistrationError("invalid_redirect_uri" / "invalid_client_metadata")` (the SDK's four RFC 7591 codes are the only ones it can return, always as `400`). Persists the client with `created_at`; rate limits live in middleware (4.9). |
| `get_client` | Returns a `ClaudeClient(OAuthClientInformationFull)` whose `validate_redirect_uri` matches loopback URIs on scheme, host, path and query while ignoring the port, and returns the requested URI (with its port) so the SDK's `/token` equality check passes; everything else is an exact string match. |
| `authorize` | Validates `resource`: absent → `<public URL>/mcp`; present and not equal to it (URL comparison: scheme and host case-insensitive, trailing slash ignored) → `AuthorizeError("invalid_target")`. `scopes` `None` → `["realoem"]`. Refuses when live pending rows exceed 10,000 (4.9). Stores a pending request `{id (256-bit random), client_id, redirect_uri, client_state, code_challenge, resource, scopes, status="awaiting_consent", expires_at=now+10 min}` and returns `https://<host>/consent?req=<id>`. **Never contacts GitHub.** |
| `consent(req_id, decision, csrf_cookie, csrf_field)` | Checks the CSRF MAC (4.6) and expiry. `allow`: moves the row `awaiting_consent → consented` with `UPDATE … WHERE status='awaiting_consent'` (0 rows → `ExpiredRequest`), generates the GitHub `state` (256-bit) and PKCE verifier, stores their hashes on the row, and returns `StartGitHub(authorization_url, state_cookie_value)`. `deny`: marks the row `denied` and returns `RedirectToClient(redirect_uri, error="access_denied", state=client_state)`. |
| `github_return(req_id, query, state_cookie)` | Finds a `consented`, unexpired row whose stored state hash matches both the query `state` and the cookie (constant-time compares); otherwise `ShowError("expired")` and **no redirect**. Clears the state hash. If the query carries `error=access_denied` (user cancelled at GitHub) → `RedirectToClient(error="access_denied")`. Exchanges the code with the stored verifier, reads `id`, `login`, `created_at`. Banned → `ShowError("banned")`. GitHub unreachable → `ShowError("github_unavailable")`. Otherwise upserts the user, writes the consent audit row, issues a one-time authorization code bound to the pending request (`client_id`, `redirect_uri`, `code_challenge`, `resource`, `scopes`, subject, 10-minute expiry) and returns `RedirectToClient(redirect_uri, code=…, state=client_state)`. |
| `load_authorization_code` | Hash lookup. A used or expired code returns `None` **and** revokes the token family issued from it (OAuth 2.1 §4.1.3). |
| `exchange_authorization_code` | In one transaction: `UPDATE authorization_codes SET used_at=? WHERE hash=? AND used_at IS NULL`; 0 rows → revoke the family and raise `TokenError("invalid_grant")`; else insert the access token (1 h) and refresh token (idle 30 days, family absolute expiry 90 days) with the code's `resource` and scopes, and a new family id. Used codes are kept until `expires_at`. |
| `load_access_token` | Hash lookup; returns `AccessToken(token, client_id, scopes, expires_at, resource, subject)` or `None` when unknown, expired, revoked, or the subject has `banned_at` set. No in-process caching of tokens or bans. |
| `load_refresh_token` | Unknown hash → `None`. A rotated or revoked hash → revoke every token in the family, log `refresh_reuse github:<id>`, return `None` (the SDK then answers `invalid_grant`). |
| `exchange_refresh_token` | In one transaction: `UPDATE tokens SET rotated_at=? WHERE hash=? AND rotated_at IS NULL AND revoked=0`; 0 rows → revoke the family and raise `TokenError("invalid_grant")`; else issue a new access and refresh token in the same family (scopes may only shrink; the SDK enforces this). Rotated rows are kept until the family's absolute expiry. At most 20 active families per subject; issuing a 21st revokes the oldest. |
| `revoke_token` | Revokes the token and its whole family. |

The SDK already enforces PKCE S256, code binding to `client_id` and `redirect_uri`, refresh-token
binding to the client, scope narrowing, `401`/`403` semantics, and the resource check on bearer
tokens. The provider adds only what the table says.

### 4.4 `auth/store.py`

SQLite (`auth.sqlite3`, WAL), stdlib `sqlite3`, forward-only numbered migrations (never
drop-and-recreate: bans, consents and usage survive upgrades). Tables: `clients` (id, secret in
clear because the SDK compares it directly, metadata, created_at, last_issued_at), `pending`
(the pending request of 4.3 plus `gh_state_hash`, `gh_verifier` (encrypted with the server
secret), `subject` once known), `authorization_codes` (hash, family, pending fields, used_at,
expires_at), `tokens` (hash, kind, family, subject, client_id, scopes, resource, expires_at,
rotated_at, revoked), `users` (subject, github_login, github_created_at, first_seen, banned_at,
banned_reason), `consents` (audit: subject, client_id, redirect_uri, granted_at), `usage` (subject,
day, requests). Tokens and codes are stored as `HMAC-SHA256(token_key, value)`; the keys are
derived from `REALOEM_SECRET_KEY` with domain separation (`"tokens"`, `"consent"`). A copied
database yields no usable credentials; it does yield GitHub ids, logins, usage and ban reasons,
which are personal data (retention in 4.9).

### 4.5 `auth/github.py`

`GitHubLogin` (a protocol with a real and a fake implementation): builds the GitHub authorization
URL (client id, redirect `https://<host>/oauth/github/callback`, PKCE S256, `state`, no scopes:
public profile only), exchanges the code at `https://github.com/login/oauth/access_token`, and reads
`id`, `login` and `created_at` from `https://api.github.com/user`. The GitHub token is used for that
one call and discarded: never stored, logged or passed through.

### 4.6 `auth/pages.py` and the custom routes

- `GET /consent?req=<id>`: sets the cookie `__Host-ro_csrf` (256-bit random; `Secure; HttpOnly;
  SameSite=Strict; Path=/; Max-Age=600`) and renders the consent form with hidden fields `req`,
  `exp` and `csrf = HMAC-SHA256(consent_key, "consent|" + req + "|" + cookie + "|" + exp)`.
  Trusted data (client, redirect URI, scopes, resource, PKCE) stays on the server-side row only.
- `POST /consent`: requires the cookie, a valid MAC (`hmac.compare_digest`) and unexpired `exp`,
  then calls `provider.consent`. `StartGitHub` → set `__Host-ro_gh_state=<state>` (`Secure;
  HttpOnly; SameSite=Lax; Max-Age=600`; Lax because GitHub's return is a cross-site top-level GET)
  and `302` to GitHub. `RedirectToClient` → `302`. `ExpiredRequest` → error page.
- `GET /oauth/github/callback`: calls `provider.github_return` with the query and the state cookie;
  clears the cookie; `RedirectToClient` → `302`; `ShowError` → error page, **never a redirect**.
- **Consent page content:** heading by redirect target, never by the self-asserted name: Claude's
  callback → "Claude (claude.ai)"; a loopback redirect → "A program on this computer
  (`http://localhost:<port>/callback`) that calls itself '<name>'" plus "Continue only if you just
  connected RealOEM Searcher in Claude Code." Always shown: the full redirect URI for this request,
  and what is granted ("RealOEM Searcher tools, counted against your daily quota; reads your public
  GitHub id and username only"). `client_name` is HTML-escaped, stripped of control and
  bidirectional-override characters, and truncated to 64 characters. Buttons: Allow, Deny.
- **Error pages:** banned ("access to RealOEM Searcher is suspended" + contact link), expired or
  invalid request, GitHub unavailable. No stack traces, no query echo.
- **Every HTML response** carries `Content-Security-Policy: default-src 'none'; style-src
  'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Plain HTML, no scripts.

### 4.7 `quota.py` and queue admission

- `Quota.charge(subject)` raises `QuotaExceeded(RealOemError)`. One atomic statement:
  `UPDATE usage SET requests = requests + 1 WHERE subject=? AND day=? AND requests < ?` (insert the
  day's row first if missing); 0 rows → refused, and refused attempts are not counted. The limit is
  `new_user_daily_limit` when the user's `github_created_at` is younger than `min_account_age_days`,
  else `user_daily_limit`; `0` means unlimited. When `global_daily_limit > 0`, a second statement on
  the day's total row applies the same way. Admins are not exempt. Charged only for a cache-miss
  page fetch (once per `RealOemClient.fetch` that goes to the network; retries and redirect hops
  are free), inside the client lock after the second cache check.
- Messages use the configured numbers: "You've used your {limit} RealOEM lookups for today; the
  limit resets at 00:00 UTC. Cached results remain available." / "RealOEM Searcher has reached its
  daily request limit; try again after 00:00 UTC."
- **Queue admission** (in the hook, before waiting for the lock): refuse immediately when the user
  is already at the limit; at most 2 waiting-or-in-flight cache-miss fetches per subject; at most
  20 waiters overall and a 60 s maximum wait; past any of these → tool error "RealOEM Searcher is
  busy; try again in a minute", nothing charged.
- **Per-call deadline** (`REALOEM_CALL_DEADLINE_S`, 50): once a tool call has run longer than this,
  its next cache-miss fetch raises `CallDeadline(RealOemError)`. `compare_vehicles` treats it like
  an exhausted request budget (switches to cache-only reads, `complete=false`, resumable). Other
  tools report it as a tool error asking the user to call again (pages already fetched are cached,
  so the retry is cheaper). PRD NFR5 (< 5 s uncached) holds per request when the queue is empty.
- `server_status` reports the caller's `quota: {used_today, limit, resets_at}` and `global_limit`
  when on.

### 4.8 Settings, changed tools, shared-mode rules

New `Settings` fields (env; defaults): `public_url` (`REALOEM_PUBLIC_URL`; required in HTTP mode),
`github_client_id` / `github_client_secret` (`REALOEM_GITHUB_CLIENT_ID` / `_SECRET`; required;
`repr=False`), `secret_key` (`REALOEM_SECRET_KEY`; base64 of ≥ 32 random bytes; required;
`repr=False`), `admins` (`REALOEM_ADMINS`, comma-separated GitHub numeric ids), `user_daily_limit`
(300), `new_user_daily_limit` (30), `min_account_age_days` (30), `global_daily_limit` (0 = off),
`call_deadline_s` (50), `cache_max_mb` (`REALOEM_CACHE_MAX_MB`, 600), `redirect_allowlist`
(`REALOEM_REDIRECT_ALLOWLIST`, default `https://claude.ai/api/mcp/auth_callback`), `auth_dir`
(`REALOEM_AUTH_DIR`, default `data_dir`). The HTTP entry point refuses to start when a required
value is missing or malformed. Rotating `secret_key` restarts the server and voids every token and
in-flight sign-in; users reconnect.

- `cache_clear`: in HTTP mode admins only (tool error otherwise); in stdio mode unchanged.
- `server_status`: in HTTP mode omits `cache_path` and adds `quota`; in stdio mode unchanged
  (PRD F0.6 and the existing tests keep applying to the local server).
- `refresh=true` in HTTP mode is honoured only when the cached copy is older than 1 hour;
  otherwise the cached page is returned (`from_cache=true` tells the truth).
- `update_vehicle_index` in HTTP mode is single-flight with a 1-hour server-wide cooldown: a call
  inside the cooldown returns `up_to_date` with a message saying when the index was last checked;
  an update in progress makes concurrent callers wait for its result. Its requests count against the
  caller who triggered it.
- **VIN pages are not shared:** `select?vin=` and `production?vin=` cache entries are keyed per
  subject in HTTP mode (the cache key gains a `user=<subject>` prefix for those page types), because
  `from_cache`/`fetched_at` on a shared entry would reveal whether and when someone else decoded a
  VIN. Every other page type is shared.
- `PageCache` gains a size cap: when the file exceeds `cache_max_mb`, least-recently-used rows are
  evicted (a `last_used` column, updated on hit) until it is 10 % under the cap; `VACUUM` weekly.
  The stdio server uses the same code with the cap off by default.
- `scripts/admin.py` (run via `fly ssh console` as the app user, not root, so SQLite's WAL files
  never become root-owned): `usage [--day]`, `ban <id> --reason`, `unban <id>`, `revoke <id>`,
  `prune`.

### 4.9 Rate limits, purging, retention

- ASGI middleware keyed on `Fly-Client-IP` (set by Fly's proxy; the socket peer is the proxy):
  `/register` 30 per hour per address outside `160.79.104.0/21` and 600 per hour across that range
  (hosted Claude registers a new client per connection), with a global ceiling of 2,000 a day;
  `/authorize` 60 per 10 minutes per address. Over a limit → `429` with `Retry-After`.
- `/authorize` refuses new pending requests above 10,000 live rows ("busy" page).
- Hourly purge task: expired pending rows, codes and tokens; clients that never completed an
  authorization after 24 hours, other clients 90 days after `last_issued_at`; `usage` rows older
  than 90 days; the consent audit after 90 days.
- Retention and privacy: the server keeps GitHub id and login, daily usage counts and ban records;
  no query content is stored outside the page cache; logs never carry query strings of OAuth
  routes, `Authorization` headers, form bodies, tokens, codes, GitHub tokens or VINs (in HTTP mode
  RealOEM URLs of page type `select` and `production` are logged with query values masked). The
  README gets a short privacy note.

### 4.10 Deployment

- Build context is the **repository root**. `server/Dockerfile`: `python:3.13-slim`, copies
  `server/` and `brands/`, `uv sync --frozen --no-dev`, non-root user, `CMD realoem-mcp-http`.
- `fly.toml` at the repository root: one process, internal port 8080, `force_https = true`,
  `auto_stop_machines = "off"`, `[http_service.concurrency] type = "requests", soft_limit = 100,
  hard_limit = 200`, HTTP check on `/healthz` (routing only), restart policy default `on-failure`,
  volume `realoem_data` at `/data`, env `REALOEM_CACHE_DIR=/data/cache`,
  `REALOEM_DATA_DIR=/data/data`, `REALOEM_BRANDS_DIR=/app/brands`. `flyctl deploy --ha=false` runs
  from the repository root.
- Secrets via `fly secrets set`: `REALOEM_PUBLIC_URL`, `REALOEM_GITHUB_CLIENT_ID`,
  `REALOEM_GITHUB_CLIENT_SECRET`, `REALOEM_SECRET_KEY`, `REALOEM_ADMINS`. Setting a secret restarts
  the machine (a few seconds of downtime).
- GitHub Actions `deploy.yml`: on a `v*` tag it runs lint and the offline tests itself (CI does not
  run on tags), then `flyctl deploy --remote-only --ha=false` with an app-scoped deploy token
  (`fly tokens create deploy`) from a GitHub Environment with a required reviewer; a repository
  ruleset protects `v*` tags.
- A second GitHub OAuth App ("RealOEM Searcher (dev)", callback on `http://localhost:8080`) is used
  for local container runs, since a GitHub OAuth App takes one callback URL.
- Fatal SQLite errors in the auth store (`CORRUPT`, `IOERR`, `FULL`) are logged and the process
  exits 1, so Fly's `on-failure` policy restarts it; `/healthz` never heals anything by itself.
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
   browser; the server validates `resource`, stores the pending request and redirects to
   `/consent`.
5. The consent page names the redirect target and what is granted. **Deny** → back to Claude with
   `access_denied`. **Allow** → the server generates the GitHub `state` and PKCE verifier, sets the
   state cookie and redirects to GitHub ("Sign in with GitHub", public profile only).
6. GitHub returns to `/oauth/github/callback`; the server checks the state cookie against the query
   and the stored hash, exchanges the code, reads the numeric id; banned → error page.
7. The server redirects to Claude's redirect URI with a one-time code and the original `state`;
   Claude exchanges it at `/token` for a 1-hour access token and a refresh token.

**Tool call:**

1. `Authorization: Bearer <token>` → the SDK validates (exists, unexpired, resource is `/mcp`, scope
   `realoem`, subject not banned) and exposes the token to `current_user()`.
2. The tool runs as today. On a cache miss, the hook applies queue admission, the per-call
   deadline and the quota, then the fetch waits its turn (one in flight, ≥ 2 s).
3. The result returns with `source_urls`. Claude refreshes tokens proactively; each refresh rotates
   the refresh token.

**Shared state:** one page cache (except VIN pages) and one vehicle index for everyone.

## 6. Error handling

| Situation | Behaviour | User-facing text |
|---|---|---|
| No or expired token | `401` + resource metadata pointer (SDK); Claude refreshes or signs in | Claude prompts to (re)connect |
| Wrong scope or resource | `403 insufficient_scope` / `401` (SDK) | Claude re-authorizes |
| `resource` foreign at `/authorize` | `invalid_target` error redirect (SDK) | Connection fails with a clear error |
| Daily user limit reached | Refused before waiting; cache hits still answered | Quota message (4.7) |
| Server-wide cap on and reached | Same | Server-wide message (4.7) |
| Queue full or wait too long | Tool error, nothing charged | "RealOEM Searcher is busy; try again in a minute." |
| Call deadline reached | `compare_vehicles`: partial, resumable; others: tool error | "…took too long; call again to continue (fetched pages are cached)." |
| Banned user | Tokens refused at `load_access_token`; sign-in refused after GitHub | Error page: access suspended, contact link |
| Bot challenge / layout change / upstream error | Unchanged; not cached; counts against quota | Today's messages (ARD §5.3) |
| GitHub unavailable or user cancelled at GitHub | Clean failure, nothing stored (cancel → `access_denied` to Claude only after the state checks pass) | "GitHub sign-in is unavailable right now; try again shortly." |
| Bad registration | `400 invalid_redirect_uri` / `invalid_client_metadata` (provider); `429` (middleware) | Client-only |
| Consent form without its cookie, stale, or replayed; callback with missing or mismatched state | Error page, never a redirect | "This sign-in request has expired. Start again from Claude." |
| Restart (deploy, migration, secret change) | Seconds of failed connections; nothing lost (no sessions; tokens and cache on disk) | Claude retries |
| Fatal auth-store error | Process exits 1 → Fly restarts it | Brief outage |

Logs carry `github:<id>`, tool name, page type and outcome; see 4.9 for what they never carry.

## 7. Testing

Offline, in CI, no network (extends the existing 942 tests; `httpx.MockTransport` per AD4, no new
test dependency):

- **Provider:** redirect allow-list (Claude callback exact; loopback any port; `localhost.evil.com`,
  `localhost@evil.com`, `127.0.0.1.nip.io`, fragments and userinfo rejected); `client_name` limits;
  `resource` missing → defaulted, foreign → `invalid_target`; consent state machine (`allow`,
  `deny`, double POST → expired); GitHub `state` mismatch, missing cookie, replay; PKCE failure
  (SDK); code single-use incl. **two concurrent exchanges of one code**; refresh rotation incl.
  **two concurrent refreshes** and reuse-revokes-family; revocation; hashes only in the store;
  banned user refused at callback and at token load; 20-family cap.
- **Pages and headers:** consent page shows the redirect URI and escapes `client_name`; CSP,
  `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`, HSTS present; error pages never redirect.
- **End-to-end over HTTP** (`httpx.AsyncClient` against the app, in-memory, fake GitHub):
  discovery → register → authorize → consent → fake GitHub → token → `tools/list` →
  `lookup_part` against the existing fixture routes; `401` without a token; `403` for a missing
  scope; two users share a `partxref` page (second identical call costs no quota) but **not** a VIN
  page; interleaved calls from two users are charged to the right subject; `cache_clear` refused
  for a non-admin, allowed for an admin; request log lines contain no query strings.
- **Middleware:** `/register` and `/authorize` return `429` keyed per `Fly-Client-IP`, with the
  Anthropic-range bucket.
- **Quota and admission:** cache hits free; retries and redirect hops free; UTC rollover; refusal
  makes no request and is not counted; new-account limit; global cap on/off; per-subject and
  overall waiter limits; the per-call deadline makes `compare_vehicles` partial and resumable.
- **Cache cap:** LRU eviction under the cap; `last_used` updated on hit.
- **Settings:** HTTP entry point refuses to start without each required value.
- **Unchanged:** all stdio, parser and tool tests (stdio keeps `cache_path` and open `cache_clear`).

Before release: Opus security review of `auth/`, `quota.py` and the middleware against this spec
and the MCP security best practices; local container run checked with `curl` discovery, MCP
Inspector and `claude mcp add`; after deploy, sign in and run the PRD §7 smoke session from Claude
Code, a Cowork cloud session and chat, with the replay check (zero repeat RealOEM requests).

## 8. Rollout

Two implementation plans: **(1)** auth, quota, admission, cache cap and the HTTP app, all testable
offline; **(2)** Dockerfile, Fly, the deploy workflow, the GitHub OAuth Apps, the hostname, and the
0.2.0 release.

1. Send the RealOEM owner message (drafted 2026-10-01: per-user daily limits, shared cache, honest
   UA, offer to adjust or stop). Hold the public switch until a reply or a reasonable wait.
2. Release **0.2.0**: `plugin.json` → hosted URL; Claude-Plugin-Collection entry → `v0.2.0`;
   README (install = "Install, then Connect / `/mcp`", tools table and troubleshooting without the
   cache path, privacy note); CHANGELOG. Documents to update: ARD §2 diagram, §3 (new AD17 "hosted
   server", AD1/AD2 marked development-only), §4 layout, §5.1 manifest, §5.2 settings, §5.2a
   `create_services(before_request=…)`, §5.3 (`QuotaExceeded`, `CallDeadline`), §5.5 (the hook),
   §5.6 (cache cap, VIN keys), §5.11 admin-tool contracts, §7 security, §8 CI/deploy; PRD F0.1,
   F0.2, F0.4, F0.6, F6.2, NFR5, NFR7, and a new risk "all users share one egress IP: one Cloudflare
   challenge stops everyone; a static egress IP would help RealOEM identify the traffic".
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
