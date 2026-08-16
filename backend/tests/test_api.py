from fastapi.testclient import TestClient
import pytest

from backend.main import app, rooms


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
