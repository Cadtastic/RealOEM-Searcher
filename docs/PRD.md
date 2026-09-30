# RealOEM Searcher: Product Requirements Document

| | |
|---|---|
| Status | Approved for implementation |
| Owner | Cadtastic |
| Repository | https://github.com/Cadtastic/RealOEM-Searcher |
| Last updated | 2026-09-30 |
| Companion docs | [ARD](ARD.md), [RealOEM site notes](research/realoem-site-notes.md), [implementation plans](superpowers/plans/) |

## 1. Problem

BMW Group owners, DIY mechanics and parts buyers use [RealOEM](https://www.realoem.com/bmw/enUS/select)
to find OEM part numbers, check which vehicles use a part, and follow replaced ("superseded") part
numbers. Doing this by hand means clicking through a 6–8 step model cascade, scanning diagram tables and
cross-referencing numbers across pages. RealOEM has no API, so an AI assistant cannot answer these
questions reliably without a purpose-built tool.

## 2. Goal

A Claude plugin that lets a user ask natural-language parts questions about BMW Group vehicles
(BMW, MINI, Rolls-Royce, BMW Motorrad) and get accurate answers sourced from RealOEM, with links back
to the pages used, while treating RealOEM as a reference source rather than something to crawl.

## 3. Users

| User | Typical questions |
|---|---|
| DIY owner | "What's the oil filter for my 2008 328i convertible, VIN ...PX22770?" |
| Parts buyer / reseller | "Is 11427566327 still current? What replaced it?" |
| Enthusiast doing a swap | "Does this E90 part fit my E92?", "Which brake parts do the R56 and R53 share?" |
| Shop / advisor | "Show me the parts diagram for the rear axle on this car." |

## 4. Scope

### 4.1 In scope: BMW Group on RealOEM

All vehicles in RealOEM's `/bmw/` catalog: BMW cars (incl. BMW i, M/Motorsport), MINI, Rolls-Royce and
BMW Motorrad, Current and Classic catalogs. Language fixed to US English (`enUS`); prices are
reported as shown by RealOEM (always USD).

### 4.2 Out of scope

- Other brands or other parts-catalog websites.
- Bulk crawling, catalog mirroring, offline database builds, or any use of RealOEM data for AI training.
- Bypassing Cloudflare or other bot protections (no headless-browser challenge solving).
- Per-VIN factory option (SA) codes, paint, upholstery or model year. RealOEM does not expose them.
- Ordering, price comparison across vendors, or affiliate links.
- Account/login features (RealOEM membership only removes ads).
- Languages other than `enUS`.

## 5. Features

Each feature ships on its own branch and pull request, in this order. `feat/foundation` is a
prerequisite for all of them.

### F0: Foundation (`feat/foundation`)

Plugin and marketplace manifests, Python MCP server skeleton, polite HTTP client, SQLite cache, brand
registry, fixture tooling, CI.

**Requirements**

- F0.1 Installable as a Claude Code plugin from this repo (`/plugin marketplace add
  Cadtastic/RealOEM-Searcher`). Listing in `Cadtastic/Claude-Plugin-Collection` happens at the first
  release, not in a feature branch.
- F0.2 The MCP server starts via `uv` from the installed plugin with no manual setup beyond having `uv`.
- F0.3 All RealOEM requests go through one client that enforces a minimum interval between requests
  (default 2 s, configurable; never below 1 s), identifies itself honestly with a
  `RealOEM-Searcher/<version> (+repo URL)` user agent, sends only the `ro_ui=v2` cookie, and never sends
  `dmode=0`.
- F0.4 Responses are cached in SQLite in the user's cache directory with per-page-type TTLs; every data
  tool accepts `refresh=true`; a `cache_clear` tool exists.
- F0.5 A Cloudflare challenge produces a clear error telling the user RealOEM is blocking automated
  requests. The server never retries through or works around a challenge.
- F0.6 A `server_status` tool reports version, cache location/size and request settings.

### F1: Part number lookup (`feat/part-lookup`) — feature A

- F1.1 Given a part number (11 digits, or 7-digit short form; spaces, dashes and dots allowed), return
  description (when the part page provides one; no extra requests to find it), supplier reference,
  valid-from/to dates, weight, status (`current`, `ended`, `not_found`), superseded-by and supersedes
  lists, and the series that use it, each tagged with its brand.
- F1.2 Given a part number and a series code, return the vehicles (type code, model, body, engine,
  market, vehicle id) and the diagrams in which the part appears.
- F1.3 Reject malformed input before any request. Report RealOEM's last-7-digit false matches and the
  junk part `00000000000` as not found.
- F1.4 Never report a part as discontinued based on the page title.

### F2: VIN decode (`feat/vin-decode`) — feature B

- F2.1 Given a VIN (last 7 or all 17 characters), return brand, product, catalog, series, body, model,
  market, production month, engine, steering, transmission (when shown), type code and vehicle id.
- F2.2 Report `not_found` when RealOEM has no match.
- F2.3 For full 17-character VINs, compare the manufacturer prefix (WMI) with the decoded brand and flag
  mismatches as low confidence.
- F2.4 Optionally return production statistics (build month, sequence within month and type).
- F2.5 The skill must state that option codes, paint and upholstery are not available from RealOEM.

### F3: Diagram browsing (`feat/diagram-browse`) — feature C

- F3.1 Step through vehicle selection (product, catalog, series, body, model, market, production month,
  engine, steering, and transmission for Classic-catalog cars) one level at a time, including
  auto-selected levels, until a vehicle id is reached.
- F3.2 List a vehicle's specs and main groups.
- F3.3 List a main group's subgroups and diagrams.
- F3.4 Return a diagram's parts list: position, description, supplement, quantity, from/to dates, part
  number, price, notes, photo flag and option-code conditions; plus the diagram image URL and hotspots.
- F3.5 Accept vehicle ids from F1 and F2 results directly.

### F4: Fitment and comparison (`feat/fitment`) — feature D

- F4.1 Given a part number and a vehicle id, answer whether the part is used on that vehicle, which part
  number the vehicle actually uses (supersession-resolved), and in which diagrams. One request.
- F4.2 Compare two vehicles within one main group (optionally narrowed to a subgroup or specific
  diagrams): the part numbers used in that scope on both, only on A, only on B, and quantity
  differences. Diagrams don't need to match between the vehicles; the comparison is by part number.
  Bounded by a network-request budget (default 20, max 60; cached pages are free); partial results list
  the diagrams that were skipped.
- F4.3 "Which vehicles use part X" is answered via F1.

### F5: Supersession chain (`feat/supersession`) — feature E

- F5.1 Given a part number, follow "superseded by" links to the current part and return the chain with
  dates and remarks, the current number, and the predecessor history.
- F5.2 Detect `current`, `replaced`, `no_successor` (ended with no replacement) and `ambiguous`
  (several open-ended successors, returned as alternatives).
- F5.3 Guard against loops and cap hops (default 5).

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR1 Politeness | ≥ 2 s between requests to RealOEM by default; one request in flight at a time per server process; no background or speculative fetching. |
| NFR2 Caching | Repeat questions within a TTL cause zero requests. TTLs: catalog structure and diagram pages 30 days, part lookups 7 days, VIN results 180 days. |
| NFR3 Correctness | A parser that finds an unexpected page structure raises `LayoutChanged` instead of returning partial or guessed data. |
| NFR4 Traceability | Every data tool result includes the RealOEM `source_urls` and `fetched_at` (admin tools `server_status`/`cache_clear` excepted). |
| NFR5 Latency | Single-lookup tools answer in < 5 s when uncached (dominated by the rate limit). |
| NFR6 Testability | Parsers are tested offline against trimmed real-page fixtures; CI needs no network. Live smoke tests are opt-in. |
| NFR7 Portability | Runs on Windows, macOS and Linux with Python ≥ 3.11 managed by `uv`. |
| NFR8 Transparency | User-facing errors say what happened and what to do (e.g. "RealOEM is showing a bot challenge; try again later or open the URL in a browser"). |

## 7. Success criteria

- Each feature's acceptance tests (in its plan) pass in CI.
- A manual smoke session answers these end to end:
  1. "What oil filter does VIN ...PX22770 use?" (F2 → F3 or F4)
  2. "Is 11427541827 current?" (F1 → F5, expected: replaced by 11427953129)
  3. "Does 11427953129 fit an E90 325i USA 10/2005?" (F4)
  4. "Compare the engine lubrication diagrams of an E90 325i and an E92 335i." (F4)
- No RealOEM request is made twice within its TTL during the smoke session.

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| RealOEM tightens bot protection (JS challenge) or blocks our user agent | Tools stop working | Detect and report clearly; honest UA so RealOEM can contact or block us deliberately; low request volume; caching. Spoofing a browser or a headless-browser fallback is out of scope. |
| Markup changes / A/B variants | Wrong or missing data | Pin `ro_ui=v2`; minimal, data-anchored selectors; `LayoutChanged` errors; fixture regression tests; fixture refresh script. |
| Last-7-digit matching returns the wrong part | Wrong answers | Client-side input validation and returned-number verification. |
| Server silently picks one vehicle for an ambiguous VIN serial | Wrong vehicle | WMI cross-check for full VINs; skill labels result as RealOEM's best match. |
| Terms of use / content signals | Legal/ethical exposure | Reference-only use, user-initiated, throttled, cached; no bulk data; fixtures trimmed to data sections. |

## 9. Open questions

See [site notes §6](research/realoem-site-notes.md#6-open-questions).
