"""Pure Block Kit builders and strict parsers for the Slack integration.

All user-controlled display text uses ``plain_text``; input state is addressed
by fixed IDs and option indices, never by labels. Authorization and the opaque
``private_metadata`` lifecycle belong to the Slack router/service.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .models import Room, RoomCreate, SubmissionCreate


MAX_SLACK_OPTIONS = 5
MAX_SLACK_CRITERIA = 5
MAX_SLACK_MEMBERS = 20
MAX_HISTORY_ROOMS = 30
ACTION_VALUE = "value"


class ViewValidationError(ValueError):
    """Errors suitable for a Slack ``response_action: errors`` response."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(errors.values()))


def _text(value: Any, limit: int = 3000) -> dict[str, Any]:
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return {"type": "plain_text", "text": text or "—", "emoji": False}


def _section(value: Any) -> dict[str, Any]:
    return {"type": "section", "text": _text(value)}


def _modal(title: str, blocks: list[dict], metadata: str = "", **extra: Any) -> dict:
    if len(blocks) > 100:
        raise ValueError("Slack modals support at most 100 blocks")
    if not isinstance(metadata, str) or len(metadata) > 3000:
        raise ValueError("Slack private_metadata must be a string of at most 3000 characters")
    return {
        "type": "modal",
        "title": _text(title, 24),
        "close": _text("닫기", 24),
        "private_metadata": metadata,
        "blocks": blocks,
        **extra,
    }


def _option(label: str, value: str) -> dict:
    return {"text": _text(label, 75), "value": value}


def _input(block_id: str, label: str, element: dict, *, optional: bool = False, hint: str = "") -> dict:
    block = {
        "type": "input", "block_id": block_id,
        "label": _text(label, 2000), "element": {"action_id": ACTION_VALUE, **element},
        "optional": optional,
    }
    if hint:
        block["hint"] = _text(hint, 2000)
    return block


def _select(options: list[dict], initial: str | None = None) -> dict:
    element: dict[str, Any] = {"type": "static_select", "options": options}
    if initial is not None:
        element["initial_option"] = next(option for option in options if option["value"] == initial)
    return element


def _button(label: str, action_id: str, value: str) -> dict:
    if not isinstance(value, str) or not value or len(value) > 2000:
        raise ValueError("Slack button values must contain 1–2000 characters")
    return {"type": "button", "text": _text(label, 75), "action_id": action_id, "value": value}


def _data(value: Any) -> Mapping:
    if isinstance(value, Mapping):
        return value
    return value.model_dump()


def create_room_view(metadata: str, retention_days: int = 90) -> dict:
    """Create an anonymous room; form duration is separate from history retention."""
    blocks = [
        _section(f"팀원에게는 개인 답변과 작성자 정보가 공개되지 않습니다. Slack 계정은 중복 제출 방지와 내 방 목록에 사용하며, 참여 이력과 분석 결과는 {retention_days}일 동안 보관합니다."),
        _input("question", "어떤 결정을 함께 내릴까요?", {"type": "plain_text_input", "max_length": 500}),
        _input("options", "선택지", {"type": "plain_text_input", "multiline": True, "max_length": 404}, hint="한 줄에 하나씩 2–5개, 선택지당 80자 이내로 입력하세요."),
        _input("criteria", "평가 기준", {"type": "plain_text_input", "multiline": True, "max_length": 404}, hint="한 줄에 하나씩 1–5개, 기준당 80자 이내로 입력하세요."),
        _input("expected_members", "참여 인원", _select([_option(f"{number}명", str(number)) for number in range(1, MAX_SLACK_MEMBERS + 1)], "4")),
        _input("expires_in_hours", "의견을 받을 기간", _select([_option("24시간", "24"), _option("3일", "72"), _option("7일", "168")], "24")),
    ]
    return _modal("새 의견방", blocks, metadata, callback_id="consensus_create", submit=_text("방 만들기", 24))


def _read(values: dict, block_id: str, *, selected: bool = False) -> Any:
    if not isinstance(values, dict):
        return None
    block = values.get(block_id)
    element = block.get(ACTION_VALUE) if isinstance(block, dict) else None
    if not isinstance(element, dict):
        return None
    if selected:
        option = element.get("selected_option")
        return option.get("value") if isinstance(option, dict) else None
    return element.get("value")


def _integer(values: dict, block_id: str, minimum: int, maximum: int, errors: dict) -> int:
    value = _read(values, block_id, selected=True)
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 3:
        errors[block_id] = f"{minimum}–{maximum} 범위에서 선택해 주세요."
        return minimum
    number = int(value)
    if not minimum <= number <= maximum:
        errors[block_id] = f"{minimum}–{maximum} 범위에서 선택해 주세요."
    return number


