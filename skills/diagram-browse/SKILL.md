---
name: diagram-browse
description: Browse RealOEM parts diagrams for a BMW, MINI, Rolls-Royce or BMW Motorrad vehicle. Use when the user asks "show me the parts diagram for ...", "what parts are in the oil pan / brakes / rear axle of my car", "list the parts groups", "which bolts hold ...", or wants to pick a vehicle by series, model, market and production month.
---

# Diagram browsing

Walks RealOEM's catalog the way its website does: vehicle -> main groups -> diagrams -> parts
list with the exploded-view image. Every step is one request and is cached for 30 days.

## 1. Get a vehicle id

- The user has a VIN: call `decode_vin` and use its `vehicle.vehicle_id`. It carries the car's
  own production month.
- If the `find_vehicle` tool is available, try it first to get a vehicle id without walking the
  cascade; its ids carry the vehicle's production-start month, so for a specific build month
  still use `select_vehicle` with `prod` (or `decode_vin`).
- Otherwise walk the cascade with `select_vehicle`, one level per call:
  1. Call it with `product` only (`P` cars, including MINI and Rolls-Royce; `M` motorcycles).
  2. Show the user `options` for `next_level` (their `label`s) and let them choose.
  3. Call again with every value from `selected` plus the chosen option's `value` for
     `next_level`. The parameter for the level `catalog` is `archive` (`0` current, `1`
     classic, for older models such as E30, E36, E46 and MINI R50/R53); every other level name
     is its own parameter. Production months are `YYYYMM00` codes such as `20051000`.
  4. Levels with a single option (and the USA market) are auto-selected: they appear in
     `selected` without a question to the user.
  5. Repeat until `complete` is true; then use `vehicle.vehicle_id`.
  If a value you sent is missing from `selected`, RealOEM did not accept it: offer `options`
  again.
- Ids from `lookup_part` rows carry a nominal production date: their date is only nominal;
  RealOEM treats the `_` form as undated (`VB13-USA---…`), so the list is not narrowed to a build
  month (undated ids are not date-filtered to a build month). Every other id's parts lists are
  filtered by its production month, so for a specific car prefer an id from `decode_vin` or
  `select_vehicle`.

## 2. Main groups

Call `list_part_groups` with the vehicle id. It returns the vehicle's `specs` and
`main_groups`. BMW main group numbers are stable across models, so you can often go straight to
`list_diagrams`:

| mg | Main group |
|---|---|
| 11 | Engine |
| 12 | Engine electrical system |
| 13 | Fuel preparation system |
| 17 | Radiator (cooling) |
| 18 | Exhaust system |
| 21 | Clutch |
| 23 / 24 | Manual / automatic transmission |
| 31 | Front axle |
| 32 | Steering |
| 33 | Rear axle |
| 34 | Brakes |
| 51 | Vehicle trim |
| 61 | Vehicle electrical system |
| 64 | Heater and air conditioning |

Not every vehicle has every group (motorcycles use their own names, e.g. 17 Cooling), and the
list is not filtered by transmission. If `list_diagrams` says the vehicle has no such main
group, call `list_part_groups`.

## 3. Diagrams

Call `list_diagrams` with the vehicle id and the two-digit `main_group`. Diagrams come grouped
by subgroup. Titles can repeat (two "OIL PAN" diagrams), so refer to a diagram by its `diag_id`
and show the user its name and subgroup.

## 4. Parts list

Call `get_diagram_parts` with the vehicle id and the `diag_id`. Present the rows as a table:
position, description, supplement, quantity, part number, price (USD, when shown) and notes.

- **Condition rows**: a row's `conditions` say when it applies, e.g. "For vehicles with
  Automatic transmission" with option code `S205A` = `Yes`: that part is only for vehicles with
  that factory option (SA code). Several rows with the same position are alternatives; use the
  conditions and dates to tell them apart. RealOEM cannot tell which options a car has.
- `valid_from` / `valid_to` give production-date limits. RealOEM already filters the list by
  the vehicle id's production month, which is why a part can be missing for another month
  (production-date filtering).
- `position` `--` marks accessories without a callout on the image (e.g. sealant "Required
  for repair"). `notes` codes such as `+core` are explained in `notes_legend`.
- The image is `image_url`. `hotspots` are boxes per position in display space: the same
  pixel space as `image_width` x `image_height` (e.g. 640 x 448), not the JPEG's own size.
- A `diag_id` from another vehicle still returns a list (RealOEM does not check it), filtered
  by this vehicle's date. Use diag_ids from this vehicle's `list_diagrams`.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Always cite the `source_urls` of the results you used, and link `diagram.url` for a diagram.
- Do not repeat calls you already made in this conversation; results are cached anyway.
- Use `refresh=true` only when the user says the data looks out of date.
- Brand notes: `brands/<brand>/README.md`.
