"""partxref: part header, supersession and the series or vehicles using a part (site notes 3)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.parts import ModelUse, PartXref, SeriesUse, SupersessionEntry
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_my, require, text, tree
from realoem_mcp.parsers.supersession import checked_mdy, parse_supersession

PAGE = PageType.PARTXREF
_HEADING = re.compile(r"(?P<number>\d+)(?:\s*-\s*(?P<description>.+))?")
_WEIGHT = re.compile(r"(?P<kg>\d+(?:\.\d+)?)\s*kg")
# "BMW 3 Series E90 LCI (07/2007-12/2011)" or "BMW MS BMW Motorsport (-)", with an en dash
_SERIES_LABEL = re.compile(r"(?P<label>.+?)\s*\((?P<start>[\d/]*)\N{EN DASH}(?P<end>[\d/]*)\)")


def parse_partxref(
    html: str, *, url: str, brands: BrandRegistry, client: RealOemClient
) -> PartXref | None:
    """The partxref page as a PartXref, or None when RealOEM says the part was not found.

    brands tags each series and vehicle with its brand; client builds diagram URLs. No I/O.
    """
    root = tree(html)
    error = root.css_first("div.content > div.error")
    if error is not None:
        if "was not found" not in text(error):
            raise LayoutChanged(PAGE, f"unexpected error message {text(error)!r}", url)
        return None
    heading = require(root, "div.content > h1", PAGE, url)
    content = heading.parent
    match = _HEADING.fullmatch(text(heading))
    if content is None or match is None:
        raise LayoutChanged(PAGE, f"unexpected part heading {text(heading)!r}", url)
    number = match["number"]
    header = _header(content, url)
    superseded_by, supersedes = parse_supersession(content, url=url)
    results = require(content, "div.partSearchResults", PAGE, url)
    series, models = _uses(results, url=url, brands=brands, client=client)
    return PartXref(
        part_number=number,
        description=match["description"]
        or _ecs_name(content)
        or _named_in(number, superseded_by + supersedes),
        supplier_ref=_supplier(content),
        weight_kg=_weight(header.get("Weight"), url),
        valid_from=checked_mdy(header["From"], PAGE, url),
        valid_to=checked_mdy(header["To"], PAGE, url, open_end="-"),
        ended="(ENDED)" in header["To"],
        superseded_by=superseded_by,
        supersedes=supersedes,
        series=series,
        models=models,
    )


def _children(content: Node, tag: str) -> list[Node]:
    return [child for child in content.iter() if child.tag == tag]


def _header(content: Node, url: str) -> dict[str, str]:
    """The From/To/Weight <dl> right under the heading."""
    lists = _children(content, "dl")
    if not lists:
        raise LayoutChanged(PAGE, "missing part header <dl>", url)
    terms, details = lists[0].css("dt"), lists[0].css("dd")
    fields = {text(dt).rstrip(":"): text(dd) for dt, dd in zip(terms, details, strict=False)}
    if len(terms) != len(details) or "From" not in fields or "To" not in fields:
        raise LayoutChanged(PAGE, f"unexpected part header {sorted(fields)}", url)
    return fields


def _weight(value: str | None, url: str) -> float | None:
    """Weight text such as "0.047 kg" as 0.047 (passed through even when nonsense)."""
    if value is None:
        return None
    match = _WEIGHT.fullmatch(value)
    if match is None:
        raise LayoutChanged(PAGE, f"unexpected weight {value!r}", url)
    return float(match["kg"])


def _supplier(content: Node) -> str | None:
    """Optional supplier reference, e.g. <h3>BOSCH ZGR6STE2</h3> (not the supersession h3s)."""
    headings = _children(content, "h3")
    return (text(headings[0]) or None) if headings else None


def _ecs_name(content: Node) -> str | None:
    button = content.css_first("a.ecs-tuning-button[data-ecs-part-name]")
    if button is None:
        return None
    return (button.attributes.get("data-ecs-part-name") or "").strip() or None


def _named_in(number: str, entries: list[SupersessionEntry]) -> str | None:
    """Description from a supersession link that names this part."""
    return next((e.description for e in entries if e.part_number == number and e.description), None)


def _uses(
    results: Node, *, url: str, brands: BrandRegistry, client: RealOemClient
) -> tuple[list[SeriesUse], list[ModelUse]]:
    series: list[SeriesUse] = []
    models: list[ModelUse] = []
    for item in results.css("li"):
        link = require(item, "a[href]", PAGE, url)
        href = link.attributes.get("href") or ""
        target = urlsplit(href).path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(urlsplit(href).query))
        if target == "partxref" and params.get("series"):
            series.append(_series_use(link, params["series"], url, brands))
        else:
            raise LayoutChanged(PAGE, f"unexpected vehicle link {href!r}", url)
    if not series and not models and "was found on the following" in text(results):
        raise LayoutChanged(PAGE, "no series or vehicle rows under 'was found on'", url)
    return series, models


def _series_use(link: Node, code: str, url: str, brands: BrandRegistry) -> SeriesUse:
    label = text(link)
    match = _SERIES_LABEL.fullmatch(label)
    if match is None:
        raise LayoutChanged(PAGE, f"unexpected series label {label!r}", url)
    return SeriesUse(
        code=code,
        name=match["label"].removeprefix("BMW "),  # RealOEM prefixes every label with "BMW"
        brand=brands.for_series(code, label=label).id,
        production_from=_month(match["start"], url),
        production_to=_month(match["end"], url),
    )


def _month(value: str, url: str) -> str | None:
    """MM/YYYY as "YYYY-MM"; None when RealOEM shows no date; anything else is LayoutChanged."""
    if not value:
        return None
    try:
        month = parse_my(value)
    except ValueError:  # impossible month
        month = None
    if month is None:
        raise LayoutChanged(PAGE, f"unexpected production date {value!r}", url)
    return month
