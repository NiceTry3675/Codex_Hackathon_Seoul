import json

import backend.llm as llm
from backend.models import ChallengerQuestion, DefenderAnswer, EvidenceSnapshot


def test_parse_opinion_returns_none_without_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = llm.parse_opinion("A가 좋아요", ["A", "B"], ["value"])

    assert result is None


def test_chat_json_returns_none_for_an_unexpected_network_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fail_request(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(llm, "urlopen", fail_request)

    result = llm._chat_json(
        "system",
        {"input": "value"},
        schema_name="test",
        schema={"type": "object"},
    )

    assert result is None


def test_chat_json_uses_strict_schema_and_an_output_limit(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"ok": true}'}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)
    result = llm._chat_json(
        "system",
        {"input": "value"},
        schema_name="test_schema",
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["strict"] is True
    assert captured["body"]["reasoning_effort"] == "medium"
    assert captured["body"]["verbosity"] == "low"
    assert captured["body"]["max_completion_tokens"] == 500
    assert captured["timeout"] == 60.0


def test_parse_opinion_accepts_only_room_labels(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "preferred_option": "A",
            "positive": ["value"],
            "concerns": ["speed"],
        },
    )

    result = llm.parse_opinion("A가 좋아요", ["A", "B"], ["value"])

    assert result is None


def test_parse_opinion_returns_valid_categorical_data(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "preferred_option": "A",
            "positive": ["value"],
            "concerns": ["speed"],
        },
    )

    result = llm.parse_opinion("A가 좋아요", ["A", "B"], ["value", "speed"])

    assert result is not None
    assert result.preferred_option == "A"
    assert result.positive == ["value"]
    assert result.concerns == ["speed"]


def test_devils_advocate_requires_two_or_three_questions(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {"challenges": ["질문 하나"]},
    )

    result = llm.generate_devils_advocate("A", ["value"], [])

    assert result is None


def test_devils_advocate_keeps_the_statistics_winner_as_target(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {"challenges": ["실패 조건은 무엇인가요?", "대안은 있나요?"]},
    )

    result = llm.generate_devils_advocate("A", ["value"], ["speed"])

    assert result is not None
    assert result.target == "A"
    assert len(result.challenges) == 2


def test_fallback_devils_advocate_is_deterministic_and_uses_evidence():
    first = llm.fallback_devils_advocate("A", ["A / speed"], ["speed"])
    second = llm.fallback_devils_advocate("A", ["A / speed"], ["speed"])

    assert first == second
    assert first.target == "A"
    assert len(first.challenges) == 2
    assert "speed" in first.challenges[0]


def test_devils_advocate_rejects_duplicate_or_numeric_questions(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "challenges": ["실패 조건은 무엇인가요?", "실패 조건은 무엇인가요?"],
        },
    )
    assert llm.generate_devils_advocate("A", [], []) is None

    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "challenges": ["일주일 안에 실패하면 어떻게 하나요?", "대안은 무엇인가요?"],
        },
    )
    # Korean number words are allowed; invented digit patterns are not.
    assert llm.generate_devils_advocate("A", [], []) is not None

    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "challenges": ["7일 안에 실패하면 어떻게 하나요?", "대안은 무엇인가요?"],
        },
    )
    assert llm.generate_devils_advocate("A", [], []) is None


def test_evaluate_defenses_validates_ids_language_and_resolution_shape(monkeypatch):
    snapshot = EvidenceSnapshot(id="snapshot-test", target="A")
    questions = [
        ChallengerQuestion(
            sequence=1,
            challenge_id="c1",
            evidence_snapshot_id=snapshot.id,
            evidence_keys=["target"],
            question="실패 조건은 무엇인가요?",
        ),
        ChallengerQuestion(
            sequence=2,
            challenge_id="c2",
            evidence_snapshot_id=snapshot.id,
            evidence_keys=["target"],
            question="대안은 무엇인가요?",
        ),
    ]
    answers = [
        DefenderAnswer(challenge_id="c1", status="mitigated", evidence="검증했습니다."),
        DefenderAnswer(challenge_id="c2", status="open", unknowns="아직 모릅니다."),
    ]
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "resolutions": [
                {
                    "challenge_id": "c2",
                    "resolution": "reframed",
                    "reason": "더 작은 질문으로 좁혀야 합니다.",
                    "reframed_question": "가장 먼저 확인할 신호는 무엇인가요?",
                },
                {
                    "challenge_id": "c1",
                    "resolution": "resolved",
                    "reason": "제시한 근거가 실패 조건을 직접 해소합니다.",
                    "reframed_question": None,
                },
            ]
        },
    )

    result = llm.evaluate_defenses(snapshot, questions, answers)

    assert result is not None
    assert [item.challenge_id for item in result] == ["c1", "c2"]
    assert result[1].resolution == "reframed"


