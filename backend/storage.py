"""Room persistence with an in-memory fallback and DynamoDB in production."""

from __future__ import annotations

import os
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
    def _item(room: Room) -> dict:
        return {
            "code": room.code,
            "room_json": room.model_dump_json(),
            "version": room.version,
            # DynamoDB TTL requires an epoch-seconds Number at top level.
            "expires_at": int(room.expires_at.timestamp()),
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
        normalized = code.upper()
        if not self.persistent:
            with self._lock:
                room = self._memory.get(normalized)
                if room is not None and self._expired(room):
                    self._memory.pop(normalized, None)
                    return None
                return room

        response = self._dynamo_table().get_item(
            Key={"code": normalized},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        room = Room.model_validate_json(item["room_json"])
        return None if self._expired(room) else room

    def save(self, room: Room) -> None:
        if not self.persistent:
            with self._lock:
                self._memory[room.code] = room
            return
        self._dynamo_table().put_item(Item=self._item(room))

    def append_submission(
        self,
        code: str,
        submission: Submission,
        token_hash: str | None,
    ) -> tuple[str, Room | None]:
        """Atomically append once; memory and DynamoDB expose the same outcomes."""

        normalized = code.upper()
        if not self.persistent:
            with self._lock:
                room = self.get(normalized)
                if room is None:
                    return "not_found", None
                outcome = self._submission_outcome(room, submission, token_hash)
                if outcome != "ok":
                    return outcome, room
                room.submissions.append(submission)
                if token_hash is not None:
                    room.used_anonymous_token_hashes.append(token_hash)
                room.version += 1
                self._memory[normalized] = room
                return "ok", room

        from botocore.exceptions import ClientError

        for _attempt in range(5):
            room = self.get(normalized)
            if room is None:
                return "not_found", None
            outcome = self._submission_outcome(room, submission, token_hash)
            if outcome != "ok":
                return outcome, room
            expected_version = room.version
            updated = room.model_copy(deep=True)
            updated.submissions.append(submission)
            if token_hash is not None:
                updated.used_anonymous_token_hashes.append(token_hash)
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
        token_hash: str | None,
    ) -> str:
        if len(room.submissions) >= room.expected_members:
            return "full"
        if token_hash is not None and token_hash in room.used_anonymous_token_hashes:
            return "duplicate_token"
        if submission.participant_name is not None and any(
            item.participant_name == submission.participant_name for item in room.submissions
        ):
            return "duplicate_name"
        return "ok"
