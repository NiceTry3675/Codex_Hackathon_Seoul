"""Offline form validation, shared-room compatibility, and disclosure boundaries."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import AnalysisResponse, Room, Submission
from backend.slack_eval_views import (
    ViewValidationError,
    history_view,
    parse_evaluation,
    result_view,
    room_actions,
    status_view,
    submission_view,
    supports_native,
)


def _room(**overrides):
    data = {
        "code": "ABC123", "question": "어떤 도구를 사용할까요?", "options": ["A", "B"],
        "criteria": ["비용", "안정성"], "expected_members": 4,
    }
    data.update(overrides)
    return Room(**data)


def _summary(**overrides):
    data = {**_room().model_dump(mode="json"), "submission_count": 4, "is_complete": True}
    data.update(overrides)
    return data


def _field(value, *, selected=False):
    return {"value": {"selected_option": {"value": str(value)}} if selected else {"value": value}}


def _state(room):
    state = {
        f"s_{oi}_{ci}": _field(5 if oi == 0 else 2, selected=True)
        for oi in range(len(room.options)) for ci in range(len(room.criteria))
    }
    state.update({f"w_{ci}": _field(100 if ci == 0 else 30, selected=True) for ci in range(len(room.criteria))})
    state.update({"first_choice": _field(1, selected=True), "reason": _field(" 근거를 확인해요. ")})
    return state


def _check_limits(view):
    assert len(view["blocks"]) <= 100
    assert len(view["title"]["text"]) <= 24
    assert len(view["private_metadata"]) <= 3000
    block_ids = [block["block_id"] for block in view["blocks"] if "block_id" in block]
    assert len(set(block_ids)) == len(block_ids)

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "static_select":
                assert len(value["options"]) <= 100
                assert all(len(option["text"]["text"]) <= 75 for option in value["options"])
                assert len({option["value"] for option in value["options"]}) == len(value["options"])
                if "initial_option" in value:
                    assert value["initial_option"] in value["options"]
            if value.get("type") == "button":
                assert len(value["text"]["text"]) <= 75
                assert 1 <= len(value["value"]) <= 2000
            if value.get("type") == "section":
                assert len(value["text"]["text"]) <= 3000
            assert value.get("type") != "mrkdwn"
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(view)


def test_evaluation_preserves_original_score_keys_and_plain_text_labels():
    room = _room(options=["<!channel> <https://bad.test|A>", "B<&>"], criteria=["안정성", "비용"])
    view = submission_view(room, "opaque-signed-metadata")
    _check_limits(view)
    assert view["callback_id"] == "synq_evaluate"
    assert view["private_metadata"] == "opaque-signed-metadata"
    payload = parse_evaluation(_state(room), room)
    assert payload.scores == {room.options[0]: {"안정성": 5, "비용": 5}, room.options[1]: {"안정성": 2, "비용": 2}}
    assert payload.weights == {"안정성": 100, "비용": 30}
    assert payload.first_choice == room.options[1]
    assert payload.reason == "근거를 확인해요."
    assert payload.participant_name is None
    input_ids = {block["block_id"] for block in view["blocks"] if block["type"] == "input"}
    assert input_ids == set(_state(room))
    assert all("<!channel>" not in block_id for block_id in input_ids)
    text = json.dumps(view, ensure_ascii=False)
    assert "Slack 사용자 ID" in text and "방 코드나 링크" in text


@pytest.mark.parametrize("overrides", [
    {"options": list("ABCDEF")},
    {"criteria": list("ABCDEF")},
    {"options": ["a" * 73, "B"]},
    {"criteria": ["a" * 201]},
    {"submission_mode": "named"},
    {"options": ["A", "A"]},
    {"criteria": [""]},
    {"context": "배" * 3001},
])
def test_unsupported_shared_rooms_choose_web_fallback_without_truncation(overrides):
    room = _room(**overrides)
    assert not supports_native(room)
    assert not supports_native(room.model_dump())
    with pytest.raises(ValueError, match="웹"):
        submission_view(room, "")
    with pytest.raises(ValueError, match="웹"):
        parse_evaluation({}, room)


def test_maximum_native_form_preserves_full_labels_and_supports_100_members():
    room = _room(
        options=[f"{index}" + "옵" * 71 for index in range(5)],
        criteria=[f"{index}" + "기" * 199 for index in range(5)], expected_members=100,
    )
    assert supports_native(room)
    view = submission_view(room.model_dump(), "signed")
    _check_limits(view)
    assert len([block for block in view["blocks"] if block["type"] == "input"]) == 32
    payload = parse_evaluation(_state(room), room)
    assert set(payload.scores) == set(room.options)
    assert set(payload.weights) == set(room.criteria)
    first_choice = next(block for block in view["blocks"] if block.get("block_id") == "first_choice")
    assert first_choice["element"]["options"][0]["text"]["text"] == "1. " + room.options[0]


def test_evaluation_includes_full_room_context():
    context = "결정 배경: " + "중요한 조건 " * 100
    view = submission_view(_room(context=context), "")
    assert any(block.get("text", {}).get("text") == context for block in view["blocks"])
    _check_limits(view)


@pytest.mark.parametrize(("block_id", "value"), [
    ("s_0_0", _field(0, selected=True)),
    ("s_0_0", _field(6, selected=True)),
    ("s_0_0", _field("１", selected=True)),
    ("s_0_0", {"value": {"selected_option": {"value": 3}}}),
    ("w_0", _field(101, selected=True)),
    ("w_0", _field("-1", selected=True)),
    ("w_0", {"value": {"selected_option": None}}),
    ("w_0", _field("1" * 10000, selected=True)),
    ("first_choice", _field(2, selected=True)),
    ("first_choice", _field("B", selected=True)),
    ("reason", _field("x" * 2001)),
    ("reason", _field({"text": "forged"})),
])
def test_invalid_evaluation_state_returns_inline_errors(block_id, value):
    room = _room()
    values = _state(room)
    values[block_id] = value
    with pytest.raises(ViewValidationError) as exc:
        parse_evaluation(values, room)
    assert set(exc.value.errors) == {block_id}


@pytest.mark.parametrize("values", [{}, None, [], {"s_0_0": []}])
def test_missing_or_malformed_state_reports_required_fields(values):
    room = _room()
    with pytest.raises(ViewValidationError) as exc:
        parse_evaluation(values, room)
    assert set(exc.value.errors) == set(_state(room)) - {"reason"}


def test_optional_reason_and_unknown_identity_fields_are_not_stored():
    room = _room()
    values = _state(room)
    values.pop("reason")
    values["participant_name"] = _field("injected name")
    values["slack_user_id"] = _field("UINJECTED")
    payload = parse_evaluation(values, room)
    assert payload.reason == ""
    assert payload.participant_name is None
    assert "UINJECTED" not in payload.model_dump_json()


def test_room_action_buttons_use_shared_room_code():
    blocks = room_actions("ABC123")
    assert {button["action_id"] for button in blocks[0]["elements"]} == {"synq_join", "synq_status", "synq_results"}
    assert {button["value"] for button in blocks[0]["elements"]} == {"ABC123"}
    with pytest.raises(ValueError):
        room_actions("A7C2E9G4J6")


def test_status_shows_counts_for_room_model_without_raw_answers():
    room = _room(submissions=[Submission(id="private-id", **parse_evaluation(_state(_room()), _room()).model_dump())])
    view = status_view(room, "signed")
    _check_limits(view)
    encoded = json.dumps(view, ensure_ascii=False)
    assert "1/4명 제출" in encoded
    assert "private-id" not in encoded and "근거를 확인해요" not in encoded
    assert view["private_metadata"] == "signed"


@pytest.mark.parametrize("overrides", [
    {"is_complete": True}, {"has_submitted": True}, {"status": "closed"},
    {"expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
])
def test_status_does_not_offer_new_submission_after_completion_or_expiry(overrides):
    view = status_view(_summary(**{"is_complete": False, **overrides}))
    actions = [button["action_id"] for block in view["blocks"] if block["type"] == "actions" for button in block["elements"]]
    assert "synq_join" not in actions


def test_completed_room_model_does_not_offer_new_submission():
    payload = parse_evaluation(_state(_room()), _room())
    room = _room(expected_members=1, submissions=[Submission(id="completed", **payload.model_dump())])
    view = status_view(room)
    encoded = json.dumps(view, ensure_ascii=False)
    assert "제출 완료 · 1/1명 제출" in encoded
    assert "synq_join" not in encoded


def test_personal_history_paginates_without_exposing_identity_or_old_retention_promise():
    page = {
        "rooms": [_summary(question="Q" * 500, user_id="private-user", submissions=[{"reason": "private-reason"}]) for _ in range(30)],
        "next_cursor": "opaque-cursor",
    }
    view = history_view(page, "opaque-history")
    _check_limits(view)
    encoded = json.dumps(view, ensure_ascii=False)
    assert "private-user" not in encoded and "private-reason" not in encoded
    assert "90일" not in encoded
    assert view["blocks"][-1]["elements"][0]["value"] == "opaque-cursor"
    assert view["blocks"][-1]["elements"][0]["action_id"] == "synq_history_more"
    assert view["blocks"][2]["elements"][0]["action_id"] == "synq_history_room"
    assert view["blocks"][2]["elements"][0]["value"] == "ABC123"
    assert view["private_metadata"] == "opaque-history"
    assert "submit" not in view
    assert "아직" in json.dumps(history_view({"rooms": []}), ensure_ascii=False)
    with pytest.raises(ValueError):
        history_view({"rooms": [_summary()] * 31})


def test_results_render_aggregate_fields_plainly_without_identity_or_raw_submission():
    analysis = {
        "current_winner": "A", "robust_choice": "B", "vote_share": {"A": 0.25, "B": 0.75},
        "stability": {"A": 0.322, "B": 0.678},
        "flip_points": [{"type": "weight", "criterion": "비용", "from": 0.5, "to": 0.6, "new_winner": "B"},
                        {"type": "member", "new_winner": "B", "member_id": "private-user"}],
        "discussion_agenda": ["<!channel> " + "긴" * 5000] * 30,
        "hidden_conflicts": ["상충하는 평가"],
        "devils_advocate": {"target": "A", "challenges": ["어떤 근거인가요?", "무엇을 확인할까요?"]},
        "submissions": [{"reason": "private-reason", "user_id": "private-user"}],
    }
    view = result_view(_summary(question="<!here> 질문", participant_names=["private-user"]), analysis, "signed-result")
    _check_limits(view)
    encoded = json.dumps(view, ensure_ascii=False)
    assert "25.0%" in encoded and "67.8%" in encoded and "50.0% → 60.0%" in encoded
    assert "한 명의 의견을 제외" in encoded
    assert "상충하는 평가" in encoded
    assert "private-reason" not in encoded and "private-user" not in encoded
    assert "submit" not in view
    assert view["private_metadata"] == "signed-result"


def test_result_accepts_models_and_nonfinite_values_do_not_display_as_probabilities():
    view = result_view(_room(), AnalysisResponse(current_winner="A", robust_choice="B", stability={"A": float("nan"), "B": float("inf")}))
    _check_limits(view)
    text = json.dumps(view, ensure_ascii=False)
    assert "NaN" not in text and "Infinity" not in text
    assert "조건을 찾지 못했습니다" in text


@pytest.mark.parametrize("builder", [
    lambda metadata: submission_view(_room(), metadata),
    lambda metadata: status_view(_room(), metadata),
    lambda metadata: history_view({"rooms": []}, metadata),
    lambda metadata: result_view(_room(), {}, metadata),
])
def test_metadata_is_never_silently_truncated(builder):
    with pytest.raises(ValueError):
        builder("a" * 3001)
