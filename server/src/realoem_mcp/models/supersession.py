"""Supersession chain models (ARD section 5.11, feature E)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta
from realoem_mcp.models.parts import SupersessionEntry


class SupersessionHop(BaseModel):
    part_number: str
    description: str | None
    valid_from: date | None  # from this part's own partxref page
    valid_to: date | None  # None = open-ended
    remark: str | None  # remark of the link that led here; None for the queried part


class SupersessionResult(ResultMeta):
    query: str  # normalized input
    status: Literal["current", "replaced", "no_successor", "ambiguous", "not_found"]
    current_part_number: str | None  # set for current and replaced
    chain: list[SupersessionHop]  # parts whose pages were read, queried part first
    alternatives: list[SupersessionEntry]  # successors the trace could not choose between
    history: list[SupersessionEntry]  # "Supersedes" list of the last part in chain
    complete: bool  # False when the trace stopped early (hop limit, missing page, loop)
    warnings: list[str]  # one entry per reason the trace stopped early
