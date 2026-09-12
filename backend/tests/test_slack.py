import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import main, slack
from backend.slack_views import CREATE_CALLBACK, creation_modal
from backend.models import DecisionDraft


@pytest.fixture
def setup(monkeypatch):
    for key, value in {
        "SLACK_SIGNING_SECRET": "test-secret", "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_TEAM_ID": "TTEST", "SYNQ_PUBLIC_URL": "https://synq.example",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    main.rooms.clear()
    main.room_analysis_locks.clear()
    slack._seen.clear()
    sent = []
    monkeypatch.setattr(slack, "post_json", lambda url, payload, token=None: sent.append((url, payload, token)))
    yield TestClient(main.app), sent
    main.rooms.clear()
    main.room_analysis_locks.clear()
    slack._seen.clear()


def command(client, text="", *, timestamp=None, secret="test-secret", **overrides):
    data = {
        "team_id": "TTEST", "channel_id": "CTEST", "command": "/synq",
        "text": text, "response_url": "https://hooks.slack.com/commands/test/response",
    }
    data.update(overrides)
    body = urlencode(data).encode()
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/api/slack/commands", content=body, headers={
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": timestamp, "x-slack-signature": signature,
    })


def create_room(client, complete=False):
    room = client.post("/api/rooms", json={
        "question": "Choose <!channel>", "options": ["A", "B"],
        "criteria": ["Impact"], "expected_members": 1,
    }).json()
    if complete:
        client.post(f"/api/rooms/{room['code']}/submit", json={
            "scores": {"A": {"Impact": 5}, "B": {"Impact": 2}},
            "weights": {"Impact": 100}, "first_choice": "A", "reason": "PRIVATE-OPINION",
        }).raise_for_status()
    return room["code"]


def modal_payload(view_id="VTEST", **values):
    fields = {"question": "이번 주 우선순위", "options": "A\nB", "criteria": "Impact",
              "expected_members": "2", "expires_in_hours": "24", "context": ""}
    fields.update(values)
    return {"type": "view_submission", "team": {"id": "TTEST"}, "user": {"id": "UPRIVATE"}, "view": {
        "id": view_id, "callback_id": CREATE_CALLBACK,
        "private_metadata": creation_modal("TTEST", "CTEST")["private_metadata"],
        "state": {"values": {key: {"value": {"value": value}} for key, value in fields.items()}},
    }}


def interaction(client, payload, secret="test-secret"):
    body = urlencode({"payload": json.dumps(payload)}).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/api/slack/interactions", content=body, headers={
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": timestamp, "x-slack-signature": signature,
    })


def submit(client, code):
    client.get(f"/api/rooms/{code}").raise_for_status()
    return client.post(f"/api/rooms/{code}/submit", json={
        "scores": {"A": {"Impact": 5}, "B": {"Impact": 2}},
        "weights": {"Impact": 100}, "first_choice": "A", "reason": "PRIVATE-OPINION",
    })


def test_new_opens_native_modal_and_deduplicates_trigger(setup):
    client, sent = setup
    timestamp = int(time.time())
    for _ in range(2):
        response = command(client, "new", trigger_id="trigger.test", timestamp=timestamp)
        assert response.status_code == 200
    assert len(sent) == 1
    url, payload, _ = sent[0]
    assert url.endswith("/views.open")
    assert payload["trigger_id"] == "trigger.test"
    assert payload["view"]["callback_id"] == CREATE_CALLBACK
    assert len(main.rooms) == 0


def test_modal_creates_once_and_keeps_notification_destination_private(setup):
    client, sent = setup
    payload = modal_payload()
    assert interaction(client, payload).json()["response_action"] == "update"
    assert interaction(client, payload).status_code == 200
    assert len(main.rooms) == 1
    room = next(iter(main.rooms.values()))
    assert room.slack_origin.channel_id == "CTEST"
    assert room.submission_mode == "anonymous"
    assert "UPRIVATE" not in room.model_dump_json()
    assert "slack_origin" not in client.get(f"/api/rooms/{room.code}").json()
    assert [url.rsplit("/", 1)[1] for url, _, _ in sent] == ["chat.postMessage", "views.update"]
    assert room.code in json.dumps(sent)


@pytest.mark.parametrize("field,value", [("options", "A\nA"), ("criteria", ""),
                                         ("expected_members", "0"), ("expires_in_hours", "169")])
def test_modal_validation_allows_correction_without_creating_room(setup, field, value):
    client, sent = setup
    response = interaction(client, modal_payload(**{field: value}))
    assert response.json()["response_action"] == "errors"
    assert field in response.json()["errors"]
    assert not main.rooms and not sent
    assert interaction(client, modal_payload()).json()["response_action"] == "update"
    assert len(main.rooms) == 1


