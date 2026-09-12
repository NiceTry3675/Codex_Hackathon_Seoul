"""Private Slack indexes and explicit Google linking for shared web rooms.

Account-token and registry CAS protocol adapted from Moon-gawon's
codex/slack-bot-account-linking implementation (791f704). Room contents stay in
RoomStore; these namespaced documents contain only account links and references.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import user_from_request
from .models import Room
from .slack_store import SlackDocument, SlackStore
from .stats import analyze_room
from .storage import RoomStore


class SlackDomainError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = self.status_code = status


class SlackAccounts:
    MAX_RETRIES = 40
    MAX_ROOMS_PER_USER = 200
    MAX_LINKS_PER_TEAM = 1000

    def __init__(self, store: SlackStore, room_store: RoomStore, signing_secret: str) -> None:
        if not signing_secret:
            raise ValueError("Slack signing secret is required")
        self.store = store
        self.room_store = room_store
        self._secret = signing_secret.encode("utf-8")

    @staticmethod
    def _identity(team: str, user: str | None = None) -> None:
        for value in (team, user):
            if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
                raise SlackDomainError("invalid identity", 400)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _hash(value) -> str:
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _mac(self, value: bytes) -> str:
        return hmac.new(self._secret, value, hashlib.sha256).hexdigest()

    def _save(self, key: str, document: SlackDocument | None, value: dict, ttl: int) -> bool:
        try:
            return self.store.compare_and_swap(key, document.version if document else None, value, ttl)
        except ValueError as exc:
            raise SlackDomainError(str(exc), 422) from exc

    @staticmethod
    def _retained_until(room: Room) -> datetime:
        return room.retained_until or room.expires_at

    def record_room(self, team: str, user: str, room: Room) -> None:
        """Called for a creator or successful submitter; never reserves a seat.

        Replaying after a committed submission repairs a failed index write.
        References include the creation timestamp so a recycled code grants no
        access to the next room. Callers supply a room read from RoomStore.
        """
        self._identity(team, user)
        if not re.fullmatch(r"[A-Z0-9]{6}", room.code):
            raise SlackDomainError("room not found", 404)
        if room.slack_origin is not None and room.slack_origin.team_id != team:
            raise SlackDomainError("room not found", 404)
        retained = self._retained_until(room).timestamp()
        if retained <= time.time():
            raise SlackDomainError("room not found", 404)
        key = f"SLACK#INDEX#{team}#{user}"
        for _ in range(self.MAX_RETRIES):
            document = self.store.get(key)
            refs = document.value["rooms"] if document else []
            refs = [ref for ref in refs if ref["retained_until"] > time.time() and ref["code"] != room.code]
            refs.append({"code": room.code, "created_at": self._iso(room.created_at), "retained_until": retained})
            refs.sort(key=lambda ref: (ref["created_at"], ref["code"]), reverse=True)
            refs = refs[:self.MAX_ROOMS_PER_USER]
            if self._save(key, document, {"rooms": refs}, int(max(ref["retained_until"] for ref in refs))):
                return
        raise SlackDomainError("room list changed; please retry", 409)

    def _history_room(self, team: str, user: str, code: str) -> Room:
        self._identity(team, user)
        if not re.fullmatch(r"[A-Za-z0-9]{6}", code):
            raise SlackDomainError("room not found", 404)
        code = code.upper()
        document = self.store.get(f"SLACK#INDEX#{team}#{user}")
        refs = document.value["rooms"] if document else []
        ref = next((item for item in refs if item["code"] == code and item["retained_until"] > time.time()), None)
        if ref is None:
            raise SlackDomainError("room not found", 404)
        return self._room_for_ref(team, ref)

    def _room_for_ref(self, team: str, ref: dict) -> Room:
        room = self.room_store.get_retained(ref["code"])
        if room is None or self._iso(room.created_at) != ref["created_at"]:
            raise SlackDomainError("room not found", 404)
        if room.slack_origin is not None and room.slack_origin.team_id != team:
            raise SlackDomainError("room not found", 404)
        return room

    def _summary(self, room: Room) -> dict:
        count = len(room.submissions)
        complete = count >= room.expected_members
        closed = room.expires_at.timestamp() <= time.time()
        return {
            "code": room.code, "question": room.question,
            "options": room.options, "criteria": room.criteria,
            "expected_members": room.expected_members, "submission_count": count,
            "is_complete": complete, "created_at": self._iso(room.created_at),
            "closes_at": self._iso(room.expires_at),
            "retained_until": self._iso(self._retained_until(room)),
            "status": "complete" if complete else ("closed" if closed else "collecting"),
            "web_available": not closed,
        }

    def get_history(self, team: str, user: str, code: str) -> dict:
        room = self._history_room(team, user, code)
        summary = self._summary(room)
        analysis = None
        if summary["is_complete"]:
            analysis = analyze_room(room.submissions, room.options, room.criteria)
            analysis["devils_advocate"] = room.devils_advocate.model_dump(mode="json") if room.devils_advocate else None
        return {
            "room": summary, "analysis": analysis,
            "decision_record": room.decision_record.model_dump(mode="json") if room.decision_record else None,
        }

    def _cursor(self, team: str, user: str, after: tuple[str, str]) -> str:
        value = {"subject": self._hash([team, user]), "after": after, "exp": int(time.time()) + 3600}
        encoded = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
        return encoded + "." + self._mac(encoded.encode())

    def list_rooms(self, team: str, user: str, limit: int = 20, cursor: str | None = None) -> dict:
        self._identity(team, user)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise SlackDomainError("limit must be between 1 and 50", 422)
        after = None
        if cursor:
            try:
                encoded, signature = cursor.split(".")
                if len(cursor) > 2048 or not hmac.compare_digest(signature, self._mac(encoded.encode())):
                    raise ValueError()
                value = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                if value["subject"] != self._hash([team, user]) or value["exp"] <= time.time():
                    raise ValueError()
                after = tuple(value["after"])
                if len(after) != 2 or not all(isinstance(item, str) for item in after):
                    raise ValueError()
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise SlackDomainError("invalid or expired history cursor", 400) from None
        document = self.store.get(f"SLACK#INDEX#{team}#{user}")
        refs = document.value["rooms"] if document else []
        results = []
        for ref in refs:
            if ref["retained_until"] <= time.time():
                continue
            if after and (ref["created_at"], ref["code"]) >= after:
                continue
            try:
                room = self._room_for_ref(team, ref)
            except SlackDomainError as exc:
                if exc.status == 404:
                    continue
                raise
            results.append(self._summary(room))
            if len(results) > limit:
                break
        has_more = len(results) > limit
        results = results[:limit]
        next_cursor = self._cursor(team, user, (results[-1]["created_at"], results[-1]["code"])) if has_more else None
        return {"rooms": results, "next_cursor": next_cursor}

    def create_link(self, team: str, user: str) -> str:
        self._identity(team, user)
        for _ in range(self.MAX_RETRIES):
            nonce = secrets.token_urlsafe(32)
            token = nonce + "." + self._mac(("link:" + nonce).encode())
            key = "SLACK#LINKTOKEN#" + self._hash(token)
            if self._save(key, None, {"team_id": team, "user_id": user, "claimed_by": None}, int(time.time()) + 600):
                return token
        raise SlackDomainError("could not create account link; please retry", 409)

    def consume_link(self, token: str, google_sub: str) -> dict:
        if not token or len(token) > 200 or not google_sub or len(google_sub) > 255:
            raise SlackDomainError("invalid account link", 400)
        try:
            nonce, signature = token.split(".")
            if not hmac.compare_digest(signature, self._mac(("link:" + nonce).encode())):
                raise ValueError()
        except ValueError:
            raise SlackDomainError("invalid account link", 400) from None
        key = "SLACK#LINKTOKEN#" + self._hash(token)
        account = self._hash(google_sub)
        for _ in range(self.MAX_RETRIES):
            document = self.store.get(key)
            if document is None:
                raise SlackDomainError("account link expired or invalid", 410)
            value = document.value
            if value["claimed_by"] not in (None, account):
                raise SlackDomainError("account link was already used", 409)
            if value["claimed_by"] == account:
                break
            value["claimed_by"] = account
            if self._save(key, document, value, document.expires_at):
                break
        else:
            raise SlackDomainError("account link changed; please retry", 409)

        team, user = value["team_id"], value["user_id"]
        registry_key = f"SLACK#ACCOUNTS#{team}"
        # Both directions commit in one document CAS. A token reservation alone
        # grants no access. If the process crashes, the same Google identity can
        # resume the reservation until its 10-minute TTL; another cannot claim it.
        for _ in range(self.MAX_RETRIES):
            if time.time() >= document.expires_at:
                raise SlackDomainError("account link expired or invalid", 410)
            registry = self.store.get(registry_key)
            links = registry.value if registry else {"google": {}, "slack": {}}
            if links["google"].get(account, user) != user or links["slack"].get(user, account) != account:
                raise SlackDomainError("an account is already linked to another identity", 409)
            if links["google"].get(account) == user and links["slack"].get(user) == account:
                return {"team_id": team, "user_id": user}
            if len(links["google"]) >= self.MAX_LINKS_PER_TEAM:
                raise SlackDomainError("workspace account-link capacity reached", 409)
            links["google"][account] = user
            links["slack"][user] = account
            # Account links survive room retention, but remain bounded. The app
            # can later migrate this single-workspace registry to a transactions
            # model if it needs more than 1000 linked users.
            if self._save(registry_key, registry, links, int(time.time()) + 10 * 365 * 86400):
                return {"team_id": team, "user_id": user}
        raise SlackDomainError("account links changed; please retry", 409)

    def linked_identity(self, team: str, google_sub: str) -> str | None:
        self._identity(team)
        account = self._hash(google_sub)
        document = self.store.get(f"SLACK#ACCOUNTS#{team}")
        if document is None:
            return None
        links = document.value
        user = links["google"].get(account)
        return user if user and links["slack"].get(user) == account else None


@lru_cache(maxsize=8)
def _cached_accounts(room_store: RoomStore, secret: str, table_name: str) -> SlackAccounts:
    return SlackAccounts(SlackStore(table_name), room_store, secret)


def get_accounts(room_store: RoomStore) -> SlackAccounts:
    secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Slack signing secret is not configured", headers={"Cache-Control": "no-store"})
    return _cached_accounts(room_store, secret, os.getenv("CONSENSUS_TABLE_NAME", "").strip())


def _configuration() -> tuple[str, str]:
    team = os.getenv("SLACK_TEAM_ID", "").strip()
    public_base = (os.getenv("SYNQ_PUBLIC_URL", "").strip() or os.getenv("SLACK_PUBLIC_BASE_URL", "").strip()).rstrip("/")
    try:
        url = urlsplit(public_base)
        valid = (
            re.fullmatch(r"T[A-Z0-9]+", team)
            and url.hostname and not url.username and not url.password
            and url.path in ("", "/") and not url.query and not url.fragment
            and (url.scheme == "https" or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))
        )
        url.port  # Reject malformed ports before comparing the browser Origin.
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(503, "Slack workspace or public URL is not configured", headers={"Cache-Control": "no-store"})
    return team, public_base


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=200)


def build_account_router(room_store: RoomStore) -> APIRouter:
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    def user(request: Request):
        identity = user_from_request(request)
        if identity is None:
            raise HTTPException(401, "Google login is required", headers=headers)
        return identity

    def domain_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SlackDomainError as exc:
            raise HTTPException(exc.status, exc.message, headers=headers) from None

    def linked_user(request: Request, accounts: SlackAccounts, team: str) -> str:
        google_user = user(request)
        slack_user = accounts.linked_identity(team, google_user.google_sub)
        if slack_user is None:
            raise HTTPException(403, "Connect Slack with /synq link first", headers=headers)
        return slack_user

    @router.post("/api/slack/link")
    def link_account(request: Request, payload: LinkRequest):
        google_user = user(request)
        team, public_base = _configuration()
        if request.headers.get("origin") != public_base:
            raise HTTPException(403, "same-origin account linking is required", headers=headers)
        accounts = get_accounts(room_store)
        # Tokens are workspace-bound even if an installation is reconfigured.
        # The consume operation itself remains reusable by verified Slack code;
        # HTTP must accept only tokens issued for this configured workspace.
        document = accounts.store.get("SLACK#LINKTOKEN#" + accounts._hash(payload.token))
        if document is not None and document.value["team_id"] != team:
            raise HTTPException(403, "account link belongs to another workspace", headers=headers)
        result = domain_call(accounts.consume_link, payload.token, google_user.google_sub)
        return JSONResponse(result, headers=headers)

    @router.get("/api/slack/me/rooms")
    def my_rooms(request: Request, limit: int = 20, cursor: str | None = None):
        team, _ = _configuration()
        accounts = get_accounts(room_store)
        slack_user = linked_user(request, accounts, team)
        result = domain_call(accounts.list_rooms, team, slack_user, limit=limit, cursor=cursor)
        return JSONResponse(result, headers=headers)

    @router.get("/api/slack/me/rooms/{code}")
    def my_room_history(request: Request, code: str):
        team, _ = _configuration()
        accounts = get_accounts(room_store)
        slack_user = linked_user(request, accounts, team)
        result = domain_call(accounts.get_history, team, slack_user, code)
        return JSONResponse(result, headers=headers)

    @router.get("/slack/link", response_class=HTMLResponse, include_in_schema=False)
    def account_page():
        nonce = secrets.token_urlsafe(24)
        page = Path(__file__).with_name("slack_link.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace("__CSP_NONCE__", nonce), headers={
            **headers, "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; "
                f"script-src 'nonce-{nonce}' https://accounts.google.com/gsi/client; "
                "style-src 'unsafe-inline' https://accounts.google.com; img-src 'self' https://*.googleusercontent.com data:; "
                "connect-src 'self' https://accounts.google.com; frame-src https://accounts.google.com; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })

    return router
