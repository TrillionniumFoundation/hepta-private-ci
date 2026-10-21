"""Lazy acquisition boundary and validation-only strategy selection."""

import time

import numpy as np

from control import (COSTS, MISSING, MODALITIES, UNSEEN, fixed_policies,
                     fixed_portfolio, next_preference)
from metrics import cvar, score_outputs, summarize
from model import encode, generate, mac_counts


def predict_all(model, raw):
    """Paid calibration/validation preprocessing; never used for heldout rollout."""
    count = len(raw["text"])
    predictions = np.full((count, 4), MISSING, dtype=np.int64)
    encoded_counts = {}
    started = time.perf_counter()
    for j, modality in enumerate(MODALITIES):
        present = np.any(raw[modality] != 0, axis=1)
        encoded_counts[modality] = int(present.sum())
        if present.any():
            predictions[present, j] = encode(model, modality, raw[modality][present])[0]
    return predictions, {"encoded_examples": encoded_counts,
                         "wall_seconds": time.perf_counter() - started}


def symbol_rollout(predictions, planner, budget):
    """Validation simulation reveals only acquired reports to the planner."""
    choices = []
    costs = []
    for row in predictions:
        observations = (int(row[0]), UNSEEN, UNSEEN, UNSEEN)
        remaining, preference = budget, 0
        while True:
            _, action, portfolio = planner.solve(observations, remaining, preference)
            if action == -1:
                choices.append(portfolio)
                costs.append(budget - remaining)
                break
            report = int(row[action])
            preference = next_preference(preference, observations, report)
            child = list(observations)
            child[action] = report
            observations = tuple(child)
            remaining -= COSTS[action]
    return np.asarray(choices), np.asarray(costs)


def select_policies(predictions, truth, loss_table, grid, planners, budgets):
    selected, selection_receipt = {}, {}
    for budget in budgets:
        fixed_candidates = []
        for specification in fixed_policies(budget):
            indices = np.asarray([fixed_portfolio(row, specification, grid)
                                  for row in predictions])
            losses = loss_table[indices, truth]
            cost = sum(COSTS[j] for j in specification["order"])
            objective = float(losses.mean() + 0.5 * cvar(losses))
            fixed_candidates.append((objective, cost, specification))
        fixed_candidates.sort(key=lambda item: (item[0], item[1]))
        best = fixed_candidates[0]
        selected[(budget, "validation_selected_fixed_portfolio")] = best[2]
        selection_receipt[str(budget)] = {"fixed": {
            "selection_objective": best[0], "acquisition_units": best[1],
            "specification": best[2], "searched_candidates": len(fixed_candidates)}}
        for arm, options in planners.items():
            candidates = []
            for planner in options:
                indices, costs = symbol_rollout(predictions, planner, budget)
                losses = loss_table[indices, truth]
                objective = float(losses.mean() + 0.5 * cvar(losses))
                candidates.append((objective, float(costs.mean()), planner))
            candidates.sort(key=lambda item: (item[0], item[1]))
            objective, average_cost, chosen = candidates[0]
            selected[(budget, arm)] = chosen
            selection_receipt[str(budget)][arm] = {
                "gamma": chosen.gamma, "mode": chosen.mode,
                "selection_objective": objective, "mean_acquisition_units": average_cost,
                "searched_candidates": len(candidates)}
    return selected, selection_receipt


