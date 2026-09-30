"""trace_supersession tool (ARD section 5.11, feature E; site notes 3.5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from realoem_mcp.models.parts import SupersessionEntry


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
