from backend.models import Room, Submission
from backend.storage import RoomStore


def test_memory_store_round_trips_rooms(monkeypatch):
    monkeypatch.delenv("CONSENSUS_TABLE_NAME", raising=False)
    memory = {}
    store = RoomStore(memory)
    room = Room(
        code="ABC123",
        question="질문",
        options=["A", "B"],
        criteria=["가치"],
        expected_members=2,
        submission_mode="named",
    )

    assert store.create(room) is True
    assert store.create(room) is False
    assert store.get("abc123") == room


def test_append_result_does_not_change_when_next_participant_submits(monkeypatch):
    monkeypatch.delenv("CONSENSUS_TABLE_NAME", raising=False)
    store = RoomStore({})
    store.create(Room(code="ABC123", question="질문", options=["A", "B"], criteria=["가치"], expected_members=2))
    submission = Submission(id="one", scores={"A": {"가치": 5}, "B": {"가치": 1}},
                            weights={"가치": 100}, first_choice="A", reason="")
    _, first = store.append_submission("ABC123", submission, "one")
    _, final = store.append_submission("ABC123", submission.model_copy(update={"id": "two"}), "two")
    assert len(first.submissions) == 1
    assert len(final.submissions) == 2
