import pytest

from backend.stats import analyze_room


def _submission(scores, weights, first_choice, parsed=None):
    return {
        "scores": scores,
        "weights": weights,
        "first_choice": first_choice,
        "parsed": parsed,
    }


def test_hand_calculated_scores_weights_and_agreement():
    submissions = [
        _submission(
            {"A": {"quality": 5, "speed": 1}, "B": {"quality": 1, "speed": 4}},
            {"quality": 3, "speed": 1},
            "A",
        ),
        _submission(
            {"A": {"quality": 3, "speed": 1}, "B": {"quality": 1, "speed": 2}},
            {"quality": 1, "speed": 3},
            "B",
        ),
    ]

    result = analyze_room(submissions, ["A", "B"], ["quality", "speed"])

    assert result["team_weights"] == pytest.approx({"quality": 0.5, "speed": 0.5})
    assert result["option_scores"] == pytest.approx({"A": 2.5, "B": 2.0})
    assert result["current_winner"] == "A"
    assert result["vote_share"] == {"A": 0.5, "B": 0.5}
    assert result["weight_agreement"] == {"quality": "MID", "speed": "MID"}
    assert result["score_agreement"]["A"] == {"quality": "MID", "speed": "HIGH"}


def test_stability_is_reproducible_and_sums_to_one():
    submissions = [
        _submission(
            {"A": {"c1": 5, "c2": 1}, "B": {"c1": 1, "c2": 5}},
            {"c1": 5, "c2": 5},
            "A",
        )
    ]

    first = analyze_room(submissions, ["A", "B"], ["c1", "c2"], seed=7)
    second = analyze_room(submissions, ["A", "B"], ["c1", "c2"], seed=7)

    assert first["stability"] == second["stability"]
    assert sum(first["stability"].values()) == pytest.approx(1.0)
    assert first["current_winner"] == "A"  # exact score tie: option order wins
    assert first["robust_choice"] == max(
        ["A", "B"], key=lambda option: first["stability"][option]
    )


def test_weight_flip_uses_one_percentage_point_steps():
    submissions = [
        _submission(
            {"A": {"quality": 5, "cost": 1}, "B": {"quality": 1, "cost": 5}},
            {"quality": 6, "cost": 4},
            "A",
        )
    ]

    result = analyze_room(submissions, ["A", "B"], ["quality", "cost"])
    cost_flip = next(
        item
        for item in result["flip_points"]
        if item["type"] == "weight" and item["criterion"] == "cost"
    )

    assert cost_flip == {
        "type": "weight",
        "criterion": "cost",
        "from": 0.4,
        "to": 0.51,
        "new_winner": "B",
    }


def test_member_removal_and_hidden_conflict_are_descriptive():
    member_flip = analyze_room(
        [
            _submission({"A": {"value": 5}, "B": {"value": 1}}, {"value": 1}, "A"),
            _submission({"A": {"value": 1}, "B": {"value": 4}}, {"value": 1}, "B"),
        ],
        ["A", "B"],
        ["value"],
    )
    assert any(item["type"] == "member" for item in member_flip["flip_points"])

    conflict = analyze_room(
        [
            _submission({"A": {"risk": 5}, "B": {"risk": 1}}, {"risk": 1}, "A"),
            _submission({"A": {"risk": 1}, "B": {"risk": 1}}, {"risk": 1}, "A"),
            _submission({"A": {"risk": 3}, "B": {"risk": 2}}, {"risk": 1}, "B"),
        ],
        ["A", "B"],
        ["risk"],
    )
    assert conflict["score_agreement"]["A"]["risk"] == "LOW"
    assert "평가는 크게 갈립니다" in conflict["hidden_conflicts"][0]


def test_empty_room_is_rejected_explicitly():
    with pytest.raises(ValueError, match="at least one submission"):
        analyze_room([], ["A", "B"], ["quality"])
