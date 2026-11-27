"""Development-only horizon comparisons with one cached prefix per policy.

Each requested panel reserves its whole legal head count and maximum registered
terminal/preparation support before inference. This conservative admission rule
does not optimize subsets. Declared compute time does not advance latent state.
No production action is dispatched; simulator tariffs are not physical prices.
"""

from dataclasses import asdict
from time import perf_counter, process_time

import numpy as np

from .contracts import JOINT_SUPPORT
from .evaluation import COST_PENALTY, TIME_PENALTY
from .models import softmax
from .preparation import (
    PreparationChoices,
    PreparationForecasts,
    PreparationTariff,
    _nonnegative_vector,
    _probabilities,
    choose_fixed_one,
    forecast_fixed_one,
)
from .simulator import ACTIONS, HORIZONS, INPUT_DIM, preparation_overhead, query_vector

PANELS = {
    "matched_cached_fixed1": (1,),
    "cached_short13": (1, 3),
    "cached_adaptive136": (1, 3, 6),
}


def forecast_cached_panel(
    model,
    history,
    legal_actions,
    deadline,
    remaining_budget,
    *,
    horizons,
    tariff,
    reset=False,
    mask_candidate_action=False,
):
    """Forecast explicit actor inputs, with no evaluator or dataset interface."""
    wall, cpu = perf_counter(), process_time()
    if (
        type(horizons) is not tuple
        or any(type(h) is not int for h in horizons)
        or horizons not in PANELS.values()
        or not isinstance(tariff, PreparationTariff)
        or type(reset) is not bool
        or type(mask_candidate_action) is not bool
    ):
        raise ValueError("invalid panel, tariff or ablation flags")
    x = np.array(history, dtype=float, copy=True)
    if (
        x.ndim != 3
        or not 0 < len(x) <= 100_000
        or not 0 < x.shape[1] <= 256
        or x.shape[2] != INPUT_DIM
        or not np.isfinite(x).all()
    ):
        raise ValueError("invalid public history")
    if mask_candidate_action:
        x[:, :, :3] = 0
    n, a, k = len(x), len(ACTIONS), len(JOINT_SUPPORT)
    legal = np.array(legal_actions, copy=True)
    if legal.dtype != np.bool_ or legal.shape != (n, a):
        raise ValueError("legal actions must be a boolean row per episode")
    budget = _nonnegative_vector(remaining_budget, n, "remaining_budget")
    deadline = _nonnegative_vector(deadline, n, "deadline")
    steps = 1 if reset or getattr(model, "kind", None) == "single_step" else x.shape[1]
    count = len(horizons) * legal.sum(axis=1)
    work, delay = tariff.charges(np.full(n, steps), count, count)
    ticks, prep = preparation_overhead(max(horizons))
    queried = (
        (count > 0)
        & (ticks + JOINT_SUPPORT[:, 1].max() + delay <= deadline)
        & (prep + JOINT_SUPPORT[:, 2].max() + work <= budget)
    )
    allowed = np.zeros((n, len(HORIZONS), a), dtype=bool)
    indices = [HORIZONS.index(h) for h in horizons]
    for hi in indices:
        allowed[:, hi] = legal & queried[:, None]
    values = np.full(allowed.shape, -np.inf)
    charged, delayed = np.where(queried, work, 0), np.where(queried, delay, 0)
    x = x[queried, -steps:]
    x.setflags(write=False)
    inference_wall, inference_cpu = perf_counter(), process_time()
    calls, rows, retained = 0, 0, 0
    if len(x):
        state = model.initial_state(len(x))
        for t in range(steps):
            state = model.observe(x[:, t], state)
        for value in state.values():
            value.setflags(write=False)
            retained += value.nbytes
        for hi in indices:
            ticks, prep = preparation_overhead(HORIZONS[hi])
            utility = (
                JOINT_SUPPORT[:, 0]
                - COST_PENALTY * (JOINT_SUPPORT[:, 2] + prep)
                - TIME_PENALTY * (JOINT_SUPPORT[:, 1] + ticks)
            )
            for action in range(a):
                selected = allowed[queried, hi, action]
                count = int(selected.sum())
                if not count:
                    continue
                candidate = {
                    key: value[selected].copy() for key, value in state.items()
                }
                query = np.tile(query_vector(action, hi), (count, 1))
                if mask_candidate_action:
                    query[:, :a] = 0
                for value in (*candidate.values(), query):
                    value.setflags(write=False)
                logits = np.asarray(model.predict_from_state(candidate, query))
                if logits.shape != (count, k) or not np.isfinite(logits).all():
                    raise ValueError("invalid cached candidate logits")
                p = _probabilities(softmax(logits), (count, k))
                values[allowed[:, hi, action], hi, action] = p @ utility
                calls, rows = calls + 1, rows + count
    meter = {
        "horizons": list(horizons),
        "prediction_calls": calls,
        "prediction_rows": rows,
        "state_update_calls": steps if len(x) else 0,
        "state_update_rows": steps * len(x),
        "history_encodings": len(x),
        "queried_episodes": len(x),
        "reserved_planning_candidate_rows": rows,
        "retained_state_bytes": retained,
        "inference_wall_seconds": perf_counter() - inference_wall,
        "inference_process_cpu_seconds": process_time() - inference_cpu,
        "forecast_total_wall_seconds": perf_counter() - wall,
        "forecast_total_process_cpu_seconds": process_time() - cpu,
        "tariff": asdict(tariff),
        "physical_cost_complete": False,
        "memory_scope": "retained numeric state only; not peak RAM or allocation traffic",
    }
    for value in (values, allowed, charged, delayed):
        value.setflags(write=False)
    return PreparationForecasts(values, allowed, charged, delayed, meter)


