"""FastAPI application for the Consensus hackathon MVP."""

from __future__ import annotations

import logging
import secrets
import string
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path as ApiPath, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .llm import fallback_devils_advocate, generate_devils_advocate, parse_opinion
from .models import (
    AnalysisResponse,
    HealthResponse,
    Room,
    RoomCreate,
    RoomResponse,
    Submission,
    SubmissionCreate,
    SubmitResponse,
)
from .stats import analyze_room


app = FastAPI(title="Consensus API", version="0.1.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

rooms: dict[str, Room] = {}
rooms_lock = Lock()
room_analysis_locks: dict[str, Lock] = {}
ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _new_room_code() -> str:
    while True:
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(6))
        if code not in rooms:
            return code


def _get_room(code: str) -> Room:
    normalized = code.upper()
    with rooms_lock:
        room = rooms.get(normalized)
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
        expected_members=room.expected_members,
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
        if room.devils_advocate_generated:
            if room.devils_advocate is not None:
                result["devils_advocate"] = room.devils_advocate
            return

        low_agreement = [
            criterion
            for criterion, level in result.get("weight_agreement", {}).items()
            if level == "LOW"
        ]
        low_agreement.extend(
            f"{option} / {criterion}"
            for option, levels in result.get("score_agreement", {}).items()
            for criterion, level in levels.items()
            if level == "LOW"
        )
        concerns = [
            concern
            for submission in room.submissions
            if submission.parsed is not None
            for concern in submission.parsed.concerns
        ]
        try:
            room.devils_advocate = generate_devils_advocate(
                result.get("current_winner"),
                low_agreement,
                concerns,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected Devil's Advocate provider failure error=%s",
                type(exc).__name__,
            )
            room.devils_advocate = None

        if room.devils_advocate is None:
            room.devils_advocate = fallback_devils_advocate(
                result["current_winner"],
                low_agreement,
                concerns,
            )
            room.devils_advocate_source = "fallback"
        else:
            room.devils_advocate_source = "live"

        room.devils_advocate_generated = True
        logger.info(
            "Devil's Advocate ready source=%s room=%s",
            room.devils_advocate_source,
            room.code,
        )
        result["devils_advocate"] = room.devils_advocate


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/api/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(payload: RoomCreate) -> RoomResponse:
    with rooms_lock:
        code = _new_room_code()
        room = Room(code=code, submissions=[], **payload.model_dump())
        rooms[code] = room
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
    with rooms_lock:
        if len(room.submissions) >= room.expected_members:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="room is full",
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

    parsed = parse_opinion(payload.reason, room.options, room.criteria)
    submission = Submission(
        id=str(uuid4()),
        parsed=parsed,
        **payload.model_dump(),
    )
    with rooms_lock:
        if len(room.submissions) >= room.expected_members:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="room is full",
            )
        room.submissions.append(submission)
        submission_count = len(room.submissions)
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

    return AnalysisResponse.model_validate(result)


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
