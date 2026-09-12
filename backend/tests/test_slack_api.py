"""Signed Slack HTTP flows; no real Slack, Google, AWS, or LLM calls."""

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import backend.slack as slack
from backend.auth import SESSION_COOKIE_NAME, create_session_token
from backend.models import AuthUser, RoomCreate
from backend.slack_client import SlackAPIError, SlackClient, SlackConfig, verify_signature
from backend.slack_service import SlackService
from backend.slack_store import SlackStore

SECRET = "s" * 32
TEAM, APP, USER, CHANNEL = "TTEST", "ATEST", "UTEST", "CTEST"


class FakeSlack:
    def __init__(self):
        self.calls = []
        self.responses = []

    def call(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True, "view": {"id": "VOPEN"}}

    def respond(self, url, payload):
        self.responses.append((url, payload))
        return {"ok": True}


@pytest.fixture
def runtime(monkeypatch):
    store = SlackStore(table_name="")
    runtime = slack.SlackRuntime(
        SlackConfig("xoxb-test", SECRET, TEAM, APP, "https://consensus.test"),
        SlackService(store, SECRET), FakeSlack(), store,
    )
    monkeypatch.setattr(slack, "get_runtime", lambda: runtime)
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    return runtime


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(slack.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, base_url="https://consensus.test")


