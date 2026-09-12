from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock

import pytest
from botocore.exceptions import ClientError

from backend.models import DecisionRecord, ParsedOpinion, Room, RoomResponse, Submission
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


class VersionedTable:
    """Dynamo fake enforcing conditional writes, including actual write races."""

    def __init__(self):
        self.items = {}
        self.lock = Lock()
        self.barrier = None
        self.versioned_writes = 0

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead
        with self.lock:
            item = self.items.get(Key["code"])
            return {"Item": deepcopy(item)} if item else {}

    def put_item(self, *, Item, ConditionExpression=None, ExpressionAttributeNames=None,
                 ExpressionAttributeValues=None):
        wait = False
        if ConditionExpression == "#version = :expected_version":
            with self.lock:
                self.versioned_writes += 1
                wait = self.barrier is not None and self.versioned_writes <= 2
            if wait:
                self.barrier.wait(timeout=5)
        with self.lock:
            previous = self.items.get(Item["code"])
            conflict = (
                ConditionExpression == "attribute_not_exists(code)" and previous is not None
            ) or (
                ConditionExpression == "#version = :expected_version"
                and (previous is None or previous["version"] != ExpressionAttributeValues[":expected_version"])
            )
            if conflict:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
            self.items[Item["code"]] = deepcopy(Item)
        return {}


@pytest.fixture(params=["memory", "dynamo"])
def room_store(request, monkeypatch):
    monkeypatch.delenv("CONSENSUS_TABLE_NAME", raising=False)
    store = RoomStore({})
    if request.param == "dynamo":
        store._table_name = "rooms"
        store._table = VersionedTable()
    return store


def make_room(**overrides):
    return Room(**{
        "code": "ABC123", "question": "질문", "options": ["A", "B"],
        "criteria": ["가치"], "expected_members": 3, **overrides,
    })


def make_submission(**overrides):
    return Submission(**{
        "id": "one", "scores": {"A": {"가치": 5}, "B": {"가치": 1}},
        "weights": {"가치": 100}, "first_choice": "A", "reason": "좋아요", **overrides,
    })


def test_private_retention_does_not_extend_public_access_or_submission(room_store):
    now = datetime.now(timezone.utc)
    room = make_room(expires_at=now - timedelta(hours=1), retained_until=now + timedelta(days=90))
    room_store.create(room)

    assert room_store.get("abc123") is None
    assert room_store.get_retained("abc123") == room
    assert room_store.append_submission(room.code, make_submission(), "cookie")[0] == "not_found"
    assert room_store.retain_until(room.code, now + timedelta(days=365)) is None
    assert room_store.get_retained(room.code) == room


def test_retained_rooms_are_hidden_and_memory_evicted_after_retention(room_store):
    now = datetime.now(timezone.utc)
    room_store.create(make_room(expires_at=now - timedelta(days=2), retained_until=now - timedelta(days=1)))
    assert room_store.get_retained("ABC123") is None
    assert room_store.get("ABC123") is None
    if not room_store.persistent:
        assert "ABC123" not in room_store._memory


def test_retention_never_shortens_public_lifetime_or_reserves_submission_slots(room_store):
    room = make_room()
    room_store.create(room)
    initial = room.model_copy(deep=True)
    unchanged = room_store.retain_until(room.code, room.expires_at - timedelta(hours=1))
    assert unchanged == initial
    extended = room_store.retain_until(room.code, room.expires_at + timedelta(days=90))
    assert extended.expires_at == initial.expires_at
    assert extended.retained_until == initial.expires_at + timedelta(days=90)
    assert extended.version == initial.version + 1
    assert extended.submissions == []
    assert extended.used_anonymous_token_hashes == []
    assert room_store.get(room.code) is not None
    assert room_store.retain_until(room.code, initial.expires_at + timedelta(days=1)) == extended
    if room_store.persistent:
        assert room_store._table.items[room.code]["expires_at"] == int(extended.retained_until.timestamp())


