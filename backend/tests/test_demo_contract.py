import json
from pathlib import Path

import pytest

from backend.stats import analyze_room


ROOT = Path(__file__).resolve().parents[2]


def test_demo_data_matches_the_presentation_story():
    data = json.loads((ROOT / "demo_data.json").read_text(encoding="utf-8"))
    room = data["room"]

    result = analyze_room(
        data["submissions"],
        room["options"],
        room["criteria"],
    )

    option_a, option_b, _option_c = room["options"]
    assert result["vote_share"] == {
        option_a: 0.75,
        option_b: 0.25,
        _option_c: 0.0,
    }
    assert result["current_winner"] == option_a
    assert result["robust_choice"] == option_b
    assert result["stability"][option_a] == pytest.approx(0.474)
    assert result["stability"][option_b] == pytest.approx(0.526)
    assert result["weight_agreement"]["구현 가능성"] == "LOW"
    assert result["score_agreement"][option_a]["구현 가능성"] == "LOW"
    assert result["hidden_conflicts"]

    first_weight_flip = next(
        item for item in result["flip_points"] if item["type"] == "weight"
    )
    assert first_weight_flip["criterion"] == "구현 가능성"
    assert first_weight_flip["new_winner"] == option_b
    assert first_weight_flip["to"] - first_weight_flip["from"] == pytest.approx(0.01)
