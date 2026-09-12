"""Single-workspace Slack adapter. Signed requests ACK before any slow work.

The Slack service owns its private room records. They cannot be retrieved through
the legacy, share-by-code web API. This router is mounted before the React SPA.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import user_from_request
from .models import Room
from .slack_client import SlackAPIError, SlackClient, SlackConfig, verify_signature
from .slack_service import SlackDomainError, SlackService
from .slack_store import SlackStore
from .slack_views import (
    ViewValidationError, create_room_view, history_view, parse_create,
    parse_submission, result_view, room_message, submission_view,
)

router = APIRouter()
logger = logging.getLogger(__name__)
# Slack includes the full view.blocks in submissions (including select options).
MAX_BODY_BYTES = 512 * 1024


@dataclass
class SlackRuntime:
    config: SlackConfig
    service: SlackService
    client: SlackClient
    store: SlackStore


@lru_cache(maxsize=1)
def get_runtime() -> SlackRuntime:
    config = SlackConfig.from_env()
    store = SlackStore()
    return SlackRuntime(config, SlackService(store, config.signing_secret, config.retention_days),
                        SlackClient(config.bot_token), store)


def _runtime() -> SlackRuntime:
    try:
        return get_runtime()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _metadata(runtime: SlackRuntime, team: str, user: str, channel: str = "",
              code: str = "") -> str:
    body = _encode(json.dumps({"team": team, "user": user, "channel": channel,
                               "code": code, "exp": int(time.time()) + 7200},
                              separators=(",", ":")).encode())
    signature = hmac.new(runtime.config.signing_secret.encode(), body.encode(), hashlib.sha256)
    return body + "." + signature.hexdigest()


def _read_metadata(runtime: SlackRuntime, value: str, team: str, user: str) -> dict:
    try:
        body, supplied = value.split(".")
        expected = hmac.new(runtime.config.signing_secret.encode(), body.encode(), hashlib.sha256)
        if not hmac.compare_digest(expected.hexdigest(), supplied):
            raise ValueError()
        data = json.loads(base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True))
        if data["team"] != team or data["user"] != user or int(data["exp"]) <= time.time():
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "invalid or expired Slack form; please reopen it") from None


async def _payload(request: Request, runtime: SlackRuntime, *, interactive: bool) -> tuple[dict, str]:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Slack request is too large")
    raw = bytes(body)
    if not verify_signature(runtime.config.signing_secret, raw,
                            request.headers.get("x-slack-request-timestamp", ""),
                            request.headers.get("x-slack-signature", "")):
        raise HTTPException(401, "invalid Slack signature")
    try:
        form = parse_qs(raw.decode(), max_num_fields=100, keep_blank_values=True)
        if any(len(values) != 1 for values in form.values()):
            raise ValueError()
        data = json.loads(form["payload"][0]) if interactive else {key: value[0] for key, value in form.items()}
        if not isinstance(data, dict):
            raise ValueError()
        if interactive:
            team, user = data["team"]["id"], data["user"]["id"]
        else:
            team, user = data["team_id"], data["user_id"]
        if not isinstance(user, str) or not user or not isinstance(team, str):
            raise ValueError()
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise HTTPException(400, "malformed Slack payload") from None
    if team != runtime.config.team_id or data.get("api_app_id") != runtime.config.app_id:
        raise HTTPException(403, "Slack workspace or app is not allowed")
    if data.get("is_ext_shared_channel") is True or data.get("is_ext_shared_channel") == "true":
        raise HTTPException(403, "Slack Connect channels are not supported")
    return data, hashlib.sha256(raw).hexdigest()


def _notice(title: str, text: str) -> dict:
    return {"type": "modal", "title": {"type": "plain_text", "text": title[:24]},
            "close": {"type": "plain_text", "text": "닫기"},
            "blocks": [{"type": "section", "text": {"type": "plain_text", "text": text[:2900]}}]}


def _open(runtime: SlackRuntime, trigger: str, view: dict) -> dict:
    return runtime.client.call("views.open", {"trigger_id": trigger, "view": view})


def _update(runtime: SlackRuntime, view_id: str, view: dict) -> None:
    runtime.client.call("views.update", {"view_id": view_id, "view": view})


def _loading_view(runtime: SlackRuntime, data: dict) -> None:
    if not data.get("view"):
        # Exchange the short-lived trigger before listing rooms or analyzing.
        opened = _open(runtime, data["trigger_id"], _notice("불러오는 중", "잠시 기다려 주세요."))
        data["view"] = {"id": opened["view"]["id"]}


def _feedback(runtime: SlackRuntime, data: dict, text: str) -> None:
    if data.get("view", {}).get("id"):
        _update(runtime, data["view"]["id"], _notice("처리 결과", text))
    elif data.get("response_url"):
        runtime.client.respond(data["response_url"], {"text": text})
    else:
        user = data.get("user", {}).get("id") or data.get("user_id")
        channel = data.get("channel", {}).get("id") or data.get("channel_id")
        if channel:
            runtime.client.call("chat.postEphemeral", {"channel": channel, "user": user, "text": text})


def _job(runtime: SlackRuntime, receipt: str, data: dict, handler) -> None:
    """Lease retries without persisting the raw request, reasons, or webhook URLs."""
    key = f"SLACK#RECEIPT#{runtime.config.team_id}#{receipt}"
    acquired = None
    committed = False
    try:
        current = runtime.store.get(key)
        if current:
            if current.value.get("state") == "done":
                # A retry ACK replaces the modal with its loading view again.
                # Restore the saved completion without repeating domain or chat writes.
                if current.value.get("completion_view") and data.get("view", {}).get("id"):
                    _update(runtime, data["view"]["id"], current.value["completion_view"])
                return
            if current.value.get("lease", 0) > time.time():
                return
        version = current.version if current else None
        if not runtime.store.compare_and_swap(key, version,
                {"state": "running", "lease": int(time.time()) + 60}, int(time.time()) + 86400):
            return
        acquired = runtime.store.get(key)
        completion_view = handler(runtime, data)
        if acquired:
            committed = runtime.store.compare_and_swap(key, acquired.version,
                {"state": "done", "completion_view": completion_view}, int(time.time()) + 86400)
        # Delivery errors must not turn a committed operation into a replayable
        # failure (especially after a channel announcement was already posted).
        if completion_view:
            _update(runtime, data["view"]["id"], completion_view)
    except Exception as exc:
        # Body, token, Slack response URL, and anonymous rationale are never logged.
        logger.warning("Slack operation failed error=%s", type(exc).__name__)
        if acquired and not committed:
            try:
                runtime.store.compare_and_swap(key, acquired.version,
                    {"state": "failed", "lease": 0}, int(time.time()) + 86400)
            except Exception:
                pass
        if isinstance(exc, SlackDomainError):
            message = exc.message
        elif isinstance(exc, (ViewValidationError, ValueError)):
            message = "입력 내용을 확인한 뒤 다시 시도해 주세요."
        else:
            message = "일시적으로 처리하지 못했습니다. /synq rooms에서 상태를 확인하고 다시 시도해 주세요."
        try:
            _feedback(runtime, data, message)
        except Exception:
            logger.warning("Slack feedback delivery failed")


HELP = ("/synq create — 새 익명 방 만들기\n/synq join 코드 — 참여하고 평가하기\n"
        "/synq status 코드 — 제출 현황\n/synq results 코드 — 분석 결과\n"
        "/synq rooms — 내 방과 이전 결과\n/synq link — Google 계정 연결")


def _show_room(runtime: SlackRuntime, data: dict, team: str, user: str, channel: str,
               code: str, action: str) -> None:
    service = runtime.service
    code = code.upper()
    _loading_view(runtime, data)
    if action == "join":
        if data.get("view") and not channel:
            # History carries no channel. Only an already-authorized member may
            # recover the original channel; never infer access from the code.
            channel = service.get_room(team, user, code)["origin_channel"]
        summary = service.join_room(team, user, code, channel)
        if summary["status"] != "collecting" or summary.get("has_submitted"):
            history = service.get_history(team, user, code)
            view = result_view(summary, history["analysis"]) if history["analysis"] else _notice(
                "제출 현황", "이미 제출했거나 의견 수집이 종료됐습니다. 전원이 제출하면 분석 결과가 공개됩니다.")
            _update(runtime, data["view"]["id"], view)
            return
        internal = service.get_room(team, user, code)
        room = Room.model_validate(internal["room"])
        view = submission_view(room, _metadata(runtime, team, user, channel, code))
        _update(runtime, data["view"]["id"], view)
    else:
        history = service.get_history(team, user, code)
        summary = history["room"]
        if action == "results" and summary["is_complete"]:
            analysis = service.analysis(team, user, code)
            _update(runtime, data["view"]["id"], result_view(summary, analysis))
        elif action == "results":
            _update(runtime, data["view"]["id"], _notice("제출 대기", "전원이 제출하면 분석 결과가 공개됩니다."))
        else:
            _update(runtime, data["view"]["id"], _notice("제출 현황",
                f"{summary['question']}\n{summary['submission_count']} / {summary['expected_members']}명 제출\n"
                f"코드: {code}\n/synq join {code}로 평가할 수 있습니다."))


def _command(runtime: SlackRuntime, data: dict) -> None:
    team, user, channel = data["team_id"], data["user_id"], data.get("channel_id", "")
    parts = data.get("text", "").strip().split()
    command = parts[0].lower() if parts else "help"
    if command in {"create", "new"} and len(parts) == 1:
        _open(runtime, data["trigger_id"], create_room_view(_metadata(runtime, team, user, channel), runtime.config.retention_days))
    elif command == "rooms" and len(parts) == 1:
        _loading_view(runtime, data)
        _update(runtime, data["view"]["id"], history_view(runtime.service.list_rooms(team, user),
                                                       _metadata(runtime, team, user), runtime.config.retention_days))
    elif command == "link" and len(parts) == 1:
        token = runtime.service.create_link(team, user)
        url = runtime.config.public_base_url + "/slack/link#token=" + token
        runtime.client.respond(data["response_url"], {"text": "본인의 Google 계정에 연결합니다. 링크는 10분간 유효합니다.",
            "blocks": [{"type": "section", "text": {"type": "plain_text", "text": "본인의 Google 계정에 연결해 참여한 방과 이전 결과를 확인하세요. 링크는 10분간 유효합니다."}},
                       {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Google 계정 연결"}, "url": url, "action_id": "consensus_link_open"}]}]})
    elif command in {"join", "status", "results"} and len(parts) == 2:
        _show_room(runtime, data, team, user, channel, parts[1], command)
    else:
        runtime.client.respond(data["response_url"], {"text": HELP})


def _interaction(runtime: SlackRuntime, data: dict) -> dict | None:
    team, user = data["team"]["id"], data["user"]["id"]
    if data["type"] == "view_submission":
        view = data["view"]
        meta = _read_metadata(runtime, view["private_metadata"], team, user)
        values = view.get("state", {}).get("values", {})
        if view["callback_id"] == "consensus_create":
            summary = runtime.service.create_room(team, user, meta["channel"], parse_create(values), view["id"])
            # Commit first. If Slack delivery fails, /synq rooms recovers the room.
            runtime.client.call("chat.postMessage", {"channel": meta["channel"], **room_message(summary)})
            return _notice("방 생성 완료", f"방 코드: {summary['code']}\n채널의 참여 버튼으로 의견을 제출해 주세요.")
        else:
            internal = runtime.service.get_room(team, user, meta["code"])
            payload = parse_submission(values, Room.model_validate(internal["room"]))
            summary = runtime.service.submit(team, user, meta["code"], payload, view["id"])
            return _notice("제출 완료",
                f"{summary['submission_count']} / {summary['expected_members']}명 제출했습니다.\n"
                f"전원이 제출한 후 /synq results {summary['code']}로 결과를 확인하세요.")

    action = data["actions"][0]
    action_id, value = action.get("action_id", ""), action.get("value", "")
    if action_id == "consensus_link_open":
        return
    channel = data.get("channel", {}).get("id", "")
    if data.get("view"):
        meta = _read_metadata(runtime, data["view"].get("private_metadata", ""), team, user)
        channel = meta.get("channel", "")
    if action_id == "consensus_more":
        page = runtime.service.list_rooms(team, user, cursor=value)
        _update(runtime, data["view"]["id"], history_view(page, _metadata(runtime, team, user), runtime.config.retention_days))
    elif action_id in {"consensus_join", "consensus_status", "consensus_results"}:
        # Opening a fresh modal from a history modal is not supported by views.open;
        # replace the current view with read-only results or the submission form.
        if data.get("view") and action_id != "consensus_join":
            history = runtime.service.get_history(team, user, value)
            summary = history["room"]
            analysis = runtime.service.analysis(team, user, value) if summary["is_complete"] else None
            new_view = result_view(summary, analysis) if analysis else _notice("제출 현황", f"{summary['question']}\n{summary['submission_count']} / {summary['expected_members']}명 제출")
            _update(runtime, data["view"]["id"], new_view)
        else:
            _show_room(runtime, data, team, user, channel, value, action_id.removeprefix("consensus_"))


@router.post("/api/slack/commands", include_in_schema=False)
async def slack_commands(request: Request, background: BackgroundTasks):
    runtime = _runtime()
    data, receipt = await _payload(request, runtime, interactive=False)
    if data.get("command") != "/synq":
        raise HTTPException(400, "unsupported command")
    background.add_task(_job, runtime, receipt, data, _command)
    return JSONResponse({})


@router.post("/api/slack/interactions", include_in_schema=False)
async def slack_interactions(request: Request, background: BackgroundTasks):
    runtime = _runtime()
    data, receipt = await _payload(request, runtime, interactive=True)
    response: dict = {}
    if data.get("type") == "view_submission":
        view = data.get("view", {})
        if view.get("callback_id") not in {"consensus_create", "consensus_submit"}:
            raise HTTPException(400, "unsupported Slack form")
        _read_metadata(runtime, view.get("private_metadata", ""), data["team"]["id"], data["user"]["id"])
        if view["callback_id"] == "consensus_create":
            try:
                parse_create(view.get("state", {}).get("values", {}))
            except ViewValidationError as exc:
                return JSONResponse({"response_action": "errors", "errors": exc.errors})
        response = {"response_action": "update", "view": _notice("저장 중", "입력을 저장하고 있습니다. 잠시 기다려 주세요.")}
    elif data.get("type") != "block_actions" or not isinstance(data.get("actions"), list) or len(data["actions"]) != 1:
        raise HTTPException(400, "unsupported Slack interaction")
    background.add_task(_job, runtime, receipt, data, _interaction)
    return JSONResponse(response)


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=300)


def _user(request: Request):
    user = user_from_request(request)
    if user is None:
        raise HTTPException(401, "Google login is required")
    return user


def _domain_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SlackDomainError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/api/slack/link")
def link_account(request: Request, payload: LinkRequest):
    runtime = _runtime()
    user = _user(request)
    if request.headers.get("origin") != runtime.config.public_base_url:
        raise HTTPException(403, "same-origin account linking is required")
    return _domain_call(runtime.service.consume_link, payload.token, user.google_sub)


def _identity(request: Request, runtime: SlackRuntime) -> str:
    user = _user(request)
    slack_user = runtime.service.linked_identity(runtime.config.team_id, user.google_sub)
    if slack_user is None:
        raise HTTPException(403, "Connect Slack with /synq link first")
    return slack_user


@router.get("/api/slack/me/rooms")
def my_rooms(request: Request, limit: int = 20, cursor: str | None = None):
    runtime = _runtime()
    user = _identity(request, runtime)
    return JSONResponse(_domain_call(runtime.service.list_rooms, runtime.config.team_id, user,
                                     limit=limit, cursor=cursor), headers={"Cache-Control": "no-store"})


@router.get("/api/slack/me/rooms/{code}")
def my_room_history(request: Request, code: str):
    runtime = _runtime()
    user = _identity(request, runtime)
    result = _domain_call(runtime.service.get_history, runtime.config.team_id, user, code)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/slack/link", response_class=HTMLResponse, include_in_schema=False)
def account_page():
    nonce = secrets.token_urlsafe(24)
    page = Path(__file__).with_name("slack_link.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("__CSP_NONCE__", nonce), headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; "
            f"script-src 'nonce-{nonce}' https://accounts.google.com/gsi/client; "
            "style-src 'unsafe-inline' https://accounts.google.com; img-src 'self' https://*.googleusercontent.com data:; "
            "connect-src 'self' https://accounts.google.com; frame-src https://accounts.google.com; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    })
