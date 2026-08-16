"""Deterministic orchestration around the optional Devil's Advocate calls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from .models import (
    ChallengerQuestion,
    ChallengerResolutionMessage,
    DebateState,
    DefenderAnswer,
    DefenderMessage,
    DefenseResolution,
    DevilsAdvocate,
    EvidenceSnapshot,
    Submission,
)


EVIDENCE_KEYS = [
    "target",
    "low_agreement",
    "concerns",
    "hidden_conflicts",
    "discussion_agenda",
]


def build_evidence_snapshot(
    result: dict[str, Any],
    submissions: Sequence[Submission],
) -> EvidenceSnapshot:
    """Freeze only allow-listed categorical and deterministic evidence."""

    target = result.get("current_winner")
    if not isinstance(target, str) or not target:
        raise ValueError("current_winner is required for adversarial review")

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
        for submission in submissions
        if submission.parsed is not None
        for concern in submission.parsed.concerns
    ]
    evidence = {
        "target": target,
        "low_agreement": low_agreement,
        "concerns": concerns,
        "hidden_conflicts": list(result.get("hidden_conflicts", [])),
        "discussion_agenda": list(result.get("discussion_agenda", [])),
    }
    canonical = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    snapshot_id = f"snapshot-{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"
    return EvidenceSnapshot(id=snapshot_id, **evidence)


def start_debate(
    snapshot: EvidenceSnapshot,
    advocate: DevilsAdvocate,
    source: str,
) -> DebateState:
    """Wrap generated questions in immutable orchestration metadata."""

    if advocate.target != snapshot.target:
        raise ValueError("Devil's Advocate target must match the evidence snapshot")
    questions = [
        ChallengerQuestion(
            sequence=index,
            challenge_id=f"c{index}",
            evidence_snapshot_id=snapshot.id,
            evidence_keys=EVIDENCE_KEYS.copy(),
            question=question,
        )
        for index, question in enumerate(advocate.challenges, start=1)
    ]
    return DebateState(
        evidence_snapshot=snapshot,
        messages=questions,
        challenger_source=source,
    )


def challenge_questions(debate: DebateState) -> list[ChallengerQuestion]:
    return [message for message in debate.messages if isinstance(message, ChallengerQuestion)]


def validate_answers(
    debate: DebateState,
    answers: Sequence[DefenderAnswer],
) -> None:
    expected = {message.challenge_id for message in challenge_questions(debate)}
    actual = [answer.challenge_id for answer in answers]
    if len(actual) != len(set(actual)):
        raise ValueError("each challenge_id must be answered once")
    if set(actual) != expected:
        raise ValueError("answers must match every challenge_id")


def append_defenses(
    debate: DebateState,
    answers: Sequence[DefenderAnswer],
) -> None:
    """Append validated human responses without changing prior messages."""

    validate_answers(debate, answers)
    by_id = {answer.challenge_id: answer for answer in answers}
    for question in challenge_questions(debate):
        answer = by_id[question.challenge_id]
        debate.messages.append(
            DefenderMessage(
                sequence=len(debate.messages) + 1,
                evidence_snapshot_id=debate.evidence_snapshot.id,
                evidence_keys=question.evidence_keys.copy(),
                **answer.model_dump(),
            )
        )


def fallback_resolutions(
    questions: Sequence[ChallengerQuestion],
) -> list[DefenseResolution]:
    """Fail closed: unresolved model checks remain open discussion items."""

    return [
        DefenseResolution(
            challenge_id=question.challenge_id,
            resolution="open",
            reason="검증 판정을 확인할 수 없어 이 쟁점은 열린 상태로 유지됩니다.",
        )
        for question in questions
    ]


def finish_debate(
    debate: DebateState,
    resolutions: Sequence[DefenseResolution],
    source: str,
) -> None:
    """Append the Challenger verdicts and close the two-round transcript."""

    questions = challenge_questions(debate)
    expected = {question.challenge_id for question in questions}
    actual = [resolution.challenge_id for resolution in resolutions]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("resolutions must match every challenge_id")

    question_by_id = {question.challenge_id: question for question in questions}
    for resolution in resolutions:
        question = question_by_id[resolution.challenge_id]
        debate.messages.append(
            ChallengerResolutionMessage(
                sequence=len(debate.messages) + 1,
                evidence_snapshot_id=debate.evidence_snapshot.id,
                evidence_keys=question.evidence_keys.copy(),
                **resolution.model_dump(),
            )
        )
    debate.completed = True
    debate.resolution_source = source


def project_open_agenda(debate: DebateState | None) -> list[str]:
    """Return only open or reframed Round 2 outcomes for the public agenda."""

    if debate is None or not debate.completed:
        return []
    projected: list[str] = []
    questions = {
        message.challenge_id: message.question
        for message in challenge_questions(debate)
    }
    for message in debate.messages:
        if not isinstance(message, ChallengerResolutionMessage):
            continue
        if message.resolution == "open":
            projected.append(questions[message.challenge_id])
        elif message.resolution == "reframed" and message.reframed_question:
            projected.append(message.reframed_question)
    return projected
