---
name: fitment
description: Check whether a BMW, MINI, Rolls-Royce or BMW Motorrad part number fits a specific vehicle, and compare the parts two vehicles use, with RealOEM. Use when the user asks "does part X fit my car / VIN ...", "will this E90 part fit my E92", "which number does my car use", "what parts do these two cars share", or wants the differences between two vehicles in one area such as the oil pan or the brakes.
---

# Fitment and comparison

Answers "does this part fit this car?" with `check_fitment` and "what do these two vehicles share
in one area?" with `compare_vehicles`, both from the `realoem` MCP server. Never fetch RealOEM
pages directly (no web fetch or browser); every request goes through the realoem tools, which
rate-limit, cache and parse RealOEM for you.

## Does part X fit my car?

1. Get the car's vehicle id:
   - From a VIN: call `decode_vin` and use `vehicle.vehicle_id`. It carries the car's own
     production month, which is what fitment needs.
   - Without a VIN: `select_vehicle`, walking the cascade down to the production month.
   - RealOEM treats ids from `lookup_part` rows as undated (and `find_vehicle` ids carry the
     production-start month, likewise not the car's build month), so results for them are not
     narrowed to a build month and fitment can be wrong in either direction. For a specific car,
     use `decode_vin` or `select_vehicle` ids.
2. Call `check_fitment(part_number=..., vehicle_id=...)` with the number as the user wrote it
   (11 digits or the last 7; spaces, dashes and dots are fine). One request, none when cached.
3. Read the result:
   - `fits` true: name the `diagrams` (name and `url`) where the part appears on that car.
   - `used_part_numbers` differs from `query`: RealOEM resolved a supersession. The car's
     diagrams show the newer number, so say "11427566327 was replaced; this car uses
     11427953129" and show `superseded_by` with dates and remarks. The newer number is the one
     RealOEM lists for this car.
   - `fits` false: RealOEM knows the part but not on this vehicle. Say "not listed for this
     vehicle", not "does not exist". Offer `lookup_part` to see which vehicles do use it.
   - An error saying RealOEM does not know the part or the vehicle: ask the user to check the
     number or the vehicle; do not guess digits.
4. Mention `price_usd` only when present ("RealOEM lists $12.25").

## Which vehicles use part X?

That is a part lookup, not fitment: call `lookup_part` (and `lookup_part` with `series` for the
models of one series). Use `check_fitment` only when the user names one vehicle.

## Compare two vehicles

1. Get both vehicle ids as above.
2. Pick one main group (e.g. `11` engine, `34` brakes), and a subgroup when the question is
   narrower: call `list_part_groups` / `list_diagrams` first if you need the codes. Never compare
   whole vehicles: one main group can hold 20 to 50 diagrams, each one request.
3. Call `compare_vehicles(vehicle_a=..., vehicle_b=..., main_group=..., subgroup=...,
   diag_ids=...)`. `subgroup` and `diag_ids` narrow the scope (both given: only the listed
   diagrams inside that subgroup). The diagrams do not have to match: the comparison is by part
   number over every in-scope diagram of each vehicle, so pass diagram ids of both cars in
   `diag_ids` (e.g. the E90 oil pan and the R56 oil pan); ids a vehicle does not have come back
   in `ignored_diag_ids_a` / `ignored_diag_ids_b`.
4. Present `in_both` (shared part numbers; `qty_a` / `qty_b` list the quantity of each
   occurrence, so a quantity difference such as 1 versus 1 + 1 is visible), `only_a` and
   `only_b` (with the diagrams they appear on). Rows without a part number are left out.
5. Budget: `max_requests` (default 20, 2 to 60) caps requests to RealOEM; cached pages are free.
   The two diagram lists come first, then the diagrams alternating between the vehicles. If
   `complete` is false, the result is partial: `unfetched_a` / `unfetched_b` list the diagrams
   that were not read, and parts from those diagrams may be missing or show up as "only" on the
   other vehicle. Say so, and offer to continue: calling again with the same arguments continues
   from the cache and only fetches what is missing (or narrow the scope, or raise
   `max_requests`).

## Rules

- Always cite RealOEM: include the `source_urls` of every result you used and link diagram
  `url`s.
- RealOEM lists factory parts per vehicle; it cannot say whether a part physically fits a car it
  is not listed for, and it does not know a car's options (check condition rows with
  `get_diagram_parts` when options matter).
- If a tool reports that a RealOEM page "did not have the expected structure", retry once with
  `refresh=true`; if it fails again, tell the user the plugin needs an update and give the URL.
- Results are cached; pass `refresh=true` only when the user asks for fresh data.
- Brand notes are in `brands/<brand>/README.md` of this plugin.
