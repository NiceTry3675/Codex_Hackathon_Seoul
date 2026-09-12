"""Offline HTTP contracts for Slack and web using the same room and participant."""

import copy
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from backend import main, slack, slack_accounts
from backend.auth import SESSION_COOKIE_NAME, create_session_token
from backend.models import AuthUser, ParsedOpinion
from backend.slack_identity import identity_hash, read_metadata, sign_metadata
from backend.slack_views import CREATE_CALLBACK


SECRET = "unified-slack-signing-secret"
TEAM = "TUNIFIED"
CHANNEL = "CUNIFIED"
REASON = "Impact 관련 우려를 검토해야 합니다."


@pytest.fixture
def setup(monkeypatch):
    for name in ("CONSENSUS_TABLE_NAME", "OPENAI_API_KEY", "SLACK_APP_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "SLACK_SIGNING_SECRET": SECRET, "SLACK_BOT_TOKEN": "xoxb-offline-test",
        "SLACK_TEAM_ID": TEAM, "SYNQ_PUBLIC_URL": "https://synq.example",
        "SESSION_SECRET": "unified-session-secret-with-at-least-32-characters",
        "GOOGLE_CLIENT_ID": "offline-test-client", "SESSION_COOKIE_SECURE": "false",
        "SLACK_HISTORY_RETENTION_DAYS": "90",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(main.room_store, "_table_name", "")
    main.rooms.clear()
    main.room_analysis_locks.clear()
    slack._seen.clear()
    monkeypatch.setattr(slack, "_receipt_store", None)
    slack_accounts._cached_accounts.cache_clear()
    sent = []

    def post(url, payload, token=None):
        sent.append((url, copy.deepcopy(payload), token))
        return {"ok": True, "view": {"id": "VOPEN"}}

    monkeypatch.setattr(slack, "post_json", post)
    with TestClient(main.app) as client:
        yield client, sent
    main.rooms.clear()
    main.room_analysis_locks.clear()
    slack._seen.clear()
    slack_accounts._cached_accounts.cache_clear()


def _post_form(client, path, fields):
    body = urlencode(fields).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post(path, content=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature,
    })


def _command(client, text, user="UALICE", **overrides):
    fields = {
        "team_id": TEAM, "channel_id": CHANNEL, "user_id": user, "command": "/synq",
        "text": text, "trigger_id": f"trigger-{text}-{user}",
        "response_url": "https://hooks.slack.com/commands/offline/response",
    }
    fields.update(overrides)
    return _post_form(client, "/api/slack/commands", fields)


def _interaction(client, payload):
    return _post_form(client, "/api/slack/interactions", {"payload": json.dumps(payload)})


def _create_web(client, expected_members=2):
    response = client.post("/api/rooms", json={
        "question": "다음 개선 순서는?", "options": ["A", "B"], "criteria": ["Impact"],
        "expected_members": expected_members,
    })
    assert response.status_code == 201
    code = response.json()["code"]
    assert len(code) == 6
    return code


def _evaluation(code, user="UALICE", view_id="VEVAL", metadata=None):
    def selected(value):
        return {"value": {"selected_option": {"value": str(value)}}}

    return {
        "type": "view_submission", "team": {"id": TEAM}, "user": {"id": user},
        "view": {
            "id": view_id, "callback_id": "synq_evaluate",
            "private_metadata": metadata or sign_metadata(SECRET, TEAM, user, CHANNEL, code),
            "state": {"values": {
                "s_0_0": selected(5), "s_1_0": selected(2), "w_0": selected(100),
                "first_choice": selected(0), "reason": {"value": {"value": REASON}},
            }},
        },
    }


def _web_evaluation():
    return {
        "scores": {"A": {"Impact": 5}, "B": {"Impact": 2}},
        "weights": {"Impact": 100}, "first_choice": "A", "reason": REASON,
    }


def _last_view(sent):
    return next(payload["view"] for url, payload, _ in reversed(sent) if url.endswith("views.update"))


