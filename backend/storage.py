"""Room persistence with an in-memory fallback and DynamoDB in production."""

from __future__ import annotations

import os
from typing import MutableMapping

from .models import Room


class RoomStore:
    def __init__(self, memory: MutableMapping[str, Room]) -> None:
        self._memory = memory
        self._table_name = os.getenv("CONSENSUS_TABLE_NAME", "").strip()
        self._table = None

    @property
    def persistent(self) -> bool:
        return bool(self._table_name)

    def _dynamo_table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    def create(self, room: Room) -> bool:
        if not self.persistent:
            if room.code in self._memory:
                return False
            self._memory[room.code] = room
            return True

        from botocore.exceptions import ClientError

        try:
            self._dynamo_table().put_item(
                Item={"code": room.code, "room_json": room.model_dump_json()},
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
            return self._memory.get(normalized)

        response = self._dynamo_table().get_item(
            Key={"code": normalized},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        return Room.model_validate_json(item["room_json"])

    def save(self, room: Room) -> None:
        if not self.persistent:
            self._memory[room.code] = room
            return
        self._dynamo_table().put_item(
            Item={"code": room.code, "room_json": room.model_dump_json()}
        )
