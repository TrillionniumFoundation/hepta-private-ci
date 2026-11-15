"""Development-only, actor-first preparation/action selection for PRED-1.

The frozen fixed-horizon evaluator is unchanged. This planner reserves the full
registered tool support before choosing an open-loop preparation and action.
It never treats a small predicted tail probability as permission to exceed a
resource cap. Stop is an ordinary outcome; no external action is dispatched.
"""

from dataclasses import asdict, dataclass
from time import perf_counter, process_time

import numpy as np

from .contracts import JOINT_SUPPORT
from .evaluation import COST_PENALTY, TIME_PENALTY
from .models import softmax
from .simulator import ACTIONS, HORIZONS, INPUT_DIM, preparation_overhead, query_vector


def _probabilities(value, shape):
    result = np.asarray(value, dtype=float)
    if (
        result.shape != shape
        or not np.isfinite(result).all()
        or (result < 0).any()
        or (result > 1).any()
        or not np.allclose(result.sum(axis=-1), 1, rtol=1e-7, atol=1e-10)
    ):
        raise ValueError("invalid preparation forecast probabilities")
    return result / result.sum(axis=-1, keepdims=True)


def _nonnegative_vector(value, count, name):
    result = np.array(value, dtype=float, copy=True)
    if result.shape != (count,) or not np.isfinite(result).all() or (result < 0).any():
        raise ValueError(f"invalid public {name}")
    return result


@dataclass(frozen=True)
class PreparationForecasts:
    """Public-input forecasts; unqueried rows have no predicted value."""

    predicted_values: np.ndarray
    admissible: np.ndarray
    decision_work_charged: np.ndarray
    decision_time_charged: np.ndarray
    meter: dict


@dataclass(frozen=True)
class PreparationChoices:
    """A stop has horizon/action -1 and incurs no preparation or tool cost."""

    horizon_index: np.ndarray
    action: np.ndarray
    status: tuple[str, ...]


@dataclass(frozen=True)
class PreparationTariff:
    """Declared simulator charges per executed episode-operation, not FLOPs.

    A state step includes the model's whole recurrent update, a head includes
    its whole candidate forward, and planning prices one considered candidate.
    Admission/validation has measured host cost but no established simulator
    price. These rates therefore do not establish complete physical costs.
    """

    state_step_work: float
    head_work: float
    candidate_planning_work: float
    state_step_time: float
    head_time: float
    candidate_planning_time: float

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("tariff rates must be finite nonnegative numbers")
            if not np.isfinite(value) or value < 0:
                raise ValueError("tariff rates must be finite nonnegative numbers")

    def charges(self, state_steps, heads, candidates):
        with np.errstate(over="ignore", invalid="ignore"):
            work = (
                state_steps * self.state_step_work
                + heads * self.head_work
                + candidates * self.candidate_planning_work
            )
            delay = (
                state_steps * self.state_step_time
                + heads * self.head_time
                + candidates * self.candidate_planning_time
            )
        if not np.isfinite(work).all() or not np.isfinite(delay).all():
            raise ValueError("computed tariff charge is not finite")
        return work, delay


