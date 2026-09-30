import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


@pytest.mark.parametrize(
    ("edits", "detail"),
    [
        ([('<div id="partsimg">', '<div id="image">')], "missing '#partsimg img'"),
        (
            [('width="640" height="448" alt="Oil Pan"', 'alt="Oil Pan"')],
            "diagram image without alt, src, width or height",
        ),
        ([('<table id="partsList"', '<table id="parts"')], "missing 'table#partsList'"),
        ([("<th ", "<td "), ("</th>", "</td>")], "parts table has no header row"),
        ([("var partsimgmap", "var partsmap")], "no partsimgmap script"),
        (
            [('["01",78,255,87,271]', '["01",78,255,87]')],
            "unexpected partsimgmap entry ['01', 78, 255, 87]",
        ),
        ([('["11",313,23,331,39]]', '["11",313,23,331,39],]')], "partsimgmap is not valid JSON"),
        ([('<tr class="r0 pos02">', '<tr class="r0">')], "parts table row without a pos class"),
        ([('<td colspan="8"></td>', "")], "parts table row with 3 cells"),
        (
            [('<td class="edge2">Oil Pan</td>', '<td class="edge2"></td>')],
            "part row without position or description",
        ),
        ([("S205A</a>=Yes", "S205A</a>")], "option code 'S205A' without =value"),
        (
            [("<li>+core = plus", "<li>+core plus")],
            "notes legend entry '+core plus core charge (possibility of a return of the old "
            "part)' has no '='",
        ),
    ],
    ids=[
        "no-image",
        "no-image-size",
        "no-table",
        "no-header",
        "no-hotspots",
        "bad-hotspot",
        "hotspots-not-json",
        "no-pos-class",
        "bad-cell-count",
        "no-description",
        "option-without-value",
        "legend-without-meaning",
    ],
)
async def test_broken_parts_page(
    services: Services, edits: list[tuple[str, str]], detail: str
) -> None:
    html = load_fixture("showparts/e90_325i_11_3733.html")
    for old, new in edits:
        assert old in html, old
        html = html.replace(old, new)
    with pytest.raises(LayoutChanged) as info:
        parse_showparts(
            html,
            url=url("showparts", id=E90, diagId="11_3733"),
            client=services.client,
            vehicle_id=E90,
            diag_id="11_3733",
        )
    assert info.value.detail == detail
    assert info.value.page_type == "showparts"
