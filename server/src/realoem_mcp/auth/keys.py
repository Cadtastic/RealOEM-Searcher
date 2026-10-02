"""Keys derived from the server secret, one per purpose (hosted design 4.4).

Tokens and codes are stored only as keyed hashes, each kind under its own key: a copied database
yields no usable credential, and a value of one kind can never match a row of another kind.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from realoem_mcp.config import MIN_SECRET_KEY_BYTES

LABELS = ("access", "refresh", "code", "github", "github-pkce", "consent", "cache-owner")


def new_secret() -> str:
    """A fresh 256-bit random value, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def b64url(raw: bytes) -> str:
    """base64url without padding (RFC 7636 appendix A)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge of a PKCE verifier."""
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


class Keys:
    """k_label = HMAC-SHA256(secret, "realoem/v1/" + label) for each label in LABELS."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < MIN_SECRET_KEY_BYTES:
            raise ValueError(f"the server secret must be at least {MIN_SECRET_KEY_BYTES} bytes")
        self._keys = {
            label: hmac.new(secret, f"realoem/v1/{label}".encode(), hashlib.sha256).digest()
            for label in LABELS
        }

    def key(self, label: str) -> bytes:
        return self._keys[label]

    def digest(self, label: str, value: str) -> bytes:
        return hmac.new(self._keys[label], value.encode("utf-8"), hashlib.sha256).digest()

    def hash(self, label: str, value: str) -> str:
        """H_label(value) as stored in the database: hex HMAC-SHA256 under k_label."""
        return self.digest(label, value).hex()
