"""FastAPI application for the Consensus hackathon MVP."""

from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path as ApiPath, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auth import (
    SESSION_COOKIE_NAME,
    AuthConfigurationError,
    GoogleVerificationUnavailable,
    InvalidGoogleCredential,
    auth_is_configured,
    create_session_token,
    google_client_id,
    session_cookie_secure,
    session_ttl_seconds,
    user_from_request,
    verify_google_credential,
)
from .debate import (
    append_defenses,
    build_evidence_snapshot,
    challenge_questions,
    fallback_resolutions,
    finish_debate,
    project_open_agenda,
    start_debate,
    validate_answers,
)
from .llm import (
    evaluate_defenses,
    fallback_criteria_suggestions,
    fallback_devils_advocate,
    generate_devils_advocate,
    parse_opinion,
    suggest_criteria,
)
from .models import (
    AnalysisResponse,
    AuthConfig,
    AuthState,
    CriteriaSuggestRequest,
    CriteriaSuggestResponse,
    DebateState,
    DecisionRecord,
    DecisionRecordCreate,
    DefenderTurnRequest,
    GoogleCredential,
    HealthResponse,
    LogoutResponse,
    Room,
    RoomCreate,
    RoomResponse,
    Submission,
    SubmissionCreate,
    SubmitResponse,
)
from .storage import RoomStore
from .stats import analyze_room


app = FastAPI(title="Consensus API", version="0.1.0")
logger = logging.getLogger(__name__)
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rooms: dict[str, Room] = {}
room_store = RoomStore(rooms)
rooms_lock = Lock()
room_analysis_locks: dict[str, Lock] = {}
ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _new_room_code() -> str:
    while True:
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(6))
        if room_store.get(code) is None:
            return code


def _get_room(code: str) -> Room:
    normalized = code.upper()
    room = room_store.get(normalized)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="room not found")
    return room


def _room_response(room: Room) -> RoomResponse:
    with rooms_lock:
        submission_count = len(room.submissions)
    return RoomResponse(
        code=room.code,
        question=room.question,
        options=room.options,
        criteria=room.criteria,
        context=room.context,
        expected_members=room.expected_members,
        submission_mode=room.submission_mode,
        participant_names=(
            [
                submission.participant_name
                for submission in room.submissions
                if submission.participant_name is not None
            ]
            if room.submission_mode == "named"
            else []
        ),
        submission_count=submission_count,
        is_complete=submission_count >= room.expected_members,
    )


def _require_exact_keys(
    actual: set[str],
    expected: list[str],
    field_name: str,
) -> None:
    expected_set = set(expected)
    if actual == expected_set:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": f"{field_name} keys must match the room definition",
            "missing": sorted(expected_set - actual),
            "unexpected": sorted(actual - expected_set),
        },
    )


def _get_devils_advocate(room: Room, result: dict) -> None:
    """Populate the optional qualitative review once per completed room."""

    with rooms_lock:
        generation_lock = room_analysis_locks.setdefault(room.code, Lock())

    with generation_lock:
        snapshot = build_evidence_snapshot(result, room.submissions)
        if room.devils_advocate_generated:
            if room.devils_advocate is not None:
                result["devils_advocate"] = room.devils_advocate
                if room.debate is None:
                    room.debate = start_debate(
                        snapshot,
                        room.devils_advocate,
                        room.devils_advocate_source or "fallback",
                    )
                    room_store.save(room)
            return

        try:
            room.devils_advocate = generate_devils_advocate(
                snapshot.target,
                snapshot.low_agreement,
                snapshot.concerns,
                snapshot.hidden_conflicts,
                snapshot.discussion_agenda,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected Devil's Advocate provider failure error=%s",
                type(exc).__name__,
            )
            room.devils_advocate = None

        if room.devils_advocate is None:
            room.devils_advocate = fallback_devils_advocate(
                snapshot.target,
                snapshot.low_agreement,
                snapshot.concerns,
            )
            room.devils_advocate_source = "fallback"
        else:
            room.devils_advocate_source = "live"

        room.debate = start_debate(
            snapshot,
            room.devils_advocate,
            room.devils_advocate_source,
        )
        room.devils_advocate_generated = True
        room_store.save(room)
        logger.info(
            "Devil's Advocate ready source=%s room=%s",
            room.devils_advocate_source,
            room.code,
        )
        result["devils_advocate"] = room.devils_advocate


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/auth/config", response_model=AuthConfig)
def get_auth_config() -> AuthConfig:
    client_id = google_client_id()
    return AuthConfig(
        enabled=auth_is_configured(),
        client_id=client_id,
    )