def signed(body: bytes, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": timestamp, "x-slack-signature": "v0=" + signature}


def command(text="create", user=USER, **extra):
    return {"team_id": TEAM, "api_app_id": APP, "user_id": user, "channel_id": CHANNEL,
            "command": "/synq", "text": text, "trigger_id": "trigger-" + text + user,
            "response_url": "https://hooks.slack.com/commands/test/test", **extra}


def post(client, data, interactive=False, **kwargs):
    body = urlencode({"payload": json.dumps(data)} if interactive else data).encode()
    return client.post("/api/slack/interactions" if interactive else "/api/slack/commands",
                       content=body, headers=signed(body), **kwargs)


def text(value):
    return {"value": {"value": value}}


def selected(value):
    return {"value": {"selected_option": {"value": str(value)}}}


def create_values():
    return {"question": text("팀의 결정"), "options": text("A\nB"), "criteria": text("가치"),
            "expected_members": selected(2), "expires_in_hours": selected(24)}


def interaction(metadata, values, view_id="VCREATE", callback="consensus_create", user=USER):
    return {"type": "view_submission", "team": {"id": TEAM}, "user": {"id": user},
            "api_app_id": APP, "view": {"id": view_id, "callback_id": callback,
            "private_metadata": metadata, "state": {"values": values}}}


def last_view(runtime, method=None):
    methods = {method} if method else {"views.open", "views.update"}
    return [payload["view"] for name, payload in runtime.client.calls if name in methods][-1]


def test_manifest_and_router_use_synq_brand_and_command(client, runtime):
    manifest = json.loads(Path(slack.__file__).with_name("slack.manifest.json").read_text())
    assert manifest["display_information"]["name"] == "SynQ"
    assert manifest["features"]["bot_user"]["display_name"] == "SynQ"
    slash_command = manifest["features"]["slash_commands"][0]["command"]
    assert slash_command == "/synq"
    post(client, command("help", command=slash_command)).raise_for_status()
    help_text = runtime.client.responses[-1][1]["text"]
    assert "/synq create" in help_text and "/synq link" in help_text
    assert "/consensus" not in help_text
    assert post(client, command(command="/consensus")).status_code == 400


def test_signed_end_to_end_create_two_votes_private_history(client, runtime):
    assert post(client, command()).status_code == 200
    form = last_view(runtime)
    payload = interaction(form["private_metadata"], create_values())
    response = post(client, payload, True)
    assert response.json()["response_action"] == "update"
    # Slack retries the same submission without creating another room or card.
    post(client, payload, True).raise_for_status()
    assert len([p for method, p in runtime.client.calls if method == "chat.postMessage"]) == 1
    assert last_view(runtime, "views.update")["title"]["text"] == "방 생성 완료"
    rooms = runtime.service.list_rooms(TEAM, USER)["rooms"]
    assert len(rooms) == 1
    code = rooms[0]["code"]

    for index, user in enumerate((USER, "UOTHER")):
        assert post(client, command(f"join {code}", user=user)).status_code == 200
        form = last_view(runtime)
        votes = {"s_0_0": selected(5), "s_1_0": selected(2), "w_0": selected(10),
                 "first_choice": selected(0), "reason": text("private rationale")}
        vote = interaction(form["private_metadata"], votes, f"VSUBMIT{index}", "consensus_submit", user)
        post(client, vote, True).raise_for_status()
        post(client, vote, True).raise_for_status()
    assert runtime.service.get_history(TEAM, USER, code)["room"]["submission_count"] == 2
    post(client, command(f"results {code}")).raise_for_status()
    result = json.dumps(last_view(runtime), ensure_ascii=False)
    assert "Stability" in result
    assert "private rationale" not in result and "UOTHER" not in result

    post(client, command("rooms")).raise_for_status()
    assert code in json.dumps(last_view(runtime))


@pytest.mark.parametrize("alter", ["body", "old", "future", "unicode", "missing"])
def test_invalid_signature_never_dispatches(client, runtime, alter):
    body = urlencode(command()).encode()
    headers = signed(body)
    if alter == "body":
        body += b"&text=changed"
    elif alter in {"old", "future"}:
        headers = signed(body, int(time.time()) + (301 if alter == "future" else -301))
    elif alter == "unicode":
        assert not verify_signature(SECRET, body, str(int(time.time())), "한글")
        return
    else:
        headers.pop("x-slack-signature")
    assert client.post("/api/slack/commands", content=body, headers=headers).status_code == 401
    assert not runtime.client.calls


@pytest.mark.parametrize("overrides", [{"team_id": "TOTHER"}, {"api_app_id": "AOTHER"},
                                       {"is_ext_shared_channel": "true"}])
def test_wrong_workspace_app_or_shared_channel_rejected(client, runtime, overrides):
    assert post(client, command(**overrides)).status_code == 403
    assert not runtime.client.calls


def test_form_bound_to_authenticated_slack_user(client, runtime):
    meta = slack._metadata(runtime, TEAM, USER, CHANNEL)
    assert post(client, interaction(meta, create_values(), user="UOTHER"), True).status_code == 403
    assert runtime.service.list_rooms(TEAM, USER)["rooms"] == []


def test_inline_create_validation_never_creates_room(client, runtime):
    values = create_values()
    values["options"] = text("A\nA")
    response = post(client, interaction(slack._metadata(runtime, TEAM, USER, CHANNEL), values), True)
    assert response.json()["response_action"] == "errors"
    assert "options" in response.json()["errors"]
    assert runtime.service.list_rooms(TEAM, USER)["rooms"] == []


def history_action(runtime, code, user=USER):
    return {"type": "block_actions", "team": {"id": TEAM}, "user": {"id": user},
            "api_app_id": APP, "view": {"id": "VHISTORY",
                "private_metadata": slack._metadata(runtime, TEAM, user)},
            "actions": [{"action_id": "consensus_join", "value": code}]}


def test_history_can_reopen_member_submission_but_not_join_strangers(client, runtime):
    room = runtime.service.create_room(TEAM, USER, CHANNEL,
        RoomCreate(question="Private", options=["A", "B"], criteria=["Value"]), "history")
    post(client, history_action(runtime, room["code"]), True).raise_for_status()
    form = last_view(runtime, "views.update")
    assert form["callback_id"] == "consensus_submit"
    assert slack._read_metadata(runtime, form["private_metadata"], TEAM, USER)["channel"] == CHANNEL
    post(client, history_action(runtime, room["code"], user="USTRANGER"), True).raise_for_status()
    failure = last_view(runtime, "views.update")
    assert failure["title"]["text"] == "처리 결과"
    assert "callback_id" not in failure
    assert runtime.service.list_rooms(TEAM, "USTRANGER")["rooms"] == []


def test_retry_after_modal_delivery_failure_does_not_repeat_announcement(client, runtime):
    payload = interaction(slack._metadata(runtime, TEAM, USER, CHANNEL), create_values())
    original_call = runtime.client.call
    fail_once = True

    def flaky_call(method, data):
        nonlocal fail_once
        if method == "views.update" and fail_once:
            fail_once = False
            raise SlackAPIError("temporary_failure")
        return original_call(method, data)

    runtime.client.call = flaky_call
    post(client, payload, True).raise_for_status()
    post(client, payload, True).raise_for_status()
    assert len([p for method, p in runtime.client.calls if method == "chat.postMessage"]) == 1
    assert len(runtime.service.list_rooms(TEAM, USER)["rooms"]) == 1
    assert last_view(runtime, "views.update")["title"]["text"] == "방 생성 완료"


def test_full_size_slack_submission_with_view_blocks_is_accepted(client, runtime):
    labels = ["가" * 79 + str(i) for i in range(5)]
    room = runtime.service.create_room(TEAM, USER, CHANNEL,
        RoomCreate(question="질" * 500, options=labels, criteria=labels), "large")
    post(client, command(f"join {room['code']}")).raise_for_status()
    form = last_view(runtime)
    values = {f"s_{i}_{j}": selected(5) for i in range(5) for j in range(5)}
    values.update({f"w_{j}": selected(100) for j in range(5)})
    values.update({"first_choice": selected(0), "reason": text("가" * 2000)})
    payload = interaction(form["private_metadata"], values, "VLARGE", "consensus_submit")
    payload["view"]["blocks"] = form["blocks"]
    body = urlencode({"payload": json.dumps(payload, ensure_ascii=False)}).encode()
    assert 128 * 1024 < len(body) < slack.MAX_BODY_BYTES
    response = client.post("/api/slack/interactions", content=body, headers=signed(body))
    assert response.status_code == 200
    assert runtime.service.get_history(TEAM, USER, room["code"])["room"]["submission_count"] == 1


def test_history_opens_modal_before_slow_room_listing(client, runtime, monkeypatch):
    original_list = runtime.service.list_rooms

    def listing(*args, **kwargs):
        assert runtime.client.calls[-1][0] == "views.open"
        return original_list(*args, **kwargs)

    monkeypatch.setattr(runtime.service, "list_rooms", listing)
    post(client, command("rooms")).raise_for_status()
    assert runtime.client.calls[-1][0] == "views.update"


def test_ack_is_sent_before_background_service_or_slack_io(app, runtime, monkeypatch):
    events = []

    def handler(*_):
        assert any(e["type"] == "http.response.body" and not e.get("more_body", False) for e in events)
        events.append({"type": "handler"})

    monkeypatch.setattr(slack, "_command", handler)
    body = urlencode(command()).encode()
    headers = [(k.encode(), v.encode()) for k, v in signed(body).items()]

    async def exercise():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(event):
            events.append(event)

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "POST", "scheme": "https", "path": "/api/slack/commands",
                   "raw_path": b"/api/slack/commands", "query_string": b"", "headers": headers,
                   "client": ("127.0.0.1", 1), "server": ("consensus.test", 443)}, receive, send)

    asyncio.run(exercise())
    assert events[-1]["type"] == "handler"