def test_dynamo_ttl_uses_later_deadline_and_ignores_other_document_types(monkeypatch):
    monkeypatch.delenv("CONSENSUS_TABLE_NAME", raising=False)
    store = RoomStore({})
    store._table_name = "rooms"
    store._table = VersionedTable()
    room = make_room()
    room.retained_until = room.expires_at - timedelta(hours=1)
    store.create(room)
    assert store._table.items[room.code]["expires_at"] == int(room.expires_at.timestamp())
    store._table.items["SLACK#ROOM#T123#ABC123"] = {"room_json": "not a room"}
    store._table.items["OTHER1"] = {"document_json": "not a room"}
    assert store.get("SLACK#ROOM#T123#ABC123") is None
    assert store.get_retained("SLACK#ROOM#T123#ABC123") is None
    assert store.get("OTHER1") is None


def test_all_submission_identities_are_atomic_and_deduplicated(room_store):
    room_store.create(make_room())
    outcome, snapshot = room_store.append_submission(
        "ABC123", make_submission(), "cookie-one", ["slack-user", "cookie-one", "slack-user"],
    )
    assert outcome == "ok"
    assert snapshot.used_anonymous_token_hashes == ["cookie-one", "slack-user"]
    outcome, _ = room_store.append_submission(
        "ABC123", make_submission(id="two"), "cookie-two", ["slack-user", "google-user"],
    )
    assert outcome == "duplicate_token"
    assert room_store.get("ABC123").used_anonymous_token_hashes == ["cookie-one", "slack-user"]
    outcome, saved = room_store.append_submission(
        "ABC123", make_submission(id="three"), "cookie-two", ["other-slack-user", "google-user"],
    )
    assert outcome == "ok"
    assert len(saved.submissions) == 2
    assert len(snapshot.submissions) == 1


def test_concurrent_web_and_slack_identity_submissions_only_consume_one_slot(room_store):
    room_store.create(make_room())
    if room_store.persistent:
        room_store._table.barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(room_store.append_submission, "ABC123", make_submission(id="web"), "cookie", ["slack-user"])
        second = pool.submit(room_store.append_submission, "ABC123", make_submission(id="slack"), "slack-user")
        assert sorted([first.result()[0], second.result()[0]]) == ["duplicate_token", "ok"]
    saved = room_store.get("ABC123")
    assert len(saved.submissions) == 1
    assert saved.version == 1
    assert saved.used_anonymous_token_hashes.count("slack-user") == 1


def test_retention_cas_preserves_concurrent_submission(room_store):
    room_store.create(make_room())
    deadline = datetime.now(timezone.utc) + timedelta(days=90)
    if room_store.persistent:
        room_store._table.barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        append = pool.submit(room_store.append_submission, "ABC123", make_submission(), "cookie", ["slack-user"])
        retain = pool.submit(room_store.retain_until, "ABC123", deadline)
        assert append.result()[0] == "ok"
        assert retain.result().retained_until == deadline
    saved = room_store.get("ABC123")
    assert saved.retained_until == deadline
    assert len(saved.submissions) == 1
    assert saved.used_anonymous_token_hashes == ["cookie", "slack-user"]
    assert saved.version == 2


def test_opt_in_submission_retry_matches_original_payload_even_when_full(room_store):
    room_store.create(make_room(expected_members=1))
    submission = make_submission()
    assert room_store.append_submission("ABC123", submission, "slack-user", idempotent=True)[0] == "ok"
    reparsed = submission.model_copy(update={"parsed": ParsedOpinion(preferred_option="A", positive=["changed parse"])})
    assert room_store.append_submission("ABC123", reparsed, "slack-user", idempotent=True)[0] == "duplicate_submission"
    assert room_store.append_submission("ABC123", make_submission(reason="changed reason"), "slack-user", idempotent=True)[0] == "duplicate_token"
    assert room_store.append_submission("ABC123", make_submission(reason="changed reason"), "other-user", idempotent=True)[0] == "conflict"
    assert room_store.get("ABC123").submissions == [submission]


