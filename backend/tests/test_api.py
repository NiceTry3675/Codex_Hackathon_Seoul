from fastapi.testclient import TestClient
import pytest

import backend.main as main
from backend.main import app, rooms
from backend.models import DevilsAdvocate


@pytest.fixture(autouse=True)
def clear_rooms():
    rooms.clear()
    yield
    rooms.clear()


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
        "expected_members",
        "submission_count",
        "is_complete",
    }


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


def test_devils_advocate_is_cached_after_the_first_analysis(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())
    calls: list[str] = []

    def fake_devils_advocate(target, _low_agreement, _concerns):
        calls.append(target)
        return DevilsAdvocate(target=target, challenges=["무엇이 실패할 수 있나요?", "대안은 있나요?"])

    monkeypatch.setattr(main, "generate_devils_advocate", fake_devils_advocate)

    first = client.get(f"/api/rooms/{room['code']}/analysis")
    second = client.get(f"/api/rooms/{room['code']}/analysis")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["A"]
    assert second.json()["devils_advocate"] == first.json()["devils_advocate"]


def test_devils_advocate_failure_does_not_block_analysis(client: TestClient, monkeypatch):
    room = client.post("/api/rooms", json=room_payload()).json()
    client.post(f"/api/rooms/{room['code']}/submit", json=submission_payload())

    def fail_devils_advocate(*_args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(main, "generate_devils_advocate", fail_devils_advocate)

    response = client.get(f"/api/rooms/{room['code']}/analysis")

    assert response.status_code == 200
    assert "devils_advocate" not in response.json()