def choose_cached_panel(forecasts):
    """Compare only queried scores; ties prefer shorter horizon, then action.

    Boolean-mask traversal is unpriced admission/filtering work. The tariff
    counts the scores supplied to argmax, not all physical planning operations.
    """
    wall, cpu = perf_counter(), process_time()
    allowed, values = forecasts.admissible, forecasts.predicted_values
    actions, horizons = np.full(len(allowed), -1), np.full(len(allowed), -1)
    status, scanned = ["no_admissible_option"] * len(allowed), 0
    for row in np.flatnonzero(allowed.any(axis=(1, 2))):
        slots = np.flatnonzero(allowed[row].ravel())
        candidates = values[row].ravel()[slots]
        if not np.isfinite(candidates).all():
            raise ValueError("admitted candidate has no finite forecast")
        best = int(np.argmax(candidates))
        scanned += len(slots)
        status[row] = "nonpositive_value"
        if candidates[best] > 0:
            horizons[row], actions[row] = divmod(int(slots[best]), len(ACTIONS))
            status[row] = "execute"
    for value in (actions, horizons):
        value.setflags(write=False)
    return PreparationChoices(horizons, actions, tuple(status)), {
        "planning_candidate_rows": scanned,
        "planning_count_scope": "candidate score comparisons; boolean-mask filtering remains unpriced",
        "choice_wall_seconds": perf_counter() - wall,
        "choice_process_cpu_seconds": process_time() - cpu,
    }


def _score(forecasts, choice, prefix, posterior, classes):
    active = choice.action >= 0
    rows, hi, ai = (
        np.flatnonzero(active),
        choice.horizon_index[active],
        choice.action[active],
    )
    success, elapsed, cost, expected = (np.zeros(len(active)) for _ in range(4))
    success[active], elapsed[active], cost[active] = JOINT_SUPPORT[
        classes[rows, hi, ai]
    ].T
    ticks, prep = np.array([preparation_overhead(h) for h in HORIZONS]).T
    elapsed[active], cost[active] = elapsed[active] + ticks[hi], cost[active] + prep[hi]
    expected[active] = posterior[rows, hi, ai]
    paid, delay = forecasts.decision_work_charged, forecasts.decision_time_charged
    full_cost, full_time = prefix + paid + cost, delay + elapsed
    net = expected - COST_PENALTY * (prefix + paid) - TIME_PENALTY * delay
    realized = success - COST_PENALTY * full_cost - TIME_PENALTY * full_time
    return {
        "expected_net_utility": float(net.mean()),
        "realized_net_utility": float(realized.mean()),
        "stop_rate": float((~active).mean()),
        "complete_environment_cost": float(full_cost.mean()),
        "per_episode": {
            "selected_action": choice.action.tolist(),
            "status": list(choice.status),
            "selected_horizon": [
                HORIZONS[i] if i >= 0 else None for i in choice.horizon_index
            ],
            "expected_net_utility": net.tolist(),
            "realized_net_utility": realized.tolist(),
            "decision_work": paid.tolist(),
            "decision_time": delay.tolist(),
            "prefix_cost": prefix.tolist(),
            "future_cost": cost.tolist(),
            "future_elapsed_time": elapsed.tolist(),
            "elapsed_time": full_time.tolist(),
            "complete_environment_cost": full_cost.tolist(),
        },
    }


