from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import backend.main as main
from backend.main import app, room_analysis_locks, rooms
from backend.models import (
    AuthUser,
    CriterionSuggestion,
    DefenseResolution,
    DevilsAdvocate,
    SubmissionCreate,
)


@pytest.fixture(autouse=True)
def clear_rooms():
    rooms.clear()
    room_analysis_locks.clear()
    yield
    rooms.clear()
    room_analysis_locks.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def room_payload() -> dict:
    return {
        "question": "어떤 안을 선택할까요?",
        "options": ["A", "B"],
        "criteria": ["가치", "실행"],
        "expected_members": 1,
    }


def submission_payload() -> dict:
    return {
        "scores": {
            "A": {"가치": 5, "실행": 2},
            "B": {"가치": 3, "실행": 5},
        },
        "weights": {"가치": 6, "실행": 4},
        "first_choice": "A",
        "reason": "",
    }


def test_room_submission_and_analysis_flow(client: TestClient):
    created = client.post("/api/rooms", json=room_payload())
    assert created.status_code == 201
    room = created.json()
    assert room["submission_count"] == 0
    assert room["is_complete"] is False

    code = room["code"]
    submitted = client.post(f"/api/rooms/{code}/submit", json=submission_payload())
    assert submitted.status_code == 201
    assert submitted.json()["is_complete"] is True

    analysis = client.get(f"/api/rooms/{code}/analysis")
    assert analysis.status_code == 200
    result = analysis.json()
    assert result["current_winner"] == "A"
    assert set(result["mean_scores"]) == {"A", "B"}
    assert sum(result["stability"].values()) == pytest.approx(1.0)


