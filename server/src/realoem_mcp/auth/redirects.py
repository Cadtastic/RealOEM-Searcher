"""Which redirect URIs a client may use (hosted design 4.3). A security invariant.

The SDK redirects some /authorize errors to the registered URI before anyone signs in. That is
safe only because registration admits nothing but Claude's own callback (an exact string) and
programs on the user's computer (http://localhost or http://127.0.0.1, any port).
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl

from realoem_mcp.config import LOOPBACK_HOSTS

MAX_LOOPBACK_URI = 512


def is_loopback(uri: str) -> bool:
    """http://localhost or http://127.0.0.1, any port, no user info, no fragment, short."""
    if len(uri) > MAX_LOOPBACK_URI or "#" in uri:
        return False
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    return parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS and "@" not in parts.netloc


def is_allowed(uri: str, allowlist: Iterable[str]) -> bool:
    return uri in tuple(allowlist) or is_loopback(uri)


def _same_but_port(registered: str, requested: str) -> bool:
    a, b = urlsplit(registered), urlsplit(requested)
    # An empty path is "/": the SDK keeps a registered "http://127.0.0.1:33418" as it is, but
    # turns the same URI in an /authorize request into "http://127.0.0.1:33418/".
    return (a.scheme, a.hostname, a.path or "/", a.query) == (
        b.scheme,
        b.hostname,
        b.path or "/",
        b.query,
    )


class ClaudeClient(OAuthClientInformationFull):
    """A registered client. A loopback redirect URI matches on everything but the port (a local
    program listens on whatever port is free); every other URI must match exactly."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and is_loopback(str(redirect_uri)):
            for registered in self.redirect_uris or []:
                if is_loopback(str(registered)) and _same_but_port(
                    str(registered), str(redirect_uri)
                ):
                    return redirect_uri  # with its port, so /token's equality check passes
            raise InvalidRedirectUriError(
                f"Redirect URI '{redirect_uri}' not registered for client"
            )
        return super().validate_redirect_uri(redirect_uri)
