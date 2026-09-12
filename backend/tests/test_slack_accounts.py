"""Shared-room history authorization and account-link concurrency contracts."""

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timedelta, timezone
import json
from threading import RLock
import time

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.auth import SESSION_COOKIE_NAME, create_session_token
from backend.models import AuthUser, DecisionRecord, DevilsAdvocate, ParsedOpinion, Room, SlackOrigin, Submission
import backend.slack_accounts as accounts_module
from backend.slack_accounts import SlackAccounts, SlackDomainError, build_account_router
from backend.slack_store import SlackStore
from backend.storage import RoomStore


class FakeTable:
    """Independent SlackStore instances share conditional writes, like DynamoDB."""

    def __init__(self):
        self.items = {}
        self.lock = RLock()

    def get_item(self, **kwargs):
        assert kwargs["ConsistentRead"] is True
        with self.lock:
            item = self.items.get(kwargs["Key"]["code"])
            return {"Item": copy.deepcopy(item)} if item else {}

    def put_item(self, **kwargs):
        with self.lock:
            item = kwargs["Item"]
            current = self.items.get(item["code"])
            values = kwargs["ExpressionAttributeValues"]
            live = current and current["expires_at"] > values[":now"]
            matches = not live if "attribute_not_exists" in kwargs["ConditionExpression"] else live and current["version"] == values[":version"]
            if not matches:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
            self.items[item["code"]] = copy.deepcopy(item)


@pytest.fixture(params=["memory", "dynamo"])
def accounts(request, monkeypatch):
    monkeypatch.delenv("CONSENSUS_TABLE_NAME", raising=False)
    store = SlackStore("") if request.param == "memory" else SlackStore(table=FakeTable())
    return SlackAccounts(store, RoomStore({}), "test-secret-not-used-in-production")


def add_room(accounts, code="ABC123", **overrides):
    room = Room(**{
        "code": code, "question": "어떤 선택을 할까요?", "options": ["A", "B"], "criteria": ["가치"],
        "expected_members": 1, "slack_origin": SlackOrigin(team_id="T1", channel_id="C1"),
        "retained_until": datetime.now(timezone.utc) + timedelta(days=90), **overrides,
    })
    assert accounts.room_store.create(room)
    return room


def completed_room(accounts, **overrides):
    return add_room(accounts, submissions=[Submission(
        id="private-submission-id", participant_name="Private Name", scores={"A": {"가치": 5}, "B": {"가치": 2}},
        weights={"가치": 100}, first_choice="A", reason="private raw reason",
        parsed=ParsedOpinion(preferred_option="A", positive=["실행 가능"], concerns=["운영 비용"]),
    )], **overrides)


def test_index_does_not_reserve_or_mutate_shared_room(accounts):
    room = add_room(accounts)
    original = room.model_dump_json()
    accounts.record_room("T1", "Ucreator", room)
    accounts.record_room("T1", "Ucreator", room)
    assert accounts.room_store.get(room.code).model_dump_json() == original
    assert accounts.list_rooms("T1", "Ucreator")["rooms"][0]["submission_count"] == 0
    assert len(accounts.list_rooms("T1", "Ucreator")["rooms"]) == 1
    assert accounts.list_rooms("T1", "Uother")["rooms"] == []
    stored = accounts.store._table.items if accounts.store.persistent else accounts.store._memory
    assert not any(key.startswith("SLACK#ROOM#") for key in stored)


@pytest.mark.parametrize("team,user,code", [("T1", "Uother", "ABC123"), ("T2", "Ucreator", "ABC123"), ("T1", "Ucreator", "SLACK#INDEX#T1#Ucreator")])
def test_history_requires_own_index(accounts, team, user, code):
    room = add_room(accounts)
    accounts.record_room("T1", "Ucreator", room)
    with pytest.raises(SlackDomainError) as error:
        accounts.get_history(team, user, code)
    assert error.value.status == 404


def test_history_rejects_recycled_room_code(accounts):
    room = add_room(accounts)
    accounts.record_room("T1", "Ucreator", room)
    replacement = room.model_copy(update={"question": "A different private decision", "created_at": room.created_at + timedelta(seconds=1)})
    accounts.room_store.save(replacement)
    with pytest.raises(SlackDomainError) as error:
        accounts.get_history("T1", "Ucreator", room.code)
    assert error.value.status == 404
    assert accounts.list_rooms("T1", "Ucreator")["rooms"] == []


