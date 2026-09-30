from datetime import date

import pytest

from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.tools.supersession import choose_successor


def _entry(number: str, start: date | None, end: date | None) -> SupersessionEntry:
    return SupersessionEntry(
        part_number=number,
        description=None,
        valid_from=start,
        valid_to=end,
        remark=None,
        in_catalog=True,
    )


def test_open_ended_entry_wins_over_a_later_start() -> None:
    # site notes 3.5: intermediates can start later than the current part, so the open end wins
    entries = [
        _entry("11111111111", date(2006, 2, 13), date(2017, 1, 30)),
        _entry("22222222222", date(2017, 6, 1), None),
        _entry("33333333333", date(2018, 1, 1), date(2018, 9, 21)),
    ]
    assert choose_successor(entries).part_number == "22222222222"


def test_latest_start_among_open_ended_entries() -> None:
    entries = [
        _entry("11111111111", date(2016, 9, 1), None),
        _entry("22222222222", date(2017, 6, 1), None),
        _entry("33333333333", None, None),
    ]
    assert choose_successor(entries).part_number == "22222222222"


def test_without_open_end_the_latest_end_then_the_latest_start() -> None:
    entries = [
        _entry("11111111111", date(2006, 2, 13), date(2017, 1, 30)),
        _entry("22222222222", date(2016, 9, 1), date(2017, 9, 21)),
        _entry("33333333333", date(2017, 1, 1), date(2017, 9, 21)),
    ]
    assert choose_successor(entries).part_number == "33333333333"


def test_ties_keep_page_order() -> None:
    entries = [
        _entry("11111111111", date(2017, 6, 1), None),
        _entry("22222222222", date(2017, 6, 1), None),
    ]
    assert choose_successor(entries).part_number == "11111111111"


def test_empty_list_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        choose_successor([])
