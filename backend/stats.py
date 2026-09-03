"""Small, deterministic statistics engine for the Consensus MVP.

The public entry point deliberately accepts plain dictionaries as well as model
objects.  This keeps the statistics layer independent from FastAPI/Pydantic and
makes it easy to test with hand-written fixtures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


N_SIMULATIONS = 1_000
DIRICHLET_CONCENTRATION = 50.0
AGREEMENT_HIGH_MAX = 0.8
AGREEMENT_MID_MAX = 1.5
WEIGHT_TOTAL_PERCENT = 100
WEIGHT_MIN_PERCENT = 1
NEARBY_FLIP_THRESHOLD_PERCENT = 15


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _agreement(values: np.ndarray) -> str:
    standard_deviation = float(np.std(values))
    if standard_deviation <= AGREEMENT_HIGH_MAX:
        return "HIGH"
    if standard_deviation <= AGREEMENT_MID_MAX:
        return "MID"
    return "LOW"


def _winner(option_scores: np.ndarray) -> int:
    """Return the first option on a tie, matching the configured option order."""

    return int(np.argmax(option_scores))


def _normalise(weights: np.ndarray) -> np.ndarray:
    total = float(np.sum(weights))
    if total <= 0:
        return np.full(len(weights), 1.0 / len(weights))
    return weights / total


def allocate_percentages(
    values: Sequence[float],
    total: int = WEIGHT_TOTAL_PERCENT,
    minimum: int = WEIGHT_MIN_PERCENT,
) -> np.ndarray:
    """Use largest remainders and stable input order to produce an exact total."""

    source = np.asarray(values, dtype=float)
    if source.ndim != 1 or len(source) == 0:
        raise ValueError("at least one weight is required")
    if len(source) * minimum > total:
        raise ValueError("minimum allocation exceeds total")
    if not np.all(np.isfinite(source)) or np.any(source < 0):
        raise ValueError("weights must be finite and non-negative")

    budget = total - len(source) * minimum
    value_total = float(np.sum(source))
    shares = (
        source / value_total * budget
        if value_total > 0
        else np.full(len(source), budget / len(source))
    )
    floors = np.floor(shares).astype(int)
    remainder = budget - int(np.sum(floors))
    order = sorted(
        range(len(source)),
        key=lambda index: (-(shares[index] - floors[index]), index),
    )
    for index in order[:remainder]:
        floors[index] += 1
    return floors + minimum


def rebalance_percentages(
    current: Sequence[float],
    changed_index: int,
    requested_value: int,
) -> np.ndarray:
    """Fix one integer percentage and redistribute the remainder proportionally."""

    values = np.asarray(current, dtype=float)
    if values.ndim != 1 or not 0 <= changed_index < len(values):
        raise ValueError("changed weight is not present")
    if len(values) == 1:
        return np.array([WEIGHT_TOTAL_PERCENT], dtype=int)

    maximum = WEIGHT_TOTAL_PERCENT - WEIGHT_MIN_PERCENT * (len(values) - 1)
    changed = max(WEIGHT_MIN_PERCENT, min(maximum, round(requested_value)))
    other_indices = [index for index in range(len(values)) if index != changed_index]
    others = allocate_percentages(
        values[other_indices],
        total=WEIGHT_TOTAL_PERCENT - changed,
        minimum=WEIGHT_MIN_PERCENT,
    )
    result = np.empty(len(values), dtype=int)
    result[changed_index] = changed
    result[other_indices] = others
    return result


def _read_submissions(
    submissions: Sequence[Any], options: list[str], criteria: list[str]
) -> tuple[np.ndarray, np.ndarray, list[str], list[Any]]:
    weights = np.empty((len(submissions), len(criteria)), dtype=float)
    scores = np.empty((len(submissions), len(options), len(criteria)), dtype=float)
    first_choices: list[str] = []
    parsed: list[Any] = []

    for member_index, submission in enumerate(submissions):
        member_weights = _field(submission, "weights")
        member_scores = _field(submission, "scores")
        first_choice = _field(submission, "first_choice")
        if not isinstance(member_weights, Mapping) or not isinstance(member_scores, Mapping):
            raise ValueError(f"submission {member_index} must contain weights and scores")
        if first_choice not in options:
            raise ValueError(f"submission {member_index} has an unknown first_choice")

        try:
            weights[member_index] = [float(member_weights[item]) for item in criteria]
            for option_index, option in enumerate(options):
                option_scores = member_scores[option]
                scores[member_index, option_index] = [
                    float(option_scores[item]) for item in criteria
                ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"submission {member_index} does not cover every option and criterion"
            ) from exc

        first_choices.append(first_choice)
        parsed.append(_field(submission, "parsed"))

    if not np.all(np.isfinite(weights)) or not np.all(np.isfinite(scores)):
        raise ValueError("weights and scores must be finite numbers")
    if np.any(weights < 0):
        raise ValueError("weights cannot be negative")

    return weights, scores, first_choices, parsed


def _weight_flip_points(
    team_percentages: np.ndarray,
    mean_scores: np.ndarray,
    options: list[str],
    criteria: list[str],
    current_winner_index: int,
) -> list[dict[str, Any]]:
    flips: list[dict[str, Any]] = []

    for criterion_index, criterion in enumerate(criteria):
        original = int(team_percentages[criterion_index])
        maximum = WEIGHT_TOTAL_PERCENT - WEIGHT_MIN_PERCENT * (len(criteria) - 1)
        for direction in (-1, 1):
            boundary = WEIGHT_MIN_PERCENT if direction < 0 else maximum
            for percentage_points in range(1, abs(boundary - original) + 1):
                target = original + direction * percentage_points
                candidate_percentages = rebalance_percentages(
                    team_percentages,
                    criterion_index,
                    target,
                )
                candidate = candidate_percentages / WEIGHT_TOTAL_PERCENT
                new_winner_index = _winner(mean_scores @ candidate)
                if new_winner_index != current_winner_index:
                    flips.append(
                        {
                            "type": "weight",
                            "criterion": criterion,
                            "from": original / WEIGHT_TOTAL_PERCENT,
                            "to": target / WEIGHT_TOTAL_PERCENT,
                            "change": percentage_points / WEIGHT_TOTAL_PERCENT,
                            "direction": "decrease" if direction < 0 else "increase",
                            "proximity": (
                                "nearby"
                                if percentage_points <= NEARBY_FLIP_THRESHOLD_PERCENT
                                else "theoretical"
                            ),
                            "new_winner": options[new_winner_index],
                        }
                    )
                    break

    # The closest flip is the most useful discussion item. Criteria and direction
    # order make ties deterministic.
    criterion_order = {criterion: index for index, criterion in enumerate(criteria)}
    flips.sort(
        key=lambda item: (
            item["change"],
            criterion_order[item["criterion"]],
            item["direction"] != "decrease",
        )
    )
    return flips


def _member_flip(
    weights: np.ndarray,
    scores: np.ndarray,
    options: list[str],
    current_winner_index: int,
) -> dict[str, Any] | None:
    if len(weights) <= 1:
        return None

    for removed_index in range(len(weights)):
        remaining_weights = np.delete(weights, removed_index, axis=0)
        remaining_scores = np.delete(scores, removed_index, axis=0)
        candidate_weights = _normalise(np.mean(remaining_weights, axis=0))
        candidate_scores = np.mean(remaining_scores, axis=0) @ candidate_weights
        new_winner_index = _winner(candidate_scores)
        if new_winner_index != current_winner_index:
            return {
                "type": "member",
                "members": 1,
                "new_winner": options[new_winner_index],
                "description": (
                    f"1명의 의견을 제외하면 결과가 {options[new_winner_index]}(으)로 바뀜"
                ),
            }

    # A first-choice-only edit cannot change this score-based winner. Richer member
    # counterfactuals can be added after the MVP has a defined score-editing rule.
    return None


def _hidden_conflicts(
    winner: str,
    winner_index: int,
    first_choices: list[str],
    score_agreement: dict[str, dict[str, str]],
    parsed: list[Any],
    criteria: list[str],
) -> tuple[list[str], list[str]]:
    if first_choices.count(winner) <= len(first_choices) / 2:
        return [], []

    conflicts: list[str] = []
    agenda: list[str] = []
    low_criteria = [
        criterion
        for criterion in criteria
        if score_agreement[winner][criterion] == "LOW"
    ]
    for criterion in low_criteria:
        conflicts.append(
            f"{winner}은(는) 1순위 다수 선택이지만 {criterion} 평가는 크게 갈립니다."
        )
        agenda.append(f"{winner}의 {criterion} 평가가 갈리는 근거를 확인하세요.")

    concern_counts = {criterion: 0 for criterion in criteria}
    for opinion in parsed:
        concerns = _field(opinion, "concerns") if opinion is not None else None
        if not isinstance(concerns, Sequence) or isinstance(concerns, (str, bytes)):
            continue
        for criterion in set(concerns):
            if criterion in concern_counts:
                concern_counts[criterion] += 1

    for criterion, count in concern_counts.items():
        if count > len(parsed) / 2 and criterion not in low_criteria:
            conflicts.append(f"{winner} 관련 의견에서 {criterion} 우려가 반복됩니다.")
            agenda.append(f"{winner}의 {criterion} 우려에 대한 대응책을 확인하세요.")

    return conflicts, agenda


def analyze_room(
    submissions: Sequence[Any],
    options: Sequence[str],
    criteria: Sequence[str],
    seed: int = 42,
) -> dict[str, Any]:
    """Analyze one room and return the API-ready descriptive statistics.

    Ties always resolve to the first item in ``options``.  Empty rooms are rejected
    explicitly so callers can return a clear API error instead of misleading zeros.
    """

    option_names = list(options)
    criterion_names = list(criteria)
    members = list(submissions)
    if not option_names:
        raise ValueError("at least one option is required")
    if not criterion_names:
        raise ValueError("at least one criterion is required")
    if not members:
        raise ValueError("at least one submission is required")
    if len(set(option_names)) != len(option_names):
        raise ValueError("options must be unique")
    if len(set(criterion_names)) != len(criterion_names):
        raise ValueError("criteria must be unique")

    weights, scores, first_choices, parsed = _read_submissions(
        members, option_names, criterion_names
    )
    team_percentages = allocate_percentages(
        _normalise(np.mean(weights, axis=0)),
        minimum=0,
    )
    team_weight_values = team_percentages / WEIGHT_TOTAL_PERCENT
    mean_scores = np.mean(scores, axis=0)
    current_score_values = mean_scores @ team_weight_values
    current_winner_index = _winner(current_score_values)
    current_winner = option_names[current_winner_index]

    vote_share = {
        option: first_choices.count(option) / len(first_choices) for option in option_names
    }
    team_weights = {
        criterion: float(team_weight_values[index])
        for index, criterion in enumerate(criterion_names)
    }
    weight_agreement = {
        criterion: _agreement(weights[:, index])
        for index, criterion in enumerate(criterion_names)
    }
    score_agreement = {
        option: {
            criterion: _agreement(scores[:, option_index, criterion_index])
            for criterion_index, criterion in enumerate(criterion_names)
        }
        for option_index, option in enumerate(option_names)
    }
    option_scores = {
        option: float(current_score_values[index])
        for index, option in enumerate(option_names)
    }
    mean_score_map = {
        option: {
            criterion: float(mean_scores[option_index, criterion_index])
            for criterion_index, criterion in enumerate(criterion_names)
        }
        for option_index, option in enumerate(option_names)
    }

    # A Dirichlet sample has one winner, so stability values form one probability
    # distribution. The fixed seed makes demos and tests reproducible.
    alpha = np.maximum(team_weight_values * DIRICHLET_CONCENTRATION, 1e-9)
    sampled_weights = np.random.default_rng(seed).dirichlet(alpha, size=N_SIMULATIONS)
    simulated_scores = sampled_weights @ mean_scores.T
    simulated_winners = np.argmax(simulated_scores, axis=1)
    win_counts = np.bincount(simulated_winners, minlength=len(option_names))
    stability_values = win_counts / N_SIMULATIONS
    stability = {
        option: float(stability_values[index])
        for index, option in enumerate(option_names)
    }
    robust_choice = option_names[_winner(stability_values)]

    weight_flips = _weight_flip_points(
        team_percentages,
        mean_scores,
        option_names,
        criterion_names,
        current_winner_index,
    )
    member_flip = _member_flip(weights, scores, option_names, current_winner_index)
    flip_points = [*weight_flips]
    if member_flip is not None:
        flip_points.append(member_flip)

    hidden_conflicts, conflict_agenda = _hidden_conflicts(
        current_winner,
        current_winner_index,
        first_choices,
        score_agreement,
        parsed,
        criterion_names,
    )
    discussion_agenda: list[str] = []
    nearby_weight_flips = [item for item in weight_flips if item["proximity"] == "nearby"]
    if nearby_weight_flips:
        closest = nearby_weight_flips[0]
        change = round(abs(closest["to"] - closest["from"]) * 100)
        direction = "오르면" if closest["direction"] == "increase" else "내리면"
        discussion_agenda.append(
            f"{closest['criterion']} 비중이 {change}%p {direction} "
            f"{closest['new_winner']}(으)로 바뀝니다. 이 기준을 먼저 논의하세요."
        )
    discussion_agenda.extend(conflict_agenda)
    if member_flip is not None:
        discussion_agenda.append(member_flip["description"] + ".")
    if not nearby_weight_flips:
        discussion_agenda.insert(0, "현재 결과는 가중치 변화에 비교적 견고합니다.")
    if not discussion_agenda:
        discussion_agenda.append("주요 가정을 먼저 확인하세요.")

    return {
        "vote_share": vote_share,
        "team_weights": team_weights,
        "weight_agreement": weight_agreement,
        "score_agreement": score_agreement,
        "option_scores": option_scores,
        "mean_scores": mean_score_map,
        "hidden_conflicts": hidden_conflicts,
        "stability": stability,
        "current_winner": current_winner,
        "robust_choice": robust_choice,
        "flip_points": flip_points,
        "discussion_agenda": discussion_agenda,
    }