def forecast_fixed_one(
    model,
    history,
    legal_actions,
    deadline,
    remaining_budget,
    *,
    tariff,
    reset=False,
    mask_candidate_action=False,
):
    """Encode one real prefix once, then query only admitted horizon-1 actions.

    All terminal actions have the same registered support bounds. Reserve the
    full support and the known operation count before any model work. A row
    that cannot fund all its legal candidates stops, without a cheaper subset
    search. Candidate queries get read-only copies of the observed state.
    """
    total_wall, total_cpu = perf_counter(), process_time()
    if (
        not isinstance(tariff, PreparationTariff)
        or type(reset) is not bool
        or type(mask_candidate_action) is not bool
    ):
        raise ValueError("a PreparationTariff and boolean reset are required")
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
    deadline = _nonnegative_vector(deadline, n, "deadline")
    budget = _nonnegative_vector(remaining_budget, n, "remaining_budget")
    steps = 1 if reset or getattr(model, "kind", None) == "single_step" else x.shape[1]
    candidates = legal.sum(axis=1)
    work, delay = tariff.charges(np.full(n, steps), candidates, candidates)
    queried = (
        (candidates > 0)
        & (JOINT_SUPPORT[:, 1].max() + delay <= deadline)
        & (JOINT_SUPPORT[:, 2].max() + work <= budget)
    )
    admitted = legal & queried[:, None]
    allowed = np.zeros((n, len(HORIZONS), a), dtype=bool)
    allowed[:, 0] = admitted
    values = np.full(allowed.shape, -np.inf)
    charged, delayed = np.where(queried, work, 0), np.where(queried, delay, 0)
    x = x[queried, -steps:]
    x.setflags(write=False)
    wall, cpu = perf_counter(), process_time()
    calls, rows, resident = 0, 0, 0
    if len(x):
        state = model.initial_state(len(x))
        for t in range(steps):
            state = model.observe(x[:, t], state)
        for value in state.values():
            value.setflags(write=False)
            resident += value.nbytes
        utility = (
            JOINT_SUPPORT[:, 0]
            - COST_PENALTY * JOINT_SUPPORT[:, 2]
            - TIME_PENALTY * JOINT_SUPPORT[:, 1]
        )
        for action in range(a):
            selected = admitted[queried, action]
            count = int(selected.sum())
            if not count:
                continue
            candidate_state = {
                key: value[selected].copy() for key, value in state.items()
            }
            query = np.tile(query_vector(action, 0), (count, 1))
            if mask_candidate_action:
                query[:, :a] = 0
            for value in (*candidate_state.values(), query):
                value.setflags(write=False)
            logits = np.asarray(model.predict_from_state(candidate_state, query))
            if logits.shape != (count, k) or not np.isfinite(logits).all():
                raise ValueError("invalid fixed-one candidate logits")
            probabilities = _probabilities(softmax(logits), (count, k))
            values[admitted[:, action], 0, action] = probabilities @ utility
            calls += 1
            rows += count
    meter = {
        "prediction_calls": calls,
        "prediction_rows": rows,
        "state_update_calls": steps if len(x) else 0,
        "state_update_rows": steps * len(x),
        "history_encodings": len(x),
        "reserved_planning_candidate_rows": rows,
        "queried_episodes": len(x),
        "retained_state_bytes": resident,
        "inference_wall_seconds": perf_counter() - wall,
        "inference_process_cpu_seconds": process_time() - cpu,
        "forecast_total_wall_seconds": perf_counter() - total_wall,
        "forecast_total_process_cpu_seconds": process_time() - total_cpu,
        "tariff": asdict(tariff),
        "tariff_scope": "declared simulator episode-operations; not FLOPs or money",
        "unpriced": "admission, validation, training, transport, energy and money",
        "physical_cost_complete": False,
    }
    for value in (values, allowed, charged, delayed):
        value.setflags(write=False)
    return PreparationForecasts(values, allowed, charged, delayed, meter)


