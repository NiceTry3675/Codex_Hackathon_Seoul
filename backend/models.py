"""Pydantic models shared by the API, statistics, and optional LLM layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Score = Annotated[int, Field(ge=1, le=5)]
Weight = Annotated[int, Field(ge=1, le=100)]
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
    expires_in_hours: int = Field(default=24, ge=1, le=168, exclude=True)

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
    description: str = Field(default="이 기준에서 각 선택지가 얼마나 긍정적인지 평가합니다.", min_length=1, max_length=500)
    one_point: str = Field(default="매우 부정적", min_length=1, max_length=200)
    five_point: str = Field(default="매우 긍정적", min_length=1, max_length=200)


class OptionSuggestion(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    why: str = Field(min_length=1, max_length=500)


class OptionSuggestRequest(ApiModel):
    question: str = Field(min_length=1, max_length=500)
    existing_options: list[str] = Field(default_factory=list, max_length=10)
    context: str = Field(default="", max_length=CONTEXT_MAX_LENGTH)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return clean_question(value)

    @field_validator("context")
    @classmethod
    def strip_context(cls, value: str) -> str:
        return value.strip()

    @field_validator("existing_options")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        return clean_labels(values)


class OptionSuggestResponse(ApiModel):
    options: list[OptionSuggestion]
    source: Literal["live", "fallback"]


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


class AssistantMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class DecisionAssistantRequest(ApiModel):
    question: str = Field(default="", max_length=500)
    options: list[str] = Field(default_factory=list, max_length=10)
    criteria: list[str] = Field(default_factory=list, max_length=10)
    context: str = Field(default="", max_length=CONTEXT_MAX_LENGTH)
    messages: list[AssistantMessage] = Field(min_length=1, max_length=8)

    @field_validator("question", "context")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("options", "criteria")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        return clean_labels(values)


class DecisionAssistantResponse(ApiModel):
    message: str = Field(min_length=1, max_length=2_000)
    source: Literal["live", "fallback"]


class DecisionRecordCreate(ApiModel):
    final_choice: str = Field(min_length=1, max_length=200)
    final_reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("final_choice", "final_reason")
    @classmethod
    def strip_decision_text(cls, value: str) -> str:
        return value.strip()


class DecisionRecord(ApiModel):
    initial_majority_choice: str
    analysis_winner: str
    robust_choice: str
    final_choice: str
    final_reason: str
    decided_at: datetime
    changed_from_initial: bool


class Room(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    context: str = ""
    expected_members: int = 4
    submission_mode: SubmissionMode = "anonymous"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=24))
    version: int = Field(default=0, ge=0)
    used_anonymous_token_hashes: list[str] = Field(default_factory=list)
    submissions: list[Submission] = Field(default_factory=list)
    devils_advocate: DevilsAdvocate | None = None
    devils_advocate_generated: bool = False
    devils_advocate_source: Literal["live", "fallback"] | None = None
    debate: DebateState | None = None
    decision_record: DecisionRecord | None = None


class RoomResponse(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    context: str = ""
    expected_members: int
    submission_mode: SubmissionMode
    created_at: datetime
    expires_at: datetime
    participant_names: list[str] = Field(default_factory=list)
    submission_count: int
    is_complete: bool


class SubmitResponse(ApiModel):
    id: str
    submission_count: int
    expected_members: int
    is_complete: bool


class ParticipationTokenResponse(ApiModel):
    expires_at: datetime


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
