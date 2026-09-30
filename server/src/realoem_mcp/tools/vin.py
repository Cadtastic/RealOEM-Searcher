"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from realoem_mcp.errors import InvalidInput

_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)