def test_history_survives_submission_deadline_but_not_retention(accounts):
    now = datetime.now(timezone.utc)
    room = completed_room(accounts, expires_at=now - timedelta(hours=1), retained_until=now + timedelta(days=3))
    accounts.record_room("T1", "Ucreator", room)
    assert accounts.room_store.get(room.code) is None
    history = accounts.get_history("T1", "Ucreator", room.code)
    assert history["room"]["web_available"] is False
    assert history["analysis"]["current_winner"] == "A"
    room.retained_until = now - timedelta(seconds=1)
    accounts.room_store.save(room)
    with pytest.raises(SlackDomainError) as error:
        accounts.get_history("T1", "Ucreator", room.code)
    assert error.value.status == 404


def test_history_is_aggregate_only_and_includes_saved_decision(accounts):
    now = datetime.now(timezone.utc)
    room = completed_room(accounts, devils_advocate=DevilsAdvocate(target="A", challenges=["비용은?", "일정은?"]),
        decision_record=DecisionRecord(initial_majority_choice="A", analysis_winner="A", robust_choice="A", final_choice="B", final_reason="합의한 최종 이유", decided_at=now, changed_from_initial=True))
    accounts.record_room("T1", "Ucreator", room)
    history = accounts.get_history("T1", "Ucreator", room.code.lower())
    rendered = json.dumps(history, ensure_ascii=False)
    for private in ("private-submission-id", "Private Name", "private raw reason", "Ucreator", "T1", "submissions", "submitted_users"):
        assert private not in rendered
    assert history["analysis"]["devils_advocate"]["challenges"] == ["비용은?", "일정은?"]
    assert history["decision_record"]["final_choice"] == "B"
    assert history["room"]["created_at"].endswith("Z")


def test_incomplete_history_does_not_analyze(accounts, monkeypatch):
    room = add_room(accounts)
    accounts.record_room("T1", "Ucreator", room)
    monkeypatch.setattr(accounts_module, "analyze_room", lambda *args: pytest.fail("incomplete rooms must not be analyzed"))
    assert accounts.get_history("T1", "Ucreator", room.code)["analysis"] is None
    assert accounts.list_rooms("T1", "Ucreator")["rooms"][0]["status"] == "collecting"


def test_listing_never_analyzes_and_cursor_is_identity_bound(accounts, monkeypatch):
    for index in range(3):
        room = add_room(accounts, code=f"AAA{index:03d}")
        accounts.record_room("T1", "Ucreator", room)
    monkeypatch.setattr(accounts_module, "analyze_room", lambda *args: pytest.fail("list must not analyze"))
    first = accounts.list_rooms("T1", "Ucreator", limit=2)
    second = accounts.list_rooms("T1", "Ucreator", limit=2, cursor=first["next_cursor"])
    assert len(first["rooms"]) == 2 and len(second["rooms"]) == 1
    assert len({room["code"] for room in first["rooms"] + second["rooms"]}) == 3
    assert second["next_cursor"] is None
    for team, user, cursor in [("T1", "Uother", first["next_cursor"]), ("T2", "Ucreator", first["next_cursor"]), ("T1", "Ucreator", first["next_cursor"] + "x")]:
        with pytest.raises(SlackDomainError, match="cursor"):
            accounts.list_rooms(team, user, cursor=cursor)


def test_history_index_is_bounded_and_concurrent_updates_survive(accounts):
    rooms = [add_room(accounts, code=f"R{number:05d}") for number in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda room: accounts.record_room("T1", "Ucreator", room), rooms))
    assert len(accounts.list_rooms("T1", "Ucreator", limit=50)["rooms"]) == 24
    accounts.MAX_ROOMS_PER_USER = 5
    accounts.record_room("T1", "Ucreator", rooms[-1])
    assert len(accounts.list_rooms("T1", "Ucreator")["rooms"]) == 5


def test_account_link_is_one_to_one_idempotent_and_not_stored_raw(accounts):
    token = accounts.create_link("T1", "Ucreator")
    with pytest.raises(SlackDomainError, match="invalid account link"):
        accounts.consume_link(token + "x", "google-one")
    assert accounts.consume_link(token, "google-one") == {"team_id": "T1", "user_id": "Ucreator"}
    assert accounts.consume_link(token, "google-one") == {"team_id": "T1", "user_id": "Ucreator"}
    with pytest.raises(SlackDomainError, match="already used"):
        accounts.consume_link(token, "google-two")
    with pytest.raises(SlackDomainError, match="already linked"):
        accounts.consume_link(accounts.create_link("T1", "Uother"), "google-one")
    with pytest.raises(SlackDomainError, match="already linked"):
        accounts.consume_link(accounts.create_link("T1", "Ucreator"), "google-two")
    assert accounts.linked_identity("T1", "google-one") == "Ucreator"
    assert accounts.linked_identity("T2", "google-one") is None
    stored = str(accounts.store._table.items if accounts.store.persistent else accounts.store._memory)
    assert token not in stored and "google-one" not in stored


