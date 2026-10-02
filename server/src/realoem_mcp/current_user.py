"""Who is calling (hosted mode) and when the current tool call started (hosted design 4.1)."""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.auth.middleware.auth_context import get_access_token

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

NOT_SIGNED_IN = "You are not signed in to RealOEM Searcher; connect it in Claude and try again."

# Start of the tool call being handled (monotonic seconds); None outside a call. The HTTP server
# must install CallClock, or no deadline ever applies.
call_started_at: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "realoem_call_started_at", default=None
)


@dataclass(frozen=True)
class CurrentUser:
    subject: str  # "github:<numeric id>"
    is_admin: bool


def current_user(settings: Settings) -> CurrentUser | None:
    """The signed-in caller, from the access token the SDK validated for this request."""
    token = get_access_token()
    if token is None or not token.subject:
        return None
    return CurrentUser(subject=token.subject, is_admin=token.subject in settings.admins)


def time_left(settings: Settings, clock: Callable[[], float]) -> float | None:
    """Seconds until the current tool call's deadline; None outside a tool call.

    clock must be the clock CallClock stamps call_started_at with.
    """
    started = call_started_at.get()
    if started is None:
        return None
    return settings.call_deadline_s - (clock() - started)


def require_user(settings: Settings) -> CurrentUser:
    """The signed-in caller; hosted-mode code paths call this so a missing user fails closed."""
    user = current_user(settings)
    if user is None:
        raise RealOemError(NOT_SIGNED_IN)
    return user


class CallClock:
    """ServerMiddleware that records when each inbound message started (for the call deadline)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        token = call_started_at.set(self._clock())
        try:
            return await call_next(ctx)
        finally:
            call_started_at.reset(token)