def test_decision_record_compares_initial_analysis_and_final_choice(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    code = room["code"]

    assert client.get(f"/api/rooms/{code}/decision-record").status_code == 404
    assert client.post(
        f"/api/rooms/{code}/decision-record",
        json={"final_choice": "B", "final_reason": "분석 전"},
    ).status_code == 409

    client.post(f"/api/rooms/{code}/submit", json=submission_payload()).raise_for_status()
    created = client.post(
        f"/api/rooms/{code}/decision-record",
        json={"final_choice": "B", "final_reason": " 실행 가능성을 우선하기로 했습니다. "},
    )

    assert created.status_code == 201
    record = created.json()
    assert record["initial_majority_choice"] == "A"
    assert record["analysis_winner"] == "A"
    assert record["robust_choice"] in {"A", "B"}
    assert record["final_choice"] == "B"
    assert record["final_reason"] == "실행 가능성을 우선하기로 했습니다."
    assert record["changed_from_initial"] is True
    assert record["decided_at"].endswith("Z")
    assert client.get(f"/api/rooms/{code}/decision-record").json() == record
    assert client.post(
        f"/api/rooms/{code}/decision-record",
        json={"final_choice": "A", "final_reason": "다시 변경"},
    ).status_code == 409


def test_decision_record_rejects_unknown_choice_without_llm(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload()).raise_for_status()
    monkeypatch.setattr(main, "generate_devils_advocate", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))

    response = client.post(
        f"/api/rooms/{room['code']}/decision-record",
        json={"final_choice": "C", "final_reason": "알 수 없는 선택"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "final_choice must be one of the room options"


def test_analysis_requires_a_submission(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()

    response = client.get(f"/api/rooms/{room['code']}/analysis")

    assert response.status_code == 409
    assert response.json()["detail"] == "all expected members must submit before analysis"


def test_analysis_requires_all_expected_members(client: TestClient):
    payload = room_payload()
    payload["expected_members"] = 2
    room = client.post("/api/rooms", json=payload).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    response = client.get(f"/api/rooms/{room['code']}/analysis")

    assert response.status_code == 409
    assert response.json()["detail"] == "all expected members must submit before analysis"


def test_unknown_room_returns_not_found(client: TestClient):
    response = client.get("/api/rooms/ABC123")

    assert response.status_code == 404
    assert response.json()["detail"] == "room not found"


def test_room_codes_are_case_insensitive(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()

    response = client.get(f"/api/rooms/{room['code'].lower()}")

    assert response.status_code == 200
    assert response.json()["code"] == room["code"]


def test_room_status_never_exposes_individual_submissions(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    response = client.get(f"/api/rooms/{room['code']}")

    assert response.status_code == 200
    assert set(response.json()) == {
        "code",
        "question",
        "options",
        "criteria",
        "context",
        "expected_members",
            "submission_mode",
            "created_at",
            "expires_at",
        "participant_names",
        "submission_count",
        "is_complete",
    }


def test_named_room_requires_and_exposes_participant_names(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        main,
        "user_from_request",
        lambda _request: AuthUser(
            google_sub="room-creator",
            email="creator@example.com",
            name="방장",
        ),
    )
    payload = room_payload()
    payload["submission_mode"] = "named"
    room = client.post("/api/rooms", json=payload).json()

    missing_name = client.post(
        f"/api/rooms/{room['code']}/submit",
        json=submission_payload(),
    )
    named_payload = submission_payload()
    named_payload["participant_name"] = " 홍길동 "
    submitted = client.post(
        f"/api/rooms/{room['code']}/submit",
        json=named_payload,
    )
    status_response = client.get(f"/api/rooms/{room['code']}").json()

    assert missing_name.status_code == 422
    assert submitted.status_code == 201
    assert status_response["submission_mode"] == "named"
    assert status_response["participant_names"] == ["홍길동"]


def test_anonymous_room_rejects_and_never_exposes_names(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    payload = submission_payload()
    payload["participant_name"] = "노출되면 안 됨"

    response = client.post(f"/api/rooms/{room['code']}/submit", json=payload)

    assert response.status_code == 422
    assert client.get(f"/api/rooms/{room['code']}").json()["participant_names"] == []


def test_submission_keys_must_match_room(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    payload = submission_payload()
    payload["scores"].pop("B")

    response = client.post(f"/api/rooms/{room['code']}/submit", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == ["B"]


def test_score_range_is_validated(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    payload = submission_payload()
    payload["scores"]["A"]["가치"] = 6

    response = client.post(f"/api/rooms/{room['code']}/submit", json=payload)

    assert response.status_code == 422


def test_first_choice_must_be_a_room_option(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    payload = submission_payload()
    payload["first_choice"] = "C"

    response = client.post(f"/api/rooms/{room['code']}/submit", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "first_choice must be one of the room options"


def test_submission_is_rejected_after_the_room_is_full(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    first = client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    response = client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    assert first.status_code == 201
    assert response.status_code == 409
    assert response.json()["detail"] == "room is full"


def test_concurrent_final_submissions_cannot_overfill_a_room(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    both_parsing = Barrier(2)

    def synchronized_parse(*_args):
        both_parsing.wait(timeout=1)
        return None

    monkeypatch.setattr(main, "parse_opinion", synchronized_parse)

    def submit_once():
        with TestClient(app) as participant:
            participant.get(f"/api/rooms/{room['code']}").raise_for_status()
            return participant.post(
                f"/api/rooms/{room['code']}/submit",
                json=submission_payload(),
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: submit_once(), range(2)))

    assert statuses == [201, 409]
    assert len(rooms[room["code"]].submissions) == 1


def test_anonymous_token_blocks_repeat_submission_from_same_browser(client: TestClient):
    payload = room_payload()
    payload["expected_members"] = 2
    room = client.post("/api/rooms", json=payload).json()
    raw_token = client.cookies.get(f"synq_participation_{room['code']}")
    assert raw_token

    first = client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    repeated = client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    with TestClient(app) as another_browser:
        another_browser.get(f"/api/rooms/{room['code']}").raise_for_status()
        other = another_browser.post(
            f"/api/rooms/{room['code']}/submit",
            json=submission_payload(),
        )

    assert first.status_code == 201
    assert repeated.status_code == 409
    assert repeated.json()["detail"] == "this browser already submitted to this room"
    assert other.status_code == 201
    assert len(rooms[room["code"]].used_anonymous_token_hashes) == 2
    assert all(len(value) == 64 for value in rooms[room["code"]].used_anonymous_token_hashes)
    assert raw_token not in rooms[room["code"]].model_dump_json()


def test_same_anonymous_token_concurrently_succeeds_only_once(client: TestClient, monkeypatch):
    payload = room_payload()
    payload["expected_members"] = 2
    room = client.post("/api/rooms", json=payload).json()
    both_parsing = Barrier(2)

    def synchronized_parse(*_args):
        both_parsing.wait(timeout=1)
        return None

    monkeypatch.setattr(main, "parse_opinion", synchronized_parse)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(
                    f"/api/rooms/{room['code']}/submit",
                    json=submission_payload(),
                ),
                range(2),
            )
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(rooms[room["code"]].submissions) == 1


def test_expired_room_blocks_read_submit_and_analysis_and_is_cleaned(client: TestClient):
    created = client.post("/api/rooms", json={**room_payload(), "expires_in_hours": 6})
    assert created.status_code == 201
    room = created.json()
    created_at = datetime.fromisoformat(room["created_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(room["expires_at"].replace("Z", "+00:00"))
    assert expires_at - created_at == timedelta(hours=6)

    rooms[room["code"]].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert client.get(f"/api/rooms/{room['code']}").status_code == 404
    assert client.post(
        f"/api/rooms/{room['code']}/submit", json=submission_payload()
    ).status_code == 404
    assert client.get(f"/api/rooms/{room['code']}/analysis").status_code == 404
    assert room["code"] not in rooms


def test_devils_advocate_is_cached_after_the_first_analysis(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    calls: list[str] = []

    def fake_devils_advocate(target, *_evidence):
        calls.append(target)
        return DevilsAdvocate(target=target, challenges=["무엇이 실패할 수 있나요?", "대안은 있나요?"])

    monkeypatch.setattr(main, "generate_devils_advocate", fake_devils_advocate)

    first = client.get(f"/api/rooms/{room['code']}/analysis")
    second = client.get(f"/api/rooms/{room['code']}/analysis")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["A"]
    assert second.json()["devils_advocate"] == first.json()["devils_advocate"]
    assert rooms[room["code"]].devils_advocate_source == "live"


def test_devils_advocate_failure_uses_a_cached_fallback(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    def fail_devils_advocate(*_args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(main, "generate_devils_advocate", fail_devils_advocate)

    first = client.get(f"/api/rooms/{room['code']}/analysis")
    second = client.get(f"/api/rooms/{room['code']}/analysis")

    assert first.status_code == 200
    assert first.json()["devils_advocate"] == second.json()["devils_advocate"]
    assert first.json()["devils_advocate"]["target"] == "A"
    assert len(first.json()["devils_advocate"]["challenges"]) == 2
    assert rooms[room["code"]].devils_advocate_source == "fallback"


def test_concurrent_analysis_calls_generate_devils_advocate_once(
    client: TestClient,
    monkeypatch,
):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    provider_started = Event()
    provider_may_finish = Event()
    calls_lock = Lock()
    calls = 0

    def slow_devils_advocate(target, *_evidence):
        nonlocal calls
        with calls_lock:
            calls += 1
        provider_started.set()
        assert provider_may_finish.wait(timeout=1)
        return DevilsAdvocate(target=target, challenges=["실패 조건은?", "전환 기준은?"])

    monkeypatch.setattr(main, "generate_devils_advocate", slow_devils_advocate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(main.get_analysis, room["code"])
        assert provider_started.wait(timeout=1)
        second_future = executor.submit(main.get_analysis, room["code"])
        provider_may_finish.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert calls == 1
    assert first.devils_advocate == second.devils_advocate


def test_analysis_starts_a_frozen_append_only_debate(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    monkeypatch.setattr(
        main,
        "generate_devils_advocate",
        lambda target, *_: DevilsAdvocate(
            target=target,
            challenges=["실패 조건은 무엇인가요?", "전환 기준은 무엇인가요?"],
        ),
    )

    client.get(f"/api/rooms/{room['code']}/analysis").raise_for_status()
    debate = client.get(f"/api/rooms/{room['code']}/debate")

    assert debate.status_code == 200
    body = debate.json()
    assert body["evidence_snapshot"]["id"].startswith("snapshot-")
    assert body["evidence_snapshot"]["target"] == "A"
    assert [message["challenge_id"] for message in body["messages"]] == ["c1", "c2"]
    assert [message["sequence"] for message in body["messages"]] == [1, 2]
    assert all(message["role"] == "challenger" for message in body["messages"])
    assert "reason" not in body["evidence_snapshot"]


def test_defender_round_appends_resolutions_and_projects_open_agenda(
    client: TestClient,
    monkeypatch,
):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    monkeypatch.setattr(
        main,
        "generate_devils_advocate",
        lambda target, *_: DevilsAdvocate(
            target=target,
            challenges=["실패 조건은 무엇인가요?", "전환 기준은 무엇인가요?"],
        ),
    )
    monkeypatch.setattr(
        main,
        "evaluate_defenses",
        lambda *_: [
            DefenseResolution(
                challenge_id="c1",
                resolution="resolved",
                reason="검증 근거와 대응책이 실패 조건을 직접 해소합니다.",
            ),
            DefenseResolution(
                challenge_id="c2",
                resolution="reframed",
                reason="전환 조건을 더 작고 검증 가능한 질문으로 좁혀야 합니다.",
                reframed_question="가장 먼저 확인할 전환 신호는 무엇인가요?",
            ),
        ],
    )
    client.get(f"/api/rooms/{room['code']}/analysis").raise_for_status()

    defended = client.post(
        f"/api/rooms/{room['code']}/debate/defend",
        json={
            "answers": [
                {
                    "challenge_id": "c1",
                    "status": "mitigated",
                    "evidence": "핵심 경로 검증을 마쳤습니다.",
                    "unknowns": "",
                    "mitigation": "실패 시 대체 경로를 사용합니다.",
                },
                {
                    "challenge_id": "c2",
                    "status": "open",
                    "evidence": "",
                    "unknowns": "전환 신호가 아직 정의되지 않았습니다.",
                    "mitigation": "관측 가능한 신호를 정합니다.",
                },
            ]
        },
    )

    assert defended.status_code == 200
    body = defended.json()
    assert body["completed"] is True
    assert body["resolution_source"] == "live"
    assert [message["sequence"] for message in body["messages"]] == list(range(1, 7))
    assert [message["role"] for message in body["messages"]] == [
        "challenger",
        "challenger",
        "defender",
        "defender",
        "challenger",
        "challenger",
    ]
    analysis = client.get(f"/api/rooms/{room['code']}/analysis").json()
    assert "가장 먼저 확인할 전환 신호는 무엇인가요?" in analysis["discussion_agenda"]


def test_defender_round_rejects_incomplete_ids(client: TestClient):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    client.get(f"/api/rooms/{room['code']}/analysis").raise_for_status()

    response = client.post(
        f"/api/rooms/{room['code']}/debate/defend",
        json={
            "answers": [
                {"challenge_id": "c1", "status": "open"},
                {"challenge_id": "unknown", "status": "open"},
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "answers must match every challenge_id"


def test_defender_provider_failure_closes_with_open_fallback(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    client.get(f"/api/rooms/{room['code']}/analysis").raise_for_status()
    monkeypatch.setattr(main, "evaluate_defenses", lambda *_: None)

    response = client.post(
        f"/api/rooms/{room['code']}/debate/defend",
        json={
            "answers": [
                {"challenge_id": "c1", "status": "open"},
                {"challenge_id": "c2", "status": "open"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["resolution_source"] == "fallback"
    verdicts = response.json()["messages"][-2:]
    assert all(message["resolution"] == "open" for message in verdicts)


def test_room_context_is_optional_and_round_trips(client: TestClient):
    created = client.post("/api/rooms", json=room_payload())
    assert created.status_code == 201
    assert created.json()["context"] == ""

    payload = {**room_payload(), "context": "  지난 회의에서 예산이 줄었다는 이야기가 나왔습니다.  "}
    created = client.post("/api/rooms", json=payload)
    assert created.status_code == 201
    code = created.json()["code"]
    assert created.json()["context"] == payload["context"].strip()
    assert client.get(f"/api/rooms/{code}").json()["context"] == payload["context"].strip()


def test_room_context_length_is_bounded(client: TestClient):
    payload = {**room_payload(), "context": "가" * 50_001}

    response = client.post("/api/rooms", json=payload)

    assert response.status_code == 422


def test_criteria_suggestions_use_the_live_provider(client: TestClient, monkeypatch):
    captured = {}

    def fake_suggest(question, options, existing, context):
        captured.update(question=question, options=options, existing=existing, context=context)
        return [
            CriterionSuggestion(name="리스크", why="실패했을 때 얼마나 크게 드러나는지 봅니다."),
            CriterionSuggestion(name="확장성", why="이후에 더 키울 수 있는지 봅니다."),
        ]

    monkeypatch.setattr(main, "suggest_criteria", fake_suggest)

    response = client.post(
        "/api/criteria/suggestions",
        json={
            "question": " 어떤 안을 선택할까요? ",
            "options": ["A", "B"],
            "existing_criteria": ["창의성"],
            "context": "회의록 전문",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "live"
    assert [item["name"] for item in body["criteria"]] == ["리스크", "확장성"]
    assert captured == {
        "question": "어떤 안을 선택할까요?",
        "options": ["A", "B"],
        "existing": ["창의성"],
        "context": "회의록 전문",
    }


@pytest.mark.parametrize(
    "provider",
    [lambda *_: None, lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))],
)
def test_criteria_suggestions_fall_back_without_a_provider(client: TestClient, monkeypatch, provider):
    monkeypatch.setattr(main, "suggest_criteria", provider)

    response = client.post(
        "/api/criteria/suggestions",
        json={"question": "어떤 안을 선택할까요?", "existing_criteria": ["리스크"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    names = [item["name"] for item in body["criteria"]]
    assert names and "리스크" not in names


def test_criteria_suggestions_validate_labels(client: TestClient):
    response = client.post(
        "/api/criteria/suggestions",
        json={"question": "어떤 안을 선택할까요?", "existing_criteria": ["가치", "가치"]},
    )

    assert response.status_code == 422
