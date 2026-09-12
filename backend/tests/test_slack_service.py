"""Slack privacy, concurrent participation and durable retry contracts."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from threading import RLock
import time

from botocore.exceptions import ClientError
import pytest

from backend.models import RoomCreate, SubmissionCreate
import backend.slack_service as service_module
from backend.slack_service import SlackDomainError, SlackService
from backend.slack_store import SlackStore


class FakeTable:
    """A conditional-write table shared by independent store instances."""

    def __init__(self):
        self.items = {}
        self.lock = RLock()
        self.reads = []

    def get_item(self, **kwargs):
        with self.lock:
            self.reads.append(kwargs)
            item = self.items.get(kwargs["Key"]["code"])
            return {"Item": copy.deepcopy(item)} if item else {}

    def put_item(self, **kwargs):
        with self.lock:
            item = kwargs["Item"]
            current = self.items.get(item["code"])
            values = kwargs["ExpressionAttributeValues"]
            live = current and current["expires_at"] > values[":now"]
            if "attribute_not_exists" in kwargs["ConditionExpression"]:
                matches = not live
            else:
                matches = live and current["version"] == values[":version"]
            if not matches:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
            self.items[item["code"]] = copy.deepcopy(item)


@pytest.fixture(params=["memory", "dynamo"])
def store(request):
    return SlackStore("") if request.param == "memory" else SlackStore(table=FakeTable())


@pytest.fixture
def service(store):
    return SlackService(store, "test-secret-not-used-in-production")


def room_payload(members=2, **overrides):
    return RoomCreate(**{
        "question": "어떤 선택을 할까요?", "options": ["A", "B"],
        "criteria": ["가치", "실행"], "expected_members": members,
        "expires_in_hours": 1, **overrides,
    })


def submission_payload(**overrides):
    return SubmissionCreate(**{
        "scores": {"A": {"가치": 5, "실행": 2}, "B": {"가치": 3, "실행": 5}},
        "weights": {"가치": 60, "실행": 40}, "first_choice": "A",
        "reason": "private opinion text", **overrides,
    })


def create(service, members=2, request_id="view-create"):
    return service.create_room("T1", "Ucreator", "C1", room_payload(members), request_id)


def test_store_cas_and_copy_isolation(store):
    ttl = int(time.time()) + 100
    assert store.compare_and_swap("SLACK#TEST", None, {"members": []}, ttl)
    assert not store.compare_and_swap("SLACK#TEST", None, {"members": ["imposter"]}, ttl)
    doc = store.get("SLACK#TEST")
    doc.value["members"].append("U1")
    assert store.get("SLACK#TEST").value["members"] == []
    assert store.compare_and_swap("SLACK#TEST", doc.version, doc.value, ttl)
    assert not store.compare_and_swap("SLACK#TEST", doc.version, {"members": []}, ttl)
    assert store.get("SLACK#TEST").value["members"] == ["U1"]
    with pytest.raises(ValueError):
        store.compare_and_swap("PUBLIC", None, {}, ttl)


def test_store_replaces_expired_dynamo_item_and_reads_consistently(monkeypatch):
    table = FakeTable()
    store = SlackStore(table=table)
    now = int(time.time())
    assert store.compare_and_swap("SLACK#TEST", None, {"old": True}, now + 5)
    monkeypatch.setattr(time, "time", lambda: now + 6)
    assert store.get("SLACK#TEST") is None
    assert store.compare_and_swap("SLACK#TEST", None, {"new": True}, now + 60)
    assert store.get("SLACK#TEST").value == {"new": True}
    assert all(read["ConsistentRead"] for read in table.reads)


def test_store_compresses_large_json_and_restores_across_instances():
    table = FakeTable()
    store = SlackStore(table=table)
    data = {"long_unicode": "😀" * 100_000}
    assert store.compare_and_swap("SLACK#LARGE", None, data, int(time.time()) + 100)
    assert table.items["SLACK#LARGE"]["slack_encoding"] == "zlib-base64"
    assert len(table.items["SLACK#LARGE"]["slack_json"].encode()) < 390_000
    assert SlackStore(table=table).get("SLACK#LARGE").value == data


def test_create_idempotency_and_request_payload_conflict(service):
    first = create(service)
    assert create(service) == first
    assert len(service.list_rooms("T1", "Ucreator")["rooms"]) == 1
    with pytest.raises(SlackDomainError, match="different input"):
        service.create_room("T1", "Ucreator", "C1", room_payload(question="different"), "view-create")


def test_membership_and_identity_privacy(service):
    room = create(service)
    code = room["code"]
    for team, user in [("T1", "Uoutsider"), ("T2", "Ucreator")]:
        with pytest.raises(SlackDomainError) as error:
            service.get_room(team, user, code)
        assert error.value.status == 404
        assert service.list_rooms(team, user)["rooms"] == []
        with pytest.raises(SlackDomainError):
            service.analysis(team, user, code)
        with pytest.raises(SlackDomainError):
            service.submit(team, user, code, submission_payload(), "view-submit")
    with pytest.raises(SlackDomainError) as error:
        service.join_room("T1", "Umember", code, "Cother")
    assert error.value.status == 404
    joined = service.join_room("T1", "Umember", code.lower(), "C1")
    assert service.join_room("T1", "Umember", code, "Dprivate") == joined
    assert service.list_rooms("T1", "Umember")["rooms"] == [joined]
    service.submit("T1", "Ucreator", code, submission_payload(), "view-1")
    service.submit("T1", "Umember", code, submission_payload(), "view-2")
    history = service.get_history("T1", "Umember", code)
    assert set(history["room"]) == {
        "code", "question", "options", "criteria", "expected_members", "submission_count",
        "is_complete", "created_at", "closes_at", "retained_until", "status",
        "has_submitted",
    }
    public = json.dumps(history)
    assert all(private not in public for private in ["Ucreator", "Umember", "private opinion text", "payload_hash", "request_id"])
    assert history["room"]["has_submitted"] is True


def test_submit_retries_cannot_overwrite_votes(service):
    code = create(service, 1)["code"]
    result = service.submit("T1", "Ucreator", code, submission_payload(), "same-view")
    assert service.submit("T1", "Ucreator", code, submission_payload(), "same-view") == result
    for request_id, payload in [("new-view", submission_payload()), ("same-view", submission_payload(first_choice="B"))]:
        with pytest.raises(SlackDomainError, match="already submitted"):
            service.submit("T1", "Ucreator", code, payload, request_id)
    assert len(service.get_room("T1", "Ucreator", code)["room"]["submissions"]) == 1


def test_concurrent_creates_and_submits_commit_once(service):
    with ThreadPoolExecutor(max_workers=8) as pool:
        rooms = list(pool.map(lambda _: create(service, 1), range(16)))
    assert len({room["code"] for room in rooms}) == 1
    code = rooms[0]["code"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit("T1", "Ucreator", code, submission_payload(), "view"), range(16)))
    assert all(result["submission_count"] == 1 for result in results)


def test_concurrent_joins_reserve_capacity_atomically(service):
    code = create(service, 3)["code"]

    def join(number):
        try:
            service.join_room("T1", f"U{number}", code, "C1")
            return f"U{number}"
        except SlackDomainError as exc:
            assert exc.status == 409
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        joined = [user for user in pool.map(join, range(20)) if user]
    assert len(joined) == 2
    participants = ["Ucreator", *joined]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda user: service.submit("T1", user, code, submission_payload(), f"view-{user}"), participants))
    internal = service.get_room("T1", "Ucreator", code)
    assert len(internal["room"]["submissions"]) == 3
    assert len(internal["members"]) == 3


def test_closed_rooms_retain_history_and_completed_analysis(service, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    incomplete = create(service)["code"]
    complete = create(service, 1, "complete-room")["code"]
    service.submit("T1", "Ucreator", complete, submission_payload(), "complete-view")
    monkeypatch.setattr(time, "time", lambda: now + 3601)
    with pytest.raises(SlackDomainError, match="closed"):
        service.submit("T1", "Ucreator", incomplete, submission_payload(), "late")
    with pytest.raises(SlackDomainError, match="closed"):
        service.join_room("T1", "Unew", incomplete, "C1")
    assert service.get_history("T1", "Ucreator", incomplete)["room"]["status"] == "closed"
    assert service.get_history("T1", "Ucreator", incomplete)["analysis"] is None
    assert service.get_history("T1", "Ucreator", complete)["analysis"]["current_winner"] == "A"
    monkeypatch.setattr(time, "time", lambda: now + 90 * 86400 + 1)
    with pytest.raises(SlackDomainError) as error:
        service.get_history("T1", "Ucreator", complete)
    assert error.value.status == 404
    assert service.list_rooms("T1", "Ucreator")["rooms"] == []


def test_analysis_is_unavailable_until_complete_then_cached(service, monkeypatch):
    code = create(service, 1)["code"]
    with pytest.raises(SlackDomainError, match="all expected"):
        service.analysis("T1", "Ucreator", code)
    service.submit("T1", "Ucreator", code, submission_payload(), "view")
    result = service.analysis("T1", "Ucreator", code)
    monkeypatch.setattr(service_module, "analyze_room", lambda *_: pytest.fail("immutable snapshot should be cached"))
    assert service.analysis("T1", "Ucreator", code) == result
    result["option_scores"].clear()
    assert service.analysis("T1", "Ucreator", code)["option_scores"]


def test_history_cursor_is_bounded_deterministic_and_user_bound(service):
    service.MAX_ROOMS_PER_USER = 3
    for number in range(6):
        create(service, 1, f"view-{number}")
    all_rooms = service.list_rooms("T1", "Ucreator")["rooms"]
    assert len(all_rooms) == 3
    first = service.list_rooms("T1", "Ucreator", limit=2)
    second = service.list_rooms("T1", "Ucreator", limit=2, cursor=first["next_cursor"])
    assert first["rooms"] + second["rooms"] == all_rooms
    assert second["next_cursor"] is None
    for team, user, cursor in [("T1", "Uother", first["next_cursor"]), ("T2", "Ucreator", first["next_cursor"]), ("T1", "Ucreator", first["next_cursor"] + "x")]:
        with pytest.raises(SlackDomainError, match="cursor"):
            service.list_rooms(team, user, cursor=cursor)


def test_index_is_repaired_by_create_retry_after_failed_index_write(service, monkeypatch):
    original = service.store.compare_and_swap

    def fail_index(key, *args):
        if key.startswith("SLACK#INDEX"):
            raise RuntimeError("connection lost")
        return original(key, *args)

    monkeypatch.setattr(service.store, "compare_and_swap", fail_index)
    with pytest.raises(RuntimeError):
        create(service)
    monkeypatch.setattr(service.store, "compare_and_swap", original)
    room = create(service)
    assert service.list_rooms("T1", "Ucreator")["rooms"] == [room]


def test_slack_rooms_persist_across_service_instances_and_are_namespaced():
    table = FakeTable()
    first = SlackService(SlackStore(table=table), "same-secret")
    code = create(first, 1)["code"]
    first.submit("T1", "Ucreator", code, submission_payload(), "view")
    expected = first.get_history("T1", "Ucreator", code)
    second = SlackService(SlackStore(table=table), "same-secret")
    assert second.get_history("T1", "Ucreator", code) == expected
    assert second.list_rooms("T1", "Ucreator")["rooms"] == [expected["room"]]
    assert code not in table.items
    assert all(key.startswith("SLACK#") for key in table.items)


def test_account_links_are_signed_hashed_at_rest_one_time_and_bijective(service):
    token = service.create_link("T1", "Ucreator")
    with pytest.raises(SlackDomainError, match="invalid account link"):
        service.consume_link(token + "x", "google-one")
    assert service.consume_link(token, "google-one") == {"team_id": "T1", "user_id": "Ucreator"}
    assert service.consume_link(token, "google-one") == {"team_id": "T1", "user_id": "Ucreator"}
    with pytest.raises(SlackDomainError, match="already used"):
        service.consume_link(token, "google-two")
    with pytest.raises(SlackDomainError, match="already linked"):
        service.consume_link(service.create_link("T1", "Uother"), "google-one")
    with pytest.raises(SlackDomainError, match="already linked"):
        service.consume_link(service.create_link("T1", "Ucreator"), "google-two")
    assert service.linked_identity("T1", "google-one") == "Ucreator"
    assert service.linked_identity("T1", "google-two") is None
    assert service.linked_identity("T2", "google-one") is None
    stored = str(service.store._table.items if service.store.persistent else service.store._memory)
    assert token not in stored
    assert "google-one" not in stored


def test_concurrent_link_consumers_cannot_claim_same_token(service):
    token = service.create_link("T1", "Ucreator")

    def claim(number):
        try:
            service.consume_link(token, f"google-{number}")
            return f"google-{number}"
        except SlackDomainError as exc:
            assert exc.status == 409
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [account for account in pool.map(claim, range(16)) if account]
    assert len(winners) == 1
    assert service.linked_identity("T1", winners[0]) == "Ucreator"


def test_link_reservation_failure_does_not_grant_access_and_can_retry(service, monkeypatch):
    token = service.create_link("T1", "Ucreator")
    original = service.store.compare_and_swap

    def fail_registry(key, *args):
        if key.startswith("SLACK#ACCOUNTS"):
            raise RuntimeError("provider unavailable")
        return original(key, *args)

    monkeypatch.setattr(service.store, "compare_and_swap", fail_registry)
    with pytest.raises(RuntimeError):
        service.consume_link(token, "google-one")
    assert service.linked_identity("T1", "google-one") is None
    monkeypatch.setattr(service.store, "compare_and_swap", original)
    with pytest.raises(SlackDomainError, match="already used"):
        service.consume_link(token, "google-two")
    service.consume_link(token, "google-one")
    assert service.linked_identity("T1", "google-one") == "Ucreator"


def test_link_expires_after_ten_minutes(service, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    token = service.create_link("T1", "Ucreator")
    monkeypatch.setattr(time, "time", lambda: now + 601)
    with pytest.raises(SlackDomainError) as error:
        service.consume_link(token, "google-one")
    assert error.value.status == 410


@pytest.mark.parametrize("overrides", [
    {"submission_mode": "named"}, {"options": ["A", "B", "C", "D", "E", "F"]},
    {"criteria": ["x" * 81]}, {"expected_members": 21}, {"context": "x" * 5001},
])
def test_rejects_unsupported_slack_room_shapes(service, overrides):
    with pytest.raises(SlackDomainError) as error:
        service.create_room("T1", "Ucreator", "C1", room_payload(**overrides), "view")
    assert error.value.status == 422


@pytest.mark.parametrize("overrides", [
    {"participant_name": "must remain anonymous"}, {"weights": {"unknown": 100}},
    {"scores": {"A": {"가치": 3}, "B": {"가치": 4}}}, {"first_choice": "C"},
])
def test_submission_validation_keeps_room_unmodified(service, overrides):
    code = create(service, 1)["code"]
    with pytest.raises(SlackDomainError) as error:
        service.submit("T1", "Ucreator", code, submission_payload(**overrides), "view")
    assert error.value.status == 422
    assert service.get_room("T1", "Ucreator", code)["room"]["submissions"] == []


def test_twenty_full_unicode_submissions_and_analysis_fit_storage(service):
    options = [str(number) + "😀" * 79 for number in range(5)]
    criteria = [str(number) + "😃" * 79 for number in range(5)]
    payload = room_payload(20, question="😀" * 500, options=options, criteria=criteria, context="😃" * 5000)
    room = service.create_room("T1", "U0", "C1", payload, "full-size-room")
    submission = SubmissionCreate(
        scores={option: {criterion: 5 for criterion in criteria} for option in options},
        weights={criterion: 20 for criterion in criteria}, first_choice=options[0], reason="😄" * 2000,
    )
    for number in range(20):
        service.join_room("T1", f"U{number}", room["code"], "C1")
        service.submit("T1", f"U{number}", room["code"], submission, f"view-{number}")
    result = service.analysis("T1", "U0", room["code"])
    assert result["current_winner"] == options[0]
    assert service.get_history("T1", "U19", room["code"])["analysis"] == result