def test_stale_analysis_save_preserves_retention_and_committed_submission(room_store):
    room_store.create(make_room())
    analysis_snapshot = room_store.get("ABC123").model_copy(deep=True)
    _, submission_snapshot = room_store.append_submission("ABC123", make_submission(), "cookie", ["slack-user"])
    deadline = datetime.now(timezone.utc) + timedelta(days=90)
    room_store.retain_until("ABC123", deadline)
    analysis_snapshot.devils_advocate_generated = True
    room_store.save(analysis_snapshot)
    stored = room_store.get("ABC123")
    assert stored.retained_until == deadline
    assert stored.expires_at == analysis_snapshot.expires_at
    assert stored.submissions == submission_snapshot.submissions
    assert stored.used_anonymous_token_hashes == ["cookie", "slack-user"]
    assert stored.devils_advocate_generated
    assert stored.version == 3
    if room_store.persistent:
        assert room_store._table.items["ABC123"]["expires_at"] == int(deadline.timestamp())


def test_analysis_save_and_retention_concurrent_writes_preserve_both(room_store):
    room_store.create(make_room())
    snapshot = room_store.get("ABC123").model_copy(deep=True)
    snapshot.devils_advocate_generated = True
    deadline = datetime.now(timezone.utc) + timedelta(days=90)
    if room_store.persistent:
        room_store._table.barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        analysis = pool.submit(room_store.save, snapshot)
        retain = pool.submit(room_store.retain_until, "ABC123", deadline)
        analysis.result()
        assert retain.result().retained_until == deadline
    saved = room_store.get("ABC123")
    assert saved.retained_until == deadline
    assert saved.devils_advocate_generated
    assert saved.version == 2


def test_stale_analysis_save_does_not_erase_a_recorded_decision(room_store):
    room_store.create(make_room())
    stale = room_store.get("ABC123").model_copy(deep=True)
    current = room_store.get("ABC123").model_copy(deep=True)
    current.decision_record = DecisionRecord(
        initial_majority_choice="A", analysis_winner="A", robust_choice="A", final_choice="B",
        final_reason="합의한 이유", decided_at=datetime.now(timezone.utc), changed_from_initial=True,
    )
    room_store.save(current)
    stale.devils_advocate_generated = True
    room_store.save(stale)
    assert room_store.get("ABC123").decision_record == current.decision_record


def test_submission_retention_survives_deadline_before_history_indexing(room_store, monkeypatch):
    import backend.storage as storage_module

    now = datetime.now(timezone.utc)
    room_store.create(make_room(expires_at=now + timedelta(minutes=1)))
    retained_until = now + timedelta(days=90)
    outcome, snapshot = room_store.append_submission(
        "ABC123", make_submission(), "cookie", ["slack-user"], retained_until=retained_until,
    )
    assert outcome == "ok"
    assert snapshot.version == 1
    assert snapshot.retained_until == retained_until

    class AfterPublicDeadline(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(minutes=2)

    monkeypatch.setattr(storage_module, "datetime", AfterPublicDeadline)
    assert room_store.get("ABC123") is None
    retained = room_store.get_retained("ABC123")
    assert retained is not None
    assert retained.retained_until == retained_until
    assert len(retained.submissions) == 1
    if room_store.persistent:
        assert room_store._table.items["ABC123"]["expires_at"] == int(retained_until.timestamp())


def test_rejected_submission_does_not_extend_retention(room_store):
    room_store.create(make_room())
    room_store.append_submission("ABC123", make_submission(), "cookie", ["slack-user"])
    before = room_store.get("ABC123").model_copy(deep=True)
    outcome, _ = room_store.append_submission(
        "ABC123", make_submission(id="two"), "another-cookie", ["slack-user"],
        retained_until=datetime.now(timezone.utc) + timedelta(days=90),
    )
    assert outcome == "duplicate_token"
    assert room_store.get("ABC123") == before


def test_private_room_fields_do_not_enter_public_response():
    assert "retained_until" in Room.model_fields
    assert "creation_request_id" in Room.model_fields
    assert "retained_until" not in RoomResponse.model_fields
    assert "creation_request_id" not in RoomResponse.model_fields