def _open_evaluation(client, sent, code, user):
    assert _command(client, f"join {code}", user).status_code == 200
    view = _last_view(sent)
    assert view["callback_id"] == "synq_evaluate"
    metadata = read_metadata(SECRET, view["private_metadata"], TEAM, user)
    assert metadata["code"] == code
    assert metadata["channel"] == CHANNEL
    return view


def _link_google(client, slack_user="UALICE"):
    user = AuthUser(google_sub="google-subject-offline", email="person@example.test", name="Test Person")
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user))
    accounts = slack_accounts.get_accounts(main.room_store)
    token = accounts.create_link(TEAM, slack_user)
    response = client.post("/api/slack/link", json={"token": token}, headers={"Origin": "https://synq.example"})
    assert response.status_code == 200
    assert accounts.linked_identity(TEAM, user.google_sub) == slack_user


def test_opening_and_cancelling_native_form_does_not_reserve_a_shared_web_room_seat(setup):
    client, sent = setup
    code = _create_web(client, expected_members=2)
    _open_evaluation(client, sent, code, "UALICE")
    # Alice closes the form without submitting; Bob and Carol can still fill both seats.
    assert main.rooms[code].submissions == []
    assert main.rooms[code].used_anonymous_token_hashes == []
    assert slack_accounts.get_accounts(main.room_store).list_rooms(TEAM, "UALICE")["rooms"] == []
    assert len(main.rooms) == 1
    for user, view_id in (("UBOB", "VBOB"), ("UCAROL", "VCAROL")):
        view = _open_evaluation(client, sent, code, user)
        assert _interaction(client, _evaluation(code, user, view_id, view["private_metadata"])).status_code == 200
    room = client.get(f"/api/rooms/{code}").json()
    assert room["code"] == code
    assert room["submission_count"] == 2 and room["is_complete"]
    assert len(main.rooms) == 1


def test_native_reason_uses_shared_opinion_parser_and_native_analysis_matches_web(setup, monkeypatch):
    client, sent = setup
    code = _create_web(client, expected_members=1)
    parsed = ParsedOpinion(preferred_option="A", positive=[], concerns=["Impact"])
    calls = []

    def parse(reason, options, criteria):
        calls.append((reason, options, criteria))
        return parsed

    monkeypatch.setattr(main, "parse_opinion", parse)
    assert _interaction(client, _evaluation(code)).status_code == 200
    assert calls == [(REASON, ["A", "B"], ["Impact"])]
    assert main.rooms[code].submissions[0].parsed == parsed
    web = client.get(f"/api/rooms/{code}/analysis")
    assert web.status_code == 200
    assert "응답의 과반에서 Impact 우려가 언급되었습니다." in web.json()["hidden_conflicts"]
    native_analyses = []
    original = slack.result_view

    def result(room, analysis, metadata=""):
        native_analyses.append(analysis.model_dump(mode="json", exclude_none=True))
        return original(room, analysis, metadata)

    monkeypatch.setattr(slack, "result_view", result)
    assert _command(client, f"results {code}").status_code == 200
    assert native_analyses == [web.json()]
    assert "Impact 우려" in json.dumps(_last_view(sent), ensure_ascii=False)
    assert REASON not in json.dumps(_last_view(sent), ensure_ascii=False)


