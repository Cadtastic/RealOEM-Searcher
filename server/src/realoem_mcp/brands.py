"""Brand registry loaded from brands/<id>/brand.toml (AD9)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from realoem_mcp.vehicle_ids import VehicleId

_LIST_KEYS = ("id_brand_segments", "series_patterns", "label_keywords", "wmi")
_KNOWN_KEYS = {"id", "display_name", "product", "notes", "dedupe_repeated_names", "priority"}
_KNOWN_KEYS.update(_LIST_KEYS)
_REQUIRED_BRAND_IDS = ("bmw", "motorrad")  # the fallbacks BrandRegistry relies on


@dataclass(frozen=True)
class Brand:
    id: str
    display_name: str
    product: str  # "P" cars, "M" motorcycles
    id_brand_segments: tuple[str, ...] = ()
    series_patterns: tuple[str, ...] = ()
    label_keywords: tuple[str, ...] = ()
    wmi: tuple[str, ...] = ()
    notes: str = ""
    dedupe_repeated_names: bool = False
    priority: int = 100
    extra: Mapping[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))

    @classmethod
    def from_toml(cls, path: Path) -> Brand:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in ("id", "display_name", "product"):
            if key not in data:
                raise ValueError(f"{path}: missing required key {key!r}")
        if data["product"] not in ("P", "M"):
            raise ValueError(f"{path}: product must be 'P' or 'M', got {data['product']!r}")
        if data["id"] != path.parent.name:
            raise ValueError(f"{path}: id {data['id']!r} must match its directory name")
        _check_types(path, data)
        return cls(
            id=data["id"],
            display_name=data["display_name"],
            product=data["product"],
            id_brand_segments=tuple(data.get("id_brand_segments", ())),
            series_patterns=tuple(data.get("series_patterns", ())),
            label_keywords=tuple(data.get("label_keywords", ())),
            wmi=tuple(data.get("wmi", ())),
            notes=data.get("notes", ""),
            dedupe_repeated_names=data.get("dedupe_repeated_names", False),
            priority=data.get("priority", 100),
            extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
        )

    def matches_label(self, label: str) -> bool:
        return any(keyword in label for keyword in self.label_keywords)

    def matches_series(self, code: str) -> bool:
        return any(re.search(pattern, code) for pattern in self.series_patterns)


def _check_types(path: Path, data: dict[str, Any]) -> None:
    for key in _LIST_KEYS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{path}: {key} must be a list of strings, got {value!r}")
    flag = data.get("dedupe_repeated_names", False)
    if not isinstance(flag, bool):
        raise ValueError(f"{path}: dedupe_repeated_names must be true or false, got {flag!r}")
    priority = data.get("priority", 100)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(f"{path}: priority must be an integer, got {priority!r}")
    for pattern in data.get("series_patterns", []):
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(
                f"{path}: invalid series_patterns entry {pattern!r}: {error}"
            ) from None


class BrandRegistry:
    def __init__(self, brands: Iterable[Brand]) -> None:
        self._brands = sorted(brands, key=lambda b: (b.priority, b.id))
        self._by_id = {b.id: b for b in self._brands}

    @classmethod
    def load(cls, directory: Path) -> BrandRegistry:
        files = sorted(Path(directory).glob("*/brand.toml"))
        if not files:
            raise FileNotFoundError(f"No brands/*/brand.toml files found under {directory}")
        brands = [Brand.from_toml(path) for path in files]
        present = {brand.id for brand in brands}
        missing = [brand_id for brand_id in _REQUIRED_BRAND_IDS if brand_id not in present]
        if missing:
            raise ValueError(
                f"{directory}: required brand(s) missing: {', '.join(missing)} "
                "(the registry falls back to them)"
            )
        return cls(brands)

    def __iter__(self) -> Iterator[Brand]:
        return iter(self._brands)

    def __len__(self) -> int:
        return len(self._brands)

    def get(self, brand_id: str) -> Brand:
        return self._by_id[brand_id]

    def brand_segments(self) -> tuple[str, ...]:
        segments: dict[str, None] = {}
        for brand in self._brands:
            segments.update(dict.fromkeys(brand.id_brand_segments))
        return tuple(segments)

    def for_series(
        self, code: str | None, *, label: str | None = None, product: str | None = None
    ) -> Brand:
        candidates = [b for b in self._brands if product is None or b.product == product]
        return self._match(code, label, candidates) or self._fallback(product)

    def for_vehicle_id(self, vid: VehicleId, *, product: str | None = None) -> Brand:
        candidates = [b for b in self._brands if vid.brand_segment in b.id_brand_segments]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return self.for_series(vid.series, product=product)
        narrowed = [b for b in candidates if product is None or b.product == product] or candidates
        return self._match(vid.series, None, narrowed) or narrowed[-1]

    def for_wmi(self, prefix: str) -> Brand | None:
        wmi = prefix[:3].upper()
        return next((b for b in self._brands if wmi in b.wmi), None)

    @staticmethod
    def _match(code: str | None, label: str | None, candidates: list[Brand]) -> Brand | None:
        if label:
            for brand in candidates:
                if brand.matches_label(label):
                    return brand
        if code:
            for brand in candidates:
                if brand.matches_series(code):
                    return brand
        return None

    def _fallback(self, product: str | None) -> Brand:
        """Default brand per product; the registry must contain "bmw" and "motorrad"."""
        return self.get("motorrad" if product == "M" else "bmw")
