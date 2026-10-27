"""Fit a joint empirical terminal law; never average before exponentiation."""

import math

import numpy as np

from .protocol import PROTOCOL as P


def proposal(arm, symbol, heads):
    if arm == "history":
        return bool(heads["history_moment_difference"][str(symbol)] >= 0)
    if arm == "linear_memory":
        from .adapter import generic_memory
        return bool(generic_memory(symbol) @ np.asarray(heads["linear_weights"]) >= 0)
    return bool(heads["native_by_feedback"][str(symbol)]["proposal"])


def task_cost(proposed, admitted, kernels=50):
    return (kernels * P["native_kernel_charge"] + P["generator_call_charge"] + P["delivery_charge"]
            + admitted * (P["generator_call_charge"] + P["delivery_charge"])
            + (proposed and not admitted) * P["refused_proposal_charge"])


def outcomes(rows, condition, arm, expires, budget, heads, shrinkage, feedback=None):
    """Return normalized weights and sampled outcomes of the *same* continuation.

    Fit rows jointly bind feedback and both generated qualities. The permuted
    intervention explicitly breaks that binding; ordinary forecasts retain it.
    """
    pooled = [row for row in rows if row["condition"] == condition]
    local = [(row, 1.0) for row in pooled]
    if shrinkage:
        local += [(row, shrinkage / len(rows)) for row in rows]
    if not local:
        raise ValueError("No fitting support for the requested context")
    values, strict, costs, weights = [], [], [], []
    donor = {symbol: np.mean([row["feedback"] == symbol for row in rows]) for symbol in (-1, 0, 1)}
    for row, mass in local:
        if feedback is not None:
            if arm in ("native_numeric", "history", "linear_memory") and row["feedback"] != feedback:
                continue
            symbols = [(feedback, 1.0)]
        elif arm == "native_zero":
            symbols = [(0, 1.0)]
        elif arm == "native_permuted":
            symbols = list(donor.items())
        else:
            symbols = [(row["feedback"], 1.0)]
        for symbol, symbol_mass in symbols:
            proposed = proposal(arm, symbol, heads)
            admitted = proposed and expires >= 7 and budget >= 2
            chosen = row["alternate"] if admitted else row["initial"]
            cost = task_cost(proposed, admitted)
            values.append(chosen["utility"] - cost)
            strict.append(chosen["strict_success"])
            costs.append(cost)
            weights.append(mass * symbol_mass)
    if not weights or sum(weights) <= 0:
        raise ValueError("Feedback lacks fitting support")
    weights = np.asarray(weights) / sum(weights)
    return np.asarray(values), np.asarray(strict), np.asarray(costs), weights


def predict(rows, condition, arm, expires, budget, heads, shrinkage, feedback=None):
    values, strict, costs, weights = outcomes(rows, condition, arm, expires, budget, heads, shrinkage, feedback)
    moment = float(np.exp(-P["gamma"] * values) @ weights)
    return {"moment": moment, "ce": -math.log(moment) / P["gamma"],
        "mean_utility": float(values @ weights), "strict_probability": float(strict @ weights),
        "mean_cost": float(costs @ weights), "weighted_records": len(weights),
        "conditioning": "public condition/owner/budget and optional delivered scalar",
        "future_target_or_test_outcome_access": False}


def select_pooling(fit, validation, heads):
    candidates = []
    for shrinkage in P["critic_shrinkage_candidates"]:
        losses = []
        for row in validation:
            for expires, budget in ((6, 1), (6, 2), (7, 1), (7, 2)):
                for arm in ("native_numeric", "native_zero"):
                    symbol = row["feedback"] if arm == "native_numeric" else 0
                    proposed = proposal(arm, symbol, heads)
                    admitted = proposed and expires >= 7 and budget >= 2
                    target = row["alternate"] if admitted else row["initial"]
                    utility = target["utility"] - task_cost(proposed, admitted)
                    estimated = predict(fit, row["condition"], arm, expires, budget, heads, shrinkage)
                    losses.append((estimated["moment"] - math.exp(-P["gamma"] * utility)) ** 2
                                  + (estimated["strict_probability"] - target["strict_success"]) ** 2)
        candidates.append({"shrinkage": shrinkage, "validation_proper_score": float(np.mean(losses))})
    selected = min(candidates, key=lambda row: (row["validation_proper_score"], row["shrinkage"]))
    return {"selected_shrinkage": selected["shrinkage"], "candidates": candidates,
        "test_used": False, "fit_outcome_records": len(fit), "validation_source_pairs": len(validation)}
