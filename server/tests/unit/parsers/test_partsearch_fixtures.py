"""Each partsearch fixture is the trimmed page RealOEM served for the part in its name."""

import pytest

from tests.harness import FIXTURES, load_fixture

# fixture slug -> the page's "Other models with this part" link: requested vehicle id and part
MARKERS = {
    "e90_325i_200510_oil_filter_11427953129": (
        'id=VB13-USA-10-2005-E90-BMW-325i&amp;q=11427953129">Other models with this part</a>'
    ),
    "e90_325i_predecessor_11427566327": (
        'id=VB13-USA---E90-BMW-325i&amp;q=11427566327">Other models with this part</a>'
    ),
    "e90_325i_not_on_vehicle_11427622446": (
        'id=VB13-USA---E90-BMW-325i&amp;q=11427622446">Other models with this part</a>'
    ),
}


def test_partsearch_fixture_set_is_complete() -> None:
    present = {path.stem for path in (FIXTURES / "partsearch").glob("*.html")}
    assert present == set(MARKERS)


@pytest.mark.parametrize(("slug", "marker"), MARKERS.items(), ids=list(MARKERS))
def test_partsearch_fixture_is_the_right_capture(slug: str, marker: str) -> None:
    assert marker in load_fixture(f"partsearch/{slug}.html")
