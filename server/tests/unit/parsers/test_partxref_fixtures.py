"""Each partxref fixture is the trimmed page RealOEM served for the part in its name."""

import pytest

from tests.harness import FIXTURES, load_fixture

# fixture slug -> text that only the right capture contains
MARKERS = {
    "oil_filter_11427953129": "Part 11427953129 was found on the following vehicles:",
    "oil_filter_11427953129_e90": "Part 11427953129 was found on the following E90 vehicles:",
    "oil_filter_11427953129_e30_no_vehicles": "11427953129 - Set oil-filter element</h1>",
    "superseded_11427541827": "11427541827 - Set oil-filter element</h1>",
    "intermediate_11427566327": "Part 11427566327 was found on the following vehicles:",
    "spark_plug_12120037244": "Part 12120037244 was found on the following vehicles:",
    "mini_oil_filter_11427622446": "Part 11427622446 was found on the following vehicles:",
    "motorrad_oil_filter_11427673541": "Part 11427673541 was found on the following vehicles:",
    "motorrad_oil_filter_11427673541_k25": (
        "Part 11427673541 was found on the following K25 vehicles:"
    ),
    "rr_oil_filter_11427583220": "Part 11427583220 was found on the following vehicles:",
    "rr_oil_filter_11427583220_rr4": "Part 11427583220 was found on the following RR4 vehicles:",
    "short_7953129": "partxref?q=7953129&amp;series=E81",
    "false_match_99999999999": "Part 00009999999 was found on the following vehicles:",
    "junk_abc": "Part 00000000000 was found on the following vehicles:",
    "empty_q": "The specified part {0} was not found.",
    "not_found_11426666661": "The specified part 11426666661 was not found.",
}


def test_partxref_fixture_set_is_complete() -> None:
    present = {path.stem for path in (FIXTURES / "partxref").glob("*.html")}
    assert present == set(MARKERS)


@pytest.mark.parametrize(("slug", "marker"), MARKERS.items(), ids=list(MARKERS))
def test_partxref_fixture_is_the_right_capture(slug: str, marker: str) -> None:
    assert marker in load_fixture(f"partxref/{slug}.html")
