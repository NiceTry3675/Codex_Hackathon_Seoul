"""Run one safe live smoke test for every optional OpenAI path."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.llm import (
    evaluate_defenses,
    generate_devils_advocate,
    parse_opinion,
    suggest_criteria,
)
from backend.models import ChallengerQuestion, DefenderAnswer, EvidenceSnapshot


def load_local_openai_config() -> None:
    """Load only known OpenAI settings from an ignored local .env file."""

    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    allowed = {"OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS"}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in allowed or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[name] = value


def main() -> None:
    load_local_openai_config()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not configured; inject it into the environment and retry"
        )

    options = ["A. AI 보안 도구", "B. 팀 의사결정 도구"]
    criteria = ["창의성", "구현 가능성", "발표 임팩트"]
    suggestions = suggest_criteria(
        "6시간 해커톤에서 어떤 아이디어를 만들까요?",
        options,
        criteria,
        "팀원은 네 명이고 발표 직후 심사가 있습니다.",
    )
    if suggestions is None:
        raise SystemExit("live criteria suggestion failed; inspect the sanitized backend log")

    opinion = parse_opinion(
        "A는 발표 임팩트가 크지만 구현 가능성이 걱정됩니다.",
        options,
        criteria,
    )
    if opinion is None:
        raise SystemExit("live opinion parsing failed; inspect the sanitized backend log")

    advocate = generate_devils_advocate(
        options[0],
        ["구현 가능성", f"{options[0]} / 구현 가능성"],
        ["구현 가능성"],
    )
    if advocate is None:
        raise SystemExit("live Devil's Advocate failed; inspect the sanitized backend log")

    snapshot = EvidenceSnapshot(
        id="snapshot-smoke",
        target=advocate.target,
        low_agreement=["구현 가능성"],
        concerns=["구현 가능성"],
    )
    questions = [
        ChallengerQuestion(
            sequence=index,
            challenge_id=f"c{index}",
            evidence_snapshot_id=snapshot.id,
            evidence_keys=["target", "low_agreement", "concerns"],
            question=question,
        )
        for index, question in enumerate(advocate.challenges, start=1)
    ]
    answers = [
        DefenderAnswer(
            challenge_id=question.challenge_id,
            status="open",
            unknowns="실서비스 조건에서 아직 검증되지 않았습니다.",
            mitigation="실서비스 스모크 테스트로 확인합니다.",
        )
        for question in questions
    ]
    resolutions = evaluate_defenses(snapshot, questions, answers)
    if resolutions is None:
        raise SystemExit("live defense review failed; inspect the sanitized backend log")

    print(
        json.dumps(
            {
                "status": "ok",
                "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
                "criteria_suggestion_count": len(suggestions),
                "parsed_preferred_option": opinion.preferred_option,
                "parsed_positive_count": len(opinion.positive),
                "parsed_concern_count": len(opinion.concerns),
                "devils_advocate_target": advocate.target,
                "devils_advocate_challenge_count": len(advocate.challenges),
                "defense_resolution_count": len(resolutions),
                "defense_resolutions": [item.resolution for item in resolutions],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("OpenAI smoke test interrupted", file=sys.stderr)
        raise SystemExit(130) from None
