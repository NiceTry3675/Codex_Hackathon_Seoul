"""Single-workspace Slack commands; existing web/API remains the decision UI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request as UrlRequest, build_opener

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from .models import Room, SlackOrigin
from .llm import suggest_thread_decision
from .slack_threads import ThreadReference, parse_thread_link, read_thread
from .slack_views import CREATE_CALLBACK, creation_modal, parse_submission, status_modal

logger = logging.getLogger(__name__)
_seen: dict[str, float] = {}
_seen_lock = Lock()
HELP = (
    "SynQ · 결정 전 점검\n"
    "/synq new — 슬랙에서 결정 만들기 · 전원 제출 시 자동 알림\n"
    "/synq from 스레드링크 — 해당 스레드 텍스트를 AI로 보내 초안 추천 후 직접 확인\n"
    "/synq share 방코드 — 이 채널에 참여 링크 공유\n"
    "/synq result 방코드 — 이 채널에 분석 요약 공유\n"
    "/synq record 방코드 — 이 채널에 저장된 최종 결정 공유\n"
    "share/result/record는 채널 구성원에게 공개됩니다."
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SlackAPIError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in {"missing_scope", "not_in_channel", "channel_not_found",
                                     "thread_not_found", "ratelimited", "not_allowed_token_type"} else "slack_error"
        super().__init__(self.code)


def parse_slack_response(raw: bytes) -> dict:
    if raw == b"ok":
        return {"ok": True}
    result = json.loads(raw)
    if not isinstance(result, dict) or not result.get("ok"):
        error = result.get("error") if isinstance(result, dict) else "slack_error"
        raise SlackAPIError(error if isinstance(error, str) else "slack_error")
    return result


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = UrlRequest(url, data=json.dumps(payload).encode(), headers=headers)
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        raw = response.read(128_000)
    return parse_slack_response(raw)


def get_thread_page(channel: str, timestamp: str, cursor: str, token: str) -> dict:
    query = urlencode({"channel": channel, "ts": timestamp, "limit": 15, "cursor": cursor})
    request = UrlRequest("https://slack.com/api/conversations.replies?" + query,
                         headers={"Authorization": f"Bearer {token}"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            return parse_slack_response(response.read(1_000_000))
    except HTTPError as exc:
        if exc.code == 429:
            raise SlackAPIError("ratelimited") from None
        raise


def private_message(text: str, blocks: list | None = None) -> dict:
    result = {"response_type": "ephemeral", "text": text, "mrkdwn": False}
    if blocks:
        result["blocks"] = blocks
    return result


def section(text: str) -> dict:
    return {"type": "section", "text": {"type": "plain_text", "text": text[:2800]}}


def web_link(base: str, label: str, code: str = "", view: str = "create") -> dict:
    query = {"view": view}
    if code:
        query["room"] = code
    # Only server-configured origins and validated room codes enter mrkdwn.
    url = f"{base}/?{urlencode(query)}"
    return {"type": "section", "text": {"type": "mrkdwn", "text": f"<{url}|{label}>"}}


def configuration() -> tuple[str, str, str, str]:
    names = ("SLACK_SIGNING_SECRET", "SLACK_BOT_TOKEN", "SLACK_TEAM_ID", "SYNQ_PUBLIC_URL")
    secret, token, team, base = (os.getenv(name, "").strip() for name in names)
    try:
        parsed = urlsplit(base)
    except ValueError:
        raise HTTPException(503, "Slack integration is not configured") from None
    if not all((secret, token, team, base)) or (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/") or any(c in base for c in "<>|\r\n")
    ):
        raise HTTPException(503, "Slack integration is not configured")
    return secret, token, team, base.rstrip("/")


def verify(body: bytes, request: Request, secret: str) -> None:
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError
    except ValueError:
        raise HTTPException(401, "Invalid Slack timestamp") from None
    expected = "v0=" + hmac.new(
        secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    supplied = request.headers.get("x-slack-signature", "")
    if not hmac.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(401, "Invalid Slack signature")


def valid_response_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https" and parsed.netloc == "hooks.slack.com"
        and parsed.path.startswith("/commands/") and not parsed.fragment
    )


async def signed_form(request: Request, secret: str) -> dict:
    body = await request.body()
    if len(body) > 262_144:
        raise HTTPException(413, "Slack request too large")
    verify(body, request, secret)
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=40)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid Slack form") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, "Duplicate Slack fields")
    return {key: values[0] for key, values in fields.items()}


def claim_request(key: str) -> bool:
    with _seen_lock:
        now = time.time()
        for expired in [item for item, deadline in _seen.items() if deadline <= now]:
            del _seen[expired]
        if key in _seen:
            return False
        if len(_seen) >= 10_000:
            raise HTTPException(503, "Slack request capacity reached")
        _seen[key] = now + 600
        return True


def post_to_channel(channel: str, code: str, blocks: list, token: str) -> dict:
    return post_json("https://slack.com/api/chat.postMessage", {
        "channel": channel, "text": f"SynQ · {code} · 결정 점검",
        "blocks": blocks, "mrkdwn": False, "parse": "none",
        "unfurl_links": False, "unfurl_media": False,
    }, token)


def participation_blocks(room: Room, base: str) -> list:
    return [section(f"{room.question}\n참여 코드: {room.code}"),
            section(f"평가 제출 {len(room.submissions)}/{room.expected_members}명\n"
                    "각자 웹에서 평가해주세요. 개인 점수와 의견은 채널에 게시하지 않습니다."),
            web_link(base, "평가 참여", room.code, "submit")]


def notify_submissions_complete(room: Room) -> None:
    """Only the successful final append schedules this; Slack failure cannot undo submission."""
    if room.slack_origin is None or len(room.submissions) != room.expected_members:
        return
    try:
        _, token, team, base = configuration()
        if room.slack_origin.team_id != team:
            return
        post_to_channel(room.slack_origin.channel_id, room.code, [
            section(f"평가 제출이 완료됐습니다 · {room.expected_members}/{room.expected_members}명\n{room.question}"),
            web_link(base, "결과 확인", room.code, "results"),
            section(f"채널에 분석 요약을 공유하려면 /synq result {room.code}를 실행해주세요."),
        ], token)
    except Exception as exc:
        logger.warning("Slack completion notification failed room=%s error=%s", room.code, type(exc).__name__)


def build_router(get_room, get_analysis, get_record, create_room=None) -> APIRouter:
    router = APIRouter(prefix="/api/slack", tags=["slack"])

    def deliver(action: str, code: str, channel: str, response_url: str, token: str, base: str):
        try:
            room = get_room(code)
            blocks = [section(f"{room.question}\n참여 코드: {room.code}")]
            if action == "share":
                blocks = participation_blocks(room, base)
            elif action == "result":
                if len(room.submissions) < room.expected_members:
                    raise HTTPException(409, "incomplete")
                result = get_analysis(code)
                blocks.append(section(f"현재 평가 1위: {result.current_winner}"))
                if result.hidden_conflicts:
                    blocks.append(section("평가가 갈린 기준\n" + "\n".join(result.hidden_conflicts[:3])))
                if result.devils_advocate:
                    blocks.append(section("결정 전 확인 질문\n" + "\n".join(result.devils_advocate.challenges[:3])))
                blocks.append(web_link(base, "분석 상세와 결과가 바뀌는 조건 확인", code, "results"))
            else:
                record = get_record(code)
                blocks += [section(f"최종 선택: {record.final_choice}\n결정 이유: {record.final_reason}"),
                           web_link(base, "결정 기록 확인", code, "results")]
            post_to_channel(channel, room.code, blocks, token)
        except HTTPException as exc:
            message = ("평가가 모두 모인 후 결과를 공유할 수 있습니다." if exc.status_code == 409
                       else "결정 또는 저장된 기록을 찾지 못했습니다. 방 코드와 만료 여부를 확인해주세요.")
            notify_failure(response_url, message)
        except Exception as exc:
            logger.warning("Slack delivery failed error=%s", type(exc).__name__)
            notify_failure(response_url, "공유 완료를 확인하지 못했습니다. 채널을 확인하고, 게시되지 않았다면 다시 실행해주세요.")

    def notify_failure(url: str, message: str):
        try:
            post_json(url, private_message(message))
        except Exception as exc:
            logger.warning("Slack error notification failed error=%s", type(exc).__name__)

    @router.post("/commands")
    async def commands(request: Request, background_tasks: BackgroundTasks):
        secret, token, team, base = configuration()
        data = await signed_form(request, secret)
        if data.get("team_id") != team:
            raise HTTPException(403, "Slack workspace not allowed")
        if data.get("command") != "/synq":
            return private_message(HELP)
        parts = data.get("text", "").split(maxsplit=1)
        if not parts or parts == ["help"]:
            return private_message(HELP, [section(HELP), web_link(base, "결정 만들기")])
        if parts == ["new"] or (len(parts) == 2 and parts[0] == "from"):
            if create_room is None:
                return private_message("결정 만들기를 사용할 수 없습니다.")
            channel = data.get("channel_id", "")
            response_url = data.get("response_url", "")
            trigger = data.get("trigger_id", "")
            if not re.fullmatch(r"[CGD][A-Z0-9]+", channel) or not valid_response_url(response_url) or not trigger:
                raise HTTPException(400, "Missing Slack modal context")
            reference = None
            if parts[0] == "from":
                try:
                    reference = parse_thread_link(parts[1], channel)
                except ValueError:
                    return private_message("현재 채널에 있는 스레드의 메시지 링크를 넣어주세요. /synq from 스레드링크")
            if claim_request(request.headers["x-slack-signature"]):
                background_tasks.add_task(open_creation_modal, trigger, team, channel, response_url, token, reference)
            return Response(status_code=200)
        if len(parts) != 2 or parts[0] not in {"share", "result", "record"} or not re.fullmatch(r"[A-Za-z0-9]{6}", parts[1]):
            return private_message(HELP)
        response_url = data.get("response_url", "")
        channel = data.get("channel_id", "")
        if not valid_response_url(response_url) or not re.fullmatch(r"[CGD][A-Z0-9]+", channel):
            raise HTTPException(400, "Invalid Slack response destination")
        # Suppress duplicate deliveries within one process for the signed request window.
        # A durable queue/idempotency store is needed before multi-instance rollout.
        if not claim_request(request.headers["x-slack-signature"]):
            return private_message("이미 접수한 요청입니다. 채널에서 결과를 확인해주세요.")
        background_tasks.add_task(deliver, parts[0], parts[1].upper(), channel, response_url, token, base)
        return private_message("공유 요청을 접수했습니다. 처리가 끝나면 이 채널에 게시합니다.")

    def open_creation_modal(trigger: str, team: str, channel: str, response_url: str, token: str,
                            reference: ThreadReference | None = None):
        try:
            view = (creation_modal(team, channel) if reference is None else
                    status_modal("지정한 스레드의 텍스트를 AI로 보내 질문·선택지·판단 기준 초안을 만들고 있습니다. "
                                 "초안을 확인하고 만들기를 눌러야 결정이 생성됩니다."))
            opened = post_json("https://slack.com/api/views.open", {
                "trigger_id": trigger, "view": view,
            }, token)
        except Exception as exc:
            logger.warning("Slack modal open failed error=%s", type(exc).__name__)
            notify_failure(response_url, "입력 창을 열지 못했습니다. /synq new를 다시 실행해주세요.")
            return
        if reference is not None:
            try:
                view_id = opened["view"]["id"]
                populate_thread_draft(reference, team, channel, view_id, token)
            except Exception as exc:
                logger.warning("Slack draft display failed error=%s", type(exc).__name__)
                notify_failure(response_url, "초안을 표시하지 못했습니다. 잠시 후 다시 실행하거나 /synq new로 직접 입력해주세요.")

    def populate_thread_draft(reference: ThreadReference, team: str, channel: str, view_id: str, token: str):
        draft = None
        try:
            thread = read_thread(reference, lambda channel, ts, cursor: get_thread_page(channel, ts, cursor, token))
            draft = suggest_thread_decision(thread.messages, thread.partial)
            coverage = f"스레드 텍스트 {len(thread.messages)}건 반영 · 파일과 봇 메시지 제외."
            if thread.partial:
                coverage += " 긴 스레드의 일부만 읽었습니다. 빠진 논의가 있는지 원문을 확인해주세요."
            if draft is None:
                notice = coverage + " AI 초안을 만들지 못했습니다. 원문을 참고해 직접 입력해주세요."
            else:
                notice = coverage + " AI가 제안한 초안입니다. 내용과 배경을 수정·확인한 뒤 만들기를 눌러주세요."
        except SlackAPIError as exc:
            notices = {
                "missing_scope": "스레드를 읽을 권한이 없습니다. 앱의 대화 조회 권한을 추가하고 재설치해주세요.",
                "ratelimited": "슬랙 조회 제한에 걸렸습니다. 잠시 후 다시 시도하거나 직접 입력해주세요.",
                "not_allowed_token_type": "현재 토큰으로 스레드를 조회할 수 없습니다. 앱 인증 설정을 확인해주세요.",
            }
            notice = notices.get(exc.code, "스레드를 읽지 못했습니다. 봇의 채널 참여 여부와 링크를 확인해주세요.")
        except Exception as exc:
            logger.warning("Slack thread draft failed error=%s", type(exc).__name__)
            notice = "스레드 추천을 완료하지 못했습니다. 원문을 확인하고 직접 입력해주세요."
        view = creation_modal(team, channel, draft, notice, reference.permalink)
        post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": view}, token)

    def finish_creation(payload, origin: SlackOrigin, view_id: str, token: str, base: str):
        room = None
        try:
            room = create_room(payload, origin)
            post_to_channel(origin.channel_id, room.code, participation_blocks(room, base), token)
            view = status_modal(f"결정을 만들고 이 채널에 평가 링크를 게시했습니다. 참여 코드: {room.code}",
                                [web_link(base, "평가 참여", room.code, "submit")])
        except Exception as exc:
            logger.warning("Slack room creation failed error=%s", type(exc).__name__)
            if room is not None:
                view = status_modal(f"결정은 저장됐지만 채널 게시 완료를 확인하지 못했습니다. 참여 코드: {room.code}\n"
                                    f"채널에 링크가 없다면 /synq share {room.code}를 실행해주세요.",
                                    [web_link(base, "평가 참여", room.code, "submit")])
            else:
                view = status_modal("결정 저장을 확인하지 못했습니다. 잠시 후 /synq new를 다시 실행해주세요.")
        try:
            post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": view}, token)
        except Exception as exc:
            logger.warning("Slack creation status update failed error=%s", type(exc).__name__)

    @router.post("/interactions")
    async def interactions(request: Request, background_tasks: BackgroundTasks):
        secret, token, team, base = configuration()
        data = await signed_form(request, secret)
        try:
            payload = json.loads(data["payload"])
            if not isinstance(payload, dict) or not isinstance(payload.get("team"), dict):
                raise ValueError
            if payload["team"].get("id") != team:
                raise HTTPException(403, "Slack workspace not allowed")
            view = payload.get("view")
            if payload.get("type") != "view_submission" or not isinstance(view, dict) or view.get("callback_id") != CREATE_CALLBACK:
                raise ValueError
            origin = SlackOrigin.model_validate_json(view["private_metadata"])
            view_id = view["id"]
            if origin.team_id != team or not isinstance(view_id, str) or not re.fullmatch(r"V[A-Z0-9]+", view_id):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise HTTPException(400, "Invalid Slack interaction") from None
        if create_room is None:
            raise HTTPException(503, "Slack creation unavailable")
        room_payload, errors = parse_submission(view)
        if errors:
            return {"response_action": "errors", "errors": errors}
        if claim_request(f"create:{team}:{view_id}"):
            background_tasks.add_task(finish_creation, room_payload, origin, view_id, token, base)
            return {"response_action": "update", "view": status_modal("결정을 저장하고 있습니다. 완료 후 이 창과 채널에서 확인할 수 있습니다.")}
        # Do not overwrite a previously completed view on a retry.
        return Response(status_code=200)

    return router
