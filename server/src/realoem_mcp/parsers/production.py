"""production?vin= page: build statistics for a VIN serial (site notes 4.4)."""

from __future__ import annotations

import re

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, require, text, tree

PAGE = PageType.PRODUCTION
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_TYPE = re.compile(r"\btype (?P<type>[0-9A-Z]+)\b")
_BUILT = re.compile(r"\bbuilt (?P<month>[A-Z][a-z]+) (?P<year>\d{4})\b")
_IN_MONTH = re.compile(r"\bVIN (?P<seq>[\d,]+) of (?P<total>[\d,]+) built that month")
_IN_TYPE = re.compile(r"\b(?P<seq>[\d,]+) of (?P<total>[\d,]+) across all\b")


def parse_production(html: str, *, url: str) -> dict[str, ProductionStats]:
    """Build statistics keyed by type code, in page order; {} when RealOEM has no record."""
    result = require(tree(html), "#ps-vin-result", PAGE, url)
    if "ps-vin-error" in (result.attributes.get("class") or "").split():
        return {}
    matches = result.css(".ps-vin-match")
    if not matches:
        raise LayoutChanged(PAGE, "#ps-vin-result has neither a match nor an error", url)
    stats: dict[str, ProductionStats] = {}
    for match in matches:
        type_code, record = _parse_match(match, url)
        if type_code in stats:
            raise LayoutChanged(PAGE, f"type {type_code} has more than one production record", url)
        stats[type_code] = record
    return stats


def _parse_match(match: Node, url: str) -> tuple[str, ProductionStats]:
    metas = [text(node) for node in match.css(".ps-vin-meta")]
    head = metas[0] if metas else ""
    type_code = _TYPE.search(head)
    built = _BUILT.search(head)
    if type_code is None or built is None or built["month"] not in MONTHS:
        raise LayoutChanged(PAGE, f"no type or build month in {head!r}", url)
    counts = " ".join(metas[1:])
    in_month = _IN_MONTH.search(counts)
    in_type = _IN_TYPE.search(counts)
    month = MONTHS.index(built["month"]) + 1
    return type_code["type"], ProductionStats(
        built_month=f"{built['year']}-{month:02d}",
        seq_in_month=_int(in_month, "seq"),
        total_in_month=_int(in_month, "total"),
        seq_in_type=_int(in_type, "seq"),
        total_in_type=_int(in_type, "total"),
    )


def _int(match: re.Match[str] | None, group: str) -> int | None:
    return int(match[group].replace(",", "")) if match is not None else None