def test_native_submission_updates_personal_index_and_retries_send_completion_once(setup):
    client, sent = setup
    fields = {
        "question": "다음 개선 순서는?", "options": "A\nB", "criteria": "Impact",
        "expected_members": "2", "expires_in_hours": "24", "context": "",
    }
    creation = {
        "type": "view_submission", "team": {"id": TEAM}, "user": {"id": "UCREATOR"},
        "view": {"id": "VCREATE", "callback_id": CREATE_CALLBACK,
            "private_metadata": sign_metadata(SECRET, TEAM, "UCREATOR", CHANNEL),
            "state": {"values": {key: {"value": {"value": value}} for key, value in fields.items()}},
        },
    }
    assert _interaction(client, creation).status_code == 200
    code = next(iter(main.rooms))
    assert len(code) == 6
    assert client.get(f"/api/rooms/{code}").status_code == 200
    sent.clear()
    first = _evaluation(code, "UALICE", "VALICE")
    final = _evaluation(code, "UBOB", "VBOB")
    assert _interaction(client, first).status_code == 200
    assert not [url for url, _, _ in sent if url.endswith("chat.postMessage")]
    for payload in (final, final, first):
        assert _interaction(client, payload).status_code == 200
    assert len(main.rooms[code].submissions) == 2
    alerts = [payload for url, payload, _ in sent if url.endswith("chat.postMessage")]
    assert len(alerts) == 1 and alerts[0]["channel"] == CHANNEL
    assert "평가 제출이 완료" in json.dumps(alerts[0], ensure_ascii=False)
    assert REASON not in json.dumps(alerts[0], ensure_ascii=False)
    accounts = slack_accounts.get_accounts(main.room_store)
    for user in ("UCREATOR", "UALICE", "UBOB"):
        assert [room["code"] for room in accounts.list_rooms(TEAM, user)["rooms"]] == [code]
    assert accounts.list_rooms(TEAM, "UCAROL")["rooms"] == []
    assert _command(client, "rooms").status_code == 200
    view = _last_view(sent)
    assert code in json.dumps(view)
    assert "synq_history_room" in json.dumps(view)
    read_metadata(SECRET, view["private_metadata"], TEAM, "UALICE")


def test_linked_google_web_submission_cannot_submit_again_from_slack(setup):
    client, sent = setup
    code = _create_web(client)
    _link_google(client)
    response = client.post(f"/api/rooms/{code}/submit", json=_web_evaluation())
    assert response.status_code == 201
    assert identity_hash(TEAM, "UALICE", code) in main.rooms[code].used_anonymous_token_hashes
    assert _command(client, f"join {code}").status_code == 200
    assert "이미 제출" in json.dumps(_last_view(sent), ensure_ascii=False)
    assert "callback_id" not in _last_view(sent)
    # Even a previously opened form is rejected at the shared atomic append.
    assert _interaction(client, _evaluation(code)).status_code == 200
    assert len(main.rooms[code].submissions) == 1
    history = client.get("/api/slack/me/rooms")
    assert history.status_code == 200
    assert [room["code"] for room in history.json()["rooms"]] == [code]


def test_slack_submission_cannot_submit_again_from_linked_google_web_session(setup):
    client, _ = setup
    code = _create_web(client)
    assert _interaction(client, _evaluation(code)).status_code == 200
    _link_google(client)
    assert client.get(f"/api/rooms/{code}").status_code == 200
    response = client.post(f"/api/rooms/{code}/submit", json=_web_evaluation())
    assert response.status_code == 409
    assert len(main.rooms[code].submissions) == 1
    history = client.get(f"/api/slack/me/rooms/{code}")
    assert history.status_code == 200
    assert history.json()["room"]["submission_count"] == 1
    assert history.headers["cache-control"] == "no-store"


def test_native_form_metadata_is_bound_to_user_before_any_submission_or_history_write(setup):
    client, sent = setup
    code = _create_web(client)
    payload = _evaluation(code)
    payload["user"]["id"] = "UBOB"
    response = _interaction(client, payload)
    assert response.status_code == 400
    assert main.rooms[code].submissions == []
    assert sent == []
    assert slack_accounts.get_accounts(main.room_store).list_rooms(TEAM, "UBOB")["rooms"] == []


