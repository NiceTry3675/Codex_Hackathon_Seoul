"""Google ID-token verification and stateless signed browser sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Request
from google.auth.exceptions import TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .models import AuthUser


SESSION_COOKIE_NAME = "consensus_session"
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 7


class AuthConfigurationError(RuntimeError):
    """Raised when server-side Google auth settings are incomplete."""


class InvalidGoogleCredential(ValueError):
    """Raised when Google rejects an ID token or required claims are absent."""


class GoogleVerificationUnavailable(RuntimeError):
    """Raised when Google's signing keys cannot currently be fetched."""


def google_client_id() -> str | None:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip() or None


def auth_is_configured() -> bool:
    return google_client_id() is not None and _session_secret(required=False) is not None


def session_cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def session_ttl_seconds() -> int:
    raw_value = os.getenv("SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS))
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS
    return min(max(value, 300), 60 * 60 * 24 * 30)


def verify_google_credential(credential: str) -> AuthUser:
    client_id = google_client_id()
    if client_id is None:
        raise AuthConfigurationError("GOOGLE_CLIENT_ID is not configured")

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except TransportError as exc:
        raise GoogleVerificationUnavailable(
            "Google token verification is temporarily unavailable"
        ) from exc
    except ValueError as exc:
        raise InvalidGoogleCredential("invalid Google ID token") from exc

    subject = _required_claim(claims, "sub")
    email = _required_claim(claims, "email")
    if claims.get("email_verified") is not True:
        raise InvalidGoogleCredential("Google email is not verified")

    name = str(claims.get("name") or email).strip()
    picture_value = claims.get("picture")
    picture = str(picture_value).strip() if picture_value else None
    return AuthUser(
        google_sub=subject,
        email=email,
        name=name,
        picture=picture,
    )


def create_session_token(user: AuthUser, now: int | None = None) -> str:
    issued_at = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "sub": user.google_sub,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "iat": issued_at,
        "exp": issued_at + session_ttl_seconds(),
    }
    encoded_payload = _encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )
    signature = hmac.new(
        _session_secret(required=True).encode(),
        encoded_payload.encode(),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def read_session_token(token: str | None, now: int | None = None) -> AuthUser | None:
    if not token:
        return None
    secret = _session_secret(required=False)
    if secret is None:
        return None

    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        expected_signature = hmac.new(
            secret.encode(),
            encoded_payload.encode(),
            hashlib.sha256,
        ).digest()
        supplied_signature = _decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None

        payload = json.loads(_decode(encoded_payload))
        current_time = int(time.time() if now is None else now)
        if payload.get("v") != 1 or int(payload["exp"]) <= current_time:
            return None
        return AuthUser(
            google_sub=str(payload["sub"]),
            email=str(payload["email"]),
            name=str(payload["name"]),
            picture=str(payload["picture"]) if payload.get("picture") else None,
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def user_from_request(request: Request) -> AuthUser | None:
    return read_session_token(request.cookies.get(SESSION_COOKIE_NAME))


def _required_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidGoogleCredential(f"Google ID token is missing {name}")
    return value.strip()


def _session_secret(*, required: bool) -> str | None:
    value = os.getenv("SESSION_SECRET", "").strip()
    if len(value) >= 32:
        return value
    if required:
        raise AuthConfigurationError("SESSION_SECRET must contain at least 32 characters")
    return None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
