"""Private, single-workspace Slack rooms, participation and account linking.

Slack identity comes only from the verified Slack request envelope. Google
identity comes only from the authenticated web session. Neither identity is
included in public room summaries or aggregate results.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import time
from uuid import uuid4

from .models import Room, RoomCreate, Submission, SubmissionCreate
from .slack_store import SlackDocument, SlackStore
from .stats import analyze_room


class SlackDomainError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = self.status_code = status


class SlackService:
    MAX_RETRIES = 40
    MAX_ROOMS_PER_USER = 200
    MAX_LINKS_PER_TEAM = 1000

    def __init__(self, store: SlackStore, secret: str, retention_days: int = 90) -> None:
        if not secret or not 7 <= retention_days <= 365:
            raise ValueError("Slack secret and retention of 7–365 days are required")
        self.store = store
        self._secret = secret.encode("utf-8")
        self.retention_days = retention_days

    @staticmethod
    def _identity(team: str, user: str | None = None) -> None:
        for value in (team, user):
            if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
                raise SlackDomainError("invalid identity", 400)

    @staticmethod
    def _request(request_id: str) -> None:
        if not request_id or len(request_id) > 200:
            raise SlackDomainError("a stable request ID is required", 422)

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _hash(value) -> str:
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _mac(self, value: bytes) -> str:
        return hmac.new(self._secret, value, hashlib.sha256).hexdigest()

    def _room_key(self, team: str, code: str) -> str:
        self._identity(team)
        if not re.fullmatch(r"[A-Za-z0-9]{10}", code):
            raise SlackDomainError("room not found", 404)
        return f"SLACK#ROOM#{team}#{code.upper()}"

    def _room_document(self, team: str, user: str, code: str) -> SlackDocument:
        self._identity(team, user)
        document = self.store.get(self._room_key(team, code))
        if document is None or user not in document.value["members"]:
            raise SlackDomainError("room not found", 404)
        return document

    def _summary(self, value: dict, user: str | None = None) -> dict:
        room = value["room"]
        count = len(room["submissions"])
        complete = count >= room["expected_members"]
        status = "complete" if complete else (
            "closed" if time.time() >= value["closes_at"] else "collecting"
        )
        summary = {
            "code": room["code"], "question": room["question"],
            "options": room["options"], "criteria": room["criteria"],
            "expected_members": room["expected_members"],
            "submission_count": count, "is_complete": complete,
            "created_at": room["created_at"],
            "closes_at": self._iso(value["closes_at"]),
            "retained_until": self._iso(value["retained_until"]), "status": status,
        }
        if user is not None:
            summary["has_submitted"] = user in value["submitted_users"]
        return summary

    def _save(self, key: str, document: SlackDocument | None, value: dict, ttl: int) -> bool:
        try:
            return self.store.compare_and_swap(
                key, document.version if document else None, value, ttl,
            )
        except ValueError as exc:
            raise SlackDomainError(str(exc), 422) from exc

    def _index(self, team: str, user: str, value: dict) -> None:
        """Recoverable after the room commit; replaying join/create repairs it."""
        key = f"SLACK#INDEX#{team}#{user}"
        room = value["room"]
        for _ in range(self.MAX_RETRIES):
            now = time.time()
            document = self.store.get(key)
            refs = document.value["rooms"] if document else []
            refs = [ref for ref in refs if ref["retained_until"] > now and ref["code"] != room["code"]]
            refs.append({
                "code": room["code"], "created_at": room["created_at"],
                "retained_until": value["retained_until"],
            })
            refs.sort(key=lambda ref: (ref["created_at"], ref["code"]), reverse=True)
            refs = refs[:self.MAX_ROOMS_PER_USER]
            if self._save(key, document, {"rooms": refs}, max(ref["retained_until"] for ref in refs)):
                return
        raise SlackDomainError("room list changed; please retry", 409)

    def create_room(
        self, team: str, user: str, channel: str, payload: RoomCreate, request_id: str,
    ) -> dict:
        self._identity(team, user)
        self._identity(team, channel)
        self._request(request_id)
        if payload.submission_mode != "anonymous":
            raise SlackDomainError("Slack rooms support anonymous submissions only", 422)
        if len(payload.options) > 5 or len(payload.criteria) > 5:
            raise SlackDomainError("Slack rooms support at most 5 options and 5 criteria", 422)
        if any(len(label) > 80 for label in [*payload.options, *payload.criteria]):
            raise SlackDomainError("Slack labels must contain at most 80 characters", 422)
        if payload.expected_members > 20 or len(payload.context) > 5000:
            raise SlackDomainError("Slack rooms support at most 20 members and 5000 context characters", 422)
        request_hash = self._mac(json.dumps([team, user, request_id]).encode())
        code = base64.b32encode(bytes.fromhex(request_hash)).decode()[:10]
        key = self._room_key(team, code)
        fingerprint = self._hash([channel, payload.model_dump(), payload.expires_in_hours])
        now = int(time.time())
        closes_at = now + payload.expires_in_hours * 3600
        retained_until = now + self.retention_days * 86400
        room = Room(
            code=code, created_at=datetime.fromtimestamp(now, timezone.utc),
            expires_at=datetime.fromtimestamp(closes_at, timezone.utc),
            **payload.model_dump(),
        )
        new_value = {
            "room": room.model_dump(mode="json"), "team_id": team,
            "origin_channel": channel, "creator": user, "members": [user],
            "submitted_users": {}, "closes_at": closes_at,
            "retained_until": retained_until, "analysis": None,
            "creation_hash": fingerprint, "request_hash": request_hash,
        }
        for _ in range(self.MAX_RETRIES):
            document = self.store.get(key)
            if document:
                value = document.value
                if value["request_hash"] != request_hash or value["creation_hash"] != fingerprint:
                    raise SlackDomainError("create request was already used with different input", 409)
            elif self._save(key, None, new_value, retained_until):
                value = new_value
            else:
                continue
            self._index(team, user, value)
            return self._summary(value, user)
        raise SlackDomainError("room creation conflicted; please retry", 409)

    def get_room(self, team: str, user: str, code: str) -> dict:
        """Internal data for the trusted adapter; never serialize this to users."""
        return self._room_document(team, user, code).value

    def join_room(self, team: str, user: str, code: str, channel: str) -> dict:
        self._identity(team, user)
        self._identity(team, channel)
        key = self._room_key(team, code)
        for _ in range(self.MAX_RETRIES):
            document = self.store.get(key)
            if document is None:
                raise SlackDomainError("room not found", 404)
            value = document.value
            if user in value["members"]:
                self._index(team, user, value)
                return self._summary(value, user)
            if channel != value["origin_channel"]:
                raise SlackDomainError("room not found", 404)
            if time.time() >= value["closes_at"]:
                raise SlackDomainError("room is closed", 409)
            if len(value["members"]) >= value["room"]["expected_members"]:
                raise SlackDomainError("room is full", 409)
            value["members"].append(user)
            if self._save(key, document, value, value["retained_until"]):
                self._index(team, user, value)
                return self._summary(value, user)
        raise SlackDomainError("room membership changed; please retry", 409)

    def submit(
        self, team: str, user: str, code: str, payload: SubmissionCreate, request_id: str,
    ) -> dict:
        self._request(request_id)
        fingerprint = self._hash(payload.model_dump())
        key = self._room_key(team, code)
        for _ in range(self.MAX_RETRIES):
            document = self._room_document(team, user, code)
            value = document.value
            room = value["room"]
            existing = value["submitted_users"].get(user)
            if existing:
                if existing["request_id"] == request_id and existing["payload_hash"] == fingerprint:
                    return self._summary(value, user)
                raise SlackDomainError("you already submitted to this room", 409)
            if time.time() >= value["closes_at"]:
                raise SlackDomainError("room is closed", 409)
            if len(room["submissions"]) >= room["expected_members"]:
                raise SlackDomainError("room is full", 409)
            if payload.participant_name is not None:
                raise SlackDomainError("participant names are not accepted in Slack rooms", 422)
            if set(payload.scores) != set(room["options"]) or set(payload.weights) != set(room["criteria"]):
                raise SlackDomainError("scores and weights must match the room labels", 422)
            if any(set(scores) != set(room["criteria"]) for scores in payload.scores.values()):
                raise SlackDomainError("each score must cover every room criterion", 422)
            if payload.first_choice not in room["options"]:
                raise SlackDomainError("first_choice must be one of the room options", 422)
            room["submissions"].append(Submission(id=str(uuid4()), **payload.model_dump()).model_dump(mode="json"))
            value["submitted_users"][user] = {"request_id": request_id, "payload_hash": fingerprint}
            if self._save(key, document, value, value["retained_until"]):
                return self._summary(value, user)
        raise SlackDomainError("another submission arrived; please retry", 409)

    def analysis(self, team: str, user: str, code: str) -> dict:
        key = self._room_key(team, code)
        for _ in range(self.MAX_RETRIES):
            document = self._room_document(team, user, code)
            value = document.value
            room = value["room"]
            if len(room["submissions"]) < room["expected_members"]:
                raise SlackDomainError("all expected members must submit before analysis", 409)
            if value["analysis"] is not None:
                return value["analysis"]
            # Complete rooms are immutable. No private identity enters statistics.
            result = analyze_room(room["submissions"], room["options"], room["criteria"])
            value["analysis"] = result
            if self._save(key, document, value, value["retained_until"]):
                return result
        raise SlackDomainError("analysis changed; please retry", 409)

    def get_history(self, team: str, user: str, code: str) -> dict:
        value = self._room_document(team, user, code).value
        room = self._summary(value, user)
        return {
            "room": room,
            "analysis": self.analysis(team, user, code) if room["is_complete"] else None,
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
                room_document = self._room_document(team, user, ref["code"])
            except SlackDomainError as exc:
                if exc.status == 404:
                    continue
                raise
            results.append(self._summary(room_document.value, user))
            if len(results) > limit:
                break
        has_more = len(results) > limit
        results = results[:limit]
        next_cursor = None
        if has_more:
            next_cursor = self._cursor(team, user, (results[-1]["created_at"], results[-1]["code"]))
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
