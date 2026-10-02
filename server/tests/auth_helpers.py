"""Test helper: act as a signed-in user, the way the SDK's bearer middleware does over HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken


@contextmanager
def signed_in(subject: str | None, *, scopes: tuple[str, ...] = ("realoem",)) -> Iterator[None]:
    """Inside the block get_access_token() returns a token for `subject`; tools called through
    the in-memory mcp.Client see it too."""
    token = AccessToken(
        token="test-token", client_id="test-client", scopes=list(scopes), subject=subject
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)
