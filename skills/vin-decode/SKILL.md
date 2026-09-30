---
name: vin-decode
description: Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM. Use when the user gives a VIN (all 17 characters or the last 7) or asks "decode my VIN", "what car is this VIN", "what engine / build date does VIN ... have", or wants parts for their own car identified by its VIN.
---

# VIN decode

Turns a VIN into the vehicle RealOEM has on file for it (series, model, body, engine, market,
production month, type code) and a vehicle id that the other RealOEM tools accept.

## Steps

1. Call `decode_vin` with the VIN as the user gave it: all 17 characters or just the last 7.
   Spaces, dashes and dots are fine, and case does not matter. The server sends only the last 7
   characters to RealOEM.
   - Add `include_production=true` only when the user asks when the vehicle was built or how many
     were made; it costs one more request. If RealOEM's production page cannot be read, the whole
     call fails; call `decode_vin` again without `include_production` to still get the vehicle.
   - Use `refresh=true` only if the user says the answer looks out of date (found VINs are
     cached for 180 days, not-found results for 1 day).
2. If the tool returns an error about the input, show it and ask for the VIN again. VINs never
   contain the letters I, O or Q; a "0" or "1" typed as a letter is the usual mistake.
3. `status` is `not_found`: RealOEM has no vehicle for that serial. Ask the user to check the last 7
   characters, or to identify the vehicle by model instead.
4. `status` is `found`: present the result as described below.

## Presenting the result

- Call it **RealOEM's best match** for the serial. RealOEM matches only the last 7 characters and
  silently picks one vehicle; it never offers alternatives.
- If `confidence` is `low`, say so first: the VIN's manufacturer prefix belongs to a different
  brand than the decoded vehicle, so the match is probably a different vehicle with the same last
  7 characters. Ask the user to double-check the VIN.
- Show every entry of `warnings`.
- Show: brand (`vehicle.brand`), `series_name`, model (`vehicle.model`, which comes from the
  vehicle id: show its underscores as spaces, e.g. `Cooper_S` as "Cooper S"), `body`, `engine`,
  `vehicle.market`, production month (`vehicle.production_month`), `steering` and `transmission`
  when present, `vehicle.type_code`, catalog (`classic` = RealOEM's Classic catalog for older
  vehicles) and `vehicle.vehicle_id`.
- Motorcycles have no body or engine in RealOEM; `product` is `motorcycle`.
- With `production`: built month, "number N of M built that month" (`seq_in_month` /
  `total_in_month`) and "number N of M of this type code" (`seq_in_type` / `total_in_type`).
- Link the pages in `source_urls`.

## What RealOEM cannot tell you

RealOEM does not have option codes (SA codes), paint, upholstery, model year or the factory build
sheet for a VIN, and it shows a transmission only for Classic-catalog cars. Say so plainly instead
of guessing, and suggest a BMW dealer or a dedicated VIN decoder for option codes.

## Next steps

Use `vehicle.vehicle_id` from this result with the other RealOEM tools:

- Parts diagrams for this vehicle: `list_part_groups` with the vehicle id.
- Does a part fit this vehicle: `check_fitment` with the part number and the vehicle id.

Prefer this vehicle id over ids from `lookup_part` rows or `find_vehicle`: it carries the
vehicle's own production month, and RealOEM filters parts lists by that month.

## Rules

- Never fetch RealOEM pages directly (no web fetch or browser); use only the realoem tools.
- Do not call `decode_vin` again for a VIN you already decoded in this conversation.
- Brand notes: `brands/<brand>/README.md`.
