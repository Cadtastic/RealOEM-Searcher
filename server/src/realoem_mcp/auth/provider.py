"""The OAuth 2.1 authorization server behind the SDK's routes (hosted design 4.3).

Pure logic over the store, GitHub and the keys: no Starlette here (the pages own cookies and the
CSRF MAC). The SDK already enforces PKCE S256 at /token, code binding to client_id and
redirect_uri, refresh-token binding to the client, scope narrowing, 401/403 semantics and the
resource check on bearer tokens; this class adds only what the design table says.
"""

from __future__ import annotations

import hmac
import logging
import re
import time
from collections.abc import Callable, Mapping
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull

from realoem_mcp.auth.github import GitHubLogin, GitHubUnavailable
from realoem_mcp.auth.keys import Keys, b64url, new_secret, pkce_challenge
from realoem_mcp.auth.outcomes import (
    ConsentDetails,
    ExpiredRequest,
    RedirectToClient,
    ShowError,
    StartGitHub,
)
from realoem_mcp.auth.records import AWAITING_CONSENT, ClientRecord, CodeRecord, PendingRequest
from realoem_mcp.auth.redirects import ClaudeClient, is_allowed
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings

SCOPE = "realoem"
PENDING_LIFETIME = timedelta(minutes=10)
CODE_LIFETIME = timedelta(minutes=10)
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_IDLE = timedelta(days=30)  # a refresh token unused this long expires
FAMILY_LIFETIME = timedelta(days=90)  # absolute: a sign-in lasts at most this long
MAX_FAMILIES = 20  # live sign-ins per user; the oldest is revoked first
MAX_REDIRECT_URIS = 5
MAX_CLIENT_NAME = 200
MAX_STATE = 512
MAX_PARAMETER = 256  # resource and scope
KEPT_METADATA = {
    "client_name",
    "redirect_uris",
    "grant_types",
    "response_types",
    "token_endpoint_auth_method",
    "scope",
}  # every other registration field (jwks, contacts, ...) is dropped
_CODE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")

log = logging.getLogger(__name__)


def _seconds(span: timedelta) -> int:
    return int(span.total_seconds())


def _same_resource(given: str, expected: str) -> bool:
    """URL comparison: scheme and host ignore case, a trailing slash is ignored."""
    a, b = urlsplit(given), urlsplit(expected)
    return (a.scheme.lower(), a.netloc.lower(), a.path.rstrip("/"), a.query, a.fragment) == (
        b.scheme.lower(),
        b.netloc.lower(),
        b.path.rstrip("/"),
        b.query,
        b.fragment,
    )


class IssuedCode(AuthorizationCode):
    family: str


class IssuedRefreshToken(RefreshToken):
    family: str
    family_expires_at: int


class IssuedAccessToken(AccessToken):
    family: str


