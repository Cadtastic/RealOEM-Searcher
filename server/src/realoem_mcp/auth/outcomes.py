"""What the sign-in steps tell the pages to do next (hosted design 4.3, 4.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal["expired", "banned", "github_unavailable"]


@dataclass(frozen=True)
class StartGitHub:
    """Consent given: send the browser to GitHub, remembering state in a cookie."""

    url: str
    state: str


@dataclass(frozen=True)
class RedirectToClient:
    """Send the browser back to the client's redirect URI (with a code or an error)."""

    url: str


@dataclass(frozen=True)
class ShowError:
    """Show an error page; never a redirect."""

    kind: ErrorKind


@dataclass(frozen=True)
class ConsentDetails:
    """What the consent page shows; everything trusted stays on the server-side row."""

    request_id: str
    client_name: str | None
    redirect_uri: str
    scopes: tuple[str, ...]


class ExpiredRequest(Exception):
    """The pending sign-in is unknown, already decided, or out of time."""
