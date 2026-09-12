"""Slack commands and modals sharing the existing web rooms and analysis."""

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
from .slack_identity import identity_hash, read_metadata, sign_metadata
from .slack_eval_views import (ViewValidationError, submission_view, parse_evaluation,
    result_view, history_view, status_view, room_actions, supports_native)
from .slack_store import SlackStore

logger = logging.getLogger(__name__)
_seen: dict[str, float] = {}
_seen_lock = Lock()
_receipt_store = None
HELP = (
    "SynQ · 결정 전 점검\n"
    "/synq new — 슬랙에서 결정 만들기 · 전원 제출 시 자동 알림\n"
    "/synq from 스레드링크 — 해당 스레드 텍스트를 AI로 보내 초안 추천 후 직접 확인\n"
    "/synq join 방코드 — Slack에서 평가 제출\n"
    "/synq status 방코드 · /synq results 방코드 — 나에게 현황·분석 표시\n"
    "/synq rooms — 내 기록 · /synq link — Google 계정 연결\n"
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
    with build_opener(NoRedirect()).open(request, timeout=2 if url.endswith("views.open") else 10) as response:
        raw = response.read(128_001)
    if len(raw) > 128_000:
        raise SlackAPIError("slack_error")
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
    base = base or os.getenv("SLACK_PUBLIC_BASE_URL", "").strip()
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
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 262_144:
            raise HTTPException(413, "Slack request too large")
    body = bytes(chunks)
    verify(body, request, secret)
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=40)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid Slack form") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, "Duplicate Slack fields")
    return {key: values[0] for key, values in fields.items()}


def claim_durable_request(key: str) -> bool:
    # Background workers persist delivery receipts across instances. This is
    # duplicate suppression, not a durable job queue.
    global _receipt_store
    if os.getenv("CONSENSUS_TABLE_NAME", "").strip():
        if _receipt_store is None:
            _receipt_store = SlackStore()
        receipt = "SLACK#RECEIPT#" + hashlib.sha256(key.encode()).hexdigest()
        if _receipt_store.get(receipt) is not None:
            return False
        return _receipt_store.compare_and_swap(receipt, None, {"accepted": True}, int(time.time()) + 600)
    return True


def claim_request(key: str) -> bool:
    """Fast admission only: never wait for DynamoDB before Slack ACK."""
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
                    "Slack 또는 웹에서 평가해주세요. 개인 점수와 의견은 채널에 게시하지 않습니다."),
            *room_actions(room.code), web_link(base, "웹에서 평가 참여", room.code, "submit")]


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