def forecast_preparations(
    model,
    history,
    legal_actions,
    deadline,
    remaining_budget,
    decision_work,
    decision_time,
    *,
    reset=False,
    mask_candidate_action=False,
):
    """Forecast from explicit actor inputs, without an evaluator or dataset port.

    ``decision_work`` and ``decision_time`` are declared simulator charges for
    the whole forecast and choice panel, not measured CPU, wall time or currency.
    Rows unable to reserve an option do not call the model. All comparison arms
    receive the same forecast panel. Host validation cost remains outside these
    simulated charges and is included only in end-to-end physical timing.
    """
    x = np.array(history, dtype=float, copy=True)
    if (
        x.ndim != 3
        or not 0 < len(x) <= 100_000
        or not 0 < x.shape[1] <= 256
        or x.shape[2] != INPUT_DIM
        or not np.isfinite(x).all()
        or type(reset) is not bool
        or type(mask_candidate_action) is not bool
    ):
        raise ValueError("invalid public history or reset policy")
    if mask_candidate_action:
        x[:, :, :3] = 0
    n, h, a, k = len(x), len(HORIZONS), len(ACTIONS), len(JOINT_SUPPORT)
    legal = np.array(legal_actions, copy=True)
    if legal.dtype != np.bool_ or legal.shape != (n, a):
        raise ValueError("legal actions must be a boolean row per episode")
    deadline = _nonnegative_vector(deadline, n, "deadline")
    budget = _nonnegative_vector(remaining_budget, n, "remaining_budget")
    charge = _nonnegative_vector(decision_work, n, "decision_work")
    delay = _nonnegative_vector(decision_time, n, "decision_time")
    ticks, preparation_cost = np.array([preparation_overhead(v) for v in HORIZONS]).T
    # These bounds come from the registered environment, never model quantiles.
    reserve_time = ticks + JOINT_SUPPORT[:, 1].max()
    reserve_cost = preparation_cost + JOINT_SUPPORT[:, 2].max()
    admissible = (
        legal[:, None, :]
        & (
            reserve_time[None, :, None] + delay[:, None, None]
            <= deadline[:, None, None]
        )
        & (reserve_cost[None, :, None] + charge[:, None, None] <= budget[:, None, None])
    )
    queried = admissible.any(axis=(1, 2))
    values = np.full((n, h, a), -np.inf)
    charged = np.where(queried, charge, 0)
    delayed = np.where(queried, delay, 0)
    x = x[queried]
    x.setflags(write=False)
    wall, cpu = perf_counter(), process_time()
    calls = 0
    if queried.any():
        for hi in range(h):
            utility = (
                JOINT_SUPPORT[:, 0]
                - COST_PENALTY * (JOINT_SUPPORT[:, 2] + preparation_cost[hi])
                - TIME_PENALTY * (JOINT_SUPPORT[:, 1] + ticks[hi])
            )
            for ai in range(a):
                query = np.tile(query_vector(ai, hi), (len(x), 1))
                if mask_candidate_action:
                    query[:, :a] = 0
                query.setflags(write=False)
                probabilities = _probabilities(
                    model.predict_proba(x, query, reset=reset), (len(x), k)
                )
                values[queried, hi, ai] = probabilities @ utility
                calls += 1
    meter = {
        "prediction_calls": calls,
        "prediction_rows": calls * len(x),
        "queried_episodes": len(x),
        "inference_wall_seconds": perf_counter() - wall,
        "inference_process_cpu_seconds": process_time() - cpu,
    }
    for value in (values, admissible, charged, delayed):
        value.setflags(write=False)
    return PreparationForecasts(values, admissible, charged, delayed, meter)


