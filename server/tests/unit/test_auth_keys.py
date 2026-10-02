"""Keys derived from the server secret (hosted design 4.4)."""

import hashlib
import hmac

import pytest

from realoem_mcp.auth.keys import LABELS, Keys, b64url, new_secret, pkce_challenge

SECRET = b"0123456789abcdef0123456789abcdef"


def test_each_purpose_has_its_own_key() -> None:
    keys = Keys(SECRET)
    assert len({keys.key(label) for label in LABELS}) == len(LABELS)
    assert len({keys.hash(label, "same value") for label in LABELS}) == len(LABELS)


def test_the_derivation_is_the_designed_one() -> None:
    # Spec 4.4. Changing this voids every stored token, code and cache owner on upgrade.
    key = hmac.new(SECRET, b"realoem/v1/access", hashlib.sha256).digest()
    assert Keys(SECRET).key("access") == key
    assert Keys(SECRET).hash("access", "t") == hmac.new(key, b"t", hashlib.sha256).hexdigest()


def test_hashes_depend_on_the_secret() -> None:
    assert Keys(SECRET).hash("access", "t") != Keys(SECRET[::-1]).hash("access", "t")
    assert Keys(SECRET).hash("access", "t") == Keys(SECRET).hash("access", "t")


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Keys(b"too short")


def test_new_secrets_are_256_bit_and_url_safe() -> None:
    values = {new_secret() for _ in range(100)}
    assert len(values) == 100
    assert all(len(value) == 43 and "=" not in value for value in values)


def test_pkce_challenge_matches_rfc_7636() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert b64url(b"\xff\xff") == "__8"
