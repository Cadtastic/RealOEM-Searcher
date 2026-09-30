---
name: part-lookup
description: Look up BMW, MINI, Rolls-Royce and BMW Motorrad OEM part numbers on RealOEM. Use whenever the user mentions a BMW Group part number (11 digits such as 11427953129 or 11 42 7 953 129, or the 7-digit short form 7953129) or asks what a part is, what it fits or which models use it, whether a part is current, discontinued or superseded, or what replaced it (its replacement).
---

# Part lookup

Answer questions about a BMW Group part number with the `lookup_part` tool of the `realoem` MCP
server. Never fetch realoem.com yourself (no WebFetch, no browser): every request must go through the
MCP tools, which rate-limit, cache and parse RealOEM for you.

## When to use

- The user gives a part number: "What is 11427953129?", "Is 11427541827 still current?",
  "What replaced 12120034087?", "Which cars use 11 42 7 566 327?".
- The user asks what fits or which models use a part they already identified.
- For "does part X fit my car" with a specific vehicle or VIN, use `check_fitment` (fitment
  skill); `lookup_part` lists series and vehicles, not one car's build.

## Steps

1. Call `lookup_part(part_number=...)` with the number as the user wrote it. Spaces, dashes and dots
   are fine; 11 digits or the last 7 digits are accepted. If the tool reports that the input is not
   a BMW part number, ask the user to check the number; do not guess digits.
2. Read `status`:
   - `current`: RealOEM does not mark the part ENDED and lists no successor.
   - `ended`: RealOEM marks the part ENDED or lists a successor. Say so and show `superseded_by`.
   - `not_found`: RealOEM does not know this number. The tool already rejects RealOEM's
     last-7-digit false matches and its junk part `00000000000`, so report "not found" and ask the
     user to double-check the number.
3. Present the part: `part_number`, `description` (may be missing; say "no description on
   RealOEM"), `supplier_ref` when present (e.g. "BOSCH ZGR6STE2"), `valid_from`/`valid_to`, and
   `weight_kg` as "RealOEM lists …" (RealOEM weights are sometimes nonsense).
4. Group `part.series` by `brand` (bmw, mini, rolls-royce, motorrad) and list each series with its
   `name`, `code` and production range. For long lists summarize per brand and model family.
5. Offer series narrowing: "Want the exact models for a series?" Check the series code (e.g. E90,
   E90N) in `part.series` before narrowing. If the user picks one, call
   `lookup_part(part_number=..., series=<code>)` with the `code` from the result (e.g. `E90N`, not
   the label "E90 LCI"). The result's `part.models` lists one row per vehicle type and diagram with
   `vehicle` (vehicle id, type code, market, model), `body`, `engine` and `diagram` (name and
   RealOEM link). Group rows by vehicle and list the diagrams under each. `vehicle.model` is in
   RealOEM's id form (`R_1200_GS_04_0307,0317_`); show it with underscores as spaces. An empty
   `part.models` means RealOEM lists no vehicle of that series using the part: say "not listed
   for <series>", not "not found".
6. Supersession: `superseded_by` lists every successor with dates and remarks (the list is already
   transitive). The successor with an empty `valid_to` is the current replacement; intermediates can
   be short-lived. "Exchangeable retrospectively" means the new part also fits older vehicles.
   `supersedes` lists earlier numbers. Use `trace_supersession` for the full chain with dates; look
   up the open-ended successor with `lookup_part` if the user wants its details.

## Rules

- Always cite RealOEM: include the `source_urls` of every result you used, and diagram links from
  `diagram.url` when you mention a diagram.
- Never call a part discontinued because of a page title; only `status` and `superseded_by` count.
- Vehicle ids in `part.models` rows carry a nominal date that RealOEM ignores (it treats them as
  undated), not a specific car's build month. For a particular car, get its vehicle id from
  `decode_vin` or `select_vehicle`.
- If a tool reports that a RealOEM page "did not have the expected structure", retry once with
  `refresh=true`; if it fails again, tell the user the plugin needs an update and give the URL.
- Call tools only for what the user asked. Results are cached; pass `refresh=true` only when the
  user asks for fresh data.
- Brand notes (vehicle id formats, series quirks) are in `brands/<brand>/README.md` of this plugin.
