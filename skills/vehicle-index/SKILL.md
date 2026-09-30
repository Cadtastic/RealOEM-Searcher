---
name: vehicle-index
description: Find a BMW, MINI, Rolls-Royce or BMW Motorrad vehicle in RealOEM's catalog by name, series, year, market or type code without clicking through the model cascade. Use when the user names a vehicle ("find a 2019 R 1250 GS", "E90 325i USA", "which markets had the MINI R56 Cooper S", "vehicles with type code VB13"), needs a vehicle id for parts diagrams, or asks to update the vehicle list.
---

# Vehicle index

A local list of every vehicle in RealOEM's vehicles index (about 8,200), shipped with the plugin
and stored on this computer. Searching it is free: `find_vehicle` never contacts RealOEM.

## Steps

1. Call `find_vehicle` first. Put the words the user used in `query` (series code, model, type
   code: `"E90 325i"`, `"R 1250 GS"`, `"VB13"`); all words must match. Narrow with `brand`
   (`bmw`, `mini`, `rolls-royce`, `motorrad`), `series` (e.g. `E90`), `year` (in production that
   year), `market` (e.g. `USA`, `EUR`) or `type_code`. Raise `limit` (up to 100) only when the
   user wants a long list; `total_matches` tells how many there are.
2. If nothing matches, retry once with fewer or different words (e.g. only the series code, or
   the model without the body style).
3. Still not found, or the user asks to update the vehicle list: call `update_vehicle_index`, then
   call `find_vehicle` again with the same arguments.
   - `up_to_date`: RealOEM has no vehicles the index lacks; the vehicle is not in RealOEM under
     those words.
   - `updated`: new vehicles were added (`added`); search again.
   - `partial`: the page limit (`max_pages`, default 5) stopped the update; the vehicles found so
     far were added. Search again; if the vehicle is still missing, call `update_vehicle_index`
     again (with a larger `max_pages`, up to 10, when `added` was empty). It continues where the
     previous call stopped.
   - `drift`: RealOEM changed older entries. Report the `message`: the maintainer should rebuild
     the index. The vehicles found so far were still added.
   Call `update_vehicle_index` at most once per conversation unless it returned `partial` or the
   user asks again.
   If `index.built_at` is null, no vehicle index baseline is installed: `update_vehicle_index`
   then returns `drift` without contacting RealOEM. Say the vehicle list is not installed yet and
   find the vehicle with `select_vehicle` (the model cascade) or `decode_vin` instead.
4. Several matches: show a short table (model, series, body, market, production range, vehicle
   id) and ask which one the user means, or pick by the user's market and year.

## Explaining the results

- **Vehicle ids carry the production START month** of that model (`VB13-USA-10-2005-...` means
  production started 10/2005), not the build month of the user's car. RealOEM filters parts lists
  by the month in the id. For a specific car's build month, use `select_vehicle` with `prod`
  (month `YYYYMM00`) or `decode_vin` with the car's VIN.
- **End dates are "as of `built_at`"**: for vehicles still in production RealOEM rewrites the end
  date with each catalog release, so say "production 03/2025 - 04/2025 (as of <index.built_at>)"
  and do not claim the model ended then.
- Link each vehicle to RealOEM as
  `https://www.realoem.com/bmw/enUS/partgrp?id=<url-encoded vehicle_id>` (or use the
  `source_urls` of `list_part_groups` once you have called it).
- `model` in `vehicle` comes from the vehicle id (underscores for spaces); prefer `model_name`
  for display.
- Rows without a vehicle id (only with `include_unlinked=true`) cannot be opened in RealOEM's
  parts catalog; say so if the user asks about one.

## Next steps

`find_vehicle` results feed the diagram tools: pass `vehicle.vehicle_id` to
`list_part_groups(vehicle_id)` to list the vehicle's main groups, then `list_diagrams` and
`get_diagram_parts`. For fitment on the user's own car, prefer a `decode_vin` or `select_vehicle`
id; a `find_vehicle` id answers for the model's production start.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Never try to download the whole vehicle list; `update_vehicle_index` only adds new vehicles,
  and a full rebuild is a maintainer task (`scripts/rebuild_vehicle_index.py`).
- Brand notes: `brands/<brand>/README.md`.
