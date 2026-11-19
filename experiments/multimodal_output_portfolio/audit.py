"""Independent bottom-up reference for the finite portfolio-control problem.

The reference accepts only problem data: the joint distribution, loss table,
portfolio grid, costs and objective parameters.  It does not call the recursive
planner's solve/stop/candidates/predictive/posterior/preference/CE routines.
Planner methods are consulted only *after* all reference values are computed.
Agreement is an implementation check, not evidence of a superior algorithm.
"""

from collections import deque
import time

import numpy as np


_COSTS = (1, 2, 1, 4)
_UNKNOWN = -1
_MISSING = 8
_TIE_TOLERANCE = 1e-12


def _forward_preference(preference, observations, report):
    if report == _MISSING:
        return preference
    previous = {value for value in observations if value in range(8)}
    if previous - {report}:
        return min(3, preference + 1)
    return max(0, preference - 1)


def _gamma(mode, gamma, preference):
    if mode == "neutral":
        return 0.0
    if mode in ("ndu", "myopic"):
        return gamma * (preference + 1)
    return gamma


def _entropic_utility(utilities, probabilities, aversion):
    if aversion == 0.0:
        return np.asarray(utilities) @ probabilities
    losses = -np.asarray(utilities)
    exponent = aversion * losses
    maximum = exponent.max(axis=-1, keepdims=True)
    weighted = np.exp(exponent - maximum) @ probabilities
    return -(maximum[..., 0] + np.log(weighted)) / aversion


def _reachable_states(roots, costs):
    queue = deque(roots)
    states = set(roots)
    while queue:
        observations, budget, preference = queue.popleft()
        for modality in (1, 2, 3):
            if observations[modality] != _UNKNOWN or costs[modality] > budget:
                continue
            for report in range(9):
                updated = list(observations)
                updated[modality] = report
                child = (
                    tuple(updated), budget - costs[modality],
                    _forward_preference(preference, observations, report),
                )
                if child not in states:
                    states.add(child)
                    queue.append(child)
    # Every acquisition removes exactly one unknown modality.  Ascending
    # unknown count is a dependency order independent of recursive execution.
    return sorted(states, key=lambda state: state[0].count(_UNKNOWN))


def bottom_up_reference(
    joint, loss_table, portfolios, budgets, gamma=2.0, mode="ndu", penalty=0.025,
    costs=_COSTS,
):
    """Evaluate the specified locally nested entropic objective by enumeration.

    State = (ordered observations, remaining budget, forward preference P).
    A stop action selects an allowed portfolio maximizing CE of negative loss.
    An acquisition uses CE at the *current* P of child continuation values,
    where each child has its own updated P, minus its deterministic cost.
    This objective is not replaced with one terminal, constant-gamma CE.
    """
    joint = np.asarray(joint, dtype=np.float64)
    loss_table = np.asarray(loss_table, dtype=np.float64)
    portfolios = np.asarray(portfolios, dtype=np.float64)
    if joint.shape != (8, 9, 9, 9, 9) or not np.isfinite(joint).all():
        raise ValueError("joint must be a finite [truth, four reports] table")
    if np.any(joint <= 0) or not np.isclose(joint.sum(), 1.0):
        raise ValueError("audit requires a normalized, strictly positive smoothed joint")
    if portfolios.ndim != 2 or portfolios.shape[1] != 8:
        raise ValueError("portfolios must have shape [candidate, 8]")
    if (not np.isfinite(portfolios).all() or np.any(portfolios < 0)
            or not np.allclose(portfolios.sum(axis=1), 1.0)
            or not np.allclose(portfolios[-1], 1.0 / 8)):
        raise ValueError("portfolios must lie on the simplex with final uniform fallback")
    if loss_table.shape != portfolios.shape or not np.isfinite(loss_table).all():
        raise ValueError("loss_table must have shape [candidate, 8] and be finite")
    if mode not in ("ndu", "myopic", "neutral", "fixed", "single"):
        raise ValueError("unsupported reference mode")
    if not np.isfinite(gamma) or gamma < 0 or not np.isfinite(penalty) or penalty < 0:
        raise ValueError("gamma and acquisition penalty must be finite and nonnegative")
    budgets = tuple(budgets)
    if not budgets or any(type(budget) is not int or budget < 0 for budget in budgets):
        raise ValueError("budgets must contain nonnegative integers")
    if tuple(costs) != _COSTS:
        raise ValueError("this frozen audit uses acquisition costs (1, 2, 1, 4)")

    roots = [((report, -1, -1, -1), budget, 0)
             for budget in budgets for report in range(9)]
    states = _reachable_states(roots, costs)
    observation_data = {}
    stopping_data = {}
    result = {}
    for observations, budget, preference in states:
        if observations not in observation_data:
            unknown = [index for index, report in enumerate(observations) if report == -1]
            selection = (slice(None),) + tuple(
                slice(None) if report == -1 else report for report in observations
            )
            conditional_table = joint[selection]
            total_mass = conditional_table.sum()
            posterior = conditional_table.sum(
                axis=tuple(range(1, conditional_table.ndim))
            ) / total_mass
            predictions = {}
            for offset, modality in enumerate(unknown, start=1):
                integrate = tuple(axis for axis in range(conditional_table.ndim)
                                  if axis != offset)
                predictions[modality] = conditional_table.sum(axis=integrate) / total_mass

            reported = {report for report in observations if report in range(8)}
            if not reported:
                choices = np.array([len(portfolios) - 1], dtype=np.int64)
            else:
                forbidden = sorted(set(range(8)) - reported)
                supported = np.all(portfolios[:, forbidden] == 0.0, axis=1)
                if mode == "single":
                    supported &= np.count_nonzero(portfolios, axis=1) == 1
                choices = np.flatnonzero(supported)
            if choices.size == 0:
                raise ValueError("portfolio domain has no admissible stop action")
            observation_data[observations] = (posterior, predictions, choices)

        posterior, predictions, choices = observation_data[observations]
        aversion = _gamma(mode, gamma, preference)
        stop_key = (observations, preference)
        if stop_key not in stopping_data:
            stopping_values = _entropic_utility(-loss_table[choices], posterior, aversion)
            best_choice = int(np.argmax(stopping_values))
            stopping_data[stop_key] = (float(stopping_values[best_choice]),
                                       int(choices[best_choice]))
        best_value, stop_portfolio = stopping_data[stop_key]
        best_action = -1
        for modality in (1, 2, 3):
            if observations[modality] != _UNKNOWN or costs[modality] > budget:
                continue
            child_values = []
            for report in range(9):
                updated = list(observations)
                updated[modality] = report
                child_observations = tuple(updated)
                child_preference = _forward_preference(preference, observations, report)
                if mode == "myopic":
                    # Every child stop is present because the reference visits
                    # all child observation tuples before their parents.
                    child_value = stopping_data[(child_observations, child_preference)][0]
                else:
                    child_value = result[(child_observations, budget - costs[modality],
                                          child_preference)][0]
                child_values.append(child_value)
            purchase_value = float(_entropic_utility(
                child_values, predictions[modality], aversion
            )) - penalty * costs[modality]
            if purchase_value > best_value + _TIE_TOLERANCE:
                best_value, best_action = purchase_value, modality
        result[(observations, budget, preference)] = (best_value, best_action, stop_portfolio)

    return {"values": result, "roots": roots,
            "augmented_states": len(states), "observation_states": len(observation_data)}


