"""Slack modal layouts and validation, with no network or persistence work."""

import json

from pydantic import ValidationError

from .models import DecisionDraft, RoomCreate

CREATE_CALLBACK = "synq_create_room"


def plain(text: str) -> dict:
    return {"type": "plain_text", "text": text}


def creation_modal(team: str, channel: str, draft: DecisionDraft | None = None, notice: str = "", source_url: str = "") -> dict:
    fields = [
        ("question", "결정할 질문", 500, False, None),
        ("options", "선택지 · 한 줄에 하나, 2~10개", 2009, True, None),
        ("criteria", "판단 기준 · 한 줄에 하나, 1~10개", 2009, True, None),
        ("expected_members", "참여 인원 · 1~100명", 3, False, "4"),
        ("expires_in_hours", "제출 마감과 공개 방 이용 기간 · 1~168시간", 3, False, "24"),
        ("context", "결정 배경 · 선택 입력", 3000, True, None),
    ]
    blocks = [{"type": "section", "text": plain(
        "만들기를 누르면 이 채널에 평가 링크를 게시하고, 전원 제출 시 완료를 알립니다. "
        "Slack 또는 웹에서 평가하며 개인 답변은 동료에게 공개하지 않습니다. "
        "Slack 계정은 중복 제출 방지와 내 기록에 사용됩니다. "
        "방 코드를 가진 사람은 공개 기간 동안 접근할 수 있고, 이후 개인 기록은 별도 보관합니다."
    )}]
    if notice:
        blocks.append({"type": "section", "text": plain(notice)})
    if source_url:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"<{source_url}|추천에 사용한 스레드>"}})
    prefilled = {} if draft is None else {
        "question": draft.question, "options": "\n".join(draft.options),
        "criteria": "\n".join(draft.criteria), "context": draft.context,
    }
    for key, label, limit, multiline, initial in fields:
        element = {"type": "plain_text_input", "action_id": "value",
                   "max_length": limit, "multiline": multiline}
        initial = prefilled.get(key, initial)
        if initial:
            element["initial_value"] = initial
        blocks.append({"type": "input", "block_id": key, "label": plain(label),
                       "optional": key == "context", "element": element})
    return {
        "type": "modal", "callback_id": CREATE_CALLBACK,
        "private_metadata": json.dumps({"team_id": team, "channel_id": channel}),
        "title": plain("결정 만들기"), "submit": plain("만들기"), "close": plain("취소"),
        "blocks": blocks,
    }


def status_modal(text: str, blocks: list | None = None) -> dict:
    return {"type": "modal", "title": plain("결정 만들기"), "close": plain("닫기"),
            "blocks": [{"type": "section", "text": plain(text)}] + (blocks or [])}


def parse_submission(view: dict) -> tuple[RoomCreate | None, dict[str, str]]:
    try:
        values = view["state"]["values"]
        if not isinstance(values, dict):
            raise ValueError

        def value(key):
            raw = values.get(key, {}).get("value", {}).get("value")
            if raw is not None and not isinstance(raw, str):
                raise ValueError
            return (raw or "").strip()

        data = {
            "question": value("question"),
            "options": [line.strip() for line in value("options").splitlines() if line.strip()],
            "criteria": [line.strip() for line in value("criteria").splitlines() if line.strip()],
            "expected_members": value("expected_members"),
            "expires_in_hours": value("expires_in_hours"),
            "context": value("context"),
        }
        if len(data["context"]) > 3000:
            return None, {"context": "배경은 3,000자 이내로 입력해주세요."}
        return RoomCreate.model_validate(data), {}
    except ValidationError as exc:
        messages = {
            "question": "질문을 1~500자로 입력해주세요.",
            "options": "서로 다른 선택지 2~10개를 한 줄에 하나씩, 각 200자 이내로 입력해주세요.",
            "criteria": "서로 다른 기준 1~10개를 한 줄에 하나씩, 각 200자 이내로 입력해주세요.",
            "expected_members": "참여 인원을 1~100 사이 정수로 입력해주세요.",
            "expires_in_hours": "공개 방 이용 기간을 1~168 사이 정수로 입력해주세요.",
            "context": "배경은 3,000자 이내로 입력해주세요.",
        }
        return None, {str(error["loc"][0]): messages[str(error["loc"][0])] for error in exc.errors()}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, {"question": "입력 내용을 읽지 못했습니다. 창을 다시 열어주세요."}
