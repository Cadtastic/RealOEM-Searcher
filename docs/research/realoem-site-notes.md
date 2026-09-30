# RealOEM site notes

Reconnaissance of https://www.realoem.com performed 2026-09-29/30 (~110 polite requests, ≥2 s apart).
These notes are the source of truth for parser and client behavior. Raw captured pages live in the
git-ignored `.research-raw/{xref,vin,diagrams}/` folder of a local checkout; trimmed fixtures derived
from them live in `server/tests/fixtures/`.

Catalog snapshot at time of research: "Catalog: 03/2025" (`span.catalog-version`).

---

## 1. Site-wide behavior

### 1.1 Base URL, language segment

- All pages: `https://www.realoem.com/bmw/{lang}/...`. BMW, MINI, Rolls-Royce, Zinoro, BMW i, Motorsport
  and BMW Motorrad all live under `/bmw/`.
- `{lang}` values: `enUS`, `en`, `de`, `fr`, `es`, `it`, `ru`, `ja`, `ko`, `zh`, `zhTW`, `nl`, `pl`, `pt`,
  `sv`, `cs`, `el`, `th`, `tr`. No `enGB`/`deDE`.
- Language changes UI labels, part descriptions and condition text (`enUS` "Oil Pan / Required for
  repair", `en` "Oil pan / Necessary for repair", `de` "Ölwanne / Für die Reparatur notwendig").
- Language does **not** change prices (always USD, e.g. `$551.84`, also for EUR-market vehicles), part
  numbers, diagIds, positions, hotspots.
- Under `enUS`, market `USA` is auto-selected in the model cascade when available.
- **Decision: always use `enUS`.**

### 1.2 Cloudflare / bot behavior

- curl's default UA → **HTTP 403** with header `Cf-Mitigated: challenge` and a "Just a moment..." page.
- A browser UA (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)
  Chrome/128.0 Safari/537.36`) → 200 on every request (used during research). No cookies required.
- An honest identifying UA `RealOEM-Searcher/0.1 (+https://github.com/Cadtastic/RealOEM-Searcher)` →
  200 (verified 2026-09-30). **The plugin uses this form** (ARD AD13).
- No 429s observed at ~1 req / 1.5–3 s.
- Pages include a passive `/cdn-cgi/challenge-platform/.../jsd/main.js` beacon; not needed.
- Site banner: slowness due to "increased load from AI bot traffic"; mitigations in progress. Expect
  stricter rules later → throttle, cache, detect challenges, never attempt to bypass them.
- `robots.txt`: `User-agent: *` → `Content-Signal: search=yes,ai-train=no,use=reference`, `Allow: /`;
  explicitly disallows `ClaudeBot`, `GPTBot`, `CCBot`, etc. Our use: user-initiated reference lookups
  only, no crawling, no bulk mirroring, no training. Single approved exception: the vehicle list
  (§5.5), fetched once by the maintainer and committed so users don't each fetch it.
- Asset versions changed (`?40` → `?42`) mid-session: live deploys; markup can drift.

### 1.3 UI A/B variants (`ro_ui` cookie)

- Server assigns `ro_ui=v1` or `v2` at random (1-year cookie) when none is sent; echoes it in the
  `X-RO-UI` response header (`v1` or `v2+new`). `?ui=v1|v2` toggles too. `Vary: Cookie, X-RO-Partial`.
- Data markup is **identical** in both variants for: partxref, partsearch, part, partgrp `&mg=` diagram
  list, showparts table/hotspots.
- **Differs** for:
  - `select` cascade: v1 = `<select id=...><option selected>`; v2 = `a.ro-lb-row` list boxes.
  - `partgrp` main groups: v1 titles "11 - ENGINE" and no `.grp-badge`; wrapper layout differs.
- **Decision: always send `Cookie: ro_ui=v2`; parse v2 only; verify `X-RO-UI` starts with `v2`.**
- Other cookies set by the server (ignore): `ab_variant`, `ad_render_ab2`, `ro_navgate`.
- **Never send `dmode=0`** — it switches `partgrp&mg=` into a text drill-down mode without diagIds.

### 1.4 Status codes and error signalling

- Almost everything returns **HTTP 200**, including not-found and invalid input. Errors must be
  detected by parsing.
- Invalid vehicle id on `partgrp`/`showparts` → **301 to `/bmw/`** (landing page). Treat a final URL
  that is not the requested page type as "vehicle not found".
- Cache headers vary (`private, max-age=3600` on xref; `no-cache` on select/partgrp).

### 1.5 Parsing scope

- Pages carry heavy ad/affiliate/obfuscated scripts. Scope parsing to `div.content` (xref family) or the
  specific containers listed below. Never anchor on layout wrappers (`#main`, `.grid`, `.page-container`,
  footer).
- Known template bugs present in markup (do **not** select on them; they may be fixed):
  `class="sup-by-{$t.count}"`, error div containing literal `{0}`.

---

## 2. Vehicle ids

Format: `{TypeCode}-{Market}-{MM}-{YYYY}-{Series}-{Brand}-{Model}` where spaces and parentheses in the
model become `_` and commas are kept.

| Vehicle | Id |
|---|---|
| BMW E90 325i USA 10/2005 | `VB13-USA-10-2005-E90-BMW-325i` |
| BMW E90 325i EUR LHD | `VB11-EUR-10-2005-E90-BMW-325i` |
| BMW E93 328i | `WL13-USA-07-2008-E93-BMW-328i` |
| MINI R56 Cooper S | `MF73-USA-02-2008-R56-Mini-Cooper_S` |
| MINI R53 Cooper S (Classic) | `RE33-USA-04-2004-R53-Mini-Cooper_S` |
| Rolls-Royce Ghost | `FK43-USA-06-2010-RR4-Rolls_Royce-Ghost` |
| Motorrad R 1250 GS | `0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_` |
| Motorrad R 1200 GS | `0A61-USA-09-2017-K50-BMW-R_1200_GS_17_0A51,_0A61_` |

- Variants seen in links: `VB13-USA---E90-BMW-325i`, `VB13-USA-02_2004_E90_BMW_325i` (xref form).
- Server keys on the leading `TypeCode-Market-MM-YYYY`; a garbage suffix is accepted and the page's
  `<link rel="canonical">` gives the normalized id. `partgrp?id=VB13` alone → 301 to `/bmw/`.
- Production month in the id matters: parts lists are filtered by it.
- Classic catalog (`archive=1`) is not visible in the id.
- **Always take ids from the site (hidden input / hrefs / canonical); URL-encode when sending** (spaces,
  commas, parentheses). The site's own hrefs are not encoded.

---

## 3. Part number pages (feature A, D, E)

### 3.1 URLs

| URL | Returns |
|---|---|
| `partxref?q=<pn>` | Part header, supersession blocks, list of **series** using the part |
| `partxref?q=<pn>&series=<code>` | Same header; one row per **type code × diagram** with showparts links |
| `partxref?id=<vid>&diagId=..&q=<pn>` | Same as plain xref plus breadcrumbs (id does not filter) |
| `part?id=<vid>&q=<pn>` | Canonical SEO page: `<h1>NNN - Description</h1>`, vehicle `<h2>`, JSON-LD. Series ranges **differ** from partxref — do not mix sources |
| `partsearch?id=<vid>&q=<pn>[&diagId=..]` | **Per-vehicle fitment in one request**: diagrams on that vehicle containing the part, price, supersession |

### 3.2 Part-number normalization (server side)

- Server strips non-digits and **matches on the last 7 digits**.
  - `11 42 7 953 129`, `11-42-7-953-129`, `7953129` → 11427953129.
  - `99999999999` → the real part **00009999999** (false match).
  - `abc` → junk part **00000000000** (listed on almost every series, weight 55662 kg).
- **Client rule:** accept only 7 or 11 digits after stripping separators; after fetching, compare the
  `h1` number with the query (exact for 11 digits, last-7 for 7 digits); mismatch → not found;
  `00000000000` → not found.

### 3.3 Not-found / empty

- Unknown part: `<div class="error vs2">The specified part 11426666661 was not found.</div>`.
- Empty `q`: same div with literal `{0}`.
- `partsearch` miss: `<div class="partSearchResults">The specified part was not found.</div>` (part header
  and supersession still shown).
- `series=` not containing the part, or a part with no vehicles → "no vehicles" template: `<title>` says
  "`<desc> <pn> - Discontinued BMW Part`" **even for current parts**; `partSearchResults` contains only
  `h4.vs2` "Search for another part". **Never infer discontinued from the title.**

### 3.4 Part header

```html
<h1>
    11427953129</h1>                                  <!-- current: number only -->
<h1>11427541827 - Set oil-filter element</h1>          <!-- no-vehicles template: number - description -->
<h1>11427566327<a class="partphoto" href="/bmw/photos/11427566327" rel="lightbox"></a></h1>
<h3>BOSCH ZGR6STE2</h3>                                <!-- optional supplier ref -->
<dl><dt>From:</dt><dd>09/01/2004</dd><dt>To:</dt><dd>03/17/2006 (ENDED)</dd>
    <dt>Weight:</dt><dd>0.047 kg</dd></dl>             <!-- To "-" = current -->
```

- Selectors: `div.content > h1` (first text node = number), following `h3` (supplier), first `dl`.
- Dates: `MM/DD/YYYY`. "(ENDED)" marks an ended part.
- Weight can be nonsense (spark plug 44.650 kg); pass through as-is.
- **Description of a current part on partxref** exists only in affiliate markup
  `a.ecs-tuning-button[data-ecs-part-name]`. Fallbacks: text of a supersession link naming this part →
  `partsearch` `h2` → `part?id=` `h1`.

### 3.5 Supersession blocks (xref, part, partsearch)

```html
<div class="superseded"><h3>Superseded by:</h3><dl>
  <dt class="sup-by-{$t.count}">
    <a href="part?id=EH31-EUR-02-2004-E63-BMW-630i&amp;q=11427953129">11427953129 - Set oil-filter element</a></dt>
  <dd>(06/01/2017 &mdash; ), Exchangeable retrospectively</dd>
</dl></div>
<div class="supersedes"><h3>Supersedes:</h3><dl>
  <dt><a href="partxref?q=11427541827">11427541827 - Set oil-filter element</a></dt>
  <dd>(09/01/2004 &mdash; 03/17/2006)</dd></dl></div>
```

- `dt a` text = `<pn> - <desc>`; `dd` = `(<from> — <to or empty>)[, <remark>]`. On partsearch the `dd`
  contains newlines before the comma → normalize whitespace.
- Link `part?...` = still in some catalog; `partxref?q=` = not.
- Lists are **transitively closed**: 11427541827 lists all three successors (11427566327, 11428683196,
  11427953129); the current part lists all predecessors.
- Open end date = current successor. Intermediates can be short-lived (11428683196 valid 09/2016–09/2017,
  Motorsport only), so prefer open-ended over "latest start".
- Only remark observed: "Exchangeable retrospectively".

### 3.6 Series list (plain xref)

```html
<div class="partSearchResults">Part 11427953129 was found on the following vehicles:
<ul><li><a href="/bmw/enUS/partxref?q=11427953129&amp;series=E90N">BMW 3 Series E90 LCI (07/2007–12/2011)</a></li>
```

- Series code from the href `series=` param. Label: `BMW <name> <code> (MM/YYYY–MM/YYYY)` (en-dash).
- "BMW" prefix even for MINI ("BMW MINI R56"), RR ("BMW Ghost RR4"), motorcycles ("BMW K25 (R 1200 GS)",
  old bikes padded: "BMW R 24         -50"). Motorsport `MOSP` with empty "(–)".
- Oil filter 11427953129 is on ~70 series.

### 3.7 Model list (xref with `series=`)

```html
<li>3 Series E90, 325i, Sedan, N52, USA, (VB13) :
    <a href="/bmw/enUS/showparts?id=VB13-USA-02_2004_E90_BMW_325i&amp;diagId=11_3867#11427953129">Lubrication system-Oil filter</a></li>
<li>Ghost RR4, Ghost, Sedan, N74R, AUTO, EUR, (FK41) : ...
<li>K25 (R 1200 GS), R 1200 GS 04 (0307,0317), N/A, , EUR, (0307) : ...
```

- One row per (type code × diagram); E90 example: 114 rows in both captured variants (an early count of
  140 was wrong). Not paginated.
- Field counts vary (RR adds transmission; motorcycles have blanks and commas in names) → **parse the
  href id**, and take the text prefix before ` :` only for display.
- No production end dates at model level.

### 3.8 partsearch (fitment)

- `h1` number, `h2` description, `dl` with `<dt>Price:</dt><dd>$12.25</dd>` (often empty), supersession.
- Hits: `div.partSearchResults > div.diagram` →
  `<div class="diag-info">Part 11427953129 was found on diagram: <a href="/bmw/enUS/showparts?id=..&diagId=02_0092#11427953129">...</a>`.
  **The hit names the part number actually used on the car**, which may differ from `q` (supersession
  resolved: querying predecessor 11427566327 on VB13 → hit names 11427953129).
- Also `<a href=".../partxref?id=..&q=..">Other models with this part</a>`.

---

## 4. VIN decode (feature B)

### 4.1 Flow

- `GET select?vin=<last7>` → HTTP 200, no redirect: the normal select page with every cascade level
  pre-selected plus the "Browse Parts" form carrying the vehicle id.
- Input: case-insensitive; a full 17-char VIN works (server uses last 7).
- **Miss** (`ZZZZZZZ`, 6-char `PX2277`): 200, empty select page, `<div id="selectResults">` empty, **no
  error message**. Detect: no `#selectResults input[name=id]`.
- **No disambiguation ever shown**: server silently picks one (`1234567` → E30 325e EUR 11/1986). Check
  digit never validated.
- "Browse Parts" → `GET partgrp?id=<vid>&vin=<last7>` sets cookie `pvin=PX22770.WL13` (8 h, path
  `/bmw/enUS/partgrp`). **VIN does not filter parts**; it only adds a production-stats card.
- `GET production?vin=<last7|17>`: explicit error `<div id="ps-vin-result" class="ps-vin-error">No
  production record found for serial ZZZZZZZ</div>`.

### 4.2 Selected levels (v2)

```html
<div class="ro-lb-label">Engine:</div>
<div class="ro-listbox-card ro-lb-plain" data-ro-gate="filter" data-ro-level="engine"><ul class="ro-listbox">
 <li><a class="ro-lb-row is-selected" href="/bmw/enUS/select?product=P&amp;archive=0&amp;series=E93&amp;body=Cab&amp;model=328i&amp;market=USA&amp;prod=20080700&amp;engine=N52N" aria-current="true">N52N</a></li>
```

Selector `[data-ro-level=X] a.ro-lb-row.is-selected`: label = link text; code = that level's query param
in the href.

| `data-ro-level` | param | example |
|---|---|---|
| product | `product` P/M | Car |
| catalog | `archive` 0 current / 1 classic | Current |
| series | `series` | `3' E93 (2005 — 2010)` / E93 |
| body | `body` (Lim, HC, Cab, Cou, com, tou, 2-T) | Convertible / Cab |
| model | `model` | 328i |
| market | `market` | USA |
| prod | `prod` `YYYYMM00` | 07/2008 / 20080700 |
| engine | `engine` | N52N |
| steering | `steering` L/R | Classic cars; EUR when both exist |
| trans | `trans` M/A | Classic cars only |

### 4.3 Result block

```html
<div id="selectResults"><div class="searchResults">
 <span class="searchResults-label">You Have Selected:</span> <strong class="searchResults-value">3 Series E93 BMW 328i</strong>
 <span class="searchResults-label">Type Code:</span> <strong class="searchResults-value">WL13</strong>
 <form action="/bmw/enUS/partgrp" target="_top">
  <input type="hidden" name="id" value="WL13-USA-07-2008-E93-BMW-328i" />
  <input type="hidden" name="vin" value="PX22770" />
```

`#selectForm[data-ro-kvp]` (e.g. `a,car,e93,328i,cab,n52n,usa,2008,,enus,select,v2`) is ad-targeting;
sanity checks only.

### 4.4 Production data

- `production?vin=` match: `#ps-vin-result .ps-vin-match` with `span.ps-vin-car` ("BMW E93 328i"),
  `span.ps-vin-meta` ("— type WL13, USA, engine N52N — built <strong>July 2008</strong>"), second
  `div.ps-vin-meta` with sequence numbers ("VIN 321 of 547 built that month", "12,557 of 17,781 across
  all WL13 production"). No vehicle id.
- Same data on partgrp (with VIN): `div.prod-stats .ps-card` `.ps-meta`, `.ps-built`, `.ps-fact-label`.

### 4.5 Not available from RealOEM

Per-VIN SA/option codes, paint, upholstery, model year, transmission (modern cars), full VIN.
`/options` is an Option Code Explorer per series/code, **not** a VIN build sheet (`?vin=` ignored).

### 4.6 Brand results observed

| | serial | result |
|---|---|---|
| BMW | PX22770 | E93 328i Cab USA 07/2008 N52N WL13, current |
| MINI | TD86476 | Classic catalog, "MINI R53", HC "3 doors", Cooper S, USA 04/2004, W11, RE33; id brand `Mini` |
| Rolls-Royce | UX52589 | "Rolls-Royce Ghost RR4", Lim, Ghost, USA 12/2013, N74R, FK43; id brand `Rolls_Royce` |
| Motorrad | Z656595 | product M, "K50 (R 1200 GS, R 1250 GS)", "R 1200 GS 17 (0A51, 0A61)", USA 09/2017, 0A61; no body (`body=ohne` hidden) / engine level |
| Classic E30 | 1234567 | adds Steering + Transmission levels |

WMI prefixes for sanity checks (first 3 chars of a 17-char VIN): BMW cars `WBA`, `WBS` (M), `WBY` (i),
US-built `5UX`, `5YM`, `4US`; MINI `WMW`, `WMZ`; Rolls-Royce `SCA`; Motorrad `WB1`, `WB3` (verify list
during implementation).

---

## 5. Vehicle selection and diagrams (feature C)

### 5.1 Select cascade

Order: `product` → `archive` → `series` → `body` → `model` → `market` → `prod` → `engine` → `steering`
(+ `trans` for Classic). Each step is a plain GET link adding one param.

- `product`: `P` cars (BMW, MINI, RR, Zinoro, i, Motorsport), `M` Motorrad.
- `archive`: `0` Current, `1` Classic (E21, E30, E36, E46, E39, E38, E31, Z3, E85/86, MINI R50/R52/R53,
  Isetta...).
- `series` codes are opaque — read from hrefs, never labels (label "K25" → `K25`, `K255`, `K25H`; RR LCI
  `R11N`, `R21N`; LCI `E90N`).
- `body` mixed case: `Lim`, `HC`, `Cab`, `Cou`, `com`, `tou`. Motorcycles: none (`ohne`).
- `model` may contain spaces, dots, parentheses, commas (`Coop.S JCW`, `R 1250 GS 19 (0J91, 0J93)`).
  Hrefs are unencoded.
- `market`: `USA`, `EUR`, `CHN`, `IDN`, `IND`, `MYS`, `RUS`, `THA`...
- `prod`: `YYYYMM00`, grouped under `<li class="ro-lb-group">2005</li>`.
- **Auto-selection**: any level with a single option (and USA under enUS) comes back `is-selected`
  without being in the URL. Always read `.is-selected` for effective state.
- Complete → `#selectResults input[name=id]` + `strong.searchResults-value` type code.
- Examples: `select?product=P&archive=0&series=E90` (body auto Lim, model list);
  `...&body=Lim&model=325i` (market auto USA, prod list); `...&market=USA&prod=20051000` (engine auto,
  id shown); `...&market=EUR&prod=20051000` → steering list.
- Classic E46 has five bodies.

### 5.2 Main groups: `partgrp?id=<vid>`

```html
<div class="blk partgrp-grid"><div class="mg-thumb">
  <a href="/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i&amp;mg=11">
    <span class="grp-badge">11</span><div class="image"><span><img src="/bmw/images/group_11-00-P.jpg" width="112" height="79" alt="ENGINE"></span></div>
    <h3 class="title">ENGINE</h3>
```

- Parse `.mg-thumb a[href*="mg="]`: mg from href, name from `img[alt]`. JSON-LD
  `CollectionPage.mainEntity.itemListElement[]` has `{url, name}` (cleaner alternative).
- Specs: `.vehicle-specs dl` → Model, Body, Engine, Production, Steering, Market (+ Transmission on RR;
  motorcycle Body `N/A`, no Engine/Steering).
- Not filtered by transmission (E90 lists 23 MANUAL, 24 AUTOMATIC, 28 DUAL-CLUTCH).
- RR adds `92 BESPOKE`, `83`. Motorrad group names differ; icons `-M.jpg` vs `-P.jpg`.

### 5.3 Diagram list: `partgrp?id=<vid>&mg=<NN>` (identical v1/v2)

```html
<div class="diagThumbs"><h2>Select a diagram:</h2>
  <a name="10"><h3 class="diag-hdr">Engine Housing</h3></a>
  <div class="diag-thumb">
    <a href="/bmw/enUS/showparts?id=VB13-USA-10-2005-E90-BMW-325i&amp;diagId=11_3731">
      <div class="image"><span><img src="/bmw/images/thumb_311u.jpg" alt="ENGINE BLOCK diagram for BMW 3 Series E90 325i"></span></div>
      <div class="title">ENGINE BLOCK</div>
```

- Walk children in order: `a[name]` = subgroup code, `h3.diag-hdr` = subgroup name, following
  `.diag-thumb` belong to it. `diagId` = `{mg}_{internal}`. Titles repeat (two "OIL PAN": 11_3733,
  11_3834) → key on diagId. JSON-LD ItemList with `numberOfItems`.
- Motorrad names printed twice ("Engine / Running Gear Engine / Running Gear") → dedupe "X X" → "X".

### 5.4 Parts list: `showparts?id=<vid>&diagId=<mg_nnnn>` (data identical v1/v2)

- Image: `<div id="partsimg">...<img src="/bmw/images/diag_2zas.jpg" width="640" height="448" alt="Oil Pan" /></div>`.
  Thumb `thumb_{code}.jpg` ↔ full `diag_{code}.jpg`. Actual JPEG 799×559.
- Hotspots: inline `var partsimgmap=[["01",78,255,87,271],["02",85,70,94,87],...];` — `[pos,x1,y1,x2,y2]`
  in 640×448 display space (scale ×799/640, ×559/448 to image pixels). Multiple boxes per position.
- Table `table#partsList[data-partlink="/bmw/enUS/partsearch?id=…&diagId=…&q="]`, header `tr.r0 > th`.
- **Part rows**: 11 `td`s, `tr.pos{NN}` (striped r0/r1): 0 pos, 1 description (`edge1..3` indent; none on
  motorcycles), 2 supplement, 3 qty, 4 from (`MM/YYYY`), 5 up to, 6 part number, 7 price (`td.price`, may
  be empty), 8 photo (`td.aphoto a[href=/bmw/photos/<pn>]` when present), 9 notes (`td.notes-cell`, e.g.
  `+core`), 10 ECS affiliate (ignore).
- **Condition rows**: first `td` empty, then description-cell text (e.g. `<b>For vehicles with</b><br/>
  Automatic transmission`), then a cell with `a.opt-code` (`S205A`) + `=Yes`, then `colspan="8"`. Apply to
  following part row(s) with the same `posNN`. Other texts: "Required for repair", "only in conjunction
  with", "Attention!...".
- Reference number may be `--` (accessories).
- Notes legend: `<div class="notes">Notes<ul><li>+core = plus core charge …</li>`.
- **Filtered by production month**: same diagId at 10/2005 shows pos 10 ("Up To 04/2006"), at 08/2006
  omits it. Not market-specific for the sampled diagram. diagIds are not validated per vehicle.
- Motorrad: German supplements (`SILBER`) even under enUS; fewer prices.
- Other: `nav.breadcrumb-nav`, JSON-LD `BreadcrumbList`/`ImageObject`, `section.see-also`.

### 5.5 Vehicles index (feature F6)

Researched 2026-09-30 (15 requests, honest UA; raw pages in `.research-raw/vehicles/`).

- `/bmw/enUS/vehicles`: 8218 vehicles, 165 pages of 50. Params: `page=N`, `sort=year|type` (default =
  curated series order), `series=<family>` (1'–8', M, X, Z, i, C, F, G, K, R; overlapping UI shortcuts,
  not a partition — Isetta/700/Veteranen are in none). Params combine (`?series=K&sort=year`).
- Rows: `table#vi-table > tbody > tr.r0|tr.r1`, 50 per page, 6 cells `td.vi-col-{series|model|type|body|prod|market}`.
  - series: display label (`3 Series F30`, `MINI Clubman R55 LCI`, `Phantom RR11 LCI`, `R 24         -50`
    — keep verbatim, collapse whitespace for display).
  - model: `a[href^="/bmw/enUS/partgrp?id="]`, text `{Brand}&nbsp;{Model}` (Brand ∈ BMW, Mini,
    Rolls-Royce, Zinoro). Href id is unencoded and may contain `ã`, `,`, `'`.
  - type, body (`N/A` for motorcycles and A-codes), prod `MM/YYYY&ndash;MM/YYYY` or empty, market.
  - Link id's `MM-YYYY` = prod start; its type/market = the cells; 5th field = series code.
  - **51 rows have no link**, and exactly those rows have an empty prod cell (market variants, some
    Motorsport, A-codes).
  - No open-ended ranges: current vehicles end near the catalog date (latest end 04/2025 vs catalog
    03/2025), so end dates are likely rewritten each catalog release.
- Motorcycles: type code starts with `0` (all such rows have body `N/A`). A-codes (`9xxx`, `9Xxx`) are
  unclassified (treated as BMW).
- Total count: second `<strong>` in `#vi-result-bar > span:first-child` ("Showing 8201–8218 of 8218
  vehicles"). Last page link `#vi-pagination a[title="Last page"]`; absent on the last page
  (`span.vi-pg-current`); no `#vi-pagination` when one page suffices.
- **`sort=year` = ascending production start**, the 51 blank-start rows first (page 1 + first row of
  page 2), latest start (03/2025) on page 165. Ties: model name, then market, then type (best guess).
  **No descending option** (`dir=desc`, `order=desc`, `sort=-year` ignored).
- New vehicles with recent starts land on the last page(s) of `sort=year`. Not detectable by tail-only
  scans: back-dated inserts, blank rows gaining dates, end-date changes.
- Row key: `{type}-{market}-{MM}-{YYYY}` (unlinked: `{type}-{market}--`); unique in sample.
- Headers: `Cache-Control: no-cache, no-store`; ~12–13 KB per page with compression.
- **Policy:** building the committed baseline (165 pages, once, by the maintainer script) was explicitly
  approved by the project owner on 2026-09-30 (PRD F6); runtime updates are incremental only.

### 5.6 Request counts

- Cold (cascade → parts list): 6–8 requests. From known vehicle id: 2 (mg page, showparts). From cached
  diagId: 1.
- Everything but prices is immutable until the next catalog release.

---

## 6. Open questions

- Other supersession remarks (e.g. "Not exchangeable", kits with quantities) not observed.
- Behavior when two parts share the same last-7 digits.
- Whether `/bmw/de/select` defaults to EUR.
- Whether a transmission cascade step exists for modern cars (none seen).
- Rolls-Royce showparts not fetched (structure presumed identical).
- Whether notes are member-only for some rows.