def audit_planner(planner, budgets=(2, 4, 7), tolerance=1e-10, compare_all=False):
    """Compare a completed independent reference with the recursive planner."""
    start = time.perf_counter()
    reference = bottom_up_reference(
        joint=planner.model.joint, loss_table=planner.loss,
        portfolios=planner.portfolios, budgets=budgets, gamma=planner.gamma,
        mode=planner.mode, penalty=planner.penalty,
    )
    reference_seconds = time.perf_counter() - start
    # No method on planner/model was invoked above this point.
    checked_states = list(reference["values"]) if compare_all else reference["roots"]
    max_error = 0.0
    value_mismatches = 0
    action_mismatches = 0
    portfolio_mismatches = 0
    failures = []
    root_rows = []
    root_set = set(reference["roots"])
    for state in checked_states:
        expected = reference["values"][state]
        actual = planner.solve(*state)
        error = abs(expected[0] - actual[0])
        max_error = max(max_error, error)
        value_bad = not np.isfinite(actual[0]) or error > tolerance
        action_bad = expected[1] != actual[1]
        portfolio_bad = expected[2] != actual[2]
        value_mismatches += int(value_bad)
        action_mismatches += int(action_bad)
        portfolio_mismatches += int(portfolio_bad)
        if value_bad or action_bad or portfolio_bad:
            failures.append({"state": [list(state[0]), state[1], state[2]],
                             "reference": list(expected), "planner": list(actual)})
        if state in root_set:
            root_rows.append({"initial_text_report": state[0][0], "budget": state[1],
                              "reference_value": expected[0], "planner_value": actual[0],
                              "reference_action": expected[1], "planner_action": actual[1],
                              "absolute_error": error})
    return {
        "passed": value_mismatches + action_mismatches + portfolio_mismatches == 0,
        "mode": planner.mode, "gamma": float(planner.gamma), "tolerance": tolerance,
        "checked_states": len(checked_states),
        "reference_augmented_states": reference["augmented_states"],
        "reference_observation_states": reference["observation_states"],
        "max_absolute_value_error": max_error,
        "value_mismatches": value_mismatches, "action_mismatches": action_mismatches,
        "stop_portfolio_mismatches": portfolio_mismatches,
        "reference_wall_seconds": reference_seconds,
        "recursive_solver_used_to_construct_reference": False,
        "roots": root_rows, "first_failures": failures[:10],
    }