def test_optional_app_id_guard_preserves_current_setup_and_rejects_other_apps(setup, monkeypatch):
    client, sent = setup
    assert _command(client, "help").status_code == 200
    monkeypatch.setenv("SLACK_APP_ID", "AUNIFIED")
    assert _command(client, "help").status_code == 403
    assert _command(client, "help", api_app_id="AOTHER").status_code == 403
    assert _command(client, "help", api_app_id="AUNIFIED").status_code == 200
    code = _create_web(client)
    payload = _evaluation(code)
    for app_id in (None, "AOTHER"):
        attempt = {**payload, **({"api_app_id": app_id} if app_id else {})}
        assert _interaction(client, attempt).status_code == 403
    assert main.rooms[code].submissions == []
    assert sent == []
    assert _interaction(client, {**payload, "api_app_id": "AUNIFIED"}).status_code == 200
    assert len(main.rooms[code].submissions) == 1


def test_private_history_button_updates_existing_modal_after_public_expiry(setup):
    from datetime import datetime, timedelta, timezone
    client, sent = setup
    code = _create_web(client, expected_members=1)
    _interaction(client, _evaluation(code))
    _command(client, "rooms")
    listing = _last_view(sent)
    main.rooms[code].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get(f"/api/rooms/{code}").status_code == 404
    sent.clear()
    response = _interaction(client, {
        "type": "block_actions", "team": {"id": TEAM}, "user": {"id": "UALICE"},
        "trigger_id": "history-trigger", "view": {"id": "VHISTORY", "private_metadata": listing["private_metadata"]},
        "actions": [{"action_id": "synq_history_room", "value": code}],
    })
    assert response.status_code == 200
    assert [url.rsplit("/", 1)[-1] for url, _, _ in sent] == ["views.update", "views.update"]
    assert all(payload["view_id"] == "VHISTORY" for _, payload, _ in sent)
    assert _last_view(sent)["title"]["text"] == "팀 분석 결과"
    assert code in json.dumps(_last_view(sent))
    assert "synq_join" not in json.dumps(_last_view(sent))


def test_durable_delivery_receipt_is_claimed_after_ack_and_survives_process_cache_reset(setup, monkeypatch):
    import asyncio
    from fastapi import BackgroundTasks
    from starlette.requests import Request
    from backend.slack_store import SlackStore

    client, sent = setup
    code = _create_web(client)
    receipt_store = SlackStore(table_name="")
    monkeypatch.setenv("CONSENSUS_TABLE_NAME", "fake-table")
    monkeypatch.setattr(slack, "_receipt_store", receipt_store)
    events = []
    original = receipt_store.get
    monkeypatch.setattr(receipt_store, "get", lambda key: (events.append("read"), original(key))[1])
    body = urlencode({"team_id": TEAM, "channel_id": CHANNEL, "user_id": "UALICE", "command": "/synq",
        "text": f"share {code}", "response_url": "https://hooks.slack.com/commands/test/response"}).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/api/slack/commands", "headers": [
        (b"x-slack-request-timestamp", timestamp.encode()), (b"x-slack-signature", signature.encode()),
    ]}, receive)
    router = slack.build_router(main._get_room, main.get_analysis, main.get_decision_record, main._create_room)
    endpoint = next(route.endpoint for route in router.routes if getattr(route, "path", None) == "/api/slack/commands")
    tasks = BackgroundTasks()
    response = asyncio.run(endpoint(request, tasks))
    assert response["response_type"] == "ephemeral"
    assert events == [] and sent == []
    asyncio.run(tasks())
    assert events == ["read"]
    assert len(sent) == 1
    slack._seen.clear()  # Equivalent new-process cache; persistent receipt remains.
    assert not slack.claim_durable_request(signature)


def test_optional_link_lookup_failure_never_leaves_an_unreported_new_web_room(setup, monkeypatch):
    client, _ = setup
    def unavailable(_request):
        raise RuntimeError("test-account-store-unavailable")
    monkeypatch.setattr(main, "_linked_identity", unavailable)
    with TestClient(main.app, raise_server_exceptions=False) as browser:
        response = browser.post("/api/rooms", json={
            "question": "Test", "options": ["A", "B"], "criteria": ["Impact"], "expected_members": 2,
        })
    assert response.status_code == 500
    assert main.rooms == {}
