"""Rows of the sign-in database (hosted design 4.4). Times are integer epoch seconds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# A pending request's status moves forward only: awaiting_consent -> consented -> github_returned,
# or awaiting_consent -> denied.
AWAITING_CONSENT = "awaiting_consent"
CONSENTED = "consented"
GITHUB_RETURNED = "github_returned"
DENIED = "denied"


@dataclass(frozen=True)
class ClientRecord:
    client_id: str
    client_secret: str | None  # in clear: the SDK compares it directly
    metadata: dict[str, Any]  # the kept registration fields
    created_at: int
    last_issued_at: int | None


@dataclass(frozen=True)
class PendingRequest:
    """An /authorize request waiting for consent and the GitHub sign-in."""

    id: str
    client_id: str
    redirect_uri: str
    redirect_uri_explicit: bool
    client_state: str | None
    code_challenge: str
    resource: str
    scopes: tuple[str, ...]
    status: str
    expires_at: int
    subject: str | None = None


@dataclass(frozen=True)
class CodeRecord:
    hash: str
    family: str  # the token family the code's exchange creates (revoked if the code is replayed)
    client_id: str
    redirect_uri: str
    redirect_uri_explicit: bool
    code_challenge: str
    resource: str
    scopes: tuple[str, ...]
    subject: str
    expires_at: int
    used_at: int | None


@dataclass(frozen=True)
class TokenRecord:
    """An access or refresh token, with the state of its family and its user."""

    hash: str
    kind: str  # "access" or "refresh"
    family: str
    subject: str
    client_id: str
    scopes: tuple[str, ...]
    resource: str
    expires_at: int
    rotated_at: int | None
    family_revoked: bool
    family_expires_at: int
    banned: bool


@dataclass(frozen=True)
class UserRecord:
    subject: str  # "github:<numeric id>"
    github_login: str
    github_created_at: datetime | None
    first_seen: int
    banned_at: int | None
    banned_reason: str | None
