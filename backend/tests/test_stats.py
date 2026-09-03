import pytest

from backend.stats import allocate_percentages, analyze_room, rebalance_percentages


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
    assert sum(result["team_weights"].values()) == pytest.approx(1.0)
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
        "change": 0.11,
        "direction": "increase",
        "proximity": "nearby",
        "new_winner": "B",
    }


def test_weight_rebalancing_is_exact_proportional_and_deterministic():
    assert allocate_percentages([1, 1, 1]).tolist() == [34, 33, 33]
    assert rebalance_percentages([50, 30, 20], 0, 70).tolist() == [70, 18, 12]
    assert rebalance_percentages([100, 0, 0], 0, 50).tolist() == [50, 25, 25]
    assert rebalance_percentages([1], 0, 1).tolist() == [100]


def test_weight_flip_searches_both_directions_and_classifies_distance():
    nearby = analyze_room(
        [
            _submission(
                {"A": {"quality": 5, "cost": 1}, "B": {"quality": 1, "cost": 5}},
                {"quality": 6, "cost": 4},
                "A",
            )
        ],
        ["A", "B"],
        ["quality", "cost"],
    )
    weight_flips = [item for item in nearby["flip_points"] if item["type"] == "weight"]
    assert {item["direction"] for item in weight_flips} == {"increase", "decrease"}
    assert all(item["proximity"] == "nearby" for item in weight_flips)

    theoretical = analyze_room(
        [
            _submission(
                {"A": {"quality": 5, "cost": 1}, "B": {"quality": 1, "cost": 3}},
                {"quality": 8, "cost": 2},
                "A",
            )
        ],
        ["A", "B"],
        ["quality", "cost"],
    )
    theoretical_flips = [
        item for item in theoretical["flip_points"] if item["type"] == "weight"
    ]
    assert theoretical_flips
    assert all(item["proximity"] == "theoretical" for item in theoretical_flips)
    assert theoretical["discussion_agenda"][0] == (
        "현재 결과는 평가 기준의 중요도가 달라져도 비교적 안정적입니다."
    )


def test_single_criterion_has_exact_weight_and_no_weight_flip():
    result = analyze_room(
        [_submission({"A": {"value": 5}, "B": {"value": 1}}, {"value": 9}, "A")],
        ["A", "B"],
        ["value"],
    )
    assert result["team_weights"] == {"value": 1.0}
    assert not any(item["type"] == "weight" for item in result["flip_points"])


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


def test_weight_override_recalculates_winner_and_flip_points():
    submissions = [
        _submission(
            {"A": {"quality": 5, "cost": 1}, "B": {"quality": 1, "cost": 5}},
            {"quality": 6, "cost": 4},
            "A",
        )
    ]

    result = analyze_room(
        submissions,
        ["A", "B"],
        ["quality", "cost"],
        weight_override={"quality": 40, "cost": 60},
    )

    assert result["team_weights"] == pytest.approx({"quality": 0.4, "cost": 0.6})
    assert result["current_winner"] == "B"
    assert result["flip_points"]
