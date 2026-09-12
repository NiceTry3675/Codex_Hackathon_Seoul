"""Small Slack HTTP boundary; credentials and response URLs never enter logs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SlackAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlackConfig:
    bot_token: str
    signing_secret: str
    team_id: str
    app_id: str
    public_base_url: str
    retention_days: int = 90

    @classmethod
    def from_env(cls) -> SlackConfig:
        values = {key: os.getenv(f"SLACK_{key}", "").strip() for key in (
            "BOT_TOKEN", "SIGNING_SECRET", "TEAM_ID", "APP_ID", "PUBLIC_BASE_URL"
        )}
        if not all(values.values()):
            raise ValueError("Slack app settings are not configured")
        if len(values["SIGNING_SECRET"]) < 32:
            raise ValueError("SLACK_SIGNING_SECRET must contain at least 32 characters")
        if not values["BOT_TOKEN"].startswith("xoxb-"):
            raise ValueError("SLACK_BOT_TOKEN must be a bot token")
        if not re.fullmatch(r"T[A-Z0-9]+", values["TEAM_ID"]):
            raise ValueError("invalid SLACK_TEAM_ID")
        if not re.fullmatch(r"A[A-Z0-9]+", values["APP_ID"]):
            raise ValueError("invalid SLACK_APP_ID")
        base = values["PUBLIC_BASE_URL"].rstrip("/")
        url = urlsplit(base)
        # Parsing the authority alone does not validate a malformed/out-of-range port.
        port = url.port
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not (local and url.scheme == "http")) or (
            not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path or port == 0
        ):
            raise ValueError("SLACK_PUBLIC_BASE_URL must be an HTTPS origin (HTTP localhost is allowed)")
        days = int(os.getenv("SLACK_HISTORY_RETENTION_DAYS", "90"))
        if not 7 <= days <= 365:
            raise ValueError("SLACK_HISTORY_RETENTION_DAYS must be between 7 and 365")
        return cls(values["BOT_TOKEN"], values["SIGNING_SECRET"], values["TEAM_ID"],
                   values["APP_ID"], base, days)


def verify_signature(secret: str, body: bytes, timestamp: str, signature: str,
                     *, now: float | None = None) -> bool:
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        return False
    if not re.fullmatch(r"v0=[a-f0-9]{64}", signature):
        return False
    if abs((time.time() if now is None else now) - int(timestamp)) > 300:
        return False
    expected = "v0=" + hmac.new(
        secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SlackClient:
    METHODS = {"views.open", "views.update", "chat.postMessage", "chat.postEphemeral"}

    def __init__(self, token: str) -> None:
        self._token = token
        self._opener = build_opener(_NoRedirect())

    def _send(self, url: str, payload: dict, *, authenticated: bool) -> dict:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=2) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise SlackAPIError("response_too_large")
            if not authenticated and raw.strip() == b"ok":
                return {"ok": True}
            result = json.loads(raw)
        except HTTPError as exc:
            raise SlackAPIError(f"http_{exc.code}") from None
        except (OSError, ValueError) as exc:
            raise SlackAPIError(type(exc).__name__) from None
        if (not isinstance(result, dict) or result.get("ok") is False
                or (authenticated and result.get("ok") is not True)):
            # A fixed error code is sufficient; never log the response payload.
            raise SlackAPIError("slack_rejected_request")
        return result

    def call(self, method: str, payload: dict) -> dict:
        if method not in self.METHODS:
            raise ValueError("unsupported Slack API method")
        return self._send(f"https://slack.com/api/{method}", payload, authenticated=True)

    def respond(self, response_url: str, payload: dict) -> dict:
        try:
            url = urlsplit(response_url)
            port = url.port
        except ValueError:
            raise SlackAPIError("invalid_response_url") from None
        if (url.scheme != "https" or url.hostname != "hooks.slack.com" or port not in (None, 443)
                or url.username or url.password or url.fragment or url.query
                or not url.path.startswith(("/commands/", "/services/"))):
            raise SlackAPIError("invalid_response_url")
        return self._send(response_url, {"response_type": "ephemeral", "replace_original": False,
                                        **payload}, authenticated=False)
