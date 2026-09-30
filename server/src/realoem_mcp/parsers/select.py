"""select page (v2 list boxes): cascade levels, options and result block (site notes 4.2-4.3, 5.1).

Used by decode_vin (B) and, unchanged, by the model cascade in C.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from realoem_mcp.models.select import LEVEL_PARAMS, SelectLevel, SelectOption, SelectPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, require, text, tree

PAGE = PageType.SELECT


def parse_select(html: str, *, url: str) -> SelectPage:
    root = tree(html)
    form = require(root, "#selectForm", PAGE, url)
    levels = [_parse_level(card) for card in form.css("[data-ro-level]")]
    vehicle_id, type_code, summary = _parse_results(require(root, "#selectResults", PAGE, url))
    return SelectPage(levels=levels, vehicle_id=vehicle_id, type_code=type_code, summary=summary)


def _parse_level(card: Node) -> SelectLevel:
    level = card.attributes.get("data-ro-level") or ""
    param = LEVEL_PARAMS.get(level, level)
    options: list[SelectOption] = []
    for row in card.css("a.ro-lb-row"):
        value = _query_param(row.attributes.get("href") or "", param) or ""
        selected = "is-selected" in (row.attributes.get("class") or "").split()
        options.append(SelectOption(value=value, label=text(row), selected=selected))
    return SelectLevel(level=level, label=_caption(card) or "", options=options)


def _caption(card: Node) -> str | None:
    """Text of the .ro-lb-label element right before the list box, without the colon."""
    node = card.prev
    while node is not None and node.is_text_node:
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


def _parse_results(results: Node) -> tuple[str | None, str | None, str | None]:
    """(vehicle_id, type_code, summary); all None until the cascade is complete or a VIN hit."""
    id_input = results.css_first('input[name="id"]')
    if id_input is None:
        return None, None, None
    values: dict[str, str] = {}
    for line in results.css(".searchResults-line"):
        label = text(line.css_first(".searchResults-label")).rstrip(":")
        values[label] = text(line.css_first(".searchResults-value"))
    vehicle_id = (id_input.attributes.get("value") or "").strip() or None
    return vehicle_id, values.get("Type Code"), values.get("You Have Selected") or None
