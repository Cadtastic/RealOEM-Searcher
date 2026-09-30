# RealOEM Searcher

A Claude Code plugin that answers BMW Group parts questions (BMW, MINI, Rolls-Royce and BMW
Motorrad) from [RealOEM.com](https://www.realoem.com/bmw/enUS/select): part-number lookups,
supersession chains, VIN decoding, parts diagrams, fitment checks, vehicle-to-vehicle part
comparison and a local vehicle finder. It bundles a small local MCP server (`server/`) that fetches
and parses RealOEM pages on demand, and six skills that teach Claude when and how to use it.

**Status:** v0.1.0 is the first release (see [CHANGELOG.md](CHANGELOG.md)). All 13 tools and all 6
skills ship. CI runs the offline tests on Ubuntu (Python 3.11 and 3.13) and Windows (Python 3.13);
macOS is supported but not in CI.

## Install

Requirements:

- [uv](https://docs.astral.sh/uv/getting-started/installation/) on your `PATH`. The plugin starts
  its server with `uv run`.
- Python 3.11 or newer. If none is installed, uv downloads one.
- Network access on the first start, because `uv run --no-dev --frozen` installs the server's
  dependencies from `server/uv.lock`.

In Claude Code:

```
/plugin marketplace add Cadtastic/RealOEM-Searcher
/plugin install realoem-searcher@realoem-searcher
```

## Example questions

Ask in plain language; the skills tell Claude which tools to call.

- "What oil filter does VIN ...PX22770 use?"
- "Is 11427541827 current?" (replaced by 11427953129)
- "Does 11427953129 fit an E90 325i USA 10/2005?"
- "Compare the engine lubrication diagrams of an E90 325i and an E92 335i."
- "Find a 2019 R 1250 GS."

These five questions were answered end to end against the live site on 2026-09-30 (15 requests in
total); replaying every call afterwards made no request, because every page was cached.

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
when nothing is cached; a cached page costs none. Tools that read cached pages accept
`refresh=true` to fetch a fresh copy. Answers built from RealOEM pages carry the `source_urls` of
the pages used.

| Tool | Purpose | Requests |
|---|---|---|
| `lookup_part` | Status (current, ended, not found), description, dates, weight, superseded-by and supersedes lists, and the series using a part; with `series`, its vehicles and diagrams | 1 |
| `trace_supersession` | Follow "superseded by" links to the part that replaces a number today | at most 1 + `max_hops` (1-10, default 5); typically 1-2 |
| `decode_vin` | Vehicle for the last 7 or all 17 VIN characters: brand, series, model, market, production month, engine, type code, vehicle id | 1, or 2 with `include_production` |
| `find_vehicle` | Search the local vehicle index by name, series, year, market or type code | none |
| `update_vehicle_index` | Add vehicles RealOEM listed since the baseline was built | 1 when nothing is new, else at most `max_pages` (1-10, default 5); one more if the local list is longer than RealOEM's |
| `select_vehicle` | Walk RealOEM's model cascade one level per call until a vehicle id is reached | 1 per call |
| `list_part_groups` | A vehicle's specifications and main groups | 1 |
| `list_diagrams` | The subgroups and diagrams of one main group | 1 |
| `get_diagram_parts` | One diagram's parts list (prices, notes, option-code conditions), image and hotspots | 1 |
| `check_fitment` | Whether a part is used on one vehicle, which number it uses there and in which diagrams | 1 |
| `compare_vehicles` | Part numbers two vehicles use in one main group: in both, only A, only B | 2 + 1 per diagram, capped by `max_requests` (2-60, default 20) |
| `server_status` | Version, base URL, user agent, request interval, cache path and size, requests sent since start | none |
| `cache_clear` | Delete all cached pages, or only one page type (for example `partxref`) | none |

## Vehicle index

`find_vehicle` searches a local list of every vehicle in RealOEM's vehicles index, so a vehicle can
be found by name, series, year, market or type code without walking the model cascade and without
a request.

- **Baseline.** `brands/<brand>/vehicles.csv` plus `brands/vehicles.meta.toml`, committed to this
  repository. Built 2026-09-30: 8218 vehicles (bmw 6824, mini 640, motorrad 642, rolls-royce 112).
- **Local store.** The baseline is loaded into `vehicles.sqlite3` in the data directory on first use
  and reloaded when the baseline files change.
- **Updates.** `update_vehicle_index` adds vehicles RealOEM has listed since the baseline was built,
  reading as few pages as possible. The rows it adds persist in `vehicles.sqlite3`. If RealOEM's
  list no longer matches the local one, it reports `drift` and the maintainer rebuilds the baseline.
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

- One request in flight at a time and at least 2 seconds between requests by default
  (`REALOEM_MIN_INTERVAL` can change it, but never below 1 s). The spacing also applies between
  redirect hops and retries. The limit is per server process; it is not shared between several
  running servers.
- Pages are cached locally, so repeat questions cost nothing (see below).
- Requests identify themselves honestly:
  `RealOEM-Searcher/<version> (+https://github.com/Cadtastic/RealOEM-Searcher)`.
- The only cookie sent is `ro_ui=v2`, which pins the page layout the parsers read. Cookies the
  server sets are discarded.
- Only same-origin redirects are followed, at most 3.
- Up to 2 retries on HTTP 429, 5xx or a timeout, waiting for `Retry-After` (capped at 30 s) when
  RealOEM sends one, otherwise 5 s and then 15 s.
- If RealOEM shows a Cloudflare bot challenge, the plugin stops and tells you; it never retries it
  or tries to get around it.
- Only the last 7 characters of a VIN are sent to RealOEM.
- No crawling, no background or speculative fetching, no use of RealOEM data for AI training. The
  single exception is the committed vehicle list: a maintainer rebuilds it with one full pass over
  RealOEM's vehicle index (about 166 requests, about 6 minutes) so that users do not each fetch it.
  Users only ever run incremental updates (`update_vehicle_index`).

### Caching

Raw pages are kept in a SQLite file (`pages.sqlite3`, see [Configuration](#configuration)):

| Page | Used by | Kept for |
|---|---|---|
| `select` (model cascade) | `select_vehicle` | 30 days |
| `select?vin` | `decode_vin` | 180 days if found, 1 day if not |
| `production` | `decode_vin` with `include_production` | 180 days; 1 day with no record |
| `partgrp` | `list_part_groups`, `list_diagrams`, `compare_vehicles` | 30 days; 1 day for an unknown main group |
| `showparts` | `get_diagram_parts`, `compare_vehicles` | 30 days |
| `partxref` | `lookup_part`, `trace_supersession` | 7 days |
| `partsearch` | `check_fitment` | 7 days |
| `vehicles` | `update_vehicle_index` | 1 day, but always fetched fresh (never served from the cache) |

Pages that fail to parse are expired immediately, so the next call fetches them again. Redirects
and error responses are not cached. `refresh=true` on a tool call, or `cache_clear`, forces fresh
copies.

## Configuration

The server reads these environment variables (all optional). `plugin.json` itself sets only
`REALOEM_BRANDS_DIR`; the server reads the others from its environment.

| Variable | Default | Notes |
|---|---|---|
| `REALOEM_MIN_INTERVAL` | `2.0` seconds between requests | Must be a finite number; values below 1.0 become 1.0 |
| `REALOEM_TIMEOUT` | `20.0` seconds | Must be a finite number greater than 0 |
| `REALOEM_CACHE_DIR` | the user cache directory for `realoem-searcher` | Holds `pages.sqlite3`, the page cache |
| `REALOEM_DATA_DIR` | the user data directory for `realoem-searcher` | Holds `vehicles.sqlite3`, the vehicle index; `cache_clear` never touches it |
| `REALOEM_BASE_URL` | `https://www.realoem.com` | |
| `REALOEM_BRANDS_DIR` | `brands/` in this repository | Brand registry and vehicle index baseline; set by `plugin.json` |

A `REALOEM_MIN_INTERVAL` or `REALOEM_TIMEOUT` that is not a finite number, or a timeout of 0 or
less, stops the server from starting. The catalog language (`enUS`) and the user agent are not
configurable.

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
- Use `server_status` to check the settings in effect, the cache location and size, and how many
  requests the server has sent since it started. If answers look stale, call the tool again with
  `refresh=true` or use `cache_clear`.

| Error | What it means | What to do |
|---|---|---|
| "RealOEM is showing a bot challenge (Cloudflare) ..." | RealOEM answered with a Cloudflare challenge instead of the page. The plugin never retries or works around it. | Try again later, or open the URL from the message in a browser. |
| "RealOEM's ... page did not have the expected structure ..." (`LayoutChanged`) | The page did not match what the parser reads, so the plugin returns an error instead of guessing. The page is not kept in the cache. | Try again later. If it persists, RealOEM changed its markup: update the plugin, or [open an issue](https://github.com/Cadtastic/RealOEM-Searcher/issues) with the page URL from the message. |
| "RealOEM request failed (...)" | RealOEM returned an error status, timed out or could not be reached (429, 5xx and timeouts are retried twice first). | Try again later. |

## Development

```bash
cd server
uv sync --locked             # create .venv from uv.lock (runtime + dev dependencies)
uv run ruff check            # lint
uv run ruff format --check   # formatting (without --check it reformats)
uv run pytest                # offline test suite; pyproject adds -m "not live"
uv run realoem-mcp           # run the MCP server on stdio (Ctrl+C to stop)
```

CI runs the first four commands (see `.github/workflows/ci.yml`). Validate the marketplace and the
plugin manifest from the repository root with:

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
[RealOEM site notes](docs/research/realoem-site-notes.md). Release history:
[CHANGELOG](CHANGELOG.md).

## License

[MIT](LICENSE). RealOEM is an independent site not affiliated with this project or with BMW AG.
