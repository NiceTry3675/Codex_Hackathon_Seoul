"""Pydantic models shared by the API, statistics, and optional LLM layer."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Score = Annotated[int, Field(ge=1, le=5)]
Weight = Annotated[int, Field(ge=1, le=10)]
AgreementLevel = Literal["HIGH", "MID", "LOW"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParsedOpinion(ApiModel):
    preferred_option: str
    positive: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class SubmissionCreate(ApiModel):
    scores: dict[str, dict[str, Score]]
    weights: dict[str, Weight]
    first_choice: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2_000)

    @field_validator("first_choice", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class Submission(SubmissionCreate):
    id: str
    parsed: ParsedOpinion | None = None


class DevilsAdvocate(ApiModel):
    target: str
    challenges: list[str]


class RoomCreate(ApiModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=10)
    criteria: list[str] = Field(min_length=1, max_length=10)
    expected_members: int = Field(default=4, ge=1, le=100)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value

    @field_validator("options", "criteria")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("labels must not be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("labels must be unique")
        return cleaned


class Room(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    expected_members: int = 4
    submissions: list[Submission] = Field(default_factory=list)
    devils_advocate: DevilsAdvocate | None = None
    devils_advocate_generated: bool = False


class RoomResponse(ApiModel):
    code: str
    question: str
    options: list[str]
    criteria: list[str]
    expected_members: int
    submission_count: int
    is_complete: bool


class SubmitResponse(ApiModel):
    id: str
    submission_count: int
    expected_members: int
    is_complete: bool


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"


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
