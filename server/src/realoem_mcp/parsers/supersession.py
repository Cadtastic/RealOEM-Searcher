"""Superseded-by / supersedes blocks shared by partxref, part and partsearch (site notes 3.5)."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.parsers.common import Node, Tree, parse_mdy, require, text

_LINK = re.compile(r"(?P<number>\d+)\s*-\s*(?P<description>.*)")
# "(02/13/2006 - 01/30/2017), Exchangeable retrospectively" or "(06/01/2017 - )", em dashes
_RANGE = re.compile(
    r"\((?P<start>[^\N{EM DASH})]*)\N{EM DASH}(?P<end>[^)]*)\)\s*(?:,\s*(?P<remark>.+))?"
)


def parse_supersession(
    root: Tree | Node, *, url: str
) -> tuple[list[SupersessionEntry], list[SupersessionEntry]]:
    """(superseded_by, supersedes); each list is empty when its block is absent."""
    return _block(root, "div.superseded", url), _block(root, "div.supersedes", url)


def checked_mdy(
    value: str, page_type: str, url: str, *, open_end: str | None = None
) -> date | None:
    """MM/DD/YYYY as a date; None only for the open-end marker; anything else is LayoutChanged.

    Guards against a date-format change silently turning every date into None (NFR3).
    """
    if open_end is not None and value.strip() == open_end:
        return None
    try:
        parsed = parse_mdy(value)
    except ValueError:  # impossible month or day
        parsed = None
    if parsed is None:
        raise LayoutChanged(page_type, f"unexpected date {value!r}", url)
    return parsed


def _page_type(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def _block(root: Tree | Node, selector: str, url: str) -> list[SupersessionEntry]:
    block = root.css_first(selector)
    if block is None:
        return []
    dl = require(block, "dl", _page_type(url), url)
    terms, details = dl.css("dt"), dl.css("dd")
    if len(terms) != len(details):
        raise LayoutChanged(_page_type(url), f"{selector} has unpaired dt/dd", url)
    return [_entry(dt, dd, url) for dt, dd in zip(terms, details, strict=True)]


def _entry(dt: Node, dd: Node, url: str) -> SupersessionEntry:
    link = dt.css_first("a")
    number = _LINK.fullmatch(text(link))
    dates = _RANGE.fullmatch(text(dd))
    if link is None or number is None or dates is None:
        detail = f"unexpected supersession entry {text(dt)!r} {text(dd)!r}"
        raise LayoutChanged(_page_type(url), detail, url)
    target = _page_type(link.attributes.get("href") or "")
    if target not in ("part", "partxref"):
        raise LayoutChanged(_page_type(url), f"unexpected supersession link to {target!r}", url)
    page_type = _page_type(url)
    return SupersessionEntry(
        part_number=number["number"],
        description=number["description"].strip() or None,
        valid_from=checked_mdy(dates["start"], page_type, url),
        valid_to=checked_mdy(dates["end"], page_type, url, open_end=""),
        remark=dates["remark"],
        in_catalog=target == "part",  # part?... = still in a catalog; partxref?q= = not
    )
