"""Pydantic models shared by the API, statistics, and optional LLM layer."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Score = Annotated[int, Field(ge=1, le=5)]
Weight = Annotated[int, Field(ge=1, le=10)]
AgreementLevel = Literal["HIGH", "MID", "LOW"]
SubmissionMode = Literal["anonymous", "named"]
DefenseStatus = Literal["mitigated", "open", "invalid"]
ChallengeResolution = Literal["resolved", "open", "reframed"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParsedOpinion(ApiModel):
    preferred_option: str
    positive: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class SubmissionCreate(ApiModel):
    participant_name: str | None = Field(default=None, max_length=100)
    scores: dict[str, dict[str, Score]]
    weights: dict[str, Weight]
    first_choice: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2_000)

    @field_validator("first_choice", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("participant_name")
    @classmethod
    def strip_participant_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class Submission(SubmissionCreate):
    id: str
    parsed: ParsedOpinion | None = None


class DevilsAdvocate(ApiModel):
    target: str
    challenges: list[str] = Field(min_length=2, max_length=3)


class EvidenceSnapshot(ApiModel):
    id: str
    target: str
    low_agreement: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    hidden_conflicts: list[str] = Field(default_factory=list)
    discussion_agenda: list[str] = Field(default_factory=list)


class ChallengerQuestion(ApiModel):
    sequence: int = Field(ge=1)
    challenge_id: str
    turn: Literal[1] = 1
    role: Literal["challenger"] = "challenger"
    evidence_snapshot_id: str
    evidence_keys: list[str]
    question: str


class DefenderAnswer(ApiModel):
    challenge_id: str = Field(min_length=1, max_length=20)
    status: DefenseStatus
    evidence: str = Field(default="", max_length=2_000)
    unknowns: str = Field(default="", max_length=2_000)
    mitigation: str = Field(default="", max_length=2_000)

    @field_validator("challenge_id", "evidence", "unknowns", "mitigation")
    @classmethod
    def strip_defense_text(cls, value: str) -> str:
        return value.strip()


class DefenderTurnRequest(ApiModel):
    answers: list[DefenderAnswer] = Field(min_length=2, max_length=3)


class DefenderMessage(DefenderAnswer):
    sequence: int = Field(ge=1)
    turn: Literal[1] = 1
    role: Literal["defender"] = "defender"
    evidence_snapshot_id: str
    evidence_keys: list[str]


class DefenseResolution(ApiModel):
    challenge_id: str
    resolution: ChallengeResolution
    reason: str
    reframed_question: str | None = None


class ChallengerResolutionMessage(DefenseResolution):
    sequence: int = Field(ge=1)
    turn: Literal[2] = 2
    role: Literal["challenger"] = "challenger"
    evidence_snapshot_id: str
    evidence_keys: list[str]


DebateMessage = ChallengerQuestion | DefenderMessage | ChallengerResolutionMessage


class DebateState(ApiModel):
    evidence_snapshot: EvidenceSnapshot
    messages: list[DebateMessage] = Field(default_factory=list)
    completed: bool = False
    challenger_source: Literal["live", "fallback"]
    resolution_source: Literal["live", "fallback"] | None = None


CONTEXT_MAX_LENGTH = 50_000


def clean_labels(values: list[str]) -> list[str]:
    """Shared option/criteria label rules: stripped, non-blank, short, unique."""

    cleaned = [value.strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError("labels must not be blank")
    if any(len(value) > 200 for value in cleaned):
        raise ValueError("labels must contain at most 200 characters")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("labels must be unique")
    return cleaned


def clean_question(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("question must not be blank")
    return value


class RoomCreate(ApiModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=10)
    criteria: list[str] = Field(min_length=1, max_length=10)
    context: str = Field(default="", max_length=CONTEXT_MAX_LENGTH)
    expected_members: int = Field(default=4, ge=1, le=100)
    submission_mode: SubmissionMode = "anonymous"

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return clean_question(value)

    @field_validator("context")
    @classmethod
    def strip_context(cls, value: str) -> str:
        return value.strip()

    @field_validator("options", "criteria")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        return clean_labels(values)


class CriterionSuggestion(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    why: str = Field(min_length=1, max_length=500)


class CriteriaSuggestRequest(ApiModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=10)
    existing_criteria: list[str] = Field(default_factory=list, max_length=10)
    context: str = Field(default="", max_length=CONTEXT_MAX_LENGTH)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return clean_question(value)

    @field_validator("context")
    @classmethod
    def strip_context(cls, value: str) -> str:
        return value.strip()

    @field_validator("options", "existing_criteria")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        return clean_labels(values)


class CriteriaSuggestResponse(ApiModel):
    criteria: list[CriterionSuggestion]
    source: Literal["live", "fallback"]


class Room(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    context: str = ""
    expected_members: int = 4
    submission_mode: SubmissionMode = "anonymous"
    submissions: list[Submission] = Field(default_factory=list)
    devils_advocate: DevilsAdvocate | None = None
    devils_advocate_generated: bool = False
    devils_advocate_source: Literal["live", "fallback"] | None = None
    debate: DebateState | None = None


class RoomResponse(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    context: str = ""
    expected_members: int
    submission_mode: SubmissionMode
    participant_names: list[str] = Field(default_factory=list)
    submission_count: int
    is_complete: bool


class SubmitResponse(ApiModel):
    id: str
    submission_count: int
    expected_members: int
    is_complete: bool


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"


class GoogleCredential(ApiModel):
    credential: str = Field(min_length=1, max_length=10_000)


class AuthUser(ApiModel):
    google_sub: str
    email: str
    name: str
    picture: str | None = None


class AuthState(ApiModel):
    authenticated: bool
    user: AuthUser | None = None


class AuthConfig(ApiModel):
    enabled: bool
    client_id: str | None = None


class LogoutResponse(ApiModel):
    ok: Literal[True] = True


class AnalysisResponse(ApiModel):
    vote_share: dict[str, float] = Field(default_factory=dict)
    team_weights: dict[str, float] = Field(default_factory=dict)
    weight_agreement: dict[str, AgreementLevel] = Field(default_factory=dict)
    score_agreement: dict[str, dict[str, AgreementLevel]] = Field(default_factory=dict)
    option_scores: dict[str, float] = Field(default_factory=dict)
    mean_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    hidden_conflicts: list[str] = Field(default_factory=list)
    stability: dict[str, float] = Field(default_factory=dict)
    current_winner: str | None = None
    robust_choice: str | None = None
    flip_points: list[dict[str, Any]] = Field(default_factory=list)
    discussion_agenda: list[str] = Field(default_factory=list)
    devils_advocate: DevilsAdvocate | None = None
