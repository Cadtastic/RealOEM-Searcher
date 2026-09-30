from collections.abc import Callable
from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import PartXref, SeriesUse
from realoem_mcp.parsers.partxref import parse_partxref
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

Parse = Callable[..., PartXref | None]


@pytest.fixture
async def parse(make_services: MakeServices) -> Parse:
    """parse(slug, q=..., series=None, html=None): parse a partxref fixture (or html)."""
    services, _ = make_services({})

    def _parse(
        slug: str, *, q: str, series: str | None = None, html: str | None = None
    ) -> PartXref | None:
        params = {"q": q} if series is None else {"q": q, "series": series}
        page_html = html if html is not None else load_fixture(f"partxref/{slug}.html")
        return parse_partxref(
            page_html,
            url=url("partxref", **params),
            brands=services.brands,
            client=services.client,
        )

    return _parse


def _part(parse: Parse, slug: str, q: str, **kwargs: str) -> PartXref:
    xref = parse(slug, q=q, **kwargs)
    assert xref is not None
    return xref


async def test_current_part_with_series_list(parse: Parse) -> None:
    xref = _part(parse, "oil_filter_11427953129", "11427953129")
    assert xref.part_number == "11427953129"
    assert xref.description == "Set oil-filter element"  # from the ECS button
    assert (xref.supplier_ref, xref.weight_kg) == (None, None)
    assert (xref.valid_from, xref.valid_to, xref.ended) == (date(2017, 6, 1), None, False)
    assert xref.superseded_by == []
    assert [e.part_number for e in xref.supersedes] == [
        "11428683196",
        "11427566327",
        "11427541827",
    ]
    assert len(xref.series) == 66
    assert xref.series[0] == SeriesUse(
        code="E81",
        name="1 Series E81",
        brand="bmw",
        production_from="2006-02",
        production_to="2011-12",
    )
    e90n = next(s for s in xref.series if s.code == "E90N")
    assert (e90n.name, e90n.production_from, e90n.production_to) == (
        "3 Series E90 LCI",
        "2007-07",
        "2011-12",
    )
    assert xref.series[-1] == SeriesUse(
        code="MOSP",
        name="MS BMW Motorsport",
        brand="bmw",
        production_from=None,
        production_to=None,
    )
    assert {s.brand for s in xref.series} == {"bmw"}
    assert xref.models == []


async def test_superseded_part_on_no_vehicles_template(parse: Parse) -> None:
    xref = _part(parse, "superseded_11427541827", "11427541827")
    assert xref.description == "Set oil-filter element"  # from "<h1>number - description"
    assert (xref.valid_from, xref.valid_to) == (date(2004, 9, 1), date(2006, 3, 17))
    assert xref.ended is True
    assert xref.weight_kg == 0.047
    assert [e.part_number for e in xref.superseded_by] == [
        "11427566327",
        "11428683196",
        "11427953129",
    ]
    assert (xref.supersedes, xref.series, xref.models) == ([], [], [])


async def test_intermediate_part_with_photo_and_both_blocks(parse: Parse) -> None:
    xref = _part(parse, "intermediate_11427566327", "11427566327")
    assert xref.part_number == "11427566327"  # the photo link inside <h1> is ignored
    assert (xref.valid_to, xref.ended) == (date(2017, 1, 30), True)
    assert [e.part_number for e in xref.superseded_by] == ["11428683196", "11427953129"]
    assert [e.part_number for e in xref.supersedes] == ["11427541827"]
    assert [(s.code, s.brand) for s in xref.series] == [("MOSP", "bmw")]


async def test_spark_plug_supplier_and_weight_pass_through(parse: Parse) -> None:
    xref = _part(parse, "spark_plug_12120037244", "12120037244")
    assert xref.description == "Spark plug, High Power"
    assert xref.supplier_ref == "BOSCH ZGR6STE2"
    assert xref.weight_kg == 44.65  # nonsense on RealOEM, passed through as-is
    assert len(xref.series) == 17


async def test_mini_series_are_tagged_mini(parse: Parse) -> None:
    xref = _part(parse, "mini_oil_filter_11427622446", "11427622446")
    assert [(s.code, s.name) for s in xref.series[:3]] == [
        ("R56", "MINI R56"),
        ("R56N", "MINI R56 LCI"),
        ("R55", "MINI Clubman R55"),
    ]
    assert {s.brand for s in xref.series} == {"mini"}


async def test_motorcycle_series_are_tagged_motorrad(parse: Parse) -> None:
    xref = _part(parse, "motorrad_oil_filter_11427673541", "11427673541")
    by_code = {s.code: s for s in xref.series}
    assert by_code["K25"] == SeriesUse(
        code="K25",
        name="K25 (R 1200 GS)",
        brand="motorrad",
        production_from="2002-12",
        production_to="2012-12",
    )
    assert by_code["K255"].name == "K25 (R 1200 GS Adventure)"
    k_codes = [code for code in by_code if code.startswith("K")]
    assert len(k_codes) == 22  # K08 ... K61 plus KR1 and KR3 (R nineT)
    assert {by_code[code].brand for code in k_codes} == {"motorrad"}
    assert (by_code["I01"].name, by_code["I01"].brand) == ("i3 I01", "bmw")
    assert (by_code["A73"].production_from, by_code["A73"].brand) == (None, "bmw")


