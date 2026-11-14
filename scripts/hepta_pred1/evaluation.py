"""Direct preparation-option forecasts and a shared PRED-1 action planner.

This is not an autoregressive imagined rollout. Models receive public histories
and candidate queries only. Evaluator-only labels are read after every forecast
and action selection. Regret uses the Bayes posterior with the same history.
Environment work units and measured host compute are reported separately.
Each horizon specifies horizon - 1 preparation ticks, followed by a terminal
tool. The model predicts the terminal tool's residual time and cost. Planning
adds preparation time/cost once, and compares four actions at fixed horizon 6;
it does not choose the preparation duration or replan during preparation.
"""

from time import perf_counter, process_time

import numpy as np

from .contracts import COSTS, JOINT_SUPPORT, TIMES
from .simulator import ACTIONS, HORIZONS, preparation_overhead, query_vector

COST_PENALTY = 0.03
TIME_PENALTY = 0.005
PRIMARY_HORIZON = 6


def _probabilities(value, shape, name):
    p = np.asarray(value, dtype=float)
    if p.shape != shape or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError(f"{name}: invalid probability array")
    totals = p.sum(axis=-1, keepdims=True)
    if not np.allclose(totals, 1.0, rtol=1e-7, atol=1e-10):
        raise ValueError(f"{name}: probabilities must sum to one")
    return p / totals  # Remove only accepted summation roundoff, never clip bad mass.


def _crps(marginal, values, truth):
    values = np.asarray(values, dtype=float)
    distances = np.abs(values[:, None] - values)
    first = (marginal * np.abs(values - truth[..., None])).sum(axis=-1)
    second = np.einsum("...i,...j,ij->...", marginal, marginal, distances)
    return np.maximum(0.0, first - 0.5 * second)


