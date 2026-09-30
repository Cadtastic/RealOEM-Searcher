"""select page (v2 list boxes): cascade levels, options and result block (site notes 4.2-4.3, 5.1).

Used by decode_vin (B) and, unchanged, by the model cascade in C.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.select import LEVEL_PARAMS, SelectLevel, SelectOption, SelectPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_yyyymm00, require, text, tree

PAGE = PageType.SELECT


def parse_select(html: str, *, url: str) -> SelectPage:
    root = tree(html)
    form = require(root, "#selectForm", PAGE, url)
    cards = form.css("[data-ro-level]")
    if not cards:
        raise LayoutChanged(PAGE, "no v2 list boxes ([data-ro-level]) in #selectForm", url)
    levels = [_parse_level(card, url) for card in cards]
    vehicle_id, type_code, summary = _parse_results(require(root, "#selectResults", PAGE, url), url)
    return SelectPage(levels=levels, vehicle_id=vehicle_id, type_code=type_code, summary=summary)


def _parse_level(card: Node, url: str) -> SelectLevel:
    level = card.attributes.get("data-ro-level") or ""
    param = LEVEL_PARAMS.get(level)
    if param is None:
        raise LayoutChanged(PAGE, f"unknown cascade level {level!r}", url)
    caption = _caption(card)
    if caption is None:
        raise LayoutChanged(PAGE, f"no .ro-lb-label before level {level!r}", url)
    options: list[SelectOption] = []
    for row in card.css("a.ro-lb-row"):
        value = _query_param(row.attributes.get("href") or "", param)
        if not value:
            raise LayoutChanged(PAGE, f"row in level {level!r} has no {param}= in its link", url)
        if level == "prod" and not _is_yyyymm00(value):
            raise LayoutChanged(PAGE, f"prod value {value!r} is not YYYYMM00", url)
        selected = "is-selected" in (row.attributes.get("class") or "").split()
        options.append(SelectOption(value=value, label=text(row), selected=selected))
    if not options:
        raise LayoutChanged(PAGE, f"level {level!r} has no rows", url)
    if sum(option.selected for option in options) > 1:
        raise LayoutChanged(PAGE, f"level {level!r} has more than one selected row", url)
    return SelectLevel(level=level, label=caption, options=options)


def _is_yyyymm00(value: str) -> bool:
    try:
        return parse_yyyymm00(value) is not None
    except ValueError:  # month 00 or 13+
        return False


def _caption(card: Node) -> str | None:
    """Text of the .ro-lb-label element right before the list box, without the colon."""
    node = card.prev
    while node is not None and (node.is_text_node or node.is_comment_node):
        node = node.prev
    if node is None or "ro-lb-label" not in (node.attributes.get("class") or "").split():
        return None
    return text(node).rstrip(":").strip() or None


def _query_param(href: str, name: str) -> str | None:
    # RealOEM's hrefs are not URL-encoded ("model=Cooper S"), so split by hand and only
    # percent-decode; parse_qsl would also turn a literal "+" into a space.
    for pair in urlsplit(href).query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key == name:
            return unquote(value)
    return None


def _parse_results(results: Node, url: str) -> tuple[str | None, str | None, str | None]:
    """(vehicle_id, type_code, summary); all None until the cascade is complete or a VIN hit."""
    id_input = results.css_first('input[name="id"]')
    if id_input is None:
        return None, None, None
    values: dict[str, str] = {}
    for line in results.css(".searchResults-line"):
        label = text(line.css_first(".searchResults-label")).rstrip(":")
        values[label] = text(line.css_first(".searchResults-value"))
    vehicle_id = (id_input.attributes.get("value") or "").strip()
    type_code = values.get("Type Code")
    if not vehicle_id or not type_code:
        raise LayoutChanged(PAGE, "#selectResults has a form but no vehicle id or type code", url)
    return vehicle_id, type_code, values.get("You Have Selected") or None
