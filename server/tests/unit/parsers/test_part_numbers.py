import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.parsers.part_numbers import JUNK_PART, matches, normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("11427953129", "11427953129"),
        ("11 42 7 953 129", "11427953129"),
        ("11-42-7-953-129", "11427953129"),
        ("11.42.7.953.129", "11427953129"),
        ("  11427953129\n", "11427953129"),
        ("7953129", "7953129"),
        ("795 3129", "7953129"),
        ("00000000000", "00000000000"),
    ],
)
def test_normalize_accepts_7_or_11_digits_with_separators(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "abc", "1142795312", "114279531290", "123456", "11427953129a", "11_42_7_953_129"],
)
def test_normalize_rejects_everything_else(raw: str) -> None:
    with pytest.raises(InvalidInput) as info:
        normalize(raw)
    assert "11 digits" in info.value.message
    assert repr(raw) in info.value.message


@pytest.mark.parametrize(
    ("query", "returned", "expected"),
    [
        ("11427953129", "11427953129", True),
        ("7953129", "11427953129", True),
        ("99999999999", "00009999999", False),  # RealOEM's last-7 false match
        ("9999999", "00009999999", True),
        ("11427953129", "11427953128", False),
        ("7953129", "11427953128", False),
        ("00000000000", JUNK_PART, False),  # junk part never matches
        ("0000000", JUNK_PART, False),
    ],
)
def test_matches(query: str, returned: str, expected: bool) -> None:
    assert matches(query, returned) is expected
