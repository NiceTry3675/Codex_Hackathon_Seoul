"""Offline checks of form round trips, limits, and anonymity boundaries."""

import json

import pytest

from backend.models import Room
from backend.slack_views import (
    ViewValidationError,
    create_room_view,
    history_view,
    parse_create,
    parse_submission,
    result_view,
    room_message,
    submission_view,
)


def _field(value, *, selected=False):
    return {"value": {"selected_option": {"value": str(value)}} if selected else {"value": value}}


def _create_state(**overrides):
    state = {
        "question": _field("  어떤 도구를 사용할까요?  "),
        "options": _field(" A \nB\n"),
        "criteria": _field("비용\n안정성"),
        "expected_members": _field(4, selected=True),
        "expires_in_hours": _field(72, selected=True),
    }
    state.update(overrides)
    return state


def _room(**overrides):
    data = {
        "code": "A7C2E9G4J6", "question": "어떤 도구를 사용할까요?",
        "options": ["A", "B"], "criteria": ["비용", "안정성"],
        "expected_members": 4,
    }
    data.update(overrides)
    return Room(**data)


def _summary(**overrides):
    summary = {
        **_room().model_dump(mode="json"),
        "submission_count": 4, "is_complete": True, "status": "complete",
    }
    summary.update(overrides)
    return summary


def _submission_state(room):
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
    assert len(view.get("private_metadata", "")) <= 3000
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
            if value.get("type") in {"section", "context"} and "text" in value:
                assert len(value["text"]["text"]) <= 3000
            assert value.get("type") != "mrkdwn"
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(view)


def test_create_form_parses_anonymous_model_and_fixed_ids():
    view = create_room_view("opaque-signed-metadata")
    _check_limits(view)
    assert view["callback_id"] == "consensus_create"
    assert view["private_metadata"] == "opaque-signed-metadata"
    payload = parse_create(_create_state())
    assert payload.question == "어떤 도구를 사용할까요?"
    assert payload.options == ["A", "B"]
    assert payload.criteria == ["비용", "안정성"]
    assert payload.expected_members == 4
    assert payload.expires_in_hours == 72
    assert payload.submission_mode == "anonymous"
    input_ids = {block["block_id"] for block in view["blocks"] if block["type"] == "input"}
    assert set(_create_state()) == input_ids


@pytest.mark.parametrize(("block_id", "state"), [
    ("question", _field(" ")),
    ("question", _field("a" * 501)),
    ("options", _field("A")),
    ("options", _field("A\n A")),
    ("options", _field("\n".join("ABCDEF"))),
    ("criteria", _field("a" * 81)),
    ("criteria", _field("")),
    ("expected_members", _field(21, selected=True)),
    ("expected_members", _field(0, selected=True)),
    ("expected_members", _field("1.0", selected=True)),
    ("expires_in_hours", _field(48, selected=True)),
])
def test_create_invalid_fields_return_inline_errors(block_id, state):
    with pytest.raises(ViewValidationError) as exc:
        parse_create(_create_state(**{block_id: state}))
    assert set(exc.value.errors) == {block_id}


def test_create_missing_state_reports_all_required_fields():
    with pytest.raises(ViewValidationError) as exc:
        parse_create({})
    assert set(exc.value.errors) == set(_create_state())


def test_submission_roundtrip_maps_indices_to_original_labels():
    room = _room(options=["<!channel>" + "a" * 80, "<&>" + "b" * 80], criteria=["안정성", "비용"])
    view = submission_view(room, "signed")
    _check_limits(view)
    assert view["callback_id"] == "consensus_submit"
    assert view["private_metadata"] == "signed"
    payload = parse_submission(_submission_state(room), room)
    assert payload.scores == {room.options[0]: {"안정성": 5, "비용": 5}, room.options[1]: {"안정성": 2, "비용": 2}}
    assert payload.weights == {"안정성": 100, "비용": 30}
    assert payload.first_choice == room.options[1]
    assert payload.reason == "근거를 확인해요."
    assert payload.participant_name is None
    input_ids = {block["block_id"] for block in view["blocks"] if block["type"] == "input"}
    assert input_ids == set(_submission_state(room))
    assert all("<!channel>" not in block_id for block_id in input_ids)


@pytest.mark.parametrize(("block_id", "state"), [
    ("s_0_0", _field(0, selected=True)),
    ("s_0_0", _field(6, selected=True)),
    ("w_0", _field(101, selected=True)),
    ("w_0", _field("-1", selected=True)),
    ("w_0", {"value": {"selected_option": None}}),
    ("first_choice", _field(2, selected=True)),
    ("first_choice", _field("B", selected=True)),
    ("reason", _field("x" * 2001)),
])
def test_submission_rejects_tampered_or_incomplete_state(block_id, state):
    room = _room()
    values = _submission_state(room)
    values[block_id] = state
    with pytest.raises(ViewValidationError) as exc:
        parse_submission(values, room)
    assert set(exc.value.errors) == {block_id}


