"""The only way the server talks to RealOEM: rate limited, cached, honest (AD6, AD8, AD13, AD14)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode, urlsplit

from realoem_mcp.config import Settings
from realoem_mcp.page_types import PageType

_PATH_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Page:
    page_type: PageType
    url: str  # canonical request URL (cache key)
    final_url: str  # after redirects
    status: int
    html: str
    fetched_at: datetime  # UTC
    from_cache: bool

    @property
    def redirected_away(self) -> bool:
        """True when RealOEM redirected to another page (e.g. /bmw/ for an invalid id)."""
        requested = urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1]
        return not urlsplit(self.final_url).path.rstrip("/").endswith("/" + requested)


def build_url(settings: Settings, path: str, params: Mapping[str, str]) -> str:
    """`{base_url}/bmw/{lang}/{path}?{params}`, params in the order given, spaces as %20."""
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"invalid RealOEM path {path!r}")
    if any(key.lower() == "dmode" for key in params):
        raise ValueError("dmode is never sent to RealOEM (AD7)")
    url = f"{settings.base_url}/bmw/{settings.lang}/{path}"
    if params:
        url += "?" + urlencode(list(params.items()), quote_via=quote)
    return url