async def test_rolls_royce_series_are_tagged_rolls_royce(parse: Parse) -> None:
    xref = _part(parse, "rr_oil_filter_11427583220", "11427583220")
    by_code = {s.code: s for s in xref.series}
    assert (by_code["RR4"].name, by_code["RR4"].brand) == ("Ghost RR4", "rolls-royce")
    assert {by_code[c].brand for c in ("RR11", "RR12", "RR21", "RR5", "RR6", "RR31")} == {
        "rolls-royce"
    }
    assert (by_code["F07"].brand, by_code["MOSP"].brand) == ("bmw", "bmw")


@pytest.mark.parametrize(
    ("slug", "q"),
    [("not_found_11426666661", "11426666661"), ("empty_q", "")],
)
async def test_not_found_page_parses_to_none(parse: Parse, slug: str, q: str) -> None:
    assert parse(slug, q=q) is None


@pytest.mark.parametrize(
    ("slug", "q", "returned"),
    [
        ("short_7953129", "7953129", "11427953129"),
        ("false_match_99999999999", "99999999999", "00009999999"),
        ("junk_abc", "00000000000", "00000000000"),
    ],
)
async def test_parser_reports_the_number_realoem_returned(
    parse: Parse, slug: str, q: str, returned: str
) -> None:
    # Deciding whether it is the part that was asked for is matches()'s job (tools/parts.py).
    assert _part(parse, slug, q).part_number == returned


async def test_title_never_decides_the_status(parse: Parse) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e30_no_vehicles.html")
    assert "Discontinued BMW Part" in html
    xref = _part(parse, "oil_filter_11427953129_e30_no_vehicles", "11427953129", series="E30")
    assert (xref.ended, xref.valid_to, xref.series, xref.models) == (False, None, [], [])


async def test_heading_description_wins_over_the_ecs_attribute(parse: Parse) -> None:
    html = load_fixture("partxref/superseded_11427541827.html")
    html = html.replace(
        'data-ecs-part-name="Set oil-filter element"', 'data-ecs-part-name="ECS name"'
    )
    assert _part(parse, "", "11427541827", html=html).description == "Set oil-filter element"


async def test_description_falls_back_to_a_supersession_link_naming_the_part(
    parse: Parse,
) -> None:
    html = load_fixture("partxref/oil_filter_11427953129.html")
    html = html.replace(' data-ecs-part-name="Set oil-filter element"', "")
    assert _part(parse, "", "11427953129", html=html).description is None
    html = html.replace("11427541827 - Set oil-filter element", "11427953129 - Oil filter kit")
    assert _part(parse, "", "11427953129", html=html).description == "Oil filter kit"


BROKEN = [
    ("<html><body><p>maintenance</p></body></html>", "div.content > h1"),
    ('<div class="content"><div class="error">Server busy</div></div>', "unexpected error"),
    ('<div class="content"><h1>Oil filter</h1></div>', "unexpected part heading"),
    ('<div class="content"><h1>11427953129</h1></div>', "missing part header"),
    (
        '<div class="content"><h1>11427953129</h1><dl><dt>Weight:</dt><dd>1 kg</dd></dl></div>',
        "unexpected part header",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd></dl></div>",
        "div.partSearchResults",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>soon</dd></dl>"
        '<div class="partSearchResults"></div></div>',
        "unexpected date",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd></dl>"
        '<div class="partSearchResults">Part 11427953129 was found on the following vehicles:'
        "<div>BMW 1 Series E81</div></div></div>",
        "no series or vehicle rows",
    ),
    (
        '<div class="content"><h1>11427953129</h1>'
        "<dl><dt>From:</dt><dd>06/01/2017</dd><dt>To:</dt><dd>-</dd>"
        "<dt>Weight:</dt><dd>heavy</dd></dl>"
        '<div class="partSearchResults"></div></div>',
        "unexpected weight",
    ),
]


@pytest.mark.parametrize(("html", "detail"), BROKEN, ids=[d for _, d in BROKEN])
async def test_broken_page_raises_layout_changed(parse: Parse, html: str, detail: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        parse("", q="11427953129", html=html)
    assert info.value.page_type == "partxref"
    assert detail in info.value.detail


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    [
        (
            "BMW 1 Series E81 (02/2006\N{EN DASH}12/2011)",
            "BMW 1 Series E81",
            "unexpected series label",
        ),
        (
            "BMW 1 Series E81 (02/2006\N{EN DASH}12/2011)",
            "BMW 1 Series E81 (13/2006\N{EN DASH}12/2011)",
            "unexpected production date",
        ),
        ("partxref?q=11427953129&amp;series=E81", "partxref?q=11427953129", "vehicle link"),
    ],
)
async def test_broken_series_row_raises_layout_changed(
    parse: Parse, old: str, new: str, detail: str
) -> None:
    html = load_fixture("partxref/oil_filter_11427953129.html")
    assert old in html
    with pytest.raises(LayoutChanged) as info:
        parse("", q="11427953129", html=html.replace(old, new))
    assert detail in info.value.detail
