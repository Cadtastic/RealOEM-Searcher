from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.parsers.common import tree
from realoem_mcp.parsers.supersession import parse_supersession
from tests.harness import load_fixture, url

OIL_FILTER = "Set oil-filter element"


def _parse(slug: str, q: str) -> tuple[list[SupersessionEntry], list[SupersessionEntry]]:
    html = load_fixture(f"partxref/{slug}.html")
    return parse_supersession(tree(html), url=url("partxref", q=q))


def test_superseded_part_lists_every_successor() -> None:
    superseded_by, supersedes = _parse("superseded_11427541827", "11427541827")
    assert supersedes == []
    assert superseded_by == [
        SupersessionEntry(
            part_number="11427566327",
            description=OIL_FILTER,
            valid_from=date(2006, 2, 13),
            valid_to=date(2017, 1, 30),
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
        SupersessionEntry(
            part_number="11428683196",
            description=OIL_FILTER,
            valid_from=date(2016, 9, 1),
            valid_to=date(2017, 9, 21),
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
        SupersessionEntry(
            part_number="11427953129",
            description=OIL_FILTER,
            valid_from=date(2017, 6, 1),
            valid_to=None,
            remark="Exchangeable retrospectively",
            in_catalog=True,
        ),
    ]


def test_current_part_lists_every_predecessor() -> None:
    superseded_by, supersedes = _parse("oil_filter_11427953129", "11427953129")
    assert superseded_by == []
    assert [e.part_number for e in supersedes] == ["11428683196", "11427566327", "11427541827"]
    oldest = supersedes[-1]
    assert (oldest.valid_from, oldest.valid_to) == (date(2004, 9, 1), date(2006, 3, 17))
    assert oldest.remark is None
    assert oldest.in_catalog is False  # partxref?q= link: no longer in any catalog


def test_intermediate_part_has_both_blocks() -> None:
    superseded_by, supersedes = _parse("intermediate_11427566327", "11427566327")
    assert [e.part_number for e in superseded_by] == ["11428683196", "11427953129"]
    assert [e.part_number for e in supersedes] == ["11427541827"]


def test_spark_plug_predecessor() -> None:
    superseded_by, supersedes = _parse("spark_plug_12120037244", "12120037244")
    assert superseded_by == []
    assert supersedes == [
        SupersessionEntry(
            part_number="12120034087",
            description="Spark plug, High Power",
            valid_from=date(2006, 6, 1),
            valid_to=date(2008, 11, 1),
            remark=None,
            in_catalog=False,
        )
    ]


def test_absent_blocks_give_empty_lists() -> None:
    assert _parse("motorrad_oil_filter_11427673541", "11427673541") == ([], [])
    assert _parse("not_found_11426666661", "11426666661") == ([], [])


def test_partsearch_style_whitespace_before_the_remark() -> None:
    html = (
        '<div class="superseded"><h3>Superseded by:</h3><dl>'
        '<dt><a href="part?id=VB13-USA-10-2005-E90-BMW-325i&amp;q=11427953129">'
        "11427953129 - Set oil-filter element</a></dt>"
        "<dd>(06/01/2017 &mdash; )\n\n        , Exchangeable retrospectively</dd>"
        "</dl></div>"
    )
    superseded_by, _ = parse_supersession(tree(html), url=url("partsearch", q="11427566327"))
    assert superseded_by[0].valid_to is None
    assert superseded_by[0].remark == "Exchangeable retrospectively"


@pytest.mark.parametrize(
    "block",
    [
        '<div class="superseded"><h3>Superseded by:</h3></div>',
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>09/01/2004</dd></dl></div>",
        '<div class="supersedes"><dl><dt>11427541827 - X</dt><dd>(09/01/2004 — )</dd></dl></div>',
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "</dl></div>",
        '<div class="supersedes"><dl><dt><a href="showparts?id=1">11427541827 - X</a></dt>'
        "<dd>(09/01/2004 — )</dd></dl></div>",
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>(2004-09-01 — )</dd></dl></div>",
        '<div class="supersedes"><dl><dt><a href="partxref?q=1">11427541827 - X</a></dt>'
        "<dd>(13/01/2004 — )</dd></dl></div>",
    ],
    ids=[
        "no dl",
        "no parentheses",
        "no link",
        "unpaired dt",
        "link target",
        "date format",
        "impossible month",
    ],
)
def test_broken_block_raises_layout_changed(block: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        parse_supersession(tree(block), url=url("partsearch", q="11427541827"))
    assert info.value.page_type == "partsearch"
