---
name: supersession
description: Trace a BMW, MINI, Rolls-Royce or BMW Motorrad OEM part number to the part that replaces it today, with the supersession chain, dates and remarks. Use whenever the user asks whether a part number is current, discontinued, superseded or replaced, what the latest or replacement number is, or for a part's supersession history.
---

# Supersession chain

Answer "is this part current, and what replaced it?" with the `trace_supersession` tool of the
`realoem` MCP server. Never fetch realoem.com yourself (no WebFetch, no browser): every request must
go through the MCP tools, which rate-limit, cache and parse RealOEM for you.

## When to use

- "Is 11427541827 still current?", "What replaced 12120034087?", "What's the latest number for
  11 42 7 566 327?", "Show the supersession history of 11427953129."
- After `lookup_part` shows `superseded_by` entries and the user wants the replacement confirmed.
- Not for fitment on a specific car; use the fitment tools for that when they are available.

## Steps

1. Call `trace_supersession(part_number=...)` with the number as the user wrote it (11 digits or
   the last 7; spaces, dashes and dots are fine). Keep the default `max_hops=5`: RealOEM lists every
   later number on each page, so a trace usually reads one or two pages. If the tool says the input
   is not a BMW part number, ask the user to check it; do not guess digits.
2. Read `status`:
   - `current`: the part itself is current (not ENDED, no successor).
   - `replaced`: `current_part_number` is the replacement. Lead with it: "11427541827 was replaced
     by 11427953129."
   - `no_successor`: RealOEM marks the part ENDED and names no replacement. Say exactly that; do not
     call it "no longer available" or suggest a replacement yourself.
   - `ambiguous`: RealOEM names several open-ended successors, or (with a "loop detected"
     warning) links that loop back to a part already in `chain`. List every entry in
     `alternatives` with its dates and remark and say that RealOEM does not identify a single
     replacement; suggest confirming with a BMW parts counter.
   - `not_found`: RealOEM does not know this number; ask the user to double-check it.
3. Present `chain` in order (queried part first): part number, description, `valid_from` to
   `valid_to` (empty `valid_to` = still current), and the `remark` of each step.
4. Check `complete`. When it is false the trace stopped early and `warnings` says why: "hop
   limit reached", "successor page missing" or "loop detected". Tell the user the reason. For
   `current_part_number`, say "RealOEM names X as the successor" rather than "X is current",
   because its own page was not confirmed; if it is null, report the last chain entry, the successor
   named in the warning or in `alternatives`, and offer `lookup_part` on the last chain entry to
   list all its successors. After a hop-limit warning, offer to continue with a larger `max_hops`
   (up to 10); otherwise offer to check X with `lookup_part`.
5. `history` is the "Supersedes" list of the last chain entry: every earlier number RealOEM knows,
   with dates. Mention it when the user asks for the history, or to show that the numbers they
   hold are older versions of the current part.

## Explaining the results

- "Exchangeable retrospectively" (the only remark RealOEM shows) means the newer part also fits
  the older vehicles, so it can replace the old number on those cars.
- RealOEM's lists are complete in both directions: an ended part lists all its successors and the
  current part lists all its predecessors. That is why the trace jumps straight to the open-ended
  successor instead of visiting every number.
- Intermediate numbers can be short-lived or limited to special applications (for example
  11428683196, valid 09/2016 to 09/2017 and listed for Motorsport vehicles). Do not recommend an
  intermediate number when an open-ended successor exists.
- `in_catalog=false` on a `history` or `alternatives` entry means RealOEM no longer shows that
  number in any vehicle catalog; it is not proof that the part cannot be bought.

## Rules

- Always cite RealOEM: include the `source_urls` of every result you used.
- Never call a part discontinued because of a page title or a description; only `status`,
  `chain` and the dates count.
- If a tool reports that a RealOEM page "did not have the expected structure", retry once with
  `refresh=true`; if it fails again, tell the user the plugin needs an update and give the URL.
- Call tools only for what the user asked. Results are cached; pass `refresh=true` only when the
  user asks for fresh data.
- Brand notes are in `brands/<brand>/README.md` of this plugin.