def login(client, sub):
    user = AuthUser(google_sub=sub, email=sub + "@example.test", name=sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user))


def test_link_requires_login_same_origin_and_identity_ownership(client, runtime):
    token = runtime.service.create_link(TEAM, USER)
    body = {"token": token}
    assert client.post("/api/slack/link", json=body).status_code == 401
    login(client, "google-one")
    assert client.post("/api/slack/link", json=body).status_code == 403
    assert client.post("/api/slack/link", json=body, headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/slack/link", json=body, headers={"Origin": "https://consensus.test"}).status_code == 200
    room = runtime.service.create_room(TEAM, USER, CHANNEL,
        RoomCreate(question="Private", options=["A", "B"], criteria=["Value"]), "create1")
    response = client.get("/api/slack/me/rooms")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["rooms"][0]["code"] == room["code"]
    login(client, "google-two")
    assert client.post("/api/slack/link", json=body, headers={"Origin": "https://consensus.test"}).status_code == 409
    assert client.get("/api/slack/me/rooms").status_code == 403


def test_history_is_private_after_link_and_legacy_api_cannot_read_slack_room(client, runtime):
    own = runtime.service.create_room(TEAM, USER, CHANNEL,
        RoomCreate(question="Private", options=["A", "B"], criteria=["Value"]), "create1")
    login(client, "google-two")
    token = runtime.service.create_link(TEAM, "UOTHER")
    client.post("/api/slack/link", json={"token": token}, headers={"Origin": "https://consensus.test"}).raise_for_status()
    assert client.get("/api/slack/me/rooms").json()["rooms"] == []
    assert client.get(f"/api/slack/me/rooms/{own['code']}").status_code == 404
    from backend.main import app as main_app
    with TestClient(main_app) as other:
        assert other.get(f"/api/rooms/{own['code']}").status_code == 422


@pytest.mark.parametrize("url", ["http://hooks.slack.com/commands/a", "https://evil.test/commands/a",
    "https://hooks.slack.com.evil.test/commands/a", "https://hooks.slack.com@evil.test/commands/a",
    "https://hooks.slack.com:444/commands/a", "https://hooks.slack.com/anything"])
def test_response_url_never_sends_outside_slack(url):
    with pytest.raises(SlackAPIError):
        SlackClient("test").respond(url, {"text": "private"})


def test_oversized_signed_request_is_rejected(client, runtime):
    body = b"a=" + b"x" * slack.MAX_BODY_BYTES
    assert client.post("/api/slack/commands", content=body, headers=signed(body)).status_code == 413


def test_link_page_csp_no_store_and_fragment_not_needed_on_server(client):
    response = client.get("/slack/link")
    assert response.status_code == 200
    assert "__CSP_NONCE__" not in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "내 Slack 방 · SynQ" in response.text
    assert "SynQ · SLACK" in response.text
    assert "/synq link" in response.text and "/consensus" not in response.text
