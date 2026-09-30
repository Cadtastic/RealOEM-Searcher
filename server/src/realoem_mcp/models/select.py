"""Select-cascade models (ARD section 5.11): parser output of parsers/select.py, reused by C."""

from __future__ import annotations

from pydantic import BaseModel

# Cascade levels in page order (data-ro-level values). Classic cars add steering and trans.
LEVELS: tuple[str, ...] = (
    "product",
    "catalog",
    "series",
    "body",
    "model",
    "market",
    "prod",
    "engine",
    "steering",
    "trans",
)
# Query parameter that carries each level's code; only "catalog" differs from its level name.
LEVEL_PARAMS: dict[str, str] = {level: level for level in LEVELS} | {"catalog": "archive"}


class SelectOption(BaseModel):
    value: str  # the level's query parameter value, e.g. "E93", "Cab", "20080700"
    label: str  # text RealOEM shows, e.g. "3' E93 (2005 — 2010)", "Convertible", "07/2008"
    selected: bool  # effective selection, including levels RealOEM auto-selected


class SelectLevel(BaseModel):
    level: str  # one of LEVELS
    label: str  # RealOEM's caption without the colon, e.g. "Prod Month"
    options: list[SelectOption]

    @property
    def selected_option(self) -> SelectOption | None:
        return next((option for option in self.options if option.selected), None)


class SelectPage(BaseModel):
    levels: list[SelectLevel]  # in page order; absent levels (e.g. motorcycle body) are omitted
    vehicle_id: str | None  # set once the cascade is complete (or a VIN matched)
    type_code: str | None
    summary: str | None  # "You Have Selected:" text, e.g. "3 Series E93 BMW 328i"

    def level(self, name: str) -> SelectLevel | None:
        return next((level for level in self.levels if level.level == name), None)

    def selected(self, name: str) -> SelectOption | None:
        level = self.level(name)
        return level.selected_option if level is not None else None
