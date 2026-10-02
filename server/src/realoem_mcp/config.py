"""Runtime settings. Every field except mode, lang and user_agent can be set by environment."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import platformdirs

from realoem_mcp import __version__

REPO_URL = "https://github.com/Cadtastic/RealOEM-Searcher"
USER_AGENT = f"RealOEM-Searcher/{__version__} (+{REPO_URL})"
MIN_INTERVAL_FLOOR_S = 1.0
HTTP_CACHE_MAX_MB = 400  # at most 40 % of the hosted server's 1 GB volume
CACHE_MIN_FREE_MB = 100  # hosted server: below this much free disk, stop caching
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
    # Hosted ("http") mode. The mode is set by the entry point, never by the environment.
    mode: Literal["stdio", "http"] = "stdio"
    admins: frozenset[str] = frozenset()  # subjects, e.g. "github:1234"
    user_daily_limit: int = 300  # cache-miss page fetches per user per UTC day; 0 = unlimited
    new_user_daily_limit: int = 30  # the same for GitHub accounts younger than the age below
    min_account_age_days: int = 30
    global_daily_limit: int = 0  # server-wide cap on the same count; 0 = off
    call_deadline_s: float = 50.0  # a tool call older than this starts no new RealOEM request
    cache_max_mb: int | None = None  # None = HTTP_CACHE_MAX_MB in http mode, no cap in stdio
    lang: str = field(default="enUS", init=False)  # AD12: fixed
    user_agent: str = field(default=USER_AGENT, init=False)  # AD13: not overridable

    def __post_init__(self) -> None:
        for name in ("min_interval_s", "timeout_s"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number, got {getattr(self, name)!r}")
        if float(self.timeout_s) <= 0:
            raise ValueError(f"timeout_s must be greater than 0, got {self.timeout_s!r}")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(
            self, "min_interval_s", max(float(self.min_interval_s), MIN_INTERVAL_FLOOR_S)
        )
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        object.__setattr__(self, "cache_dir", Path(self.cache_dir).expanduser())
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser())
        object.__setattr__(self, "brands_dir", Path(self.brands_dir).expanduser())
        if self.mode not in ("stdio", "http"):
            raise ValueError(f"mode must be 'stdio' or 'http', got {self.mode!r}")
        for name in _COUNT_FIELDS:
            value = getattr(self, name)
            if name == "cache_max_mb" and value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a whole number of 0 or more, got {value!r}")
        deadline = self.call_deadline_s
        if isinstance(deadline, bool) or not math.isfinite(float(deadline)) or float(deadline) <= 0:
            raise ValueError(
                f"call_deadline_s must be a finite number greater than 0, got {deadline!r}"
            )
        object.__setattr__(self, "call_deadline_s", float(deadline))
        if isinstance(self.admins, str) or not all(
            isinstance(subject, str) and subject.startswith("github:") for subject in self.admins
        ):
            raise ValueError(f"admins must be a set of 'github:<id>' subjects, got {self.admins!r}")
        object.__setattr__(self, "admins", frozenset(self.admins))

    @property
    def cache_max_bytes(self) -> int:
        """The page cache's size cap in bytes; 0 = no cap."""
        megabytes = self.cache_max_mb
        if megabytes is None:
            megabytes = HTTP_CACHE_MAX_MB if self.mode == "http" else 0
        return megabytes * 1024 * 1024

    @property
    def cache_min_free_bytes(self) -> int:
        """Free disk space below which new pages are not cached; 0 = no floor (stdio)."""
        return CACHE_MIN_FREE_MB * 1024 * 1024 if self.mode == "http" else 0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        kwargs: dict[str, object] = {}
        if value := env.get("REALOEM_BASE_URL"):
            kwargs["base_url"] = value
        if value := env.get("REALOEM_MIN_INTERVAL"):
            kwargs["min_interval_s"] = _to_float("REALOEM_MIN_INTERVAL", value)
        if value := env.get("REALOEM_TIMEOUT"):
            timeout = _to_float("REALOEM_TIMEOUT", value)
            if timeout <= 0:
                raise ValueError(f"REALOEM_TIMEOUT must be greater than 0, got {value!r}")
            kwargs["timeout_s"] = timeout
        if value := env.get("REALOEM_CACHE_DIR"):
            kwargs["cache_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_DATA_DIR"):
            kwargs["data_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_BRANDS_DIR"):
            kwargs["brands_dir"] = Path(value).expanduser()
        if value := env.get("REALOEM_ADMINS"):
            kwargs["admins"] = _to_admins(value)
        for env_name, field_name in _COUNT_ENV.items():
            if value := env.get(env_name):
                kwargs[field_name] = _to_count(env_name, value)
        if value := env.get("REALOEM_CALL_DEADLINE_S"):
            deadline = _to_float("REALOEM_CALL_DEADLINE_S", value)
            if deadline <= 0:
                raise ValueError(f"REALOEM_CALL_DEADLINE_S must be greater than 0, got {value!r}")
            kwargs["call_deadline_s"] = deadline
        return cls(**kwargs)  # type: ignore[arg-type]


_COUNT_ENV = {
    "REALOEM_USER_DAILY_LIMIT": "user_daily_limit",
    "REALOEM_NEW_USER_DAILY_LIMIT": "new_user_daily_limit",
    "REALOEM_MIN_ACCOUNT_AGE_DAYS": "min_account_age_days",
    "REALOEM_GLOBAL_DAILY_LIMIT": "global_daily_limit",
    "REALOEM_CACHE_MAX_MB": "cache_max_mb",
}
_COUNT_FIELDS = tuple(_COUNT_ENV.values())


def _to_count(name: str, value: str) -> int:
    text = value.strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"{name} must be a whole number of 0 or more, got {value!r}")
    return int(text)


def _to_admins(value: str) -> frozenset[str]:
    ids = [part.strip() for part in value.split(",") if part.strip()]
    for part in ids:
        if not (part.isascii() and part.isdigit()):
            raise ValueError(
                f"REALOEM_ADMINS must be comma-separated GitHub numeric ids, got {part!r}"
            )
    return frozenset(f"github:{part}" for part in ids)


def _to_float(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of seconds, got {value!r}")
    return number
