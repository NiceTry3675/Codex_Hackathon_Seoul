"""Slack evaluation and personal history views for the shared six-character rooms.

These builders render only explicitly selected fields. Authorization, signed
private metadata, persistence, and analysis belong to the router and services.
Form state uses indices, never display labels, as Slack block identifiers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .models import Room, SubmissionCreate


EVALUATE_CALLBACK = "synq_evaluate"
MAX_NATIVE_OPTIONS = 5
MAX_NATIVE_CRITERIA = 5
MAX_HISTORY_ROOMS = 30
ACTION_VALUE = "value"


class ViewValidationError(ValueError):
    """Validation errors keyed by the input block ID for inline Slack feedback."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(errors.values()))


def _data(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else value.model_dump()


def _text(value: Any, limit: int = 3000) -> dict:
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return {"type": "plain_text", "text": text or "—", "emoji": False}


def _section(value: Any) -> dict:
    return {"type": "section", "text": _text(value)}


def _modal(title: str, blocks: list[dict], metadata: str, **extra: Any) -> dict:
    if len(blocks) > 100:
        raise ValueError("Slack modals support at most 100 blocks")
    if not isinstance(metadata, str) or len(metadata) > 3000:
        raise ValueError("Slack private_metadata must contain at most 3000 characters")
    return {
        "type": "modal", "title": _text(title, 24), "close": _text("닫기", 24),
        "private_metadata": metadata, "blocks": blocks, **extra,
    }


def _option(label: str, value: str) -> dict:
    # Native room eligibility ensures labels fit; never silently abbreviate a choice.
    if len(label) > 75:
        raise ValueError("Slack select labels support at most 75 characters")
    return {"text": _text(label, 75), "value": value}


def _select(options: list[dict], initial: str | None = None) -> dict:
    element: dict[str, Any] = {"type": "static_select", "options": options}
    if initial is not None:
        element["initial_option"] = next(option for option in options if option["value"] == initial)
    return element


def _input(block_id: str, label: str, element: dict, *, optional: bool = False, hint: str = "") -> dict:
    block = {
        "type": "input", "block_id": block_id, "label": _text(label, 2000),
        "element": {"action_id": ACTION_VALUE, **element}, "optional": optional,
    }
    if hint:
        block["hint"] = _text(hint, 2000)
    return block


def _button(label: str, action_id: str, value: str) -> dict:
    if not isinstance(value, str) or not 1 <= len(value) <= 2000:
        raise ValueError("Slack button values must contain 1–2000 characters")
    return {"type": "button", "text": _text(label, 75), "action_id": action_id, "value": value}


def supports_native(room: Room | dict) -> bool:
    """Whether every field can be shown in the compact anonymous Slack form.

    Other shared rooms remain usable through their existing web evaluation page.
    Selection labels must fit without changing or truncating the actual choices.
    """
    data = _data(room)
    options, criteria = data.get("options", []), data.get("criteria", [])
    return (
        data.get("submission_mode", "anonymous") == "anonymous"
        and isinstance(options, list) and isinstance(criteria, list)
        and 2 <= len(options) <= MAX_NATIVE_OPTIONS
        and 1 <= len(criteria) <= MAX_NATIVE_CRITERIA
        and all(isinstance(label, str) and 1 <= len(label) <= 72 for label in options)
        and all(isinstance(label, str) and 1 <= len(label) <= 200 for label in criteria)
        and len(set(options)) == len(options) and len(set(criteria)) == len(criteria)
        and isinstance(data.get("context", ""), str) and len(data.get("context", "")) <= 3000
    )


def _room_labels(room: Room | dict) -> tuple[Mapping, list[str], list[str]]:
    if not supports_native(room):
        raise ValueError("이 방의 평가는 웹에서 입력해 주세요.")
    data = _data(room)
    return data, data["options"], data["criteria"]


def submission_view(room: Room | dict, metadata: str) -> dict:
    data, options, criteria = _room_labels(room)
    blocks = [
        _section(data["question"]),
        _section("각 선택지가 기준을 얼마나 충족하는지 1점(매우 낮음)–5점(매우 높음)으로 평가해 주세요. "
                 "Slack 사용자 ID는 중복 제출 방지와 개인 기록을 위해 저장합니다. "
                 "개인 답변과 작성자는 팀원에게 공개하지 않으며, 제출 후 수정할 수 없습니다. "
                 "방 코드나 링크를 가진 사람은 웹에서 방과 집계 결과에 접근할 수 있습니다."),
    ]
    if data.get("context"):
        blocks.append(_section(data["context"]))
    for option_index, option in enumerate(options):
        for criterion_index, criterion in enumerate(criteria):
            blocks.append(_input(
                f"s_{option_index}_{criterion_index}", f"{option_index + 1}. {option} · {criterion}",
                _select([_option(f"{score}점", str(score)) for score in range(1, 6)]),
            ))
    blocks.append(_section("기준의 상대적인 중요도를 1–100으로 정해 주세요. 같은 값이면 같은 비중이며, 분석할 때 전체 합으로 나누어 반영합니다."))
    for index, criterion in enumerate(criteria):
        blocks.append(_input(
            f"w_{index}", f"{criterion} 중요도",
            _select([_option(str(weight), str(weight)) for weight in range(1, 101)], "10"),
        ))
    blocks.extend([
        _input("first_choice", "현재 가장 선호하는 선택지", _select([
            _option(f"{index + 1}. {option}", str(index)) for index, option in enumerate(options)
        ])),
        _input("reason", "이유 또는 우려 사항", {"type": "plain_text_input", "multiline": True, "max_length": 2000},
               optional=True, hint="이름 등 개인을 식별할 정보는 제외해 주세요. 내용은 웹 제출과 같은 의견 분석에 반영됩니다."),
    ])
    return _modal("내 의견 남기기", blocks, metadata, callback_id=EVALUATE_CALLBACK, submit=_text("의견 제출", 24))


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


def parse_evaluation(values: dict, room: Room | dict) -> SubmissionCreate:
    """Parse state.values into the same submission payload used by the web API."""
    _, options, criteria = _room_labels(room)
    errors: dict[str, str] = {}
    scores = {
        option: {criterion: _integer(values, f"s_{oi}_{ci}", 1, 5, errors) for ci, criterion in enumerate(criteria)}
        for oi, option in enumerate(options)
    }
    weights = {criterion: _integer(values, f"w_{index}", 1, 100, errors) for index, criterion in enumerate(criteria)}
    choice = _integer(values, "first_choice", 0, len(options) - 1, errors)
    raw_reason = _read(values, "reason")
    reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
    if raw_reason is not None and not isinstance(raw_reason, str):
        errors["reason"] = "이유는 텍스트로 입력해 주세요."
    elif len(reason) > 2000:
        errors["reason"] = "이유는 2,000자 이내로 입력해 주세요."
    if errors:
        raise ViewValidationError(errors)
    return SubmissionCreate(scores=scores, weights=weights, first_choice=options[choice], reason=reason)


def _expired(data: Mapping) -> bool:
    expires = data.get("expires_at")
    try:
        parsed = datetime.fromisoformat(expires.replace("Z", "+00:00")) if isinstance(expires, str) else expires
        return isinstance(parsed, datetime) and parsed.tzinfo is not None and parsed <= datetime.now(timezone.utc)
    except ValueError:
        return False


def _progress(data: Mapping) -> str:
    count = data.get("submission_count", len(data.get("submissions", [])))
    expected = data.get("expected_members", 0)
    status = "제출 완료" if _complete(data) else "의견 수집 중"
    if data.get("status") in {"expired", "closed"} or _expired(data):
        status = "제출·공개 방 이용 종료"
    return f"{status} · {count}/{expected}명 제출"


def _complete(data: Mapping) -> bool:
    count = data.get("submission_count", len(data.get("submissions", [])))
    expected = data.get("expected_members", 0)
    return bool(data.get("is_complete", expected > 0 and count >= expected))


def room_actions(code: str) -> list[dict]:
    """Action blocks for channel invitations and status modals (shared room code)."""
    if not isinstance(code, str) or re.fullmatch(r"[A-Za-z0-9]{6}", code) is None:
        raise ValueError("Shared room codes must contain six letters or digits")
    return [{"type": "actions", "elements": [
        _button("의견 남기기", "synq_join", code),
        _button("제출 현황", "synq_status", code),
        _button("분석 결과", "synq_results", code),
    ]}]


def status_view(room: Room | dict, metadata: str = "") -> dict:
    data = _data(room)
    blocks = [
        _section(f"{data['question']}\n방 코드: {data['code']}\n{_progress(data)}"),
        _section("개인 답변과 작성자는 팀원에게 공개하지 않습니다. 방 코드나 링크를 가진 사람은 웹에서 방과 집계 결과에 접근할 수 있습니다."),
    ]
    if "has_submitted" in data:
        blocks.append(_section("내 의견을 제출했습니다." if data["has_submitted"] else "이 Slack 계정으로 아직 의견을 제출하지 않았습니다."))
    if not _expired(data) and data.get("web_available", True) and data.get("status") not in {"expired", "closed"}:
        actions = room_actions(data["code"])
        if data.get("has_submitted") or _complete(data) or data.get("status") == "complete":
            actions[0]["elements"] = [button for button in actions[0]["elements"] if button["action_id"] != "synq_join"]
        blocks.extend(actions)
    return _modal("제출 현황", blocks, metadata)


def history_view(page: dict, metadata: str = "") -> dict:
    """Render only the caller's selected history; retention follows each shared room."""
    rooms = page.get("rooms", [])
    if len(rooms) > MAX_HISTORY_ROOMS:
        raise ValueError(f"History pages must contain at most {MAX_HISTORY_ROOMS} rooms")
    blocks = [_section("Slack 또는 연결된 Google 계정으로 만들거나 제출한 결정입니다. "
                       "공개 기간에는 방 코드로 웹에 접근하며, 이후에는 개인 기록 보관 기한까지 이 목록에서 확인할 수 있습니다.")]
    for index, room in enumerate(rooms):
        data = _data(room)
        own_state = " · 내 의견 제출됨" if data.get("has_submitted") else ""
        blocks.extend([
            _section(f"{data['question']}\n방 코드: {data['code']}\n{_progress(data)}{own_state}"),
            {"type": "actions", "block_id": f"h_{index}", "elements": [
                _button("결정 보기", "synq_history_room", data["code"]),
            ]},
        ])
    if not rooms:
        blocks.append(_section("아직 참여한 결정이 없습니다. /synq new로 만들거나 /synq join 방코드로 참여해 주세요."))
    if page.get("next_cursor"):
        blocks.append({"type": "actions", "elements": [_button("다음 페이지", "synq_history_more", page["next_cursor"])]})
    return _modal("내 결정 기록", blocks, metadata)


def _percentage(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return "—"
    return f"{value * 100:.1f}%"


def result_view(room: Room | dict, analysis: Any, metadata: str = "") -> dict:
    """Render an allowlist of aggregate fields, never raw answers or identities."""
    summary, data = _data(room), _data(analysis)
    blocks = [
        _section(f"{summary['question']}\n방 코드: {summary['code']} · {_progress(summary)}"),
        _section(f"현재 평가 1위: {data.get('current_winner') or '—'}\n가중치 변화에 가장 안정적인 선택: {data.get('robust_choice') or '—'}"),
    ]
    votes, stability = data.get("vote_share", {}), data.get("stability", {})
    options = summary.get("options") or list(dict.fromkeys([*votes, *stability]))
    for option in options[:10]:
        blocks.append(_section(f"{option}\n초기 1순위 비율: {_percentage(votes.get(option))} · 가중치 변화 시 1위 비율: {_percentage(stability.get(option))}"))
    blocks.append(_section("가중치 변화 시 1위 비율은 여러 가중치로 계산했을 때 해당 선택지가 1위였던 비율입니다. 실제 성공 확률을 의미하지 않습니다."))
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
    for item in (data.get("hidden_conflicts") or [])[:10]:
        blocks.append(_section(f"의견이 갈리는 부분\n{item}"))
    for index, item in enumerate((data.get("discussion_agenda") or [])[:20], 1):
        blocks.append(_section(f"토론할 질문 {index}\n{item}"))
    advocate = data.get("devils_advocate")
    if advocate:
        for item in (_data(advocate).get("challenges") or [])[:3]:
            blocks.append(_section(f"함께 점검할 반론\n{item}"))
    return _modal("팀 분석 결과", blocks, metadata)
