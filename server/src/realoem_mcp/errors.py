"""Error hierarchy. `.message` is written for the end user (NFR8)."""

from __future__ import annotations


class RealOemError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInput(RealOemError):
    """Input rejected before any request was made."""


class NotFound(RealOemError):
    """RealOEM has no such part, vehicle or VIN."""


class BotChallenge(RealOemError):
    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            "RealOEM is showing a bot challenge (Cloudflare) and is blocking automated requests. "
            f"Try again later, or open {url} in a browser."
        )


class LayoutChanged(RealOemError):
    def __init__(self, page_type: str, detail: str, url: str) -> None:
        self.page_type = str(page_type)
        self.detail = detail
        self.url = url
        super().__init__(
            f"RealOEM's {self.page_type} page did not have the expected structure ({detail}). "
            f"The site may have changed; this plugin needs an update. Page: {url}"
        )


class UpstreamError(RealOemError):
    def __init__(self, status: int | None, url: str, detail: str | None = None) -> None:
        self.status = status
        self.url = url
        reason = f"HTTP {status}" if status is not None else (detail or "a network error")
        super().__init__(f"RealOEM request failed ({reason}) for {url}. Try again later.")