def _labels(values: dict, block_id: str, minimum: int, maximum: int, errors: dict) -> list[str]:
    raw = _read(values, block_id)
    labels = [line.strip() for line in raw.splitlines() if line.strip()] if isinstance(raw, str) else []
    if not minimum <= len(labels) <= maximum:
        errors[block_id] = f"한 줄에 하나씩 {minimum}–{maximum}개를 입력해 주세요."
    elif any(len(label) > 80 for label in labels):
        errors[block_id] = "각 항목은 80자 이내로 입력해 주세요."
    elif len(set(labels)) != len(labels):
        errors[block_id] = "중복된 항목을 제거해 주세요."
    return labels


def parse_create(values: dict) -> RoomCreate:
    errors: dict[str, str] = {}
    raw_question = _read(values, "question")
    question = raw_question.strip() if isinstance(raw_question, str) else ""
    if not question or len(question) > 500:
        errors["question"] = "결정할 주제를 1–500자로 입력해 주세요."
    options = _labels(values, "options", 2, MAX_SLACK_OPTIONS, errors)
    criteria = _labels(values, "criteria", 1, MAX_SLACK_CRITERIA, errors)
    expected_members = _integer(values, "expected_members", 1, MAX_SLACK_MEMBERS, errors)
    duration = _integer(values, "expires_in_hours", 1, 168, errors)
    if duration not in {24, 72, 168}:
        errors["expires_in_hours"] = "24시간, 3일, 7일 중 선택해 주세요."
    if errors:
        raise ViewValidationError(errors)
    return RoomCreate(question=question, options=options, criteria=criteria, expected_members=expected_members, submission_mode="anonymous", expires_in_hours=duration)


def _room_labels(room: Room | dict) -> tuple[Mapping, list[str], list[str]]:
    data = _data(room)
    options, criteria = data["options"], data["criteria"]
    if not 2 <= len(options) <= MAX_SLACK_OPTIONS or not 1 <= len(criteria) <= MAX_SLACK_CRITERIA:
        raise ValueError("Slack 의견 입력은 선택지 2–5개, 평가 기준 1–5개를 지원합니다.")
    return data, options, criteria


def submission_view(room: Room | dict, metadata: str) -> dict:
    data, options, criteria = _room_labels(room)
    blocks = [
        _section(data["question"]),
        _section("각 선택지가 기준을 얼마나 충족하는지 1점(매우 낮음)–5점(매우 높음)으로 평가해 주세요. 개인 답변과 작성자 정보는 팀원에게 공개되지 않습니다. 제출 후 수정할 수 없습니다."),
    ]
    for option_index, option in enumerate(options):
        for criterion_index, criterion in enumerate(criteria):
            blocks.append(_input(f"s_{option_index}_{criterion_index}", f"{option_index + 1}. {option} · {criterion}", _select([_option(f"{score}점", str(score)) for score in range(1, 6)])))
    blocks.append(_section("기준의 상대적인 중요도를 1–100으로 정해 주세요. 같은 값이면 같은 비중이며, 분석할 때 전체 합으로 나누어 반영합니다."))
    for index, criterion in enumerate(criteria):
        blocks.append(_input(f"w_{index}", f"{criterion} 중요도", _select([_option(str(weight), str(weight)) for weight in range(1, 101)], "10")))
    blocks.extend([
        _input("first_choice", "현재 가장 선호하는 선택지", _select([_option(f"{index + 1}. {option}", str(index)) for index, option in enumerate(options)])),
        _input("reason", "이유 또는 우려 사항", {"type": "plain_text_input", "multiline": True, "max_length": 2000}, optional=True, hint="이름이나 개인을 식별할 정보를 포함하지 마세요. 내용은 팀의 집계 분석에 반영됩니다."),
    ])
    return _modal("내 의견 남기기", blocks, metadata, callback_id="consensus_submit", submit=_text("의견 제출", 24))


def parse_submission(values: dict, room: Room | dict) -> SubmissionCreate:
    _, options, criteria = _room_labels(room)
    errors: dict[str, str] = {}
    scores = {option: {criterion: _integer(values, f"s_{oi}_{ci}", 1, 5, errors) for ci, criterion in enumerate(criteria)} for oi, option in enumerate(options)}
    weights = {criterion: _integer(values, f"w_{index}", 1, 100, errors) for index, criterion in enumerate(criteria)}
    first_choice = _integer(values, "first_choice", 0, len(options) - 1, errors)
    raw_reason = _read(values, "reason")
    reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
    if raw_reason is not None and not isinstance(raw_reason, str):
        errors["reason"] = "이유는 텍스트로 입력해 주세요."
    elif len(reason) > 2000:
        errors["reason"] = "이유는 2,000자 이내로 입력해 주세요."
    if errors:
        raise ViewValidationError(errors)
    return SubmissionCreate(scores=scores, weights=weights, first_choice=options[first_choice], reason=reason)