def build_router(get_room, get_analysis, get_record, create_room=None, *,
                 submit_room=None, accounts=None, remember_room=None) -> APIRouter:
    router = APIRouter(prefix="/api/slack", tags=["slack"])

    def deliver(action: str, code: str, channel: str, response_url: str, token: str, base: str, receipt: str):
        try:
            if not claim_durable_request(receipt):
                return
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

    def check_app(data: dict) -> None:
        app_id = os.getenv("SLACK_APP_ID", "").strip()
        if app_id and data.get("api_app_id") != app_id:
            raise HTTPException(403, "Slack app not allowed")
        if data.get("is_ext_shared_channel") in (True, "true", "1"):
            raise HTTPException(403, "Slack Connect channels are not supported")

    def user_id(data: dict, interactive: bool = False) -> str:
        value = data.get("user", {}).get("id", "") if interactive else data.get("user_id", "")
        if not isinstance(value, str) or not re.fullmatch(r"[UW][A-Z0-9]+", value):
            raise HTTPException(400, "Missing Slack user")
        return value

    def scoped_room(code: str, team: str) -> Room:
        room = get_room(code)
        if room.slack_origin is not None and room.slack_origin.team_id != team:
            raise HTTPException(404, "room not found")
        return room

    def private_error(exc: Exception) -> str:
        status = getattr(exc, "status", getattr(exc, "status_code", None))
        if status == 404:
            return "방이 만료됐거나 접근할 수 없습니다. 방 코드와 내 기록을 확인해주세요."
        if status == 409:
            return "이미 제출했거나 정원이 찼습니다. 분석은 전원 제출 후 확인할 수 있습니다."
        return "요청을 완료하지 못했습니다. 잠시 후 다시 실행해주세요."

    def open_private(action: str, code: str, trigger: str, team: str, user: str,
                     channel: str, token: str, base: str, response_url: str = "", existing_view_id: str | None = None):
        view_id = existing_view_id
        try:
            loading = status_modal("불러오는 중입니다. 잠시 기다려주세요.")
            if view_id:
                post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": loading}, token)
            else:
                opened = post_json("https://slack.com/api/views.open", {
                    "trigger_id": trigger, "view": loading,
                }, token)
                view_id = opened["view"]["id"]
            metadata = sign_metadata(configuration()[0], team, user, channel, code)
            if action in {"rooms", "history_more"}:
                page = accounts().list_rooms(team, user, cursor=code or None)
                view = history_view(page, metadata)
            elif action == "history_room":
                history = accounts().get_history(team, user, code)
                view = (result_view(history["room"], history["analysis"], metadata)
                        if history["analysis"] else status_view(history["room"], metadata))
                if history.get("decision_record"):
                    record = history["decision_record"]
                    view["blocks"].append(section(f"최종 선택: {record['final_choice']}\n결정 이유: {record['final_reason']}"))
                if history["room"].get("web_available"):
                    view["blocks"].append(web_link(base, "같은 방 웹에서 열기", code, "results"))
            else:
                room = scoped_room(code, team)
                if action == "join":
                    if identity_hash(team, user, code) in room.used_anonymous_token_hashes:
                        view = status_modal("이 Slack 계정으로 이미 제출했습니다.",
                                            [web_link(base, "웹에서 결과 확인", code, "results")])
                    elif len(room.submissions) >= room.expected_members:
                        view = status_view(room, metadata)
                    elif supports_native(room):
                        # Opening and cancelling a form never mutates membership or capacity.
                        view = submission_view(room, metadata)
                    else:
                        view = status_modal("이 방은 선택지·기준 수, 긴 이름 또는 실명 설정에 맞춰 웹에서 평가해주세요. "
                            "Google 계정을 Slack과 연결하면 웹 제출도 같은 계정의 기록에 남습니다.",
                            [web_link(base, "웹에서 평가 참여", code, "submit")])
                elif action == "results":
                    view = result_view(room, get_analysis(code), metadata)
                else:
                    view = status_view(room, metadata)
                view["blocks"].append(web_link(base, "같은 방 웹에서 열기", code,
                                               "submit" if action == "join" else "results"))
            post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": view}, token)
        except Exception as exc:
            logger.warning("Slack private view failed error=%s", type(exc).__name__)
            if view_id:
                try:
                    post_json("https://slack.com/api/views.update", {
                        "view_id": view_id, "view": status_modal(private_error(exc)),
                    }, token)
                except Exception:
                    pass
            elif response_url:
                notify_failure(response_url, "창을 열지 못했습니다. 명령어를 다시 실행해주세요.")

    def send_link(team: str, user: str, response_url: str, base: str):
        try:
            link = accounts().create_link(team, user)
            post_json(response_url, private_message("Google 계정 연결 · 본인만 사용할 수 있는 10분 링크", [
                {"type": "section", "text": {"type": "mrkdwn", "text":
                    f"<{base}/slack/link#token={link}|Google 계정 연결 확인하기>"}},
                section("본인 Google 계정으로 로그인하고 연결을 확인해주세요. Slack 신원은 중복 제출 방지와 개인 기록에 사용합니다."),
            ]))
        except Exception as exc:
            logger.warning("Slack link failed error=%s", type(exc).__name__)
            notify_failure(response_url, "계정 연결 링크를 만들지 못했습니다. 다시 실행해주세요.")

    def finish_evaluation(code: str, values: dict, team: str, user: str, view_id: str, token: str, base: str):
        try:
            room = scoped_room(code, team)
            payload = parse_evaluation(values, room)
            result = submit_room(code, payload, team, user, view_id)
            view = status_modal(f"의견을 저장했습니다. {result.submission_count}/{result.expected_members}명 제출. "
                                "내 기록은 /synq rooms에서 확인할 수 있습니다.",
                                [web_link(base, "같은 방 결과 확인", code, "results")])
        except ViewValidationError:
            view = status_modal("입력이 유효하지 않습니다. /synq join 방코드로 다시 열어주세요.")
        except Exception as exc:
            logger.warning("Slack evaluation failed error=%s", type(exc).__name__)
            view = status_modal(private_error(exc))
        try:
            post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": view}, token)
        except Exception as exc:
            logger.warning("Slack evaluation status failed error=%s", type(exc).__name__)

    @router.post("/commands")
    async def commands(request: Request, background_tasks: BackgroundTasks):
        secret, token, team, base = configuration()
        data = await signed_form(request, secret)
        if data.get("team_id") != team:
            raise HTTPException(403, "Slack workspace not allowed")
        check_app(data)
        if data.get("command") != "/synq":
            return private_message(HELP)
        parts = data.get("text", "").split(maxsplit=1)
        if not parts or parts == ["help"]:
            return private_message(HELP, [section(HELP), web_link(base, "결정 만들기")])
        if parts and parts[0] in {"join", "status", "results", "rooms", "link"}:
            action = parts[0]
            if accounts is None or submit_room is None:
                return private_message("Slack 평가와 기록을 사용할 수 없습니다.")
            if ((action in {"rooms", "link"} and len(parts) != 1) or
                    (action not in {"rooms", "link"} and (len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9]{6}", parts[1])))):
                return private_message(HELP)
            user = user_id(data)
            channel, trigger, response_url = (data.get(key, "") for key in ("channel_id", "trigger_id", "response_url"))
            if not re.fullmatch(r"[CGD][A-Z0-9]+", channel) or not valid_response_url(response_url) or (action != "link" and not trigger):
                raise HTTPException(400, "Missing Slack modal context")
            if claim_request(request.headers["x-slack-signature"]):
                if action == "link":
                    background_tasks.add_task(send_link, team, user, response_url, base)
                else:
                    background_tasks.add_task(open_private, action, parts[1].upper() if len(parts) > 1 else "",
                                              trigger, team, user, channel, token, base, response_url)
            return Response(status_code=200)
        if parts in (["new"], ["create"]) or (len(parts) == 2 and parts[0] == "from"):
            if create_room is None:
                return private_message("결정 만들기를 사용할 수 없습니다.")
            channel = data.get("channel_id", "")
            response_url = data.get("response_url", "")
            trigger = data.get("trigger_id", "")
            if not re.fullmatch(r"[CGD][A-Z0-9]+", channel) or not valid_response_url(response_url) or not trigger:
                raise HTTPException(400, "Missing Slack modal context")
            user = user_id(data)
            reference = None
            if parts[0] == "from":
                try:
                    reference = parse_thread_link(parts[1], channel)
                except ValueError:
                    return private_message("현재 채널에 있는 스레드의 메시지 링크를 넣어주세요. /synq from 스레드링크")
            if claim_request(request.headers["x-slack-signature"]):
                background_tasks.add_task(open_creation_modal, trigger, team, channel, response_url, token, reference, user)
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
        background_tasks.add_task(deliver, parts[0], parts[1].upper(), channel, response_url, token, base, request.headers["x-slack-signature"])
        return private_message("공유 요청을 접수했습니다. 처리가 끝나면 이 채널에 게시합니다.")

    def open_creation_modal(trigger: str, team: str, channel: str, response_url: str, token: str,
                            reference: ThreadReference | None = None, user: str = ""):
        try:
            view = (creation_modal(team, channel) if reference is None else
                    status_modal("지정한 스레드의 텍스트를 AI로 보내 질문·선택지·판단 기준 초안을 만들고 있습니다. "
                                 "초안을 확인하고 만들기를 눌러야 결정이 생성됩니다."))
            view["private_metadata"] = sign_metadata(configuration()[0], team, user, channel)
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
                populate_thread_draft(reference, team, channel, view_id, token, user)
            except Exception as exc:
                logger.warning("Slack draft display failed error=%s", type(exc).__name__)
                notify_failure(response_url, "초안을 표시하지 못했습니다. 잠시 후 다시 실행하거나 /synq new로 직접 입력해주세요.")

    def populate_thread_draft(reference: ThreadReference, team: str, channel: str, view_id: str, token: str, user: str):
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
        view["private_metadata"] = sign_metadata(configuration()[0], team, user, channel)
        post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": view}, token)

    def finish_creation(payload, origin: SlackOrigin, view_id: str, token: str, base: str, user: str):
        room = None
        try:
            if not claim_durable_request(f"create:{origin.team_id}:{view_id}"):
                post_json("https://slack.com/api/views.update", {"view_id": view_id, "view": status_modal(
                    "이미 접수한 생성 요청입니다. 채널 또는 /synq rooms에서 확인해주세요.")}, token)
                return
            room = create_room(payload, origin, request_id=view_id)
            if remember_room is not None:
                remember_room(room, origin.team_id, user)
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
            check_app(payload)
            user = user_id(payload, True)
            if payload.get("type") == "block_actions":
                actions = payload.get("actions")
                if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
                    raise ValueError
                action = actions[0].get("action_id", "")
                mapping = {"synq_join": "join", "synq_status": "status", "synq_results": "results",
                           "synq_history_more": "history_more", "synq_history_room": "history_room"}
                if action not in mapping or accounts is None or submit_room is None:
                    raise ValueError
                value = actions[0].get("value", "")
                view = payload.get("view")
                if view:
                    metadata = read_metadata(secret, view.get("private_metadata", ""), team, user)
                    channel = metadata["channel"]
                else:
                    channel = payload.get("channel", {}).get("id", "")
                if not re.fullmatch(r"[CGD][A-Z0-9]+", channel) or not payload.get("trigger_id"):
                    raise ValueError
                if not isinstance(value, str) or (action != "synq_history_more" and not re.fullmatch(r"[A-Z0-9]{6}", value)):
                    raise ValueError
                if claim_request(request.headers["x-slack-signature"]):
                    background_tasks.add_task(open_private, mapping[action], value, payload["trigger_id"],
                                              team, user, channel, token, base, "", view.get("id") if view else None)
                return Response(status_code=200)
            view = payload.get("view")
            if payload.get("type") != "view_submission" or not isinstance(view, dict):
                raise ValueError
            metadata = read_metadata(secret, view.get("private_metadata", ""), team, user)
            origin = SlackOrigin(team_id=metadata["team"], channel_id=metadata["channel"])
            view_id = view["id"]
            if not isinstance(view_id, str) or not re.fullmatch(r"V[A-Z0-9]+", view_id):
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(400, "Invalid Slack interaction") from None
        if view.get("callback_id") == "synq_evaluate":
            if submit_room is None:
                raise HTTPException(503, "Slack submission unavailable")
            code = metadata.get("code", "")
            if not re.fullmatch(r"[A-Z0-9]{6}", code):
                raise HTTPException(400, "Invalid room code")
            state = view.get("state")
            values = state.get("values", {}) if isinstance(state, dict) else {}
            # The signed Slack form is ACKed before database/AI work. Capacity is
            # committed only by the same atomic append as web submissions.
            background_tasks.add_task(finish_evaluation, code, values, team, user, view_id, token, base)
            return {"response_action": "update", "view": status_modal("의견을 저장하고 있습니다. 잠시 기다려주세요.")}
        if view.get("callback_id") != CREATE_CALLBACK:
            raise HTTPException(400, "Invalid Slack callback")
        if create_room is None:
            raise HTTPException(503, "Slack creation unavailable")
        room_payload, errors = parse_submission(view)
        if errors:
            return {"response_action": "errors", "errors": errors}
        if claim_request(f"create:{team}:{view_id}"):
            background_tasks.add_task(finish_creation, room_payload, origin, view_id, token, base, user)
            return {"response_action": "update", "view": status_modal("결정을 저장하고 있습니다. 완료 후 이 창과 채널에서 확인할 수 있습니다.")}
        return Response(status_code=200)

    return router
