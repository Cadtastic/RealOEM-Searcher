"""partgrp pages (site notes 5.2-5.3): main groups and vehicle specs, a main group's diagrams."""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlsplit

from realoem_mcp.brands import Brand, BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.catalog import (
    DiagramThumb,
    MainGroup,
    PartGroups,
    Subgroup,
    VehicleSpecs,
)
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, Tree, canonical_url, require, text, tree
from realoem_mcp.vehicle_ids import VehicleId

PAGE = PageType.PARTGRP
MAIN_GROUP = re.compile(r"\d{2}")
DIAG_ID = re.compile(r"\d{2}_\d+")
_SPEC_FIELDS = {
    "Model": "model_name",
    "Body": "body",
    "Engine": "engine",
    "Steering": "steering",
    "Transmission": "transmission",
}
_NOT_AVAILABLE = {"", "N/A"}


def vehicle_brand(brands: BrandRegistry, vid: VehicleId) -> Brand:
    """Brand of a vehicle id; motorcycle type codes start with "0" (ARD F6 rule)."""
    return brands.for_vehicle_id(vid, product="M" if vid.type_code.startswith("0") else "P")


def dedupe_repeated(name: str) -> str:
    """Collapse a name printed twice ("Engine Engine" -> "Engine"), as on BMW Motorrad pages."""
    half, rest = divmod(len(name), 2)
    if rest and name[half] == " " and name[:half] == name[half + 1 :]:
        return name[:half]
    return name


def parse_part_groups(html: str, *, url: str, brands: BrandRegistry) -> PartGroups:
    root = tree(html)
    vehicle_id = _canonical_id(root, url)
    vid = VehicleId.parse(vehicle_id, brand_segments=brands.brand_segments())
    vehicle = VehicleRef.from_id(vid, vehicle_brand(brands, vid).id)
    specs = _specs(require(root, ".vehicle-specs dl", PAGE, url), vehicle)
    main_groups = [_main_group(link, url) for link in root.css('.mg-thumb a[href*="mg="]')]
    if not main_groups:
        raise LayoutChanged(PAGE, "no main groups (.mg-thumb links)", url)
    return PartGroups(specs=specs, main_groups=main_groups)


def parse_diagram_list(
    html: str, *, url: str, client: RealOemClient, vehicle_id: str, dedupe_names: bool
) -> list[Subgroup] | None:
    """Subgroups in page order; None when the vehicle has no such main group.

    For a main group the vehicle lacks, RealOEM answers with the vehicle's main-groups page
    (.partgrp-grid, no .diagThumbs).
    """
    root = tree(html)
    if root.css_first(".partgrp-selects") is not None:
        raise LayoutChanged(PAGE, "text drill-down page (dmode=0) instead of diagrams", url)
    container = root.css_first(".diagThumbs")
    if container is None:
        if root.css_first(".partgrp-grid") is not None:
            return None
        raise LayoutChanged(PAGE, "neither .diagThumbs nor .partgrp-grid", url)
    subgroups: list[Subgroup] = []
    for child in container.iter():
        classes = (child.attributes.get("class") or "").split()
        if child.tag == "a" and child.attributes.get("name"):
            name = _clean(text(child.css_first("h3.diag-hdr")), dedupe_names)
            if not name:
                raise LayoutChanged(PAGE, "subgroup anchor without h3.diag-hdr", url)
            subgroups.append(Subgroup(code=child.attributes["name"], name=name, diagrams=[]))
        elif "diag-thumb" in classes:
            if not subgroups:
                raise LayoutChanged(PAGE, "diagram before the first subgroup heading", url)
            thumb = _thumb(child, url, client, vehicle_id, dedupe_names)
            subgroups[-1].diagrams.append(thumb)
    return subgroups


def _canonical_id(root: Tree, url: str) -> str:
    canonical = canonical_url(root)
    vehicle_id = _query_param(canonical or "", "id")
    if not vehicle_id:
        raise LayoutChanged(PAGE, "no vehicle id in the canonical link", url)
    return vehicle_id


def _specs(dl: Node, vehicle: VehicleRef) -> VehicleSpecs:
    values: dict[str, str | None] = dict.fromkeys(_SPEC_FIELDS.values())
    for dt in dl.css("dt"):
        field = _SPEC_FIELDS.get(text(dt))
        dd = dt.next
        while dd is not None and dd.tag != "dd":
            dd = dd.next
        if field is not None and dd is not None:
            value = text(dd)
            values[field] = None if value in _NOT_AVAILABLE else value
    return VehicleSpecs(vehicle=vehicle, **values)


def _main_group(link: Node, url: str) -> MainGroup:
    mg = _query_param(link.attributes.get("href") or "", "mg") or ""
    if not MAIN_GROUP.fullmatch(mg):
        raise LayoutChanged(PAGE, f"main group link with mg={mg!r}", url)
    img = link.css_first("img")
    name = (img.attributes.get("alt") or "").strip() if img is not None else ""
    name = name or text(link.css_first(".title"))
    if not name:
        raise LayoutChanged(PAGE, f"main group {mg} has no name", url)
    return MainGroup(mg=mg, name=name)


def _thumb(
    node: Node, url: str, client: RealOemClient, vehicle_id: str, dedupe_names: bool
) -> DiagramThumb:
    link = node.css_first('a[href*="diagId="]')
    diag_id = _query_param(link.attributes.get("href") or "", "diagId") if link else None
    if diag_id is None or not DIAG_ID.fullmatch(diag_id):
        raise LayoutChanged(PAGE, f"diagram link with diagId={diag_id!r}", url)
    name = _clean(text(node.css_first(".title")), dedupe_names)
    img = node.css_first("img")
    src = img.attributes.get("src") if img is not None else None
    if not name or not src:
        raise LayoutChanged(PAGE, f"diagram {diag_id} has no title or thumbnail", url)
    return DiagramThumb(
        diagram=DiagramRef.build(client, vehicle_id, diag_id, name),
        thumbnail_url=urljoin(url, src),
    )


def _clean(name: str, dedupe_names: bool) -> str:
    return dedupe_repeated(name) if dedupe_names else name


def _query_param(href: str, name: str) -> str | None:
    # RealOEM's hrefs are not URL-encoded ("id=...R_1250_GS_19_0J91,_0J93_"), so split by hand.
    for pair in urlsplit(href).query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key == name:
            return unquote(value)
    return None
