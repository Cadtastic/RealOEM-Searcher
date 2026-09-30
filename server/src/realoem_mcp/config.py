"""Runtime settings. Every field except lang and user_agent can be overridden by environment."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from realoem_mcp import __version__

REPO_URL = "https://github.com/Cadtastic/RealOEM-Searcher"
USER_AGENT = f"RealOEM-Searcher/{__version__} (+{REPO_URL})"
MIN_INTERVAL_FLOOR_S = 1.0
# src/realoem_mcp/config.py -> parents[3] is the repository root that holds brands/.
DEFAULT_BRANDS_DIR = Path(__file__).resolve().parents[3] / "brands"


def _default_cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir("realoem-searcher"))


def _default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir("realoem-searcher"))


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://www.realoem.com"
    min_interval_s: float = 2.0
    timeout_s: float = 20.0
    cache_dir: Path = field(default_factory=_default_cache_dir)
    data_dir: Path = field(default_factory=_default_data_dir)  # durable data (vehicle index)
    brands_dir: Path = DEFAULT_BRANDS_DIR
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

    def __post_init__(self) -> None:
        for name in ("min_interval_s", "timeout_s"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number, got {getattr(self, name)!r}")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(
            self, "min_interval_s", max(float(self.min_interval_s), MIN_INTERVAL_FLOOR_S)
        )
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        object.__setattr__(self, "cache_dir", Path(self.cache_dir))
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "brands_dir", Path(self.brands_dir))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        kwargs: dict[str, object] = {}
        if value := env.get("REALOEM_BASE_URL"):
            kwargs["base_url"] = value
        if value := env.get("REALOEM_MIN_INTERVAL"):
            kwargs["min_interval_s"] = _to_float("REALOEM_MIN_INTERVAL", value)
        if value := env.get("REALOEM_TIMEOUT"):
            kwargs["timeout_s"] = _to_float("REALOEM_TIMEOUT", value)
        if value := env.get("REALOEM_CACHE_DIR"):
            kwargs["cache_dir"] = Path(value)
        if value := env.get("REALOEM_DATA_DIR"):
            kwargs["data_dir"] = Path(value)
        if value := env.get("REALOEM_BRANDS_DIR"):
            kwargs["brands_dir"] = Path(value)
        return cls(**kwargs)  # type: ignore[arg-type]


def _to_float(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of seconds, got {value!r}")
    return number
