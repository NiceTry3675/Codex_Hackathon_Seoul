"""Server-only Slack identities and user-bound modal metadata."""

import base64
import hashlib
import hmac
import json
import os
import time


def identity_hash(team: str, user: str, code: str) -> str:
    # Domain-separated from browser cookies; raw Slack IDs never enter a Room.
    secret = os.environ["SLACK_SIGNING_SECRET"].encode()
    return hmac.new(secret, json.dumps(["participation", team, user, code.upper()]).encode(), hashlib.sha256).hexdigest()


def sign_metadata(secret: str, team: str, user: str, channel: str, code: str = "") -> str:
    payload = json.dumps({"team": team, "user": user, "channel": channel, "code": code,
                          "exp": int(time.time()) + 7200}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def read_metadata(secret: str, value: str, team: str, user: str) -> dict:
    try:
        if not isinstance(value, str) or len(value) > 3000:
            raise ValueError()
        encoded, signature = value.split(".")
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (not isinstance(payload, dict) or payload.get("team") != team or payload.get("user") != user
                or payload.get("exp", 0) <= time.time()):
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid or expired Slack form") from None
