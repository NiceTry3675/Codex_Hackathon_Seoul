"""Validate a load_demo.py result against the presentation contract."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def validate_demo_result(payload: dict) -> str:
    analysis = payload["analysis"]
    option_a = "A. AI 보안 도구"
    option_b = "B. 팀 의사결정 도구"

    if analysis["current_winner"] != option_a:
        raise SystemExit("demo contract failed: current_winner must be option A")
    if analysis["robust_choice"] != option_b:
        raise SystemExit("demo contract failed: robust_choice must be option B")
    if not math.isclose(analysis["stability"][option_a], 0.474, abs_tol=0.001):
        raise SystemExit("demo contract failed: option A stability drifted")
    if not math.isclose(analysis["stability"][option_b], 0.526, abs_tol=0.001):
        raise SystemExit("demo contract failed: option B stability drifted")

    first_weight_flip = next(
        item for item in analysis["flip_points"] if item["type"] == "weight"
    )
    if first_weight_flip["criterion"] != "구현 가능성":
        raise SystemExit("demo contract failed: first weight flip criterion drifted")
    if not math.isclose(
        first_weight_flip["to"] - first_weight_flip["from"],
        0.01,
        abs_tol=0.0001,
    ):
        raise SystemExit("demo contract failed: first weight flip must be 1%p")

    advocate = analysis.get("devils_advocate")
    if not advocate or advocate.get("target") != option_a:
        raise SystemExit("demo contract failed: Devil's Advocate fallback/live result missing")
    if len(advocate.get("challenges", [])) not in (2, 3):
        raise SystemExit("demo contract failed: Devil's Advocate must have 2 or 3 challenges")

    return (
        "demo contract ok: "
        f"room={payload['room_code']} current=A robust=B stability=47.4/52.6 flip=1%p"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_demo_result.py RESULT.json")

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(validate_demo_result(payload))


if __name__ == "__main__":
    main()
