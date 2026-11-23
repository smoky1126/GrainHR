"""The Cloudflare Access sign-in for the website. A PC copy leaves this off."""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit

_TEAM = "quiet-butterfly-e2f4.cloudflareaccess.com"
_AUD = "073f7d972830c3d82c7ac62477dab074fb255f287bfe736546547324a4eb9078"
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_LOCK = threading.Lock()
_KEYS = {"url": "", "at": 0.0, "keys": {}, "forced": 0.0}
_WARNED = {"certs": False}


def clean_team(raw):
    text = str(raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip("/")
    if re.fullmatch(r"[a-z0-9-]+\.cloudflareaccess\.com", text):
        return text
    return ""


def clean_aud(raw):
    text = str(raw or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{32,128}", text):
        return text
    return ""


def access_settings():
    """The team and audience for this process. Empty means Access is off."""
    team = clean_team(os.environ.get("GRAINHR_ACCESS_TEAM", ""))
    aud = clean_aud(os.environ.get("GRAINHR_ACCESS_AUD", ""))
    if os.environ.get("GRAINHR_SERVER") == "1":
        team = team or _TEAM
        aud = aud or _AUD
    if team and aud:
        return team, aud
    return "", ""


def access_required():
    team, aud = access_settings()
    return bool(team and aud)


def clear_key_cache():
    with _LOCK:
        _KEYS.update(url="", at=0.0, keys={}, forced=0.0)
        _WARNED["certs"] = False


def token_from(headers, cookies):
    """The Access token from the header Cloudflare adds, or from its cookie."""
    for name in ("cf-access-jwt-assertion", "Cf-Access-Jwt-Assertion"):
        found = _one(headers, name)
        if found.count(".") == 2:
            return found
    for name in ("CF_Authorization", "cf_authorization"):
        found = _one(cookies, name)
        if found.count(".") == 2:
            return found
    return ""


def email_from_token(token, *, team, aud, now=None, fetch=None):
    """The email in a token signed for this application, or an empty string."""
    team = clean_team(team)
    aud = clean_aud(aud)
    if not team or not aud:
        return ""
    parts = _parts(token)
    if parts is None:
        return ""
    header, payload_raw, signature = parts
    if header.get("alg") != "RS256" or header.get("crit"):
        return ""
    kid = str(header.get("kid") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kid):
        return ""
    url = f"https://{team}/cdn-cgi/access/certs"
    moment = time.time() if now is None else float(now)
    keys = _keys_for(url, fetch or _fetch_certs, moment, force=False)
    if kid not in keys:
        keys = _keys_for(url, fetch or _fetch_certs, moment, force=True)
    if kid not in keys:
        return ""
    signing = token.strip().rsplit(".", 1)[0].encode("ascii")
    modulus, exponent = keys[kid]
    if not _signature_ok(signing, signature, modulus, exponent):
        return ""
    if not isinstance(payload_raw, dict):
        return ""
    if not _claims_ok(payload_raw, team, aud, moment):
        return ""
    email = str(payload_raw.get("email") or "").strip().lower()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}", email):
        return ""
    return email


def access_email():
    """The signed-in email for this browser session, when Access is on."""
    if not access_required():
        return ""
    import streamlit as st

    try:
        token = token_from(st.context.headers, st.context.cookies)
    except Exception:
        return ""
    team, aud = access_settings()
    return email_from_token(token, team=team, aud=aud)


def _one(source, name):
    if source is None:
        return ""
    try:
        value = source.get(name, "")
    except Exception:
        try:
            value = source[name]
        except Exception:
            return ""
    return str(value or "").strip().strip('"')


def _parts(token):
    text = str(token or "").strip()
    if not text.isascii() or text.count(".") != 2 or len(text) > 12000:
        return None
    try:
        header = json.loads(_b64(text.split(".", 1)[0]))
        payload = json.loads(_b64(text.split(".")[1]))
        signature = _b64(text.rsplit(".", 1)[1])
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(header, dict):
        return None
    return header, payload, signature


def _b64(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _claims_ok(payload, team, aud, now):
    if payload.get("iss") != f"https://{team}":
        return False
    audience = payload.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    if not isinstance(audience, list) or aud not in audience:
        return False
    exp = payload.get("exp")
    nbf = payload.get("nbf", payload.get("iat", now))
    if isinstance(exp, bool) or isinstance(nbf, bool):
        return False
    if not isinstance(exp, (int, float)) or not isinstance(nbf, (int, float)):
        return False
    if now > float(exp) + 60 or now + 60 < float(nbf):
        return False
    return True


def _keys_for(url, fetch, now, force):
    with _LOCK:
        same = _KEYS["url"] == url
        fresh = same and _KEYS["keys"] and now - _KEYS["at"] < 3600
        if fresh and not force:
            return dict(_KEYS["keys"])
        if same and now - _KEYS["at"] < 30 and not force:
            return dict(_KEYS["keys"])
        if force and same and _KEYS["keys"] and now - _KEYS.get("forced", 0.0) < 30:
            return dict(_KEYS["keys"])
    payload = None
    try:
        payload = fetch(url)
    except Exception:
        if not _WARNED["certs"]:
            _WARNED["certs"] = True
            print("GRAINHR_ACCESS certs unavailable", flush=True)
    parsed = _parse_keys(payload) if isinstance(payload, dict) else {}
    with _LOCK:
        if parsed:
            update = {"url": url, "at": now, "keys": parsed}
            if force:
                update["forced"] = now
            _KEYS.update(update)
            return dict(parsed)
        if _KEYS["url"] == url and _KEYS["keys"]:
            _KEYS["at"] = now
            return dict(_KEYS["keys"])
        _KEYS.update(url=url, at=now, keys={})
        return {}


def _parse_keys(payload):
    found = {}
    for item in payload.get("keys") or []:
        if not isinstance(item, dict) or item.get("kty") != "RSA":
            continue
        kid = str(item.get("kid") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kid):
            continue
        try:
            modulus = int.from_bytes(_b64(str(item.get("n") or "")), "big")
            exponent = int.from_bytes(_b64(str(item.get("e") or "")), "big")
        except (ValueError, UnicodeError):
            continue
        if modulus.bit_length() < 2048 or exponent < 3 or exponent.bit_length() > 32:
            continue
        found[kid] = (modulus, exponent)
    return found


def _fetch_certs(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.path != "/cdn-cgi/access/certs":
        raise ValueError("unexpected certs address")
    if not re.fullmatch(r"[a-z0-9-]+\.cloudflareaccess\.com", host):
        raise ValueError("unexpected certs address")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GrainHR"})
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("certs response is too large")
    return json.loads(body.decode("utf-8"))


def _signature_ok(signing, signature, modulus, exponent):
    size = (modulus.bit_length() + 7) // 8
    if len(signature) != size or exponent < 3 or exponent % 2 == 0:
        return False
    value = int.from_bytes(signature, "big")
    if value <= 0 or value >= modulus:
        return False
    encoded = pow(value, exponent, modulus).to_bytes(size, "big")
    if len(encoded) < 11 or not encoded.startswith(b"\x00\x01"):
        return False
    rest = encoded[2:]
    marker = rest.find(b"\x00")
    if marker < 8 or rest[:marker] != b"\xff" * marker:
        return False
    digest_info = rest[marker + 1:]
    if not digest_info.startswith(_SHA256_PREFIX) or len(digest_info) != len(_SHA256_PREFIX) + 32:
        return False
    signed = digest_info[len(_SHA256_PREFIX):]
    return hmac.compare_digest(signed, hashlib.sha256(signing).digest())
