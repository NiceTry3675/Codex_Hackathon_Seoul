"""Small, optional OpenAI REST adapter.

The API remains fully usable without ``OPENAI_API_KEY``. Any missing key, timeout,
bad response, or validation error returns ``None`` instead of failing a request.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import DevilsAdvocate, ParsedOpinion


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
logger = logging.getLogger(__name__)


PARSED_OPINION_SCHEMA = {
    "type": "object",
    "properties": {
        "preferred_option": {"type": "string"},
        "positive": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["preferred_option", "positive", "concerns"],
    "additionalProperties": False,
}

DEVILS_ADVOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "challenges": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
        }
    },
    "required": ["challenges"],
    "additionalProperties": False,
}


def _chat_json(
    system_prompt: str,
    payload: dict[str, Any],
    *,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.info("OpenAI call skipped: OPENAI_API_KEY is not configured")
        return None

    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
        "max_completion_tokens": 500,
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

    started_at = time.monotonic()
    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "5"))
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            logger.warning("OpenAI returned a non-object JSON response")
            return None
        logger.info(
            "OpenAI call succeeded model=%s latency_ms=%d",
            body["model"],
            round((time.monotonic() - started_at) * 1000),
        )
        return parsed
    except (
        HTTPError,
        URLError,
        OSError,
        TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        status_code = exc.code if isinstance(exc, HTTPError) else None
        logger.warning(
            "OpenAI call failed error=%s status=%s latency_ms=%d",
            type(exc).__name__,
            status_code,
            round((time.monotonic() - started_at) * 1000),
        )
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
        schema_name="parsed_opinion",
        schema=PARSED_OPINION_SCHEMA,
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
        schema_name="devils_advocate",
        schema=DEVILS_ADVOCATE_SCHEMA,
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


def fallback_devils_advocate(
    target: str,
    low_agreement: list[str],
    concerns: list[str],
) -> DevilsAdvocate:
    """Build a deterministic qualitative fallback without inventing statistics."""

    evidence = concerns[0] if concerns else (low_agreement[0] if low_agreement else None)
    if evidence:
        first = (
            f"{evidence}에 대한 판단이 틀렸다면 {target} 선택은 어떻게 실패할 수 있나요?"
        )
    else:
        first = f"{target} 선택이 성립하려면 반드시 참이어야 하는 가정은 무엇인가요?"
    second = (
        f"{target} 추진을 중단하고 대안으로 전환해야 할 가장 이른 신호는 무엇인가요?"
    )
    return DevilsAdvocate(target=target, challenges=[first, second])
