"""Cloudflare Access tokens. No company files and no network."""

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.access_token import (
    _signature_ok,
    access_required,
    access_settings,
    clear_key_cache,
    email_from_token,
    token_from,
)

TEAM = "example.cloudflareaccess.com"
AUD = "a" * 64
KID = "test-key"
# A throwaway 2048-bit key. The signature below was made by the operating system.
MODULUS = int.from_bytes(base64.urlsafe_b64decode(
    "8ptMKR0cxYGbWfxEi3MfTNLK3_NWD2RzOByfIz59GxshovbvuvLNNNxCDpQkCrDSny1isktqZtA7kGxiM7I7nLI101NSOiszsPAqOZ5BZAcZaMklk4_WQrPnmkviFG0DBpjBIErY6bgEmjwYt_pLjaXmCNnmixpeoyThWKq28Q13-OuHQ5Wi4KxKI7uOpI3jpC_q32IoC5kYS1s3YuCxIGLLlnLd6NJKiKBu9irmEjkqsw9fQZa3W-ooV8aPEe5SW6WOFId4iiiK7uIbz2xMtepDCSkVxn5YqT7equleGZRMwqW7QEm-2cg1xM-eQLx5hInW8iM79KOzxtS4zHzPGQ=="
), "big")
EXPONENT = 65537
PRIVATE = int.from_bytes(base64.urlsafe_b64decode(
    "PawkzD7OVZcA-vsaIaj-R_U-BXhCZF9Quu7rtXXpL77R6i-D-a5HZCypzjLyhpU0tao_8LsjLUe6HJiwzht88_SJolMIEClzVoN2-Ha2gMsdNnoLx1tFSGebdKndqvubTU3_qkncom1ZHiwwzHQgSL3noFBkPvBRJn_1mSisoNIg--dD-RH6GNvRI13f6BYrM_4pgwnrFUJybqBUI4y5xQ7NzG7PYAp9AGwvXX7eP6P4dxh9Mtkp6mC2Dae5scyyrj0lDmo8D4UJf6mh-BIZjN4IWtiNnmz9cY0drvfSpzguM_yQwm5FkbseF67cwvwm7F4RKE21PWLN6vXnPESO0Q=="
), "big")
OS_SIGNATURE = base64.urlsafe_b64decode(
    "QJFhrnGjbcE_dxrx57p3q4dI9d0nHqCux9t_zSX92N-utDbgediDh-Hlx4wqZIBe1yN1aWaqItvsP272Dw65_97DuBo4ZcPMEpHSxMRmSJvnLb0cB5h5pSLqOJakArAuO4DESuQOL_C5X5BxVqgMSpmP4_G9e8wcoHWXMzhkdTyClEgNhnb4FFu56kjpYYakxSBf8Ci1zDunGrNiVXX65WoISZHHpAXlb5D4QZW8NRNFSJvSZVWMW9-wDDhmaUPrTk4CcoffBvPSU99l4TJSncN3053AgW6twOXoB5_l8xZgE9G2gy8c48Ogcl7Ahv1QJwcmo-aIKR9bxDPh8Uw-8w=="
)
NOW = 1_800_000_000