@app.post("/api/auth/google", response_model=AuthState)
def google_login(payload: GoogleCredential, response: Response) -> AuthState:
    try:
        user = verify_google_credential(payload.credential)
        session_token = create_session_token(user)
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except GoogleVerificationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except InvalidGoogleCredential as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return AuthState(authenticated=True, user=user)


@app.get("/api/auth/me", response_model=AuthState)
def get_current_user(request: Request) -> AuthState:
    user = user_from_request(request)
    return AuthState(authenticated=user is not None, user=user)


@app.post("/api/auth/logout", response_model=LogoutResponse)
def logout(response: Response) -> LogoutResponse:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return LogoutResponse()


@app.post("/api/criteria/suggestions", response_model=CriteriaSuggestResponse)
def suggest_room_criteria(payload: CriteriaSuggestRequest) -> CriteriaSuggestResponse:
    """Offer criteria the team may add; the team always makes the final pick."""

    try:
        suggestions = suggest_criteria(
            payload.question,
            payload.options,
            payload.existing_criteria,
            payload.context,
        )
    except Exception as exc:
        logger.warning(
            "Unexpected criteria suggestion provider failure error=%s",
            type(exc).__name__,
        )
        suggestions = None
    if suggestions is None:
        return CriteriaSuggestResponse(
            criteria=fallback_criteria_suggestions(payload.existing_criteria),
            source="fallback",
        )
    return CriteriaSuggestResponse(criteria=suggestions, source="live")


@app.post("/api/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(request: Request, payload: RoomCreate) -> RoomResponse:
    if payload.submission_mode == "named" and user_from_request(request) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication is required to create named rooms",
        )
    with rooms_lock:
        while True:
            code = _new_room_code()
            room = Room(code=code, submissions=[], **payload.model_dump())
            if room_store.create(room):
                break
        room_analysis_locks[code] = Lock()
    return _room_response(room)


@app.get("/api/rooms/{code}", response_model=RoomResponse)
def get_room(
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> RoomResponse:
    return _room_response(_get_room(code))


@app.post(
    "/api/rooms/{code}/submit",
    response_model=SubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_opinion(
    payload: SubmissionCreate,
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> SubmitResponse:
    room = _get_room(code)
    if len(room.submissions) >= room.expected_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="room is full",
        )
    if room.submission_mode == "named" and payload.participant_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="participant_name is required for named rooms",
        )
    if room.submission_mode == "anonymous" and payload.participant_name is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="participant_name must be omitted for anonymous rooms",
        )
    _require_exact_keys(set(payload.scores), room.options, "scores")
    _require_exact_keys(set(payload.weights), room.criteria, "weights")
    for option, criterion_scores in payload.scores.items():
        _require_exact_keys(set(criterion_scores), room.criteria, f"scores.{option}")
    if payload.first_choice not in room.options:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="first_choice must be one of the room options",
        )

    try:
        parsed = parse_opinion(payload.reason, room.options, room.criteria)
    except Exception as exc:
        logger.warning(
            "Unexpected opinion parser failure error=%s",
            type(exc).__name__,
        )
        parsed = None
    submission = Submission(
        id=str(uuid4()),
        parsed=parsed,
        **payload.model_dump(),
    )

    with rooms_lock:
        submission_lock = room_analysis_locks.setdefault(code.upper(), Lock())

    with submission_lock:
        room = _get_room(code)
        if len(room.submissions) >= room.expected_members:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="room is full",
            )

        if payload.participant_name is not None and any(
            item.participant_name == payload.participant_name for item in room.submissions
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="participant name already submitted",
            )

        room.submissions.append(submission)
        submission_count = len(room.submissions)
        room_store.save(room)
    return SubmitResponse(
        id=submission.id,
        submission_count=submission_count,
        expected_members=room.expected_members,
        is_complete=submission_count >= room.expected_members,
    )


