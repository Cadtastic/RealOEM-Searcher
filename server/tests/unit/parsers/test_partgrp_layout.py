import re

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.catalog import Subgroup
from realoem_mcp.parsers.partgrp import parse_diagram_list, parse_part_groups
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
GROUPS = "common/partgrp_e90_325i.html"
DIAGRAMS = "partgrp/e90_325i_mg11.html"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


def _edited(fixture: str, *edits: tuple[str, str]) -> str:
    html = load_fixture(fixture)
    for old, new in edits:
        assert old in html, f"{old!r} not in {fixture}"
        html = html.replace(old, new)
    return html


def _diagrams(html: str, services: Services) -> list[Subgroup] | None:
    return parse_diagram_list(
        html,
        url=url("partgrp", id=E90, mg="11"),
        client=services.client,
        vehicle_id=E90,
        dedupe_names=False,
    )


@pytest.mark.parametrize(
    ("edits", "detail"),
    [
        (
            [('<link rel="canonical"', '<link rel="alternate"')],
            "no vehicle id in the canonical link",
        ),
        ([('class="vehicle-specs"', 'class="specs"')], "missing '.vehicle-specs dl'"),
        ([('class="mg-thumb"', 'class="group"')], "no main groups (.mg-thumb links)"),
        ([("325i&amp;mg=11", "325i&amp;mg=ENGINE")], "main group link with mg='ENGINE'"),
        (
            [('alt="ENGINE">', 'alt="">'), ('<h3 class="title">ENGINE</h3>', "<h3></h3>")],
            "main group 11 has no name",
        ),
    ],
    ids=["no-canonical", "no-specs", "no-main-groups", "bad-mg", "no-name"],
)
async def test_broken_main_groups_page(
    services: Services, edits: list[tuple[str, str]], detail: str
) -> None:
    html = _edited(GROUPS, *edits)
    with pytest.raises(LayoutChanged) as info:
        parse_part_groups(html, url=url("partgrp", id=E90), brands=services.brands)
    assert info.value.detail == detail
    assert info.value.page_type == "partgrp"


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        ('class="diagThumbs"', 'class="thumbs"', "neither .diagThumbs nor .partgrp-grid"),
        ("diagId=11_3733", "diagram=11_3733", "diagram link with diagId=None"),
        ("diagId=11_3733", "diagId=3733", "diagram link with diagId='3733'"),
        ('<h3 class="diag-hdr">Engine Housing</h3>', "", "subgroup anchor without h3.diag-hdr"),
        ('<a name="05"><h3 class="diag-hdr">Engine</h3></a>', "", "diagram before the first"),
        (
            '<div class="title">SHORT ENGINE</div>',
            '<div class="title"></div>',
            "diagram 11_3730 has no title or thumbnail",
        ),
    ],
    ids=[
        "no-container",
        "no-diag-id",
        "bad-diag-id",
        "no-subgroup-name",
        "no-first-subgroup",
        "no-diagram-title",
    ],
)
async def test_broken_diagram_list(services: Services, old: str, new: str, detail: str) -> None:
    with pytest.raises(LayoutChanged, match=re.escape(detail)):
        _diagrams(_edited(DIAGRAMS, (old, new)), services)


async def test_text_drill_down_page_is_a_layout_change(services: Services) -> None:
    html = load_fixture("partgrp/e90_325i_mg11_textmode.html")
    with pytest.raises(LayoutChanged, match="text drill-down page"):
        _diagrams(html, services)


async def test_main_groups_page_means_the_vehicle_has_no_such_main_group(
    services: Services,
) -> None:
    html = load_fixture("partgrp/e90_325i_mg99.html")  # RealOEM's answer to mg=99
    assert _diagrams(html, services) is None