def evaluate(model, dataset, reset=False, mask_candidate_action=False):
    """Return aggregate metrics and paired-episode arrays; no training is performed.

    All four actions are forecast for preparations of 0, 2, and 5 ticks. Only legal
    actions enter scoring and selection. A zero probability for an observed event
    yields infinite NLL, with an explicit count; no epsilon floor hides it.
    Action masking removes historical and candidate actions while preserving
    horizon bits. Future totals include preparation and terminal execution;
    complete environment cost additionally includes the already-incurred prefix.
    """
    x = np.array(dataset.x, dtype=float, copy=True)
    if x.ndim != 3 or not len(x) or not x.shape[1] or not np.isfinite(x).all():
        raise ValueError("invalid public history")
    if mask_candidate_action:
        x[:, :, :3] = 0
    x.setflags(write=False)
    n, h, a, k = len(x), len(HORIZONS), len(ACTIONS), len(JOINT_SUPPORT)
    legal = np.asarray(dataset.legal_actions)
    if legal.dtype != np.bool_ or legal.shape != (n, a) or not legal.any(axis=1).all():
        raise ValueError("each episode needs a boolean nonempty legal-action set")
    public = {}
    for key in ("deadline", "remaining_budget", "prefix_cost"):
        value = np.asarray(getattr(dataset, key), dtype=float)
        if value.shape != (n,) or not np.isfinite(value).all() or (value < 0).any():
            raise ValueError(f"invalid public {key}")
        public[key] = value.copy()
    prefix = public["prefix_cost"]
    sy, st, sc = JOINT_SUPPORT.T
    preparation_ticks, preparation_cost = np.array(
        [preparation_overhead(v) for v in HORIZONS]
    ).T
    total_time = st + preparation_ticks[:, None]
    future_cost = sc + preparation_cost[:, None]
    feasible = (
        (sy == 1)
        & (total_time <= public["deadline"][:, None, None])
        & (future_cost <= public["remaining_budget"][:, None, None])
    )
    atom_utility = (
        feasible.astype(float) - COST_PENALTY * future_cost - TIME_PENALTY * total_time
    )
    predictions = np.empty((n, h, a, k))
    inference_wall, inference_cpu = perf_counter(), process_time()
    for hi in range(h):
        for ai in range(a):
            query = np.tile(query_vector(ai, hi), (n, 1))
            if mask_candidate_action:
                query[:, :a] = 0
            query.setflags(write=False)
            predictions[:, hi, ai] = _probabilities(
                model.predict_proba(x, query, reset=reset), (n, k), "model forecast"
            )
    inference_wall = perf_counter() - inference_wall
    inference_cpu = process_time() - inference_cpu
    planning_wall, planning_cpu = perf_counter(), process_time()
    primary = HORIZONS.index(PRIMARY_HORIZON)
    predicted_values = np.einsum(
        "nak,nk->na", predictions[:, primary], atom_utility[:, primary]
    )
    chosen = np.where(legal, predicted_values, -np.inf).argmax(axis=1)
    planning_wall = perf_counter() - planning_wall
    planning_cpu = process_time() - planning_cpu

    # The prediction/selection boundary ends here. No evaluator field is an input.
    evidence = dataset.evaluator
    bayes = _probabilities(evidence.bayes_joint, (n, h, a, k), "Bayes evaluator")
    classes = np.asarray(evidence.realized_class)
    if classes.shape != (n, h, a) or not np.issubdtype(classes.dtype, np.integer):
        raise ValueError("invalid evaluator classes")
    if ((classes < 0) | (classes >= k)).any():
        raise ValueError("evaluator class outside registered support")
    posterior_values = np.einsum(
        "nak,nk->na", bayes[:, primary], atom_utility[:, primary]
    )
    rows = np.arange(n)
    oracle = np.where(legal, posterior_values, -np.inf).max(axis=1)
    expected = posterior_values[rows, chosen]
    regret = oracle - expected
    if (regret < -1e-12).any():
        raise AssertionError("selected action exceeds same-information Bayes optimum")
    regret = np.maximum(0.0, regret)
    residual = JOINT_SUPPORT[classes]
    realized = residual.copy()
    realized[..., 1] += preparation_ticks[None, :, None]
    realized[..., 2] += preparation_cost[None, :, None]
    selected = realized[rows, primary, chosen]
    success, elapsed, cost = selected.T
    timely, affordable = (
        elapsed <= public["deadline"],
        cost <= public["remaining_budget"],
    )
    goal = (success == 1) & timely & affordable
    realized_utility = goal.astype(float) - COST_PENALTY * cost - TIME_PENALTY * elapsed
    full_cost = prefix + cost
    exact_probability = np.take_along_axis(predictions, classes[..., None], axis=-1)[
        ..., 0
    ]
    with np.errstate(divide="ignore"):
        nll = -np.log(exact_probability)
    joint = predictions.reshape(n, h, a, 2, len(TIMES), len(COSTS))
    event_probability = joint[:, :, :, 1].sum(axis=(-1, -2))
    goal_probability = np.einsum("nhak,nhk->nha", predictions, feasible)
    actual_goal = (
        (realized[..., 0] == 1)
        & (realized[..., 1] <= public["deadline"][:, None, None])
        & (realized[..., 2] <= public["remaining_budget"][:, None, None])
    )
    scores = {
        "joint_nll": nll,
        "outcome_brier": (event_probability - realized[..., 0]) ** 2,
        "deadline_budget_brier": (goal_probability - actual_goal) ** 2,
        # CRPS is translation-invariant: shifting both support and observation
        # by each option's known preparation overhead gives exactly these scores.
        "time_crps": _crps(joint.sum(axis=(3, 5)), TIMES, residual[..., 1]),
        "cost_crps": _crps(joint.sum(axis=(3, 4)), COSTS, residual[..., 2]),
        "joint_total_variation_to_bayes": 0.5
        * np.abs(predictions - bayes).sum(axis=-1),
    }
    legal_grid = np.broadcast_to(legal[:, None], (n, h, a))
    by_horizon = {}
    for hi, horizon in enumerate(HORIZONS):
        by_horizon[str(horizon)] = {
            key: float(value[:, hi][legal].mean()) for key, value in scores.items()
        }
        by_horizon[str(horizon)]["legal_predictions"] = int(legal.sum())
        by_horizon[str(horizon)].update(
            {
                "preparation_ticks": int(preparation_ticks[hi]),
                "preparation_cost": float(preparation_cost[hi]),
                "mean_predicted_deadline_budget_success_probability": float(
                    goal_probability[:, hi][legal].mean()
                ),
                "realized_deadline_budget_success_rate": float(
                    actual_goal[:, hi][legal].mean()
                ),
                "mean_total_time": float(realized[:, hi, :, 1][legal].mean()),
                "mean_total_future_cost": float(realized[:, hi, :, 2][legal].mean()),
            }
        )
    metrics = {
        "protocol": "direct_preparation_option_forecast",
        "autoregressive_rollout_evaluated": False,
        "horizon_selection_evaluated": False,
        "planning_scope": "four_actions_at_fixed_five_tick_preparation",
        "oracle_information": "exact_Bayes_posterior_of_same_public_history",
        "primary_horizon": PRIMARY_HORIZON,
        "primary_preparation_ticks": int(preparation_ticks[primary]),
        "primary_preparation_cost": float(preparation_cost[primary]),
        "episodes": n,
        "forecast_scores": {
            key: float(value[legal_grid].mean()) for key, value in scores.items()
        },
        "forecast_scores_by_horizon": by_horizon,
        "zero_mass_observed_event_count": int(
            ((exact_probability == 0) & legal_grid).sum()
        ),
        "prediction_calls": h * a,
        "prediction_rows": n * h * a,
        "legal_scored_prediction_rows": int(legal_grid.sum()),
        "inference_wall_seconds": inference_wall,
        "inference_process_cpu_seconds": inference_cpu,
        "planning_wall_seconds": planning_wall,
        "planning_process_cpu_seconds": planning_cpu,
        "expected_utility": float(expected.mean()),
        "net_utility": float((expected - COST_PENALTY * prefix).mean()),
        "oracle_expected_utility": float(oracle.mean()),
        "oracle_net_utility": float((oracle - COST_PENALTY * prefix).mean()),
        "bayes_regret": float(regret.mean()),
        "realized_utility": float(realized_utility.mean()),
        "realized_net_utility": float(
            (realized_utility - COST_PENALTY * prefix).mean()
        ),
        "success_rate": float(success.mean()),
        "deadline_budget_success_rate": float(goal.mean()),
        "deadline_met_rate": float(timely.mean()),
        "budget_met_rate": float(affordable.mean()),
        "mean_time": float(elapsed.mean()),
        "time_p95": float(np.quantile(elapsed, 0.95)),
        "mean_tool_cost": float(residual[rows, primary, chosen, 2].mean()),
        "mean_tool_time": float(residual[rows, primary, chosen, 1].mean()),
        "mean_future_cost": float(cost.mean()),
        "mean_prefix_cost": float(prefix.mean()),
        "complete_environment_cost": float(full_cost.mean()),
        "environment_cost_unit": "simulator_dimensionless_work",
        "host_compute_cost_monetized_in_utility": False,
    }
    per_episode = {
        "expected_utility": expected,
        "net_utility": expected - COST_PENALTY * prefix,
        "bayes_regret": regret,
        "realized_utility": realized_utility,
        "realized_net_utility": realized_utility - COST_PENALTY * prefix,
        "success": success,
        "deadline_budget_success": goal.astype(float),
        "complete_environment_cost": full_cost,
        "future_cost": cost,
        "elapsed_time": elapsed,
        "selected_action": chosen,
    }
    return metrics, per_episode