@app.get(
    "/api/rooms/{code}/analysis",
    response_model=AnalysisResponse,
    response_model_exclude_none=True,
)
def get_analysis(
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> AnalysisResponse:
    room = _get_room(code)
    with rooms_lock:
        submission_count = len(room.submissions)
    if submission_count < room.expected_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="all expected members must submit before analysis",
        )

    try:
        result = analyze_room(room.submissions, room.options, room.criteria)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    _get_devils_advocate(room, result)
    for agenda_item in project_open_agenda(room.debate):
        if agenda_item not in result["discussion_agenda"]:
            result["discussion_agenda"].append(agenda_item)

    return AnalysisResponse.model_validate(result)


@app.get("/api/rooms/{code}/decision-record", response_model=DecisionRecord)
def get_decision_record(
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> DecisionRecord:
    room = _get_room(code)
    if room.decision_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="decision record not found",
        )
    return room.decision_record


@app.post(
    "/api/rooms/{code}/decision-record",
    response_model=DecisionRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_decision_record(
    payload: DecisionRecordCreate,
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> DecisionRecord:
    with rooms_lock:
        decision_lock = room_analysis_locks.setdefault(code.upper(), Lock())

    with decision_lock:
        room = _get_room(code)
        if room.decision_record is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="decision record already exists",
            )
        if len(room.submissions) < room.expected_members:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="all expected members must submit before recording a decision",
            )
        if payload.final_choice not in room.options:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="final_choice must be one of the room options",
            )

        result = analyze_room(room.submissions, room.options, room.criteria)
        initial_majority = max(
            room.options,
            key=lambda option: sum(
                submission.first_choice == option for submission in room.submissions
            ),
        )
        record = DecisionRecord(
            initial_majority_choice=initial_majority,
            analysis_winner=result["current_winner"],
            robust_choice=result["robust_choice"],
            final_choice=payload.final_choice,
            final_reason=payload.final_reason,
            decided_at=datetime.now(timezone.utc),
            changed_from_initial=payload.final_choice != initial_majority,
        )
        room.decision_record = record
        room_store.save(room)
        return record


@app.get("/api/rooms/{code}/debate", response_model=DebateState)
def get_debate(
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> DebateState:
    room = _get_room(code)
    if room.debate is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="analysis must be generated before the debate",
        )
    return room.debate


@app.post("/api/rooms/{code}/debate/defend", response_model=DebateState)
def defend_decision(
    payload: DefenderTurnRequest,
    code: str = ApiPath(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$"),
) -> DebateState:
    room = _get_room(code)
    with rooms_lock:
        debate_lock = room_analysis_locks.setdefault(room.code, Lock())

    with debate_lock:
        room = _get_room(code)
        if room.debate is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="analysis must be generated before the debate",
            )
        if room.debate.completed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="debate is already complete",
            )
        try:
            validate_answers(room.debate, payload.answers)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        questions = challenge_questions(room.debate)
        append_defenses(room.debate, payload.answers)
        try:
            resolutions = evaluate_defenses(
                room.debate.evidence_snapshot,
                questions,
                payload.answers,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected defense review provider failure error=%s",
                type(exc).__name__,
            )
            resolutions = None
        if resolutions is None:
            resolutions = fallback_resolutions(questions)
            source = "fallback"
        else:
            source = "live"
        finish_debate(room.debate, resolutions, source)
        room_store.save(room)
        return room.debate


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