def test_concurrent_account_token_consumers_have_only_one_winner(accounts):
    token = accounts.create_link("T1", "Ucreator")

    def claim(number):
        try:
            accounts.consume_link(token, f"google-{number}")
            return f"google-{number}"
        except SlackDomainError as exc:
            assert exc.status == 409
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [account for account in pool.map(claim, range(16)) if account]
    assert len(winners) == 1
    assert accounts.linked_identity("T1", winners[0]) == "Ucreator"


def test_failed_registry_write_reserves_token_without_granting_access(accounts, monkeypatch):
    token = accounts.create_link("T1", "Ucreator")
    original = accounts.store.compare_and_swap

    def fail_registry(key, *args):
        if key.startswith("SLACK#ACCOUNTS"):
            raise RuntimeError("provider unavailable")
        return original(key, *args)

    monkeypatch.setattr(accounts.store, "compare_and_swap", fail_registry)
    with pytest.raises(RuntimeError):
        accounts.consume_link(token, "google-one")
    assert accounts.linked_identity("T1", "google-one") is None
    monkeypatch.setattr(accounts.store, "compare_and_swap", original)
    with pytest.raises(SlackDomainError, match="already used"):
        accounts.consume_link(token, "google-two")
    accounts.consume_link(token, "google-one")
    assert accounts.linked_identity("T1", "google-one") == "Ucreator"


def test_link_expires_after_ten_minutes(accounts, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    token = accounts.create_link("T1", "Ucreator")
    monkeypatch.setattr(time, "time", lambda: now + 601)
    with pytest.raises(SlackDomainError) as error:
        accounts.consume_link(token, "google-one")
    assert error.value.status == 410


@pytest.fixture
def account_client(accounts, monkeypatch):
    monkeypatch.setenv("SLACK_TEAM_ID", "T1")
    monkeypatch.setenv("SYNQ_PUBLIC_URL", "http://testserver")
    # Use localhost HTTP only; production public origins must be HTTPS.
    monkeypatch.setenv("SYNQ_PUBLIC_URL", "https://testserver")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-at-least-32-characters")
    monkeypatch.setattr(accounts_module, "get_accounts", lambda _room_store: accounts)
    app = FastAPI()
    app.include_router(build_account_router(accounts.room_store))
    return TestClient(app, base_url="https://testserver")


def authenticate(client, google_sub="google-one"):
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(AuthUser(google_sub=google_sub, name="Google User", email="member@example.com")))


def test_account_http_requires_session_origin_and_explicit_token(accounts, account_client):
    token = accounts.create_link("T1", "Ucreator")
    assert account_client.post("/api/slack/link", json={"token": token}).status_code == 401
    authenticate(account_client)
    for origin in (None, "https://attacker.example", "https://testserver.evil.example", "https://testserver/"):
        headers = {"Origin": origin} if origin else {}
        response = account_client.post("/api/slack/link", json={"token": token}, headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
    assert accounts.linked_identity("T1", "google-one") is None
    response = account_client.post("/api/slack/link", json={"token": token}, headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_history_http_denies_other_google_user_and_other_workspace_link(accounts, account_client):
    room = completed_room(accounts)
    accounts.record_room("T1", "Ucreator", room)
    accounts.consume_link(accounts.create_link("T1", "Ucreator"), "google-one")
    assert account_client.get("/api/slack/me/rooms").status_code == 401
    authenticate(account_client, "google-two")
    assert account_client.get("/api/slack/me/rooms").status_code == 403
    other_token = accounts.create_link("T2", "Ucreator")
    response = account_client.post("/api/slack/link", json={"token": other_token}, headers={"Origin": "https://testserver"})
    assert response.status_code == 403
    assert accounts.linked_identity("T2", "google-two") is None
    authenticate(account_client)
    response = account_client.get("/api/slack/me/rooms/ABC123")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["room"]["code"] == "ABC123"
    assert account_client.get("/api/slack/me/rooms/XYZ999").status_code == 404


def test_account_page_has_nonce_csp_and_requires_confirmation(account_client):
    first = account_client.get("/slack/link")
    second = account_client.get("/slack/link")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in first.headers["content-security-policy"]
    assert first.headers["content-security-policy"] != second.headers["content-security-policy"]
    assert "__CSP_NONCE__" not in first.text
    assert "이 계정에 Slack 연결" in first.text
    assert "같은 6자리 방" in first.text
    assert "기본 90일" in first.text
    assert first.text.index("history.replaceState") < first.text.index('src="https://accounts.google.com/gsi/client"')