def _fail(message):
    raise SystemExit(message)


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign(header, payload):
    signing = (
        _b64(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64(json.dumps(payload, separators=(",", ":")).encode())
    )
    body = signing.encode("ascii")
    digest = hashlib.sha256(body).digest()
    prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    info = prefix + digest
    size = (MODULUS.bit_length() + 7) // 8
    encoded = b"\x00\x01" + (b"\xff" * (size - len(info) - 3)) + b"\x00" + info
    signature = pow(int.from_bytes(encoded, "big"), PRIVATE, MODULUS).to_bytes(size, "big")
    return signing + "." + _b64(signature)


def _payload(**extra):
    body = {
        "iss": f"https://{TEAM}",
        "aud": [AUD],
        "exp": NOW + 600,
        "nbf": NOW - 10,
        "email": "Person@Example.com",
    }
    body.update(extra)
    return body


def _token(header=None, payload=None):
    return _sign(header or {"alg": "RS256", "kid": KID}, payload or _payload())


def _certs(kid=KID, modulus=MODULUS, exponent=EXPONENT):
    def fetch(url):
        if url != f"https://{TEAM}/cdn-cgi/access/certs":
            _fail(url)
        return {"keys": [{
            "kty": "RSA",
            "kid": kid,
            "n": _b64(modulus.to_bytes((modulus.bit_length() + 7) // 8, "big")),
            "e": _b64(exponent.to_bytes((exponent.bit_length() + 7) // 8, "big")),
        }]}

    return fetch


def _email(token, fetch=None, aud=AUD, now=NOW):
    clear_key_cache()
    return email_from_token(token, team=TEAM, aud=aud, now=now, fetch=fetch or _certs())


def test_operating_system_signature_matches():
    if not _signature_ok(b"header.payload", OS_SIGNATURE, MODULUS, EXPONENT):
        _fail("the verifier rejected a signature made outside Python")


def test_a_signed_token_returns_the_email():
    if _email(_token()) != "person@example.com":
        _fail("a valid token should return the email in lower case")


def test_header_beats_the_cookie():
    header = {"Cf-Access-Jwt-Assertion": "a.b.c"}
    cookie = {"CF_Authorization": "d.e.f"}
    if token_from(header, cookie) != "a.b.c":
        _fail(token_from(header, cookie))
    if token_from({}, cookie) != "d.e.f":
        _fail("the cookie should be used when the header is absent")


def test_the_wrong_audience_key_or_time_is_rejected():
    if _email(_token(), aud="b" * 64):
        _fail("another application's token was accepted")
    if _email(_token(payload=_payload(iss="https://other.cloudflareaccess.com"))):
        _fail("a token from another team was accepted")
    if _email(_token(payload=_payload(exp=NOW - 120))):
        _fail("an expired token was accepted")
    if _email(_token(payload=_payload(nbf=NOW + 120))):
        _fail("a token that is not valid yet was accepted")
    if _email(_token(), fetch=_certs(kid="other-key")):
        _fail("a token signed by an unknown key was accepted")
    other = MODULUS ^ (1 << 255)
    if other.bit_length() < 2048:
        other ^= 1 << 2048
    if _email(_token(), fetch=_certs(modulus=other)):
        _fail("a token checked with the wrong key was accepted")
    if _email(_token(header={"alg": "none", "kid": KID})):
        _fail("an unsigned token was accepted")
    if _email(_token(payload=_payload(email="not-an-email"))):
        _fail("a token without an email was accepted")


def test_an_unknown_key_is_fetched_again():
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        kid = "other-key" if calls["n"] == 1 else KID
        return _certs(kid=kid)(url)

    clear_key_cache()
    if email_from_token(_token(), team=TEAM, aud=AUD, now=NOW, fetch=fetch) != "person@example.com":
        _fail("the second key list should have verified the token")
    if calls["n"] != 2:
        _fail(calls["n"])


def test_access_stays_off_on_a_pc():
    saved = {name: os.environ.get(name) for name in (
        "GRAINHR_SERVER", "GRAINHR_ACCESS_TEAM", "GRAINHR_ACCESS_AUD",
    )}
    try:
        for name in saved:
            os.environ.pop(name, None)
        if access_required():
            _fail("a PC should not require Cloudflare")
        os.environ["GRAINHR_SERVER"] = "1"
        os.environ["GRAINHR_ACCESS_TEAM"] = "https://evil.example.com"
        os.environ["GRAINHR_ACCESS_AUD"] = "not a tag"
        team, aud = access_settings()
        if team != "quiet-butterfly-e2f4.cloudflareaccess.com" or len(aud) != 64:
            _fail("a bad override should keep the server's built-in check")
        os.environ["GRAINHR_SERVER"] = "0"
        os.environ["GRAINHR_ACCESS_TEAM"] = "https://shop.cloudflareaccess.com/"
        os.environ["GRAINHR_ACCESS_AUD"] = "c" * 64
        if access_settings() != ("shop.cloudflareaccess.com", "c" * 64):
            _fail(access_settings())
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    test_operating_system_signature_matches()
    test_a_signed_token_returns_the_email()
    test_header_beats_the_cookie()
    test_the_wrong_audience_key_or_time_is_rejected()
    test_an_unknown_key_is_fetched_again()
    test_access_stays_off_on_a_pc()
    print("access token ok")
