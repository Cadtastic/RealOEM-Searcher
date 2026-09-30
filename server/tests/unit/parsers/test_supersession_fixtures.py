"""Each supersession fixture is the trimmed page RealOEM served for the part in its name."""

import pytest

from tests.harness import FIXTURES, load_fixture

# fixture slug -> text that only the right capture contains
MARKERS = {
    "spark_plug_pred_12120034087": "12120034087 - Spark plug, High Power</h1>",
}


def test_supersession_fixture_set_is_complete() -> None:
    present = {path.stem for path in (FIXTURES / "supersession").glob("*.html")}
    assert present == set(MARKERS)


@pytest.mark.parametrize(("slug", "marker"), MARKERS.items(), ids=list(MARKERS))
def test_supersession_fixture_is_the_right_capture(slug: str, marker: str) -> None:
    assert marker in load_fixture(f"supersession/{slug}.html")