def _progress(summary: Mapping) -> str:
    count = summary.get("submission_count", 0)
    expected = summary.get("expected_members", 0)
    status = "제출 완료" if summary.get("is_complete") else "의견 수집 중"
    if summary.get("status") in {"expired", "closed"}:
        status = "의견 수집 종료"
    return f"{status} · {count}/{expected}명 제출"


def room_message(summary: dict) -> dict:
    """Channel-safe invitation with no participant or individual answer fields."""
    code = summary["code"]
    return {
        "text": "SynQ 의견방이 열렸습니다. 의견 제출과 현황 조회 버튼을 이용해 주세요.",
        "blocks": [
            _section(summary["question"]),
            _section(f"방 코드: {code}\n{_progress(summary)}\n팀원에게는 집계 결과만 공개됩니다."),
            {"type": "actions", "elements": [
                _button("의견 남기기", "consensus_join", code),
                _button("제출 현황", "consensus_status", code),
                _button("분석 결과", "consensus_results", code),
            ]},
        ],
    }


def history_view(page: dict, metadata: str = "", retention_days: int = 90) -> dict:
    """Personal modal. Caller must supply only rooms accessible to this user."""
    rooms = page.get("rooms", [])
    if len(rooms) > MAX_HISTORY_ROOMS:
        raise ValueError(f"History pages must contain at most {MAX_HISTORY_ROOMS} rooms")
    blocks = [_section(f"내가 만들거나 참여한 의견방입니다. 참여 이력과 분석 결과는 방 생성 후 {retention_days}일 동안 보관됩니다.")]
    for index, room in enumerate(rooms):
        own_state = " · 내 의견 제출됨" if room.get("has_submitted") else ""
        buttons = [
            _button("제출 현황", "consensus_status", room["code"]),
            _button("분석 결과", "consensus_results", room["code"]),
        ]
        if room.get("status") == "collecting" and not room.get("has_submitted"):
            buttons.insert(0, _button("의견 남기기", "consensus_join", room["code"]))
        blocks.extend([
            _section(f"{room['question']}\n방 코드: {room['code']}\n{_progress(room)}{own_state}"),
            {"type": "actions", "block_id": f"h_{index}", "elements": buttons},
        ])
    if not rooms:
        blocks.append(_section("아직 참여한 의견방이 없습니다. /synq 명령으로 방을 만들거나 채널의 참여 버튼을 눌러 주세요."))
    if page.get("next_cursor"):
        blocks.append({"type": "actions", "elements": [_button("다음 페이지", "consensus_more", page["next_cursor"])]})
    return _modal("내 의견방", blocks, metadata)


def _percentage(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return "—"
    return f"{value * 100:.1f}%"


def result_view(summary: dict, analysis: dict) -> dict:
    """Render an allowlist of aggregate fields, never raw answers or identities."""
    data = _data(analysis)
    blocks = [
        _section(f"{summary['question']}\n방 코드: {summary['code']} · {_progress(summary)}"),
        _section(f"현재 평가 1위: {data.get('current_winner') or '—'}\n가중치 변화에 가장 안정적인 선택: {data.get('robust_choice') or '—'}"),
    ]
    votes, stability = data.get("vote_share", {}), data.get("stability", {})
    options = summary.get("options") or list(dict.fromkeys([*votes, *stability]))
    for option in options[:10]:
        blocks.append(_section(f"{option}\n초기 1순위 비율: {_percentage(votes.get(option))} · Stability: {_percentage(stability.get(option))}"))
    blocks.append(_section("Stability는 가중치를 바꾼 시뮬레이션에서 해당 선택지가 1위였던 비율입니다. 실제 성공 확률을 의미하지 않습니다."))
    flips = data.get("flip_points") or []
    for flip in flips[:10]:
        if flip.get("type") == "weight":
            detail = f"{flip.get('criterion', '기준')}: {_percentage(flip.get('from'))} → {_percentage(flip.get('to'))}이면 1위가 {flip.get('new_winner', '—')}(으)로 바뀝니다."
        elif flip.get("type") == "member":
            detail = f"한 명의 의견을 제외하면 1위가 {flip.get('new_winner', '—')}(으)로 바뀔 수 있습니다."
        else:
            continue
        blocks.append(_section("결과가 바뀌는 조건\n" + detail))
    if not flips:
        blocks.append(_section("현재 분석 범위에서 결과가 바뀌는 조건을 찾지 못했습니다."))
    for index, item in enumerate((data.get("discussion_agenda") or [])[:20], 1):
        blocks.append(_section(f"토론할 질문 {index}\n{item}"))
    advocate = data.get("devils_advocate")
    if advocate:
        for item in (_data(advocate).get("challenges") or [])[:3]:
            blocks.append(_section(f"함께 점검할 반론\n{item}"))
    return _modal("팀 분석 결과", blocks)
