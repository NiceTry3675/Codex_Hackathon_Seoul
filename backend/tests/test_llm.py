import backend.llm as llm


def test_parse_opinion_returns_none_without_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = llm.parse_opinion("A가 좋아요", ["A", "B"], ["value"])

    assert result is None


def test_chat_json_returns_none_for_an_unexpected_network_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fail_request(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(llm, "urlopen", fail_request)

    result = llm._chat_json("system", {"input": "value"})

    assert result is None


def test_parse_opinion_accepts_only_room_labels(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_: {
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
        lambda *_: {
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
    monkeypatch.setattr(llm, "_chat_json", lambda *_: {"challenges": ["질문 하나"]})

    result = llm.generate_devils_advocate("A", ["value"], [])

    assert result is None


def test_devils_advocate_keeps_the_statistics_winner_as_target(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_chat_json",
        lambda *_: {"challenges": ["실패 조건은 무엇인가요?", "대안은 있나요?"]},
    )

    result = llm.generate_devils_advocate("A", ["value"], ["speed"])

    assert result is not None
    assert result.target == "A"
    assert len(result.challenges) == 2
