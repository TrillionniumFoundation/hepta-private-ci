"""Frequency-specialized candidate training under equal optimizer-update budgets.

The four streams are numerical proxies, NOT actual PERC/PRED/CTRL/ACT Cells.
Model weights are private in-memory learner candidates, never runtime artifacts.
"""
import math
import random
import statistics

FAMILIES = ("PERC", "PRED", "CTRL", "ACT")
SLOTS = {
    "uniform": ("PERC", "PRED", "CTRL", "ACT"),
    "heterogeneous": (
        "CTRL", "PRED", "CTRL", "ACT",
        "CTRL", "PRED", "CTRL", "PERC",
        "CTRL", "PRED", "CTRL", "ACT",
        "CTRL", "PRED", "CTRL", "ACT",
    ),
}
LEARNING_RATE_GRID = (0.04, 0.08, 0.16, 0.32)
CALIBRATION_SEEDS = tuple(range(9001, 9007))
TEST_SEEDS = tuple(range(11001, 11017))


def hidden_target(family, t):
    if family == "PERC":
        return 0.65
    if family == "CTRL":
        return 0.75 if (t // 32) % 2 == 0 else -0.75
    if family == "PRED":
        return 0.6 * math.sin(t / 18)
    if family == "ACT":
        return 0.7 if (t // 96) % 2 == 0 else -0.7
    raise ValueError("unknown task family")


def run_schedule(seed, policy, learning_rates, steps=256):
    if policy not in SLOTS or steps <= 0:
        raise ValueError("invalid schedule")
    if set(learning_rates) != set(FAMILIES):
        raise ValueError("missing family-specific learner rate")
    if any(not 0 < learning_rates[f] <= 1 for f in FAMILIES):
        raise ValueError("invalid learning rate")

    world = random.Random(400000 + seed)
    candidate_weights = {f: 0.0 for f in FAMILIES}
    squared_errors = {f: [] for f in FAMILIES}
    update_counts = {f: 0 for f in FAMILIES}
    for t in range(steps):
        chosen = SLOTS[policy][t % len(SLOTS[policy])]
        observations = {}
        for family in FAMILIES:
            target = hidden_target(family, t)  # private evaluator target
            squared_errors[family].append(
                (candidate_weights[family] - target) ** 2)
            observations[family] = target + world.gauss(0, 0.18)
        candidate_weights[chosen] += learning_rates[chosen] * (
            observations[chosen] - candidate_weights[chosen])
        update_counts[chosen] += 1

    # All arms expend exactly one optimizer update per step. Observation costs
    # are identical; real-model wall time/activation memory are NOT measured.
    assert sum(update_counts.values()) == steps
    by_family = {family: statistics.fmean(squared_errors[family])
                 for family in FAMILIES}
    return {
        "mean_mse": statistics.fmean(by_family.values()),
        "family_mse": by_family,
        "optimizer_updates": steps,
        "updates_by_family": update_counts,
    }


def tune_rates(policy):
    """Same pre-registered grid and calibration seeds for BOTH policies."""
    best = {}
    for family in FAMILIES:
        scored = []
        for alpha in LEARNING_RATE_GRID:
            rates = {f: alpha for f in FAMILIES}
            value = statistics.fmean(
                run_schedule(seed, policy, rates)["family_mse"][family]
                for seed in CALIBRATION_SEEDS)
            scored.append((value, alpha))
        best[family] = min(scored)[1]
    return best