def rollout(model, raw, planner_or_fixed, budget, grid):
    """Only raw observations cross this boundary: no truth, reports, or scenario.

    A raw modality is encoded only after its acquisition action. The controller
    receives discretized encoder predictions, not future raw data or outcomes.
    All final raw outputs come from an actual neural forward pass.
    """
    count = len(raw["text"])
    observations = np.full((count, 4), UNSEEN, dtype=np.int64)
    remaining = np.full(count, budget, dtype=np.int64)
    preferences = np.zeros(count, dtype=np.int64)
    portfolios = np.full(count, -1, dtype=np.int64)
    encoded_counts = {name: 0 for name in MODALITIES}
    encoder_calls = {name: 0 for name in MODALITIES}
    acquired = np.zeros((count, 4), dtype=bool)
    trace = [[] for _ in range(count)]
    started = time.perf_counter()
    controller_seconds = 0.0
    fixed = isinstance(planner_or_fixed, dict)

    def acquire(indices, modality):
        name = MODALITIES[modality]
        values = raw[name][indices]
        present = np.any(values != 0, axis=1)
        reports = np.full(len(indices), MISSING, dtype=np.int64)
        if present.any():
            reports[present] = encode(model, name, values[present])[0]
            encoded_counts[name] += int(present.sum())
            encoder_calls[name] += 1
        for row, report in zip(indices, reports):
            if modality != 0:
                preferences[row] = next_preference(int(preferences[row]),
                                                   tuple(observations[row]), int(report))
                remaining[row] -= COSTS[modality]
            observations[row, modality] = report
            acquired[row, modality] = True
            trace[row].append([int(modality), int(report), int(preferences[row]),
                               int(remaining[row])])

    acquire(np.arange(count), 0)
    for step in range(4):
        pending = np.flatnonzero(portfolios < 0)
        if not len(pending):
            break
        action_groups = {j: [] for j in range(1, 4)}
        lookup_start = time.perf_counter()
        for row in pending:
            if fixed:
                order = planner_or_fixed["order"]
                action = order[step] if step < len(order) else -1
                portfolio = (fixed_portfolio(tuple(observations[row]), planner_or_fixed, grid)
                             if action == -1 else -1)
            else:
                _, action, portfolio = planner_or_fixed.solve(
                    tuple(int(x) for x in observations[row]), int(remaining[row]),
                    int(preferences[row]))
            if action == -1:
                portfolios[row] = portfolio
            else:
                if acquired[row, action] or COSTS[action] > remaining[row]:
                    raise AssertionError("invalid or over-budget acquisition")
                action_groups[action].append(row)
        controller_seconds += time.perf_counter() - lookup_start
        for action, indices in action_groups.items():
            if indices:
                acquire(np.asarray(indices), action)
    if np.any(portfolios < 0) or np.any(remaining < 0):
        raise AssertionError("rollout did not terminate within its finite budget")
    outputs = generate(model, grid[portfolios])
    profile = mac_counts(model)
    per_world_macs = np.full(count, profile["generate_all_modalities"], dtype=np.int64)
    for j, name in enumerate(MODALITIES):
        per_world_macs += ((observations[:, j] >= 0) & (observations[:, j] < MISSING)) * profile["encoder"][name]
    return outputs, {
        "portfolio_indices": portfolios, "remaining": remaining, "preference": preferences,
        "observations": observations, "trace": trace, "linear_macs": per_world_macs,
        "acquired_count": acquired.sum(axis=1), "acquisition_units": budget - remaining + 1,
        "encoded_examples": encoded_counts, "encoder_batch_calls": encoder_calls,
        "generator_examples": count, "generator_batch_calls": 1,
        "controller_lookup_seconds": controller_seconds,
        "wall_seconds": time.perf_counter() - started,
    }


def evaluate_rollout(model, world, policy, budget, grid, canonical):
    outputs, receipt = rollout(model, world["raw"], policy, budget, grid)
    scoring_start = time.perf_counter()
    scores = score_outputs(outputs, world["truth"], canonical)
    summary = summarize(scores)
    summary.update({"mean_linear_macs": float(receipt["linear_macs"].mean()),
                    "mean_acquisition_units": float(receipt["acquisition_units"].mean()),
                    "mixture_fraction": float((np.max(grid[receipt["portfolio_indices"]], axis=1) < 1).mean()),
                    "wall_seconds": receipt["wall_seconds"],
                    "external_scoring_seconds": time.perf_counter() - scoring_start,
                    "controller_lookup_seconds": receipt["controller_lookup_seconds"],
                    "encoded_examples": receipt["encoded_examples"],
                    "encoder_batch_calls": receipt["encoder_batch_calls"],
                    "generator_examples": receipt["generator_examples"]})
    return scores, receipt, summary
