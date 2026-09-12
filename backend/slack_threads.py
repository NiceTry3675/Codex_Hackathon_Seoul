"""Bounded retrieval of one explicitly selected Slack thread."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit
import re


@dataclass(frozen=True)
class ThreadReference:
    channel: str
    timestamp: str
    permalink: str


@dataclass(frozen=True)
class ThreadText:
    messages: list[str]
    partial: bool


def parse_thread_link(value: str, current_channel: str) -> ThreadReference:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].split("|", 1)[0]
    parsed = urlsplit(value)
    match = re.fullmatch(r"/archives/([CG][A-Z0-9]+)/p([0-9]{10})([0-9]{6})", parsed.path)
    if (parsed.scheme != "https" or not parsed.hostname or not re.fullmatch(r"[a-z0-9-]+\.slack\.com", parsed.hostname)
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or not match or match[1] != current_channel):
        raise ValueError("Use a thread link from the command's channel")
    query = parse_qs(parsed.query, max_num_fields=10)
    timestamps = query.get("thread_ts", [f"{match[2]}.{match[3]}"])
    if len(timestamps) != 1 or not re.fullmatch(r"[0-9]{10}\.[0-9]{6}", timestamps[0]):
        raise ValueError("Invalid thread timestamp")
    timestamp = timestamps[0]
    permalink = f"https://{parsed.hostname}/archives/{current_channel}/p{timestamp.replace('.', '')}"
    return ThreadReference(current_channel, timestamp, permalink)


def read_thread(reference: ThreadReference, read_page) -> ThreadText:
    """Read up to 100 messages / 20,000 characters, following bounded cursor pages."""
    messages = []
    characters = 0
    inspected = 0
    seen_cursors = set()
    seen_messages = set()
    cursor = ""
    for _ in range(10):
        page = read_page(reference.channel, reference.timestamp, cursor)
        raw_messages = page.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("Invalid Slack thread response")
        for message in raw_messages:
            if not isinstance(message, dict):
                continue
            timestamp = message.get("ts")
            if not isinstance(timestamp, str) or timestamp in seen_messages:
                continue
            seen_messages.add(timestamp)
            inspected += 1
            if inspected > 100:
                return ThreadText(messages, True)
            if message.get("bot_id") or message.get("subtype") in {"bot_message", "message_deleted"}:
                continue
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            text = re.sub(r"<@[A-Z0-9]+>", "[참여자]", text.strip())
            remaining = 20_000 - characters
            if remaining <= 0:
                return ThreadText(messages, True)
            messages.append(text[:remaining])
            characters += len(messages[-1])
            if len(text) > remaining:
                return ThreadText(messages, True)
        next_cursor = page.get("response_metadata", {}).get("next_cursor", "")
        if not next_cursor:
            return ThreadText(messages, bool(page.get("has_more")))
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ValueError("Invalid Slack pagination")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return ThreadText(messages, True)