def choose_preparation(forecasts, *, fixed_horizon=None):
    """Choose positive future utility; equal values prefer shorter preparation.

    Already-incurred decision work and delay are common to execute and stop;
    they enter reported net utility and are not subtracted twice at choice.
    """
    if fixed_horizon is not None and (
        type(fixed_horizon) is not int or fixed_horizon not in HORIZONS
    ):
        raise ValueError("unsupported fixed preparation horizon")
    allowed = forecasts.admissible.copy()
    if fixed_horizon is not None:
        allowed[:, np.arange(len(HORIZONS)) != HORIZONS.index(fixed_horizon)] = False
    # Unadmitted rows already stopped before inference. They do not perform
    # the value-panel scan priced by the registered planning tariff.
    queried = forecasts.admissible.any(axis=(1, 2))
    selected = np.zeros(len(allowed), dtype=int)
    execute = np.zeros(len(allowed), dtype=bool)
    if queried.any():
        values = np.where(
            allowed[queried], forecasts.predicted_values[queried], -np.inf
        )
        flat = values.reshape(int(queried.sum()), -1)
        selected[queried] = flat.argmax(axis=1)
        execute[queried] = flat[np.arange(len(flat)), selected[queried]] > 0
    status = tuple(
        "execute"
        if act
        else "nonpositive_value"
        if admissible
        else "no_admissible_option"
        for act, admissible in zip(execute, allowed.any(axis=(1, 2)))
    )
    horizon = np.where(execute, selected // len(ACTIONS), -1)
    action = np.where(execute, selected % len(ACTIONS), -1)
    horizon.setflags(write=False)
    action.setflags(write=False)
    return PreparationChoices(horizon, action, status)


def choose_fixed_one(forecasts):
    """Compare only actually queried horizon-1 candidates against zero/STOP."""
    legal = forecasts.admissible[:, 0]
    actions = np.full(len(legal), -1)
    status = ["no_admissible_option"] * len(legal)
    for row in np.flatnonzero(legal.any(axis=1)):
        candidates = np.flatnonzero(legal[row])
        values = forecasts.predicted_values[row, 0, candidates]
        best = int(np.argmax(values))
        status[row] = "nonpositive_value"
        if values[best] > 0:
            actions[row], status[row] = candidates[best], "execute"
    horizons = np.where(actions >= 0, 0, -1)
    for value in (actions, horizons):
        value.setflags(write=False)
    return PreparationChoices(horizons, actions, tuple(status))


def evaluate_development_preparations(
    model,
    dataset,
    *,
    decision_work=None,
    decision_time=None,
    reset=False,
    fixed1_tariff=None,
    mask_candidate_action=False,
):
    """Compare shared forecasts on development data, never frozen confirmation.

    Outcomes are read only after every arm has chosen. Simulator charges and
    measured host time remain separate; physical costs and adoption stay HOLD.
    """
    total_wall, total_cpu = perf_counter(), process_time()
    if len(dataset.groups) != len(dataset.x) or not all(
        isinstance(group, str)
        and len(group.rsplit(":", 2)) == 3
        and group.rsplit(":", 2)[-2] == "dev"
        for group in dataset.groups
    ):
        raise ValueError("preparation comparison requires development groups")
    n, h, a, k = len(dataset.x), len(HORIZONS), len(ACTIONS), len(JOINT_SUPPORT)
    prefix = _nonnegative_vector(dataset.prefix_cost, n, "prefix_cost")
    if fixed1_tariff is not None:
        if not isinstance(fixed1_tariff, PreparationTariff):
            raise ValueError("fixed1_tariff must be a PreparationTariff")
        if decision_work is not None or decision_time is not None:
            raise ValueError(
                "tariff comparison derives both arms' charges; no panel override"
            )
        steps = (
            1
            if reset or getattr(model, "kind", None) == "single_step"
            else dataset.x.shape[1]
        )
        count = np.full(n, h * a)
        decision_work, decision_time = fixed1_tariff.charges(
            steps * count, count, count
        )
    forecasts = forecast_preparations(
        model,
        dataset.x,
        dataset.legal_actions,
        dataset.deadline,
        dataset.remaining_budget,
        decision_work,
        decision_time,
        reset=reset,
        mask_candidate_action=mask_candidate_action,
    )
    wall, cpu = perf_counter(), process_time()
    policies = {"adaptive": None, **{f"fixed_{value}": value for value in HORIZONS}}
    choices = {
        name: choose_preparation(forecasts, fixed_horizon=horizon)
        for name, horizon in policies.items()
    }
    choice_meter = {
        "choice_panel_wall_seconds": perf_counter() - wall,
        "choice_panel_process_cpu_seconds": process_time() - cpu,
    }
    arm_forecasts = {name: forecasts for name in choices}
    cheap = None
    if fixed1_tariff is not None:
        forecasts.meter.update(
            {
                "state_update_calls": steps * forecasts.meter["prediction_calls"],
                "state_update_rows": steps * forecasts.meter["prediction_rows"],
                "history_encodings": forecasts.meter["prediction_rows"],
                "planning_candidate_rows_per_arm": forecasts.meter["queried_episodes"]
                * h
                * a,
                "tariff": asdict(fixed1_tariff),
            }
        )
        policies = {name + "_shared_panel": value for name, value in policies.items()}
        choices = {name + "_shared_panel": value for name, value in choices.items()}
        arm_forecasts = {name: forecasts for name in choices}
        cheap = forecast_fixed_one(
            model,
            dataset.x,
            dataset.legal_actions,
            dataset.deadline,
            dataset.remaining_budget,
            tariff=fixed1_tariff,
            reset=reset,
            mask_candidate_action=mask_candidate_action,
        )
        wall, cpu = perf_counter(), process_time()
        choices["fixed_1_cheap"] = choose_fixed_one(cheap)
        cheap.meter.update(
            {
                "planning_candidate_rows": int(cheap.admissible[:, 0].sum()),
                "choice_wall_seconds": perf_counter() - wall,
                "choice_process_cpu_seconds": process_time() - cpu,
            }
        )
        arm_forecasts["fixed_1_cheap"] = cheap
        policies["fixed_1_cheap"] = 1
    # No evaluator field has been accessed before the choices above are frozen.
    wall, cpu = perf_counter(), process_time()
    evidence = dataset.evaluator
    bayes = _probabilities(evidence.bayes_joint, (n, h, a, k))
    classes = np.asarray(evidence.realized_class)
    if (
        classes.shape != (n, h, a)
        or not np.issubdtype(classes.dtype, np.integer)
        or ((classes < 0) | (classes >= k)).any()
    ):
        raise ValueError("invalid development evaluator classes")
    ticks, prep = np.array([preparation_overhead(v) for v in HORIZONS]).T
    atom = (
        JOINT_SUPPORT[None, :, 0]
        - COST_PENALTY * (JOINT_SUPPORT[None, :, 2] + prep[:, None])
        - TIME_PENALTY * (JOINT_SUPPORT[None, :, 1] + ticks[:, None])
    )
    posterior = np.einsum("nhak,hk->nha", bayes, atom)
    arms = {}
    for name, choice in choices.items():
        current = arm_forecasts[name]
        charged = current.decision_work_charged
        delayed = current.decision_time_charged
        active = choice.action >= 0
        rows = np.flatnonzero(active)
        hi, ai = choice.horizon_index[active], choice.action[active]
        selected = JOINT_SUPPORT[classes[rows, hi, ai]]
        elapsed, cost, success, expected = (np.zeros(n) for _ in range(4))
        success[active], elapsed[active], cost[active] = selected.T
        elapsed[active] += ticks[hi]
        cost[active] += prep[hi]
        expected[active] = posterior[rows, hi, ai]
        allowed = current.admissible.copy()
        if policies[name] is not None:
            allowed[:, np.arange(h) != HORIZONS.index(policies[name])] = False
        oracle = np.maximum(0, np.where(allowed, posterior, -np.inf).max(axis=(1, 2)))
        full_cost = prefix + charged + cost
        total_elapsed = delayed + elapsed
        realized = success - COST_PENALTY * full_cost - TIME_PENALTY * total_elapsed
        net = expected - COST_PENALTY * (prefix + charged) - TIME_PENALTY * delayed
        arms[name] = {
            "expected_net_utility": float(net.mean()),
            "realized_net_utility": float(realized.mean()),
            "bayes_regret": float((oracle - expected).mean()),
            "complete_environment_cost": float(full_cost.mean()),
            "stop_rate": float((~active).mean()),
            "per_episode": {
                "selected_horizon": [
                    HORIZONS[i] if i >= 0 else None for i in choice.horizon_index
                ],
                "selected_action": choice.action.tolist(),
                "status": list(choice.status),
                "expected_net_utility": net.tolist(),
                "realized_net_utility": realized.tolist(),
                "prefix_cost": prefix.tolist(),
                "decision_work": charged.tolist(),
                "decision_time": delayed.tolist(),
                "future_cost": cost.tolist(),
                "future_elapsed_time": elapsed.tolist(),
                "elapsed_time": total_elapsed.tolist(),
                "complete_environment_cost": full_cost.tolist(),
            },
        }
    return {
        "schema": "pred1-preparation-development-v3"
        if cheap is not None
        else "pred1-preparation-development-v2",
        "status": "HOLD",
        "scope": "development-only finite simulator; no production adoption",
        "autoregressive_rollout_evaluated": False,
        "horizon_selection_evaluated": True,
        "reservation": "full tool support plus preparation and decision work/time",
        "comparison": "same model/history and tariff; legacy shared panel versus cached legal-only Fixed1"
        if cheap is not None
        else "same model, history, forecast panel and declared decision work/time",
        "arms": arms,
        "meter": {
            **forecasts.meter,
            **choice_meter,
            **(
                {
                    "shared_panel": forecasts.meter,
                    "fixed_1_cheap": cheap.meter,
                    "prediction_calls": forecasts.meter["prediction_calls"]
                    + cheap.meter["prediction_calls"],
                    "prediction_rows": forecasts.meter["prediction_rows"]
                    + cheap.meter["prediction_rows"],
                    "inference_wall_seconds": forecasts.meter["inference_wall_seconds"]
                    + cheap.meter["inference_wall_seconds"],
                    "inference_process_cpu_seconds": forecasts.meter[
                        "inference_process_cpu_seconds"
                    ]
                    + cheap.meter["inference_process_cpu_seconds"],
                }
                if cheap is not None
                else {}
            ),
            "evaluation_wall_seconds": perf_counter() - wall,
            "evaluation_process_cpu_seconds": process_time() - cpu,
            "end_to_end_wall_seconds": perf_counter() - total_wall,
            "end_to_end_process_cpu_seconds": process_time() - total_cpu,
            "shared_panel_charged_to_each_arm": cheap is None,
            "environment_cost_unit": "simulator_dimensionless_work",
            "decision_time_unit": "simulator_ticks; not measured host wall time",
            "training_cost": None,
            "energy_joules": None,
            "financial_cost": None,
            "physical_cost_complete": False,
        },
    }
