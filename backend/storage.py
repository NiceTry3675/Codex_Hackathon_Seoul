"""Room persistence with an in-memory fallback and DynamoDB in production."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import MutableMapping

from .models import Room, Submission


class RoomStore:
    def __init__(self, memory: MutableMapping[str, Room]) -> None:
        self._memory = memory
        self._table_name = os.getenv("CONSENSUS_TABLE_NAME", "").strip()
        self._table = None
        self._lock = RLock()

    @property
    def persistent(self) -> bool:
        return bool(self._table_name)

    def _dynamo_table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    @staticmethod
    def _expired(room: Room) -> bool:
        return room.expires_at <= datetime.now(timezone.utc)

    @staticmethod
    def _retention_deadline(room: Room) -> datetime:
        return max(room.expires_at, room.retained_until or room.expires_at)

    @staticmethod
    def _item(room: Room) -> dict:
        return {
            "code": room.code,
            "room_json": room.model_dump_json(),
            "version": room.version,
            # DynamoDB TTL requires an epoch-seconds Number at top level.
            "expires_at": int(RoomStore._retention_deadline(room).timestamp()),
        }

    def create(self, room: Room) -> bool:
        if not self.persistent:
            with self._lock:
                if room.code in self._memory:
                    return False
                self._memory[room.code] = room
                return True

        from botocore.exceptions import ClientError

        try:
            self._dynamo_table().put_item(
                Item=self._item(room),
                ConditionExpression="attribute_not_exists(code)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get(self, code: str) -> Room | None:
        room = self.get_retained(code)
        return None if room is None or self._expired(room) else room

    def get_retained(self, code: str) -> Room | None:
        """Read a retained room; callers must enforce private-history access."""

        normalized = code.upper()
        # Slack account/index/receipt documents share the DynamoDB table, but
        # are never Room objects and cannot be reached through room lookups.
        if normalized.startswith("SLACK#"):
            return None
        if not self.persistent:
            with self._lock:
                room = self._memory.get(normalized)
                if room is not None and self._retention_deadline(room) <= datetime.now(timezone.utc):
                    self._memory.pop(normalized, None)
                    return None
                return room

        response = self._dynamo_table().get_item(
            Key={"code": normalized},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item or "room_json" not in item:
            return None
        room = Room.model_validate_json(item["room_json"])
        return None if self._retention_deadline(room) <= datetime.now(timezone.utc) else room

    def save(self, room: Room) -> None:
        """Save analysis changes without rolling back submissions or retention."""

        if not self.persistent:
            with self._lock:
                current = self._memory.get(room.code)
                self._memory[room.code] = self._merge_saved_room(room, current)
            return

        from botocore.exceptions import ClientError

        for _attempt in range(5):
            current = self.get_retained(room.code)
            if current is None:
                if self.create(room):
                    return
                continue
            updated = self._merge_saved_room(room, current)
            try:
                self._dynamo_table().put_item(
                    Item=self._item(updated),
                    ConditionExpression="#version = :expected_version",
                    ExpressionAttributeNames={"#version": "version"},
                    ExpressionAttributeValues={":expected_version": current.version},
                )
                return
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
        raise RuntimeError("room changed while saving; please retry")

    @staticmethod
    def _merge_saved_room(room: Room, current: Room | None) -> Room:
        updated = room.model_copy(deep=True)
        if current is None:
            return updated
        updated.version = max(room.version, current.version) + 1
        if current.created_at != room.created_at:
            return updated

        # These fields are committed by append_submission/retain_until. Analysis
        # can hold an older snapshot while a final submitter extends retention.
        updated.submissions = [item.model_copy(deep=True) for item in current.submissions]
        updated.used_anonymous_token_hashes = list(current.used_anonymous_token_hashes)
        retained = [value for value in (room.retained_until, current.retained_until) if value is not None]
        updated.retained_until = max(retained) if retained else None
        updated.expires_at = current.expires_at
        updated.creation_request_id = current.creation_request_id
        updated.slack_origin = current.slack_origin.model_copy(deep=True) if current.slack_origin else None

        # An older analysis snapshot must not erase a completed decision. These
        # fields are append-only in the API; debate progress is likewise monotone.
        for field in ("decision_record", "decision_recheck"):
            if getattr(current, field) is not None:
                setattr(updated, field, deepcopy(getattr(current, field)))
        if current.devils_advocate_generated and not room.devils_advocate_generated:
            updated.devils_advocate_generated = True
            updated.devils_advocate = current.devils_advocate.model_copy(deep=True) if current.devils_advocate else None
            updated.devils_advocate_source = current.devils_advocate_source
        if current.debate is not None and (
            room.debate is None
            or (current.debate.completed and not room.debate.completed)
            or len(current.debate.messages) > len(room.debate.messages)
        ):
            updated.debate = current.debate.model_copy(deep=True)
        return updated

    def retain_until(self, code: str, deadline: datetime) -> Room | None:
        """Extend a live room's private retention without changing its deadline."""

        normalized = code.upper()
        if not self.persistent:
            with self._lock:
                room = self.get(normalized)
                if room is None:
                    return None
                if deadline > self._retention_deadline(room):
                    room.retained_until = deadline
                    room.version += 1
                return room.model_copy(deep=True)

        from botocore.exceptions import ClientError

        for _attempt in range(5):
            room = self.get(normalized)
            if room is None:
                return None
            if deadline <= self._retention_deadline(room):
                return room
            updated = room.model_copy(deep=True)
            updated.retained_until = deadline
            updated.version += 1
            try:
                self._dynamo_table().put_item(
                    Item=self._item(updated),
                    ConditionExpression="#version = :expected_version",
                    ExpressionAttributeNames={"#version": "version"},
                    ExpressionAttributeValues={":expected_version": room.version},
                )
                return updated
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
        # Do not report successful retention after exhausting version retries.
        return None

    def append_submission(
        self,
        code: str,
        submission: Submission,
        token_hash: str | None,
        additional_token_hashes: list[str] | None = None,
        *,
        idempotent: bool = False,
        retained_until: datetime | None = None,
    ) -> tuple[str, Room | None]:
        """Atomically append once; memory and DynamoDB expose the same outcomes."""

        normalized = code.upper()
        token_hashes = list(dict.fromkeys(
            ([token_hash] if token_hash is not None else []) + (additional_token_hashes or [])
        ))
        if not self.persistent:
            with self._lock:
                room = self.get(normalized)
                if room is None:
                    return "not_found", None
                outcome = self._submission_outcome(room, submission, token_hashes, idempotent)
                if outcome != "ok":
                    return outcome, room.model_copy(deep=True)
                room.submissions.append(submission)
                room.used_anonymous_token_hashes.extend(token_hashes)
                if retained_until is not None and retained_until > self._retention_deadline(room):
                    room.retained_until = retained_until
                room.version += 1
                self._memory[normalized] = room
                # Return this append's snapshot. A later concurrent append must not
                # make two callers both observe themselves as the final submission.
                return "ok", room.model_copy(deep=True)

        from botocore.exceptions import ClientError

        for _attempt in range(5):
            room = self.get(normalized)
            if room is None:
                return "not_found", None
            outcome = self._submission_outcome(room, submission, token_hashes, idempotent)
            if outcome != "ok":
                return outcome, room
            expected_version = room.version
            updated = room.model_copy(deep=True)
            updated.submissions.append(submission)
            updated.used_anonymous_token_hashes.extend(token_hashes)
            if retained_until is not None and retained_until > self._retention_deadline(updated):
                updated.retained_until = retained_until
            updated.version += 1
            try:
                self._dynamo_table().put_item(
                    Item=self._item(updated),
                    ConditionExpression="#version = :expected_version",
                    ExpressionAttributeNames={"#version": "version"},
                    ExpressionAttributeValues={":expected_version": expected_version},
                )
                return "ok", updated
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
        return "conflict", self.get(normalized)

    @staticmethod
    def _submission_outcome(
        room: Room,
        submission: Submission,
        token_hashes: list[str],
        idempotent: bool = False,
    ) -> str:
        existing = next((item for item in room.submissions if item.id == submission.id), None)
        if idempotent and existing is not None:
            # LLM parsing may vary across retries; compare only the submitted
            # payload, while retaining the first stored derived analysis.
            if existing.model_dump(exclude={"id", "parsed"}) == submission.model_dump(exclude={"id", "parsed"}):
                return "duplicate_submission"
            if any(token in room.used_anonymous_token_hashes for token in token_hashes):
                return "duplicate_token"
            return "conflict"
        if len(room.submissions) >= room.expected_members:
            return "full"
        if any(token in room.used_anonymous_token_hashes for token in token_hashes):
            return "duplicate_token"
        if submission.participant_name is not None and any(
            item.participant_name == submission.participant_name for item in room.submissions
        ):
            return "duplicate_name"
        return "ok"