def test_evaluate_defenses_rejects_invented_numbers(monkeypatch):
    snapshot = EvidenceSnapshot(id="snapshot-test", target="A")
    questions = [
        ChallengerQuestion(
            sequence=index,
            challenge_id=f"c{index}",
            evidence_snapshot_id=snapshot.id,
            evidence_keys=["target"],
            question="실패 조건은 무엇인가요?",
        )
        for index in (1, 2)
    ]
    answers = [
        DefenderAnswer(challenge_id=f"c{index}", status="open")
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "resolutions": [
                {
                    "challenge_id": f"c{index}",
                    "resolution": "open",
                    "reason": "검증 확률이 50퍼센트라서 열려 있습니다.",
                    "reframed_question": None,
                }
                for index in (1, 2)
            ]
        },
    )

    assert llm.evaluate_defenses(snapshot, questions, answers) is None


def test_suggest_criteria_returns_none_without_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = llm.suggest_criteria("어떤 안을 고를까요?", ["A", "B"], ["창의성"], "")

    assert result is None


def test_suggest_criteria_drops_duplicates_and_existing_names(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "criteria": [
                {"name": "창의성", "why": "이미 있는 기준입니다."},
                {"name": "실행 가능성", "why": "주어진 시간 안에 해낼 수 있는지 봅니다."},
                {"name": "실행-가능성", "why": "같은 기준을 표기만 바꾼 것입니다."},
                {"name": "리스크", "why": "실패했을 때 얼마나 크게 드러나는지 봅니다."},
            ]
        },
    )

    result = llm.suggest_criteria("어떤 안을 고를까요?", ["A", "B"], ["창의성"], "")

    assert result is not None
    assert [item.name for item in result] == ["실행 가능성", "리스크"]


def test_suggest_criteria_rejects_numeric_or_non_korean_reasons(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "criteria": [
                {"name": "비용", "why": "예산의 30%를 넘기면 안 됩니다."},
                {"name": "Cost", "why": "purely english reason"},
                {"name": "기대 효과", "why": "목표에 얼마나 기여하는지 봅니다."},
            ]
        },
    )

    result = llm.suggest_criteria("어떤 안을 고를까요?", [], [], "")

    assert result is None


def test_suggest_criteria_passes_context_and_a_larger_output_limit(monkeypatch):
    captured = {}

    def fake_chat_json(system_prompt, payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {
            "criteria": [
                {"name": "실행 가능성", "why": "주어진 시간 안에 해낼 수 있는지 봅니다."},
                {"name": "리스크", "why": "실패했을 때 얼마나 크게 드러나는지 봅니다."},
                {"name": "확장성", "why": "이후에 더 키울 수 있는지 봅니다."},
            ]
        }

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)

    result = llm.suggest_criteria("어떤 안을 고를까요?", ["A"], ["창의성"], "회의록 전문")

    assert result is not None and len(result) == 3
    assert captured["payload"]["context"] == "회의록 전문"
    assert captured["payload"]["existing_criteria"] == ["창의성"]
    assert captured["kwargs"]["max_completion_tokens"] == 900


def test_fallback_criteria_skip_existing_names():
    result = llm.fallback_criteria_suggestions(["리스크", "실행 가능성"])

    names = [item.name for item in result]
    assert "리스크" not in names
    assert "실행 가능성" not in names
    assert len(names) == 3
    assert all(item.why for item in result)


def test_suggest_options_drops_existing_and_duplicate_names(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_, **__: {
            "options": [
                {"name": "직접 개발", "why": "이미 적은 후보입니다."},
                {"name": "외부 도구 도입", "why": "기존 제품을 활용하는 방법을 비교합니다."},
                {"name": "외부-도구 도입", "why": "같은 접근을 다르게 쓴 표현입니다."},
                {"name": "작게 시험 운영", "why": "작은 범위에서 먼저 가설을 확인합니다."},
            ]
        },
    )

    result = llm.suggest_options("어떤 방식으로 만들까요?", ["직접 개발"], "회의록")

    assert result is not None
    assert [item.name for item in result] == ["외부 도구 도입", "작게 시험 운영"]


def test_fallback_option_suggestions_skip_existing_names():
    result = llm.fallback_option_suggestions(["현재 방식 유지"])

    assert result
    assert "현재 방식 유지" not in [item.name for item in result]


def test_answer_decision_assistant_passes_room_state_and_history(monkeypatch):
    captured = {}

    def fake_chat_json(system_prompt, payload, **kwargs):
        captured["payload"] = payload
        return {"message": "선택지는 후보이고 평가 기준은 비교하는 잣대예요."}

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    messages = [llm.AssistantMessage(role="user", content="차이가 뭐야?")]

    result = llm.answer_decision_assistant("무엇을 만들까요?", ["A", "B"], ["가치"], "맥락", messages)

    assert result == "선택지는 후보이고 평가 기준은 비교하는 잣대예요."
    assert captured["payload"]["conversation"] == [{"role": "user", "content": "차이가 뭐야?"}]


def test_fallback_decision_assistant_guides_incomplete_setup():
    assert "결정 질문" in llm.fallback_decision_assistant("", [], [])
    assert "선택지" in llm.fallback_decision_assistant("무엇을 할까요?", ["A"], [])
    assert "평가 기준" in llm.fallback_decision_assistant("무엇을 할까요?", ["A", "B"], [])
