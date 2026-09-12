"""Versioned Slack documents in the existing DynamoDB table or local memory.

Every key is namespaced, so public room-code endpoints cannot read Slack rooms.
TTL is checked on reads as DynamoDB deletion is asynchronous. All mutations use
compare-and-swap; a failed conditional write never silently loses another vote.
"""

from __future__ import annotations

import copy
import base64
from dataclasses import dataclass
import json
import os
from threading import RLock
import time
import zlib


@dataclass(frozen=True)
class SlackDocument:
    value: dict
    version: int
    expires_at: int


class SlackStore:
    def __init__(self, table_name: str | None = None, table=None) -> None:
        self._table_name = (
            os.getenv("CONSENSUS_TABLE_NAME", "").strip()
            if table_name is None else table_name.strip()
        )
        self._table = table
        self._memory: dict[str, SlackDocument] = {}
        self._lock = RLock()

    @property
    def persistent(self) -> bool:
        return bool(self._table_name or self._table is not None)

    def _dynamo_table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    @staticmethod
    def _check_key(key: str) -> None:
        if not key.startswith("SLACK#") or len(key.encode("utf-8")) > 1024:
            raise ValueError("Slack document keys must use the SLACK# namespace")

    def get(self, key: str) -> SlackDocument | None:
        self._check_key(key)
        if not self.persistent:
            with self._lock:
                document = self._memory.get(key)
                if document is None:
                    return None
                if document.expires_at <= time.time():
                    self._memory.pop(key, None)
                    return None
                return copy.deepcopy(document)
        item = self._dynamo_table().get_item(
            Key={"code": key}, ConsistentRead=True,
        ).get("Item")
        if item is None or int(item["expires_at"]) <= time.time():
            return None
        encoded = item["slack_json"]
        if item.get("slack_encoding") == "zlib-base64":
            decoder = zlib.decompressobj()
            raw = decoder.decompress(base64.b64decode(encoded, validate=True), 2_000_001)
            if len(raw) > 2_000_000 or not decoder.eof:
                raise ValueError("Slack document exceeds decoded size limit")
            encoded = raw.decode("utf-8")
        return SlackDocument(
            value=json.loads(encoded),
            version=int(item["version"]),
            expires_at=int(item["expires_at"]),
        )

    def compare_and_swap(
        self, key: str, expected_version: int | None, value: dict, expires_at: int,
    ) -> bool:
        self._check_key(key)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        raw = encoded.encode("utf-8")
        if len(raw) > 2_000_000:
            raise ValueError("Slack document is too large")
        encoding = "json"
        stored = encoded
        # Repeated option/criterion labels dominate larger room documents.
        # Compress transparently so all 20 supported members can submit full
        # Unicode inputs and still leave space for the aggregate snapshot.
        if len(raw) > 300_000:
            stored = base64.b64encode(zlib.compress(raw)).decode("ascii")
            encoding = "zlib-base64"
        # Leave headroom for DynamoDB attribute names, code, version and TTL.
        if len(stored.encode("utf-8")) > 390_000:
            raise ValueError("Slack document is too large")
        now = time.time()
        if expires_at <= now:
            return False
        version = 1 if expected_version is None else expected_version + 1
        if not self.persistent:
            with self._lock:
                current = self._memory.get(key)
                live = current is not None and current.expires_at > now
                if expected_version is None:
                    if live:
                        return False
                elif not live or current.version != expected_version:
                    return False
                self._memory[key] = SlackDocument(json.loads(encoded), version, expires_at)
                return True

        from botocore.exceptions import ClientError

        if expected_version is None:
            condition = "attribute_not_exists(#code) OR #ttl <= :now"
            names = {"#code": "code", "#ttl": "expires_at"}
            values = {":now": int(now)}
        else:
            condition = "#version = :version AND #ttl > :now"
            names = {"#version": "version", "#ttl": "expires_at"}
            values = {":version": expected_version, ":now": int(now)}
        try:
            self._dynamo_table().put_item(
                Item={
                    "code": key, "slack_json": stored, "slack_encoding": encoding,
                    "version": version, "expires_at": expires_at,
                },
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True