class RealOemAuthProvider(
    OAuthAuthorizationServerProvider[IssuedCode, IssuedRefreshToken, IssuedAccessToken]
):
    def __init__(
        self,
        settings: Settings,
        store: AuthStore,
        github: GitHubLogin,
        keys: Keys,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._store = store
        self._github = github
        self._keys = keys
        self._clock = clock
        self.resource = f"{settings.public_url}/mcp"

    def _now(self) -> int:
        return int(self._clock())

    def _verifier(self, request_id: str, state: str) -> str:
        """The PKCE verifier for GitHub, derived (never stored): 43 base64url characters."""
        return b64url(self._keys.digest("github-pkce", f"{request_id}|{state}"))

    # --- registration -------------------------------------------------------------------------

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(uri) for uri in client_info.redirect_uris or []]
        if not uris or len(uris) > MAX_REDIRECT_URIS:
            raise RegistrationError(
                "invalid_redirect_uri", f"register between 1 and {MAX_REDIRECT_URIS} redirect URIs"
            )
        for uri in uris:
            if not is_allowed(uri, self._settings.redirect_allowlist):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "only Claude's callback and http://localhost or http://127.0.0.1 redirect "
                    "URIs can be registered",
                )
        if client_info.client_name is not None and len(client_info.client_name) > MAX_CLIENT_NAME:
            raise RegistrationError("invalid_client_metadata", "client_name is too long")
        metadata = client_info.model_dump(mode="json", include=KEPT_METADATA, exclude_none=True)
        self._store.add_client(
            ClientRecord(
                client_id=client_info.client_id,
                client_secret=client_info.client_secret,
                metadata=metadata,
                created_at=self._now(),
                last_issued_at=None,
            )
        )

    async def get_client(self, client_id: str) -> ClaudeClient | None:
        """The client, with only the redirect URIs the allow-list admits today (an operator may
        have narrowed it since the client registered); None when none is left."""
        record = self._store.client(client_id)
        if record is None:
            return None
        allowed = [
            uri
            for uri in record.metadata.get("redirect_uris", [])
            if is_allowed(uri, self._settings.redirect_allowlist)
        ]
        if not allowed:
            return None
        return ClaudeClient.model_validate(
            {
                **record.metadata,
                "redirect_uris": allowed,
                "client_id": record.client_id,
                "client_secret": record.client_secret,
            }
        )

    # --- sign-in: /authorize, consent, GitHub -------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Store the request and send the browser to the consent page. Never contacts GitHub."""
        if params.state is not None and len(params.state) > MAX_STATE:
            raise AuthorizeError("invalid_request", "state is too long")
        if not _CODE_CHALLENGE.fullmatch(params.code_challenge):
            raise AuthorizeError("invalid_request", "code_challenge must be an S256 challenge")
        if params.resource is not None and len(params.resource) > MAX_PARAMETER:
            raise AuthorizeError("invalid_request", "resource is too long")
        scopes = params.scopes or [SCOPE]
        if len(" ".join(scopes)) > MAX_PARAMETER:
            raise AuthorizeError("invalid_request", "scope is too long")
        if params.resource is not None and not _same_resource(params.resource, self.resource):
            raise AuthorizeError("invalid_target", f"this server's resource is {self.resource}")
        request = PendingRequest(
            id=new_secret(),
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_explicit=params.redirect_uri_provided_explicitly,
            client_state=params.state,
            code_challenge=params.code_challenge,
            resource=self.resource,
            scopes=tuple(scopes),
            status=AWAITING_CONSENT,
            expires_at=self._now() + _seconds(PENDING_LIFETIME),
        )
        self._store.add_pending(request)
        return f"{self._settings.public_url}/consent?{urlencode({'req': request.id})}"

    def describe(self, request_id: str) -> ConsentDetails | None:
        """What the consent page shows for a request still waiting for consent."""
        pending = self._store.pending(request_id, self._now())
        if pending is None:
            return None
        client = self._store.client(pending.client_id)
        name = client.metadata.get("client_name") if client else None
        return ConsentDetails(pending.id, name, pending.redirect_uri, pending.scopes)

    def consent(self, request_id: str, decision: str) -> StartGitHub | RedirectToClient:
        """The user's answer on the consent page. Each request can be answered once."""
        now = self._now()
        if decision == "allow":
            state = new_secret()
            pending = self._store.consent(request_id, self._keys.hash("github", state), now)
            if pending is None:
                raise ExpiredRequest()
            challenge = pkce_challenge(self._verifier(request_id, state))
            return StartGitHub(
                self._github.authorization_url(state=state, code_challenge=challenge), state
            )
        if decision != "deny":
            raise ValueError(f"decision must be 'allow' or 'deny', got {decision!r}")
        pending = self._store.deny(request_id, now)
        if pending is None:
            raise ExpiredRequest()
        return RedirectToClient(
            construct_redirect_uri(
                pending.redirect_uri, error="access_denied", state=pending.client_state
            )
        )

    async def github_return(
        self, query: Mapping[str, str], state_cookie: str | None
    ) -> RedirectToClient | ShowError:
        """GitHub's callback (code and state only). Errors here are pages, never redirects,
        until the state checks pass."""
        state = query.get("state") or ""
        if (
            not state
            or not state_cookie
            or not hmac.compare_digest(state.encode("utf-8"), state_cookie.encode("utf-8"))
        ):
            return ShowError("expired")
        pending = self._store.return_from_github(self._keys.hash("github", state), self._now())
        if pending is None:
            return ShowError("expired")
        if query.get("error") == "access_denied":  # the user cancelled at GitHub
            return RedirectToClient(
                construct_redirect_uri(
                    pending.redirect_uri, error="access_denied", state=pending.client_state
                )
            )
        code = query.get("code")
        if query.get("error") or not code:
            return ShowError("github_unavailable")
        try:
            user = await self._github.fetch_user(
                code=code, code_verifier=self._verifier(pending.id, state)
            )
        except GitHubUnavailable as error:
            log.warning("GitHub sign-in failed: %s", error)
            return ShowError("github_unavailable")
        subject = f"github:{user.id}"
        if self._store.is_banned(subject):
            log.info("refused the sign-in of banned %s", subject)
            return ShowError("banned")
        issued = new_secret()
        now = self._now()

        def record_sign_in() -> None:
            self._store.upsert_user(subject, user.login, user.created_at, now)
            self._store.add_consent(subject, pending.client_id, pending.redirect_uri, now)
            self._store.record_subject(pending.id, subject)
            self._store.add_code(
                CodeRecord(
                    hash=self._keys.hash("code", issued),
                    family=new_secret(),
                    client_id=pending.client_id,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_explicit=pending.redirect_uri_explicit,
                    code_challenge=pending.code_challenge,
                    resource=pending.resource,
                    scopes=pending.scopes,
                    subject=subject,
                    expires_at=now + _seconds(CODE_LIFETIME),
                    used_at=None,
                )
            )
            self._store.touch_client(pending.client_id, now)

        self._store.atomic(record_sign_in)
        log.info("signed in %s", subject)
        return RedirectToClient(
            construct_redirect_uri(pending.redirect_uri, code=issued, state=pending.client_state)
        )