def test_interactions_reject_invalid_signature_and_cross_workspace(setup):
    client, sent = setup
    payload = modal_payload()
    assert interaction(client, payload, secret="wrong").status_code == 401
    payload["team"]["id"] = "TOTHER"
    assert interaction(client, payload).status_code == 403
    payload["team"]["id"] = "TTEST"
    payload["view"]["private_metadata"] = json.dumps({"team_id": "TOTHER", "channel_id": "CTEST"})
    assert interaction(client, payload).status_code == 400
    assert not main.rooms and not sent


def test_only_final_submission_sends_completion_to_original_channel(setup):
    client, sent = setup
    interaction(client, modal_payload())
    code = next(iter(main.rooms))
    sent.clear()
    assert submit(client, code).status_code == 201
    assert not sent
    with TestClient(main.app) as second:
        assert submit(second, code).status_code == 201
        assert submit(second, code).status_code == 409
    assert len(sent) == 1
    _, payload, _ = sent[0]
    assert payload["channel"] == "CTEST"
    assert "평가 제출이 완료" in json.dumps(payload, ensure_ascii=False)
    assert "PRIVATE-OPINION" not in json.dumps(payload)
    assert "view=results" in json.dumps(payload)


def test_completion_delivery_failure_preserves_submission(setup, monkeypatch, caplog):
    client, _ = setup
    interaction(client, modal_payload(expected_members="1"))
    code = next(iter(main.rooms))

    def fail(*args, **kwargs):
        raise RuntimeError("secret-should-not-leak")

    monkeypatch.setattr(slack, "post_json", fail)
    response = submit(client, code)
    assert response.status_code == 201 and response.json()["is_complete"]
    assert len(main.rooms[code].submissions) == 1
    assert "secret-should-not-leak" not in caplog.text


def test_creation_post_failure_preserves_room_and_shows_recovery_code(setup, monkeypatch):
    client, sent = setup

    def fail_channel(url, payload, token=None):
        if url.endswith("chat.postMessage"):
            raise RuntimeError("offline")
        sent.append((url, payload, token))

    monkeypatch.setattr(slack, "post_json", fail_channel)
    assert interaction(client, modal_payload()).status_code == 200
    assert len(main.rooms) == 1
    code = next(iter(main.rooms))
    assert len(sent) == 1 and sent[0][0].endswith("views.update")
    assert f"/synq share {code}" in json.dumps(sent)


def test_from_thread_opens_loading_view_then_editable_draft_without_creating_room(setup, monkeypatch):
    client, sent = setup
    events = []

    def post(url, payload, token=None):
        events.append(url.rsplit("/", 1)[1])
        sent.append((url, payload, token))
        return {"ok": True, "view": {"id": "VDRAFT"}}

    def page(channel, timestamp, cursor, token):
        events.append("read")
        return {"messages": [{"ts": "1789170000.123456", "user": "UPRIVATE", "text": "API 개선과 검색 개선을 비교하자"}]}

    def suggest(messages, partial):
        events.append("AI")
        assert "UPRIVATE" not in json.dumps(messages)
        return DecisionDraft(question="무엇을 먼저 개선할까요?", options=["API 개선", "검색 개선"],
                             criteria=["기대 효과", "실행 가능성"], context="개선 순서를 정합니다.")

    monkeypatch.setattr(slack, "post_json", post)
    monkeypatch.setattr(slack, "get_thread_page", page)
    monkeypatch.setattr(slack, "suggest_thread_decision", suggest)
    response = command(client, "from https://synq-test.slack.com/archives/CTEST/p1789170000123456", trigger_id="trigger")
    assert response.status_code == 200
    assert events == ["views.open", "read", "AI", "views.update"]
    assert not main.rooms
    view = sent[-1][1]["view"]
    assert view["callback_id"] == CREATE_CALLBACK
    question = next(block for block in view["blocks"] if block.get("block_id") == "question")
    assert question["element"]["initial_value"] == "무엇을 먼저 개선할까요?"
    assert all(not url.endswith("chat.postMessage") for url, _, _ in sent)
    # Only the user's explicit submission creates and announces the decision.
    edited = modal_payload(view_id="VDRAFT", question="직접 수정한 질문")
    assert interaction(client, edited).status_code == 200
    assert next(iter(main.rooms.values())).question == "직접 수정한 질문"


def test_thread_from_other_channel_never_reads_or_opens_modal(setup):
    client, sent = setup
    response = command(client, "from https://synq-test.slack.com/archives/COTHER/p1789170000123456", trigger_id="trigger")
    assert response.status_code == 200
    assert response.json()["response_type"] == "ephemeral"
    assert not sent and not main.rooms