def evaluate_cached_development(
    model, dataset, *, tariff, reset=False, mask_candidate_action=False
):
    """Compare matched caches, preserving a separately metered old-Fixed1 bridge."""
    wall, cpu = perf_counter(), process_time()
    if len(dataset.groups) != len(dataset.x) or not all(
        isinstance(g, str)
        and len(g.rsplit(":", 2)) == 3
        and g.rsplit(":", 2)[-2] == "dev"
        for g in dataset.groups
    ):
        raise ValueError("cached comparison requires development groups")
    n = len(dataset.x)
    prefix = _nonnegative_vector(dataset.prefix_cost, n, "prefix_cost")
    public = (
        model,
        dataset.x,
        dataset.legal_actions,
        dataset.deadline,
        dataset.remaining_budget,
    )
    options = dict(
        tariff=tariff, reset=reset, mask_candidate_action=mask_candidate_action
    )
    forecasts, choices, meters = {}, {}, {}
    for name, horizons in PANELS.items():
        forecasts[name] = forecast_cached_panel(*public, horizons=horizons, **options)
        choices[name], planning = choose_cached_panel(forecasts[name])
        meters[name] = {**forecasts[name].meter, **planning}
    bridge_wall, bridge_cpu = perf_counter(), process_time()
    legacy = forecast_fixed_one(*public, **options)
    legacy_choice = choose_fixed_one(legacy)
    first, first_choice = (
        forecasts["matched_cached_fixed1"],
        choices["matched_cached_fixed1"],
    )
    parity = all(
        np.array_equal(getattr(first, field), getattr(legacy, field))
        for field in (
            "predicted_values",
            "admissible",
            "decision_work_charged",
            "decision_time_charged",
        )
    )
    parity &= (
        np.array_equal(first_choice.action, legacy_choice.action)
        and np.array_equal(first_choice.horizon_index, legacy_choice.horizon_index)
        and first_choice.status == legacy_choice.status
    )
    if not parity:
        raise AssertionError("cached horizon-1 diverged from the frozen cheap Fixed1")
    bridge = {
        "parity": True,
        "meter": legacy.meter,
        "wall_seconds": perf_counter() - bridge_wall,
        "process_cpu_seconds": process_time() - bridge_cpu,
        "scope": "extra old-cheap bridge execution; not an independent policy arm",
    }
    # Every policy, including the parity bridge, is fixed before evaluator access.
    evidence = dataset.evaluator
    bayes = _probabilities(
        evidence.bayes_joint, (n, len(HORIZONS), len(ACTIONS), len(JOINT_SUPPORT))
    )
    classes = np.asarray(evidence.realized_class)
    if (
        classes.shape != (n, len(HORIZONS), len(ACTIONS))
        or not np.issubdtype(classes.dtype, np.integer)
        or ((classes < 0) | (classes >= len(JOINT_SUPPORT))).any()
    ):
        raise ValueError("invalid development evaluator classes")
    ticks, prep = np.array([preparation_overhead(h) for h in HORIZONS]).T
    atom = (
        JOINT_SUPPORT[None, :, 0]
        - COST_PENALTY * (JOINT_SUPPORT[None, :, 2] + prep[:, None])
        - TIME_PENALTY * (JOINT_SUPPORT[None, :, 1] + ticks[:, None])
    )
    posterior = np.einsum("nhak,hk->nha", bayes, atom)
    arms = {
        name: _score(forecasts[name], choices[name], prefix, posterior, classes)
        for name in PANELS
    }
    return {
        "schema": "pred1-cached-preparation-development-v1",
        "status": "HOLD",
        "scope": "development-only finite simulator; no real effects or autoregressive rollout",
        "reservation": "entire requested legal panel and its maximum support; no subset optimization",
        "comparison": "same single-prefix cache rule; requested horizons, panel admission and head counts vary",
        "utility_reference": "original full-history simulator posterior, including for input ablations",
        "arms": arms,
        "policy_meters": meters,
        "old_cheap_bridge": bridge,
        "meter": {
            "end_to_end_wall_seconds": perf_counter() - wall,
            "end_to_end_process_cpu_seconds": process_time() - cpu,
            "physical_cost_complete": False,
            "energy_joules": None,
            "financial_cost": None,
            "tariff_scope": "declared simulator episode-operations, not FLOPs or physical prices",
            "unpriced": "admission, validation, training, transport, energy and money",
            "time_scope": "measured host spans include all arms and bridge; declared delay does not advance latent state",
        },
    }
