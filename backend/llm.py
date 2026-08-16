"""Small, optional OpenAI REST adapter.

The API remains fully usable without ``OPENAI_API_KEY``. Any missing key, timeout,
bad response, or validation error returns ``None`` instead of failing a request.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import DevilsAdvocate, ParsedOpinion


OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _chat_json(system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    request = Request(
        OPENAI_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "5"))
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except (
        HTTPError,
        URLError,
        OSError,
        TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ):
        return None


def parse_opinion(
    reason: str,
    options: list[str],
    criteria: list[str],
) -> ParsedOpinion | None:
    """Convert free text to categorical labels; never create numeric results."""

    if not reason.strip():
        return None

    result = _chat_json(
        (
            "Structure an anonymous decision rationale as JSON. Return only "
            "preferred_option, positive, and concerns. preferred_option must be one "
            "provided option; positive and concerns may contain only provided criteria. "
            "Do not produce scores, rankings, probabilities, or other numbers."
        ),
        {"reason": reason, "options": options, "criteria": criteria},
    )
    if result is None:
        return None

    try:
        opinion = ParsedOpinion.model_validate(result)
    except ValueError:
        return None

    allowed_criteria = set(criteria)
    if opinion.preferred_option not in options:
        return None
    if not set(opinion.positive).issubset(allowed_criteria):
        return None
    if not set(opinion.concerns).issubset(allowed_criteria):
        return None
    return opinion


def generate_devils_advocate(
    target: str | None,
    low_agreement: list[str],
    concerns: list[str],
) -> DevilsAdvocate | None:
    """Generate two or three qualitative challenges to the current winner."""

    if not target:
        return None

    result = _chat_json(
        (
            "Act as a constructive red-team reviewer. Return JSON with a challenges "
            "array containing 2 or 3 concise questions that test when the target "
            "decision could fail. Use only the supplied qualitative evidence. Do not "
            "invent scores, probabilities, or numeric claims."
        ),
        {
            "target": target,
            "low_agreement": low_agreement,
            "concerns": concerns,
        },
    )
    if result is None:
        return None

    challenges = result.get("challenges")
    if not isinstance(challenges, list):
        return None
    cleaned = [item.strip() for item in challenges if isinstance(item, str) and item.strip()]
    if not 2 <= len(cleaned) <= 3:
        return None
    return DevilsAdvocate(target=target, challenges=cleaned)