def test_submission_accepts_optional_empty_reason():
    room = _room()
    values = _submission_state(room)
    values.pop("reason")
    assert parse_submission(values, room).reason == ""


def test_largest_submission_form_stays_within_slack_limits():
    room = _room(options=[f"{i}" + "옵" * 79 for i in range(5)], criteria=[f"{i}" + "기" * 79 for i in range(5)])
    view = submission_view(room.model_dump(), "opaque")
    _check_limits(view)
    assert len([block for block in view["blocks"] if block["type"] == "input"]) == 32
    assert len(parse_submission(_submission_state(room), room).scores) == 5
    with pytest.raises(ValueError):
        submission_view(_room(options=list("ABCDEF")), "")


def test_channel_message_never_renders_identity_or_individual_answers():
    secret = "PRIVATE_PERSON_IDENTIFIER"
    summary = _summary(question="<!channel> <https://bad.test|visit>", submissions=[{"reason": secret}], email=secret, participant_names=[secret])
    message = room_message(summary)
    encoded = json.dumps(message, ensure_ascii=False)
    assert secret not in encoded
    assert "<!channel>" not in message["text"]
    assert message["text"].startswith("SynQ 의견방")
    assert message["blocks"][0]["text"]["type"] == "plain_text"
    buttons = message["blocks"][-1]["elements"]
    assert {button["action_id"] for button in buttons} == {"consensus_join", "consensus_status", "consensus_results"}
    assert {button["value"] for button in buttons} == {summary["code"]}


def test_personal_history_has_pagination_and_keeps_identities_out():
    page = {"rooms": [_summary(question="Q" * 500, user_id="private-user", submissions=[{"reason": "private-reason"}]) for _ in range(30)], "next_cursor": "opaque-cursor"}
    view = history_view(page, "opaque-history")
    _check_limits(view)
    encoded = json.dumps(view)
    assert "private-user" not in encoded and "private-reason" not in encoded
    assert view["blocks"][-1]["elements"][0]["value"] == "opaque-cursor"
    assert view["blocks"][-1]["elements"][0]["action_id"] == "consensus_more"
    assert "submit" not in view
    assert view["private_metadata"] == "opaque-history"
    empty_history = json.dumps(history_view({"rooms": []}), ensure_ascii=False)
    assert "아직" in empty_history
    assert "/synq" in empty_history and "/consensus" not in empty_history
    with pytest.raises(ValueError):
        history_view({"rooms": [_summary()] * 31})


def test_results_show_only_aggregate_fields_and_limit_long_analysis():
    summary = _summary(question="<!here> 질문", user_id="private-user")
    analysis = {
        "current_winner": "A", "robust_choice": "B", "vote_share": {"A": 0.25, "B": 0.75},
        "stability": {"A": 0.322, "B": 0.678},
        "flip_points": [{"type": "weight", "criterion": "비용", "from": 0.5, "to": 0.6, "new_winner": "B"}, {"type": "member", "new_winner": "B", "member_id": "private-user"}],
        "discussion_agenda": ["<!channel> " + "긴" * 5000] * 30,
        "devils_advocate": {"target": "A", "challenges": ["어떤 근거인가요?", "무엇을 확인할까요?"]},
        "submissions": [{"reason": "private-reason", "user_id": "private-user"}],
    }
    view = result_view(summary, analysis)
    _check_limits(view)
    encoded = json.dumps(view, ensure_ascii=False)
    assert "25.0%" in encoded and "67.8%" in encoded
    assert "50.0% → 60.0%" in encoded
    assert "private-reason" not in encoded and "private-user" not in encoded
    assert "한 명의 의견을 제외" in encoded
    assert "submit" not in view


def test_result_without_optional_analysis_has_clear_fallback():
    view = result_view(_summary(), {"current_winner": "A", "robust_choice": "A"})
    _check_limits(view)
    assert "조건을 찾지 못했습니다" in json.dumps(view, ensure_ascii=False)


def test_opaque_metadata_is_not_silently_truncated():
    with pytest.raises(ValueError):
        create_room_view("a" * 3001)


@pytest.mark.parametrize("retention_days", [7, 90, 365])
def test_create_and_history_display_configured_retention(retention_days):
    for view in [create_room_view("signed", retention_days=retention_days), history_view({"rooms": []}, retention_days=retention_days)]:
        text = view["blocks"][0]["text"]["text"]
        assert f"{retention_days}일 동안" in text
        if retention_days != 90:
            assert "90일" not in text


@pytest.mark.parametrize(("status", "has_submitted", "can_join"), [
    ("collecting", False, True),
    ("collecting", True, False),
    ("complete", False, False),
    ("closed", False, False),
])
def test_history_allows_join_only_while_collecting_before_own_submission(status, has_submitted, can_join):
    room = _summary(status=status, has_submitted=has_submitted)
    view = history_view({"rooms": [room]})
    _check_limits(view)
    buttons = view["blocks"][2]["elements"]
    joins = [button for button in buttons if button["action_id"] == "consensus_join"]
    assert bool(joins) is can_join
    if can_join:
        assert joins[0]["value"] == room["code"]
