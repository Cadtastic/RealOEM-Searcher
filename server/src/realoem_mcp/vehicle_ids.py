"""RealOEM vehicle ids, e.g. VB13-USA-10-2005-E90-BMW-325i (site notes section 2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote

from realoem_mcp.errors import InvalidInput

DEFAULT_BRAND_SEGMENTS: tuple[str, ...] = ("Rolls_Royce", "Zinoro", "Mini", "BMW")

_HEAD = r"(?P<type>[^-]+)-(?P<market>[^-]+)-"
# (pattern, separator between series, brand segment and model)
_FORMS: tuple[tuple[re.Pattern[str], str], ...] = (
    # VB13-USA-10-2005-E90-BMW-325i
    (re.compile(_HEAD + r"(?P<month>\d{2})-(?P<year>\d{4})-(?P<rest>.+)"), "-"),
    # VB13-USA-02_2004_E90_BMW_325i (partxref links)
    (re.compile(_HEAD + r"(?P<month>\d{2})_(?P<year>\d{4})_(?P<rest>.+)"), "_"),
    # VB13-USA---E90-BMW-325i (no date)
    (re.compile(_HEAD + r"--(?P<rest>.+)"), "-"),
)


@dataclass(frozen=True)
class VehicleId:
    raw: str
    type_code: str
    market: str
    month: str | None = None  # "10"
    year: str | None = None  # "2005"
    series: str | None = None
    brand_segment: str | None = None
    model: str | None = None

    @classmethod
    def parse(
        cls, raw: str, *, brand_segments: Sequence[str] = DEFAULT_BRAND_SEGMENTS
    ) -> VehicleId:
        text = unquote(raw).strip()
        if not text:
            raise InvalidInput("The vehicle id is empty.")
        for pattern, sep in _FORMS:
            match = pattern.fullmatch(text)
            if match is None:
                continue
            series, _, after = match["rest"].partition(sep)
            brand_segment, model = _split_brand(after, sep, brand_segments)
            return cls(
                raw=text,
                type_code=match["type"],
                market=match["market"],
                month=match.groupdict().get("month"),
                year=match.groupdict().get("year"),
                series=series or None,
                brand_segment=brand_segment,
                model=model,
            )
        type_code, _, rest = text.partition("-")
        return cls(raw=text, type_code=type_code, market=rest.split("-", 1)[0])

    @property
    def production_month(self) -> str | None:
        """Production month as "YYYY-MM", or None when the id carries no date."""
        if self.year is None or self.month is None:
            return None
        return f"{self.year}-{self.month}"

    def __str__(self) -> str:
        return self.raw


def _split_brand(
    after: str, sep: str, brand_segments: Sequence[str]
) -> tuple[str | None, str | None]:
    for segment in sorted(brand_segments, key=len, reverse=True):
        if after == segment:
            return segment, None
        if after.startswith(segment + sep):
            return segment, after[len(segment) + len(sep) :] or None
    return None, None
