# RealOEM Searcher

A Claude Code plugin that answers BMW Group parts questions (BMW, MINI, Rolls-Royce and BMW
Motorrad) from [RealOEM.com](https://www.realoem.com/bmw/enUS/select): part-number lookups,
VIN decoding, parts diagrams, fitment checks and supersession chains. It bundles a small local MCP
server (`server/`) that fetches and parses RealOEM pages on demand, plus skills that teach Claude
how to use it.

**Status:** in development — the foundation (server, cache, rate limiting) is in place; lookup
features land in upcoming releases (see [docs/PRD.md](docs/PRD.md)).

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

PowerShell:

```powershell
$env:REALOEM_LIVE = "1"; uv run --directory server pytest -m live
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
