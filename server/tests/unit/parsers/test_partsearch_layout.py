import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.partsearch import parse_partsearch
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

VEHICLE = "VB13-USA-10-2005-E90-BMW-325i"
HIT = "e90_325i_200510_oil_filter_11427953129"
MISS = "e90_325i_not_on_vehicle_11427622446"
FIRST_HIT = "Engine oil / maintenance service"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


@pytest.mark.parametrize(
    ("slug", "edits", "detail"),
    [
        (HIT, [("<h1>", "<h5>"), ("</h1>", "</h5>")], "missing 'div.content > h1'"),
        (HIT, [("11427953129</h1>", "1142795312</h1>")], "unexpected part heading '1142795312'"),
        (
            HIT,
            [('<div class="partSearchResults">', '<div class="results">')],
            "missing 'div.partSearchResults'",
        ),
        (
            MISS,
            [("The specified part was not found.", "Nothing to show")],
            "unexpected search result 'Nothing to show'",
        ),
        (HIT, [('<div class="diag-info">', '<div class="info">')], "missing 'div.diag-info'"),
        (
            HIT,
            [("was found on diagram:", "appears on diagram:")],
            f"unexpected diagram hit 'Part 11427953129 appears on diagram: {FIRST_HIT}'",
        ),
        (
            HIT,
            [("diagId=02_0092#", "diag=02_0092#")],
            f"unexpected diagram hit 'Part 11427953129 was found on diagram: {FIRST_HIT}'",
        ),
        (
            HIT,
            [("<h1>", '<div class="error vs2">Try again later.</div><h1>')],
            "unexpected error message 'Try again later.'",
        ),
        (HIT, [("09/21/2017", "2017-09-21")], "unexpected date ' 2017-09-21'"),
    ],
    ids=[
        "no-heading",
        "bad-heading",
        "no-results",
        "unexpected-result-text",
        "hit-without-info",
        "hit-text-changed",
        "hit-link-without-diag-id",
        "unexpected-error",
        "bad-supersession-date",
    ],
)
async def test_broken_partsearch_page(
    services: Services, slug: str, edits: list[tuple[str, str]], detail: str
) -> None:
    html = load_fixture(f"partsearch/{slug}.html")
    for old, new in edits:
        assert old in html, old
        html = html.replace(old, new)
    with pytest.raises(LayoutChanged) as info:
        parse_partsearch(
            html,
            url=url("partsearch", id=VEHICLE, q="11427953129"),
            client=services.client,
            vehicle_id=VEHICLE,
        )
    assert info.value.detail == detail
    assert info.value.page_type == "partsearch"
