"""showparts page (site notes 5.4): diagram image, hotspots, parts table, notes legend."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import groupby
from urllib.parse import urljoin

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.catalog import Condition, DiagramParts, Hotspot, OptionCode, PartRow
from realoem_mcp.models.common import DiagramRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, Tree, parse_my, parse_price_usd, require, text, tree

PAGE = PageType.SHOWPARTS
# Part row cells: pos, description, supplement, qty, from, up to, part number, price, photo,
# notes, ECS link. Condition row cells: empty, text, option codes, colspan=8 filler.
PART_CELLS = 11
CONDITION_CELLS = 4
_HOTSPOTS = re.compile(r"var\s+partsimgmap\s*=\s*(\[.*?\])\s*;", re.DOTALL)
_POS_CLASS = re.compile(r"pos\S+")
_EDGE_CLASS = re.compile(r"edge([1-3])")


@dataclass
class _Part:
    cells: list[Node]
    conditions: list[Condition] = field(default_factory=list)


def parse_showparts(
    html: str, *, url: str, client: RealOemClient, vehicle_id: str, diag_id: str
) -> DiagramParts:
    root = tree(html)
    img = require(root, "#partsimg img", PAGE, url)
    name = (img.attributes.get("alt") or "").strip()
    src = img.attributes.get("src")
    width, height = img.attributes.get("width") or "", img.attributes.get("height") or ""
    if not name or not src or not width.isdigit() or not height.isdigit():
        raise LayoutChanged(PAGE, "diagram image without alt, src, width or height", url)
    table = require(root, "table#partsList", PAGE, url)
    if table.css_first("tr th") is None:
        raise LayoutChanged(PAGE, "parts table has no header row", url)
    return DiagramParts(
        diagram=DiagramRef.build(client, vehicle_id, diag_id, name),
        image_url=urljoin(url, src),
        image_width=int(width),
        image_height=int(height),
        hotspots=_hotspots(root, url),
        rows=[_part_row(part, url) for part in _parts(table, url)],
        notes_legend=_notes_legend(root, url),
    )


def _hotspots(root: Tree, url: str) -> list[Hotspot]:
    """var partsimgmap=[["01",78,255,87,271],...]: [position, x1, y1, x2, y2] per box."""
    for script in root.css("script"):
        match = _HOTSPOTS.search(script.text(deep=True))
        if match is None:
            continue
        try:
            entries = json.loads(match.group(1))
        except ValueError:
            raise LayoutChanged(PAGE, "partsimgmap is not valid JSON", url) from None
        hotspots = []
        for entry in entries:
            if not _is_hotspot(entry):
                raise LayoutChanged(PAGE, f"unexpected partsimgmap entry {entry!r}", url)
            position, x1, y1, x2, y2 = entry
            hotspots.append(Hotspot(position=position, x1=x1, y1=y1, x2=x2, y2=y2))
        return hotspots
    raise LayoutChanged(PAGE, "no partsimgmap script", url)


def _is_hotspot(entry: object) -> bool:
    return (
        isinstance(entry, list)
        and len(entry) == 5
        and isinstance(entry[0], str)
        and all(type(value) is int for value in entry[1:])
    )


def _parts(table: Node, url: str) -> list[_Part]:
    """Part rows with their conditions (the colspan=8 rows of the same position).

    A run of condition rows applies to every following part row of that position until the
    next condition row; condition rows after a position's last part row (e.g. a trailing
    "Attention!" note) belong to that last part row.
    """
    parts: list[_Part] = []
    for _, rows in groupby(_data_rows(table, url), key=lambda row: row[0]):
        run: list[Condition] = []  # the latest run of consecutive condition rows
        in_run = False
        last: _Part | None = None  # the latest part row of this position
        for _, cells in rows:
            if len(cells) == PART_CELLS:
                last = _Part(cells=cells, conditions=list(run))
                parts.append(last)
                in_run = False
            else:
                if not in_run:
                    run = []
                run.append(_condition(cells, url))
                in_run = True
        if in_run and last is not None:
            last.conditions.extend(run)
    return parts


def _data_rows(table: Node, url: str) -> Iterator[tuple[str, list[Node]]]:
    """(posNN class, cells) of every part and condition row; the header row is skipped."""
    for row in table.css("tr"):
        cells = row.css("td")
        if not cells:
            continue  # header row (th cells)
        classes = (row.attributes.get("class") or "").split()
        position = next((name for name in classes if _POS_CLASS.fullmatch(name)), None)
        if position is None:
            raise LayoutChanged(PAGE, "parts table row without a pos class", url)
        condition = len(cells) == CONDITION_CELLS and cells[-1].attributes.get("colspan") == "8"
        if len(cells) != PART_CELLS and not condition:
            raise LayoutChanged(PAGE, f"parts table row with {len(cells)} cells", url)
        yield position, cells


def _condition(cells: list[Node], url: str) -> Condition:
    codes: list[OptionCode] = []
    for link in cells[2].css("a.opt-code"):
        code = text(link)
        after = link.next
        raw = after.text(deep=False).strip() if after is not None and after.is_text_node else ""
        if not code or not raw.startswith("=") or not raw[1:].strip():
            raise LayoutChanged(PAGE, f"option code {code!r} without =value", url)
        codes.append(OptionCode(code=code, value=raw[1:].strip()))
    return Condition(text=_cell_text(cells[1]), option_codes=codes)


def _part_row(part: _Part, url: str) -> PartRow:
    cells = part.cells
    position, description = _cell_text(cells[0]), _cell_text(cells[1])
    if not position or not description:
        raise LayoutChanged(PAGE, "part row without position or description", url)
    edge = _EDGE_CLASS.search(cells[1].attributes.get("class") or "")
    return PartRow(
        position=position,
        description=description,
        supplement=_cell_text(cells[2]) or None,
        qty=_cell_text(cells[3]) or None,
        valid_from=parse_my(_cell_text(cells[4])),
        valid_to=parse_my(_cell_text(cells[5])),
        part_number=_cell_text(cells[6]) or None,
        price_usd=parse_price_usd(_cell_text(cells[7])),
        notes=_cell_text(cells[9]) or None,
        has_photo=cells[8].css_first('a[href*="/photos/"]') is not None,
        indent=int(edge.group(1)) if edge else 0,
        conditions=part.conditions,
    )


def _notes_legend(root: Tree, url: str) -> dict[str, str]:
    legend: dict[str, str] = {}
    for item in root.css("div.notes li"):
        key, sep, meaning = text(item).partition("=")
        if not sep or not key.strip():
            raise LayoutChanged(PAGE, f"notes legend entry {text(item)!r} has no '='", url)
        legend[key.strip()] = meaning.strip()
    return legend


def _cell_text(cell: Node) -> str:
    """Cell text with <br> and element boundaries as spaces, whitespace collapsed."""
    return " ".join(cell.text(deep=True, separator=" ").split())
