# Changelog

All notable changes to RealOEM Searcher are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-30

First release. A Claude Code plugin with a local MCP server (`realoem`) and six skills that answer
BMW Group parts questions (BMW, MINI, Rolls-Royce and BMW Motorrad) from RealOEM.com.

### Added

- **Part number lookup (`lookup_part`).** Status (`current` / `ended` / `not_found`), description,
  dates, weight, superseded-by and supersedes lists, and the series using a part, or, narrowed to
  one series, the vehicles and diagrams that show it. Accepts 7 or 11 digits and rejects RealOEM's
  last-7-digit false matches.
- **VIN decode (`decode_vin`).** The last 7 or all 17 characters give the vehicle (brand, series,
  model, market, production month, engine, type code, vehicle id). Only the last 7 characters are
  ever sent. A full VIN's manufacturer prefix is checked against the decoded brand; production
  statistics are optional.
- **Diagram browsing (`select_vehicle`, `list_part_groups`, `list_diagrams`, `get_diagram_parts`).**
  Walks RealOEM's model cascade one level at a time, lists main groups and diagrams, and reads a
  diagram's parts list with option-code conditions, prices, notes, image and hotspots.
- **Fitment and comparison (`check_fitment`, `compare_vehicles`).** Answers "is part X used on
  vehicle Y" with one request, including the number the vehicle actually uses and where. Compares
  the part numbers two vehicles use in one main group, under a request budget, with resumable
  partial results.
- **Supersession chains (`trace_supersession`).** Follows "Superseded by" links to the part that
  replaces a number today: `current`, `replaced`, `no_successor`, `ambiguous` or `not_found`, with
  the chain, alternatives and history. A typical trace takes one or two requests.
- **Local vehicle index (`find_vehicle`, `update_vehicle_index`).** A committed baseline of all 8218
  vehicles in RealOEM's index (built 2026-09-30), searchable with no network requests and refreshed
  incrementally. A maintainer-only script rebuilds the baseline.
- **Skills.** `part-lookup`, `vin-decode`, `diagram-browse`, `fitment`, `supersession` and
  `vehicle-index` teach Claude when and how to use the tools, what to cite and what not to guess.
- **Polite, cached client.** One request in flight, at least 2 s between requests by default (never
  below 1 s), an honest `RealOEM-Searcher/0.1.0` user agent, and a SQLite page cache with per-page
  TTLs (VIN results 180 days, catalog and diagram pages 30 days, part lookups 7 days). Tools that
  read cached pages accept `refresh=true`. A Cloudflare challenge is reported, never worked around.
- **Admin tools (`server_status`, `cache_clear`).** Version, cache location and size, request
  settings, and cache clearing by page type.
- **Tests.** Parsers are tested offline against trimmed real RealOEM pages. CI runs the offline
  suite on Ubuntu (Python 3.11, 3.13) and Windows (3.13) and never contacts RealOEM; opt-in live
  smoke tests are not run in CI. The release was checked with the PRD's smoke session against the
  live site: five end-to-end questions in 15 requests, and a replay of every call made no further
  request.

[0.1.0]: https://github.com/Cadtastic/RealOEM-Searcher/releases/tag/v0.1.0
