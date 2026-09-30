"""BMW part numbers: input normalization and returned-number verification (site notes 3.2)."""

from __future__ import annotations

import re

from realoem_mcp.errors import InvalidInput

JUNK_PART = "00000000000"  # RealOEM's answer to junk input; never a real match
_SEPARATORS = re.compile(r"[\s.\-]+")
_DIGITS = re.compile(r"[0-9]{7}|[0-9]{11}")


def normalize(raw: str) -> str:
    """Digits of a part number: 11 digits or the 7-digit short form.

    Spaces, dashes and dots are removed first; anything else raises InvalidInput, so malformed
    input never reaches RealOEM.
    """
    digits = _SEPARATORS.sub("", raw)
    if not _DIGITS.fullmatch(digits):
        raise InvalidInput(
            f"{raw!r} is not a BMW part number. Enter 11 digits (e.g. 11427953129) or the last "
            "7 digits (7953129); spaces, dashes and dots are allowed."
        )
    return digits


def matches(query: str, returned: str) -> bool:
    """True when the part RealOEM returned is the part that was asked for.

    RealOEM matches on the last 7 digits, so an 11-digit query must match exactly and a 7-digit
    query must be the last 7 digits of an 11-digit number. The junk part never matches.
    """
    if returned == JUNK_PART or len(returned) != 11:
        return False
    if len(query) == 11:
        return returned == query
    return len(query) == 7 and returned.endswith(query)
