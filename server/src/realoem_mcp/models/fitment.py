"""Fitment and comparison models (ARD section 5.11, feature D). PartSearch is the parser output."""

from __future__ import annotations

from pydantic import BaseModel

from realoem_mcp.models.common import DiagramRef, ResultMeta
from realoem_mcp.models.parts import SupersessionEntry


class PartSearchHit(BaseModel):
    part_number: str  # the number the vehicle actually uses (may differ from the query)
    diagram: DiagramRef  # built for the requested vehicle id


class PartSearch(BaseModel):  # parser output of parsers/partsearch.py
    part_number: str  # number in the page heading
    description: str | None
    price_usd: float | None
    hits: list[PartSearchHit]  # empty when the part is not on the vehicle
    superseded_by: list[SupersessionEntry]
    supersedes: list[SupersessionEntry]


class FitmentResult(ResultMeta):
    query: str  # normalized input
    vehicle_id: str
    fits: bool
    used_part_numbers: list[str]  # distinct numbers named by the hits, in page order
    description: str | None
    price_usd: float | None
    diagrams: list[DiagramRef]  # distinct diagrams, in page order
    superseded_by: list[SupersessionEntry]
    supersedes: list[SupersessionEntry]


class CompareScope(BaseModel):
    main_group: str
    subgroup: str | None
    diag_ids: list[str] | None


class PartComparison(BaseModel):
    part_number: str
    description: str | None  # vehicle A's first occurrence, else vehicle B's
    qty_a: list[str]  # raw qty per occurrence (row) on vehicle A
    qty_b: list[str]


class PartSummary(BaseModel):
    part_number: str
    description: str | None
    qty: list[str]  # raw qty per occurrence (row)
    diag_ids: list[str]  # diagrams showing the part, in scope order


class ComparisonResult(ResultMeta):
    scope: CompareScope
    complete: bool  # False when some in-scope diagrams could not be read within max_requests
    in_both: list[PartComparison]
    only_a: list[PartSummary]
    only_b: list[PartSummary]
    unfetched_a: list[str]  # in-scope diagIds not read (budget spent, not cached)
    unfetched_b: list[str]
    ignored_diag_ids_a: list[str]  # requested diag_ids not in vehicle A's scope
    ignored_diag_ids_b: list[str]