@pytest.mark.parametrize("failure", ["missing_scope", "ratelimited", "no_ai"])
def test_thread_failures_offer_manual_form_without_fabricated_recommendations(setup, monkeypatch, failure):
    client, sent = setup

    def post(url, payload, token=None):
        sent.append((url, payload, token))
        return {"ok": True, "view": {"id": "VDRAFT"}}

    def page(*args):
        if failure != "no_ai":
            raise slack.SlackAPIError(failure)
        return {"messages": [{"ts": "1", "text": "검토해보자"}]}

    monkeypatch.setattr(slack, "post_json", post)
    monkeypatch.setattr(slack, "get_thread_page", page)
    monkeypatch.setattr(slack, "suggest_thread_decision", lambda *_: None)
    assert command(client, "from https://synq-test.slack.com/archives/CTEST/p1789170000123456", trigger_id="trigger").status_code == 200
    view = sent[-1][1]["view"]
    assert view["callback_id"] == CREATE_CALLBACK
    options = next(block for block in view["blocks"] if block.get("block_id") == "options")
    assert "initial_value" not in options["element"]
    assert not main.rooms


def test_start_is_private_with_creation_deep_link(setup):
    client, sent = setup
    response = command(client)
    assert response.status_code == 200
    assert response.json()["response_type"] == "ephemeral"
    assert "https://synq.example/?view=create" in json.dumps(response.json())
    assert sent == []


@pytest.mark.parametrize("overrides, expected", [
    ({"secret": "wrong"}, 401),
    ({"timestamp": 1}, 401),
    ({"timestamp": int(time.time()) + 600}, 401),
    ({"timestamp": "invalid"}, 401),
    ({"team_id": "TOTHER"}, 403),
    ({"response_url": "http://127.0.0.1/commands/x"}, 400),
    ({"response_url": "https://hooks.slack.com.evil.test/commands/x"}, 400),
    ({"response_url": "https://[invalid/commands/x"}, 400),
    ({"channel_id": "@someone"}, 400),
])
def test_rejects_invalid_requests_without_delivery(setup, overrides, expected):
    client, sent = setup
    assert command(client, "share ABC123", **overrides).status_code == expected
    assert sent == []


def test_missing_configuration_disables_commands(setup, monkeypatch):
    client, sent = setup
    monkeypatch.delenv("SLACK_SIGNING_SECRET")
    assert command(client).status_code == 503
    assert not sent


def test_share_suppresses_replay_and_renders_input_as_plain_text(setup):
    client, sent = setup
    code = create_room(client)
    timestamp = int(time.time())
    for _ in range(2):
        assert command(client, f"share {code}", timestamp=timestamp).status_code == 200
    assert len(sent) == 1
    url, payload, token = sent[0]
    assert url == "https://slack.com/api/chat.postMessage"
    assert payload["channel"] == "CTEST"
    assert payload["blocks"][0]["text"]["type"] == "plain_text"
    assert f"room={code}" in json.dumps(payload)
    assert token == "xoxb-test"


def test_incomplete_analysis_and_missing_room_stay_private(setup):
    client, sent = setup
    code = create_room(client)
    command(client, f"result {code}")
    command(client, "share ZZZZZZ")
    assert len(sent) == 2
    assert all(payload["response_type"] == "ephemeral" for _, payload, _ in sent)


def test_result_and_final_record_share_without_personal_submissions(setup):
    client, sent = setup
    code = create_room(client, complete=True)
    assert command(client, f"result {code}").status_code == 200
    client.post(f"/api/rooms/{code}/decision-record", json={
        "final_choice": "B", "final_reason": "Team confirmed implementation constraints",
    }).raise_for_status()
    assert command(client, f"record {code}").status_code == 200
    assert len(sent) == 2
    payloads = json.dumps(sent, ensure_ascii=False)
    assert "현재 평가 1위: A" in payloads
    assert "최종 선택: B" in payloads
    assert "PRIVATE-OPINION" not in payloads
    assert "participant_name" not in payloads


def test_delivery_failure_notifies_privately_without_exposing_exception(setup, monkeypatch, caplog):
    client, sent = setup
    code = create_room(client)

    def fail_public(url, payload, token=None):
        if token:
            raise RuntimeError("secret-value-must-not-appear")
        sent.append((url, payload, token))

    monkeypatch.setattr(slack, "post_json", fail_public)
    response = command(client, f"share {code}")
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0][1]["response_type"] == "ephemeral"
    assert "secret-value-must-not-appear" not in caplog.text + json.dumps(sent)


def test_analysis_work_starts_after_http_ack(setup):
    # TestClient waits for background tasks; capture raw ASGI message order instead.
    import asyncio

    _, sent = setup
    events = []
    app = FastAPI()

    def missing(code):
        events.append("lookup")
        raise HTTPException(404)

    app.include_router(slack.build_router(missing, missing, missing))
    body = urlencode({"team_id": "TTEST", "channel_id": "CTEST", "command": "/synq",
                      "text": "result ABC123", "response_url": "https://hooks.slack.com/commands/test"}).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"test-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()

    async def run():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            events.append(message["type"])

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "POST", "scheme": "https", "path": "/api/slack/commands",
                   "query_string": b"", "root_path": "", "server": ("test", 443),
                   "client": ("test", 1), "headers": [
                       (b"x-slack-request-timestamp", timestamp.encode()),
                       (b"x-slack-signature", signature.encode()),
                   ]}, receive, send)

    asyncio.run(run())
    assert events.index("http.response.body") < events.index("lookup")
