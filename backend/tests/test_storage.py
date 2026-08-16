from backend.models import Room
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
