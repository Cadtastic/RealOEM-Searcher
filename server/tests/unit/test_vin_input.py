import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.tools.vin import VinInput, normalize_vin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PX22770", VinInput(serial="PX22770", wmi=None)),
        ("px22770", VinInput(serial="PX22770", wmi=None)),
        (" px-22 770 ", VinInput(serial="PX22770", wmi=None)),
        ("...PX22770", VinInput(serial="PX22770", wmi=None)),
        ("1234567", VinInput(serial="1234567", wmi=None)),
        ("WBA0000000PX22770", VinInput(serial="PX22770", wmi="WBA")),
        ("wba 0000000 px22770", VinInput(serial="PX22770", wmi="WBA")),
        ("WBA-0000000-PX22770", VinInput(serial="PX22770", wmi="WBA")),
        ("WBA.0000000/PX22770", VinInput(serial="PX22770", wmi="WBA")),
    ],
)
def test_normalize_vin_keeps_the_last_seven_and_the_prefix(raw: str, expected: VinInput) -> None:
    assert normalize_vin(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "A VIN has 17 characters; give all 17 or just the last 7 (got 0)."),
        ("PX2277", "A VIN has 17 characters; give all 17 or just the last 7 (got 6)."),
        ("PX227701", "A VIN has 17 characters; give all 17 or just the last 7 (got 8)."),
        ("WBA0000000PX2277", "A VIN has 17 characters; give all 17 or just the last 7 (got 16)."),
        ("PX22770#", "'PX22770#' is not a VIN: a VIN has only letters and digits."),
        ("PX2Ä770", "'PX2Ä770' is not a VIN: a VIN has only letters and digits."),
        # U+017F (long s) upper-cases to an ASCII "S"; it must still be rejected.
        ("PX2\u017f770", "'PX2\u017f770' is not a VIN: a VIN has only letters and digits."),
        (
            "PX2277O",
            "VINs never contain the letters I, O or Q (found O); "
            "check for a 1 or 0 typed as a letter.",
        ),
        (
            "WBAIQ00000PX22770",
            "VINs never contain the letters I, O or Q (found I, Q); "
            "check for a 1 or 0 typed as a letter.",
        ),
    ],
)
def test_normalize_vin_rejects_malformed_input(raw: str, message: str) -> None:
    with pytest.raises(InvalidInput) as info:
        normalize_vin(raw)
    assert info.value.message == message
