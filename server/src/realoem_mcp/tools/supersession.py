"""trace_supersession tool (ARD section 5.11, feature E; site notes 3.5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.parts import PartXref, SupersessionEntry
from realoem_mcp.models.supersession import SupersessionHop, SupersessionResult
from realoem_mcp.parsers.part_numbers import normalize
from realoem_mcp.services import Services
from realoem_mcp.tools.parts import fetch_part_xref

MIN_HOPS, MAX_HOPS = 1, 10


def _day(value: date | None) -> date:
    return value or date.min


def choose_successor(entries: Sequence[SupersessionEntry]) -> SupersessionEntry:
    """The successor to follow from a non-empty "Superseded by" list.

    Lists are transitively closed and the open-ended entry is the current part (site notes 3.5),
    so open-ended entries win; among them the latest start. Without an open-ended entry, the
    latest end (then the latest start). Ties keep page order.
    """
    candidates = [e for e in entries if e.valid_to is None] or list(entries)
    return max(candidates, key=lambda e: (_day(e.valid_to), _day(e.valid_from)))


def _hop(xref: PartXref, remark: str | None) -> SupersessionHop:
    return SupersessionHop(
        part_number=xref.part_number,
        description=xref.description,
        valid_from=xref.valid_from,
        valid_to=xref.valid_to,
        remark=remark,
    )


async def trace_chain(
    services: Services, part_number: str, *, max_hops: int = 5, refresh: bool = False
) -> SupersessionResult:
    """Follow "Superseded by" links from part_number; one partxref request per part read.

    A hop is one successor page read, so at most 1 + max_hops requests. Raises InvalidInput
    before any request for a malformed part number or max_hops outside 1-10.
    """
    query = normalize(part_number)
    if not MIN_HOPS <= max_hops <= MAX_HOPS:
        raise InvalidInput(f"max_hops must be between {MIN_HOPS} and {MAX_HOPS}, not {max_hops}.")
    xref, page = await fetch_part_xref(services, query, refresh=refresh)
    pages: list[Page] = [page]
    if xref is None:
        return SupersessionResult.from_pages(
            pages,
            query=query,
            status="not_found",
            current_part_number=None,
            chain=[],
            alternatives=[],
            history=[],
            complete=True,
            warnings=[],
        )
    chain = [_hop(xref, None)]
    visited = {xref.part_number}
    alternatives: list[SupersessionEntry] = []
    warnings: list[str] = []
    current: str | None = None
    while True:
        if not xref.superseded_by:
            if xref.ended:
                status = "no_successor"
            else:
                status = "current" if len(chain) == 1 else "replaced"
                current = xref.part_number
            break
        open_ended = [e for e in xref.superseded_by if e.valid_to is None]
        pick = choose_successor(xref.superseded_by)
        if pick.part_number in visited:  # RealOEM's links loop back into the chain
            status, alternatives = "ambiguous", open_ended or [pick]
            warnings.append(
                f"loop detected: {xref.part_number} is superseded by {pick.part_number}, "
                "which is already in the chain"
            )
            break
        successor = None
        if len(chain) > max_hops:
            warnings.append(
                f"hop limit reached (max_hops={max_hops}): the page of successor "
                f"{pick.part_number} was not read"
            )
        else:
            successor, page = await fetch_part_xref(services, pick.part_number, refresh=refresh)
            pages.append(page)
            if successor is None:
                warnings.append(
                    f"successor page missing: RealOEM has no page for {pick.part_number}"
                )
        if successor is None:  # stopped early: hop limit or missing page
            if len(open_ended) > 1:
                status, alternatives = "ambiguous", open_ended
            else:
                status = "replaced"
                current = pick.part_number if pick.valid_to is None else None
            break
        others = {e.part_number for e in open_ended} - {pick.part_number}
        if not others <= {e.part_number for e in successor.supersedes}:
            status, alternatives = "ambiguous", open_ended  # distinct open-ended successors
            break
        chain.append(_hop(successor, pick.remark))
        visited.add(successor.part_number)
        xref = successor
    return SupersessionResult.from_pages(
        pages,
        query=query,
        status=status,
        current_part_number=current,
        chain=chain,
        alternatives=alternatives,
        history=xref.supersedes,
        complete=not warnings,
        warnings=warnings,
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def trace_supersession(
        part_number: str, max_hops: int = 5, refresh: bool = False
    ) -> SupersessionResult:
        """Trace a BMW Group part number to the part that replaces it today.

        Use it when the user asks whether a part is current, what replaced it, or for its
        supersession history. part_number: 11 digits or the 7-digit short form; spaces, dashes
        and dots are fine. max_hops (1-10, default 5): how many successor pages may be read;
        one is usually enough because RealOEM lists every later number on each page.

        Returns status "current" (the part itself is current), "replaced" (current_part_number
        is the replacement), "no_successor" (ended, RealOEM names no replacement), "ambiguous"
        (several open-ended successors, or links that loop back; see alternatives) or
        "not_found". chain lists the parts whose pages were read, queried part first, with their
        dates and the remark of the link that led to each (e.g. "Exchangeable retrospectively").
        complete=false with warnings means the trace stopped early (hop limit, missing successor
        page, or a loop); current_part_number is then the newest successor RealOEM names, or null,
        unconfirmed by its own page. history is the "Supersedes" list of the
        last chain entry. Cite source_urls. One request per part read, none when cached;
        refresh=true fetches fresh copies.
        """
        try:
            return await trace_chain(services, part_number, max_hops=max_hops, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err
