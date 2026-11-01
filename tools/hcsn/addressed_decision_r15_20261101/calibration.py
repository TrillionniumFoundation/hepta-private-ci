"""Observed-sequence calibration with common information and measured budgets.

The only supervision is a public initial WRITE followed by raw timed tokens.
Hidden CTMC states exist only inside ``make_training``.  Financial parameters,
hidden phases, current content labels and teacher beliefs are never returned in
the public data.  Validation chooses a free-rate CTMC or the matrix HMM that
reuses the fitted HX model; identical matrices are not charged as free learning.
"""

import copy
import hashlib
import json
import math
import time

import numpy as np
from scipy.optimize import minimize

from .law import Law, default_free_raw


DEFAULT_CONFIG = {
    "train_count": 64,
    "validation_count": 32,
    "sequence_length": 8,
    "train_dts": [0.15, 0.45, 1.05, 2.10],
    "refresh_probability": 0.25,
    "true_theta": [0.30, 0.020],
    "initial_theta": [0.27, 0.016],
    "initial_jitter": [0.015, 0.002],
    "hx_bounds": [[0.18, 0.38], [0.004, 0.035]],
    "free_bounds": [[-2.995732273553991, 3.4011973816621555]] * 3
                   + [[-5.0, 5.0]],
    "max_evals": 80,
    "cpu_seconds": 8.0,
    "train_seed_offset": 11_000_000,
    "validation_seed_offset": 21_000_000,
}


def data_identity(data):
    """Hash canonical public sequence bytes, excluding only the hash itself."""
    raw = {key: value for key, value in data.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def make_training(law, seed, count=64, length=8, dts=(0.15, 0.45, 1.05, 2.10),
                  refresh_probability=0.25):
    """Sample a public raw-sequence dataset; the sampled hidden states stay local.

    WRITE fixes initial content while the physical phase has the law's reset
    prior.  Each interval elapses before its scheduled read.  Refresh is merely
    a publicly announced higher-quality observation channel in this calibration
    dataset; it neither teleports the hidden state nor supplies its content.
    """
    if not isinstance(seed, int) or seed < 0 or count < 1 or length < 1:
        raise ValueError("Nonnegative integer seed and positive dataset sizes required")
    durations = np.asarray(dts, dtype=float)
    if (durations.ndim != 1 or not len(durations) or not np.isfinite(durations).all()
            or np.any(durations < 0) or not 0 <= refresh_probability <= 1):
        raise ValueError("Finite nonnegative durations and a valid refresh probability required")
    rng = np.random.default_rng(seed)
    transitions = {float(dt): law.transition(float(dt)) for dt in durations}
    sequences = []
    for _ in range(int(count)):
        value = int(rng.integers(4))
        prior = np.asarray(law.initial_prior(value), dtype=float)
        state = int(rng.choice(len(prior), p=prior / prior.sum()))
        observations = []
        for _ in range(int(length)):
            dt = float(rng.choice(durations))
            row = transitions[dt][state]
            state = int(rng.choice(len(row), p=row / row.sum()))
            quality = "refresh" if rng.random() < refresh_probability else "read"
            emission = law.E_refresh if quality == "refresh" else law.E_read
            token = int(rng.choice(emission.shape[1], p=emission[state]))
            observations.append({"dt": dt, "quality": quality, "token": token})
        sequences.append({"initial_value": value, "observations": observations})
    data = {"schema": "hcsn.public_observed_sequences.v1", "seed": seed,
            "count": int(count), "length": int(length), "dts": durations.tolist(),
            "refresh_probability": float(refresh_probability), "sequences": sequences}
    data["sha256"] = data_identity(data)
    return data


def _compile(data):
    if isinstance(data, dict):
        if data.get("sha256") is not None and data_identity(data) != data["sha256"]:
            raise ValueError("Public sequence identity changed")
        sequences = data["sequences"]
    else:
        sequences = data
    if not sequences:
        raise ValueError("At least one public sequence is required")
    lengths = [len(row["observations"]) for row in sequences]
    if min(lengths) < 1 or len(set(lengths)) != 1:
        raise ValueError("This registered vectorized likelihood uses equal positive sequence lengths")
    shape = (len(sequences), lengths[0])
    initial = np.empty(shape[0], dtype=int)
    dt, quality, token = np.empty(shape), np.empty(shape, dtype=int), np.empty(shape, dtype=int)
    for i, row in enumerate(sequences):
        if set(row) != {"initial_value", "observations"}:
            raise ValueError("Only public initial_value and observations may enter a training sequence")
        value = row["initial_value"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 4:
            raise ValueError("Initial WRITE value must be an integer in [0,4)")
        initial[i] = value
        for j, event in enumerate(row["observations"]):
            if set(event) != {"dt", "quality", "token"}:
                raise ValueError("A public event contains only dt, quality and token")
            if event["quality"] not in ("read", "refresh"):
                raise ValueError("Unknown public observation channel")
            q = int(event["quality"] == "refresh")
            k = event["token"]
            if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k < (4 if q else 5):
                raise ValueError("Raw token outside its observation alphabet")
            dt[i, j], quality[i, j], token[i, j] = event["dt"], q, k
    if not np.isfinite(dt).all() or np.any(dt < 0):
        raise ValueError("Invalid public elapsed time")
    return initial, dt, quality, token


def _log_likelihood(compiled, law):
    initial, dt, quality, token = compiled
    p = np.stack([law.initial_prior(int(value)) for value in initial])
    transitions = {float(t): law.transition(float(t)) for t in np.unique(dt)}
    result = 0.0
    for j in range(dt.shape[1]):
        for duration in np.unique(dt[:, j]):
            selected = dt[:, j] == duration
            p[selected] = p[selected] @ transitions[float(duration)]
        for channel, emission in ((0, law.E_read), (1, law.E_refresh)):
            selected = quality[:, j] == channel
            if np.any(selected):
                p[selected] *= emission[:, token[selected, j]].T
        mass = p.sum(axis=1)
        if np.any(mass <= 0) or not np.isfinite(mass).all():
            return -math.inf
        result += float(np.log(mass).sum())
        p /= mass[:, None]
    return result


def likelihood(train_sequences, law):
    """Total log P(raw timed tokens | known WRITE, observation schedule, law).

    Initial values and schedules are conditioned on, not learned targets.
    Impossible observations return -inf instead of an invented probability floor.
    """
    return _log_likelihood(_compile(train_sequences), law)


class _BudgetExhausted(RuntimeError):
    pass


def _candidate(mode, seed, compiled, config, theta_initial):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    evaluations, best, result = [], None, None
    # Both candidate starts describe the same Q; the free-rate conversion cost
    # is measured inside its own budget, not borrowed from the HX fit.
    x0 = (np.asarray(theta_initial, dtype=float) if mode == "hx" else
          np.asarray(default_free_raw(tuple(theta_initial)), dtype=float))
    bounds = config["hx_bounds"] if mode == "hx" else config["free_bounds"]
    if np.any(x0 < np.asarray(bounds)[:, 0]) or np.any(x0 > np.asarray(bounds)[:, 1]):
        raise ValueError("Declared initialization is outside the declared bounds")
    observations = compiled[1].size

    def objective(parameters):
        nonlocal best
        if len(evaluations) >= config["max_evals"]:
            raise _BudgetExhausted("maximum_evaluations")
        if time.process_time() - started_cpu >= config["cpu_seconds"]:
            raise _BudgetExhausted("cpu_budget")
        call_cpu, call_wall = time.process_time(), time.perf_counter()
        row = {"evaluation": len(evaluations) + 1, "parameters": parameters.tolist()}
        value = 1e12
        try:
            candidate = (Law(theta=tuple(parameters), mode="hx") if mode == "hx" else
                         Law(mode="free", free_raw=parameters))
            loglik = _log_likelihood(compiled, candidate)
            if not math.isfinite(loglik):
                raise FloatingPointError("Candidate gives an impossible or nonfinite observation likelihood")
            value = -loglik / observations
            row.update(status="valid", total_log_likelihood=loglik, mean_nll=value)
            if best is None or value < best["mean_nll"]:
                best = {"mean_nll": value, "log_likelihood": loglik,
                        "parameters": parameters.tolist(), "model": candidate,
                        "evaluation": row["evaluation"]}
        except (ValueError, FloatingPointError, ArithmeticError, np.linalg.LinAlgError) as error:
            row.update(status="rejected", error_type=type(error).__name__, error=str(error))
        row.update(cpu_seconds=time.process_time() - call_cpu,
                   wall_seconds=time.perf_counter() - call_wall,
                   elapsed_cpu_seconds=time.process_time() - started_cpu)
        evaluations.append(row)
        return value

    status, stop_reason = "optimizer_stopped", None
    try:
        result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                          options={"maxfun": config["max_evals"], "maxiter": config["max_evals"],
                                   "maxls": 10, "ftol": 1e-9, "gtol": 1e-5})
        status = "converged" if result.success else "optimizer_stopped"
        stop_reason = str(result.message)
    except _BudgetExhausted as error:
        status, stop_reason = "budget_exhausted", str(error)
    except Exception as error:
        status, stop_reason = "optimizer_exception", f"{type(error).__name__}: {error}"
    payload = None if best is None else best["model"].export()
    return {"candidate": mode, "seed": int(seed), "status": status if best else "failed",
            "stop_reason": stop_reason, "optimizer_success": bool(result.success) if result is not None else False,
            "optimizer": "L-BFGS-B with observed-likelihood finite differences",
            "initial_parameters": x0.tolist(), "bounds": copy.deepcopy(bounds),
            "declared_parameter_count": len(x0), "budget_cpu_seconds": config["cpu_seconds"],
            "maximum_evaluations": config["max_evals"], "evaluations": evaluations,
            "valid_evaluations": sum(row["status"] == "valid" for row in evaluations),
            "selected_evaluation": None if best is None else best["evaluation"],
            "selected_parameters": None if best is None else best["parameters"],
            "training_log_likelihood": None if best is None else best["log_likelihood"],
            "payload": payload, "fit_cpu_seconds": time.process_time() - started_cpu,
            "fit_wall_seconds": time.perf_counter() - started_wall,
            "budget_scope": "Initialization, all successful/rejected objective calls, optimizer and final export; one operation may overshoot"}


def fit(seed, config=None):
    """Calibrate both candidates, then select the ordinary model on public validation.

    Returned ``training`` and ``validation`` are directly JSON serializable.
    Models contain ``payload`` accepted by ``Law.from_payload``.  ``true_theta``
    is used only to sample the two public datasets, never to initialize or score
    a candidate.  Validation is not consulted by the training optimizer.
    """
    config = {} if config is None else dict(config)
    if set(config) - set(DEFAULT_CONFIG):
        raise ValueError(f"Unknown calibration configuration keys: {sorted(set(config) - set(DEFAULT_CONFIG))}")
    effective = copy.deepcopy(DEFAULT_CONFIG)
    effective.update(config)
    if not isinstance(seed, int) or not 0 <= seed < 1_000_000:
        raise ValueError("Fit seed must be an integer in [0,1000000) for disjoint streams")
    if effective["max_evals"] < 1 or effective["cpu_seconds"] <= 0:
        raise ValueError("Positive finite optimization budgets required")
    train_seed = effective["train_seed_offset"] + seed
    validation_seed = effective["validation_seed_offset"] + seed
    if train_seed == validation_seed:
        raise ValueError("Training and validation streams must differ")
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    common_started = time.process_time()
    true_law = Law(theta=tuple(effective["true_theta"]), mode="hx")
    training = make_training(true_law, train_seed, effective["train_count"],
                             effective["sequence_length"], effective["train_dts"],
                             effective["refresh_probability"])
    validation = make_training(true_law, validation_seed, effective["validation_count"],
                               effective["sequence_length"], effective["train_dts"],
                               effective["refresh_probability"])
    del true_law
    compiled, valid_compiled = _compile(training), _compile(validation)
    common_cpu = time.process_time() - common_started
    rng = np.random.default_rng(np.random.SeedSequence([seed, 6239]))
    theta_initial = np.asarray(effective["initial_theta"]) + rng.uniform(-1, 1, 2) * effective["initial_jitter"]
    order = ["hx", "free"] if seed % 2 else ["free", "hx"]
    models = {mode: _candidate(mode, seed, compiled, effective, theta_initial) for mode in order}
    validation_cost = {}
    for name in ("hx", "free"):
        begin = time.process_time()
        item = models[name]
        if item["payload"] is None:
            item["validation_log_likelihood"] = None
            item["validation_status"] = "no_valid_training_model"
        else:
            try:
                restored = Law.from_payload(item["payload"])
                score = _log_likelihood(valid_compiled, restored)
                if not math.isfinite(score):
                    raise FloatingPointError("Impossible or nonfinite validation likelihood")
                item["validation_log_likelihood"] = score
                item["validation_status"] = "completed"
            except (ValueError, FloatingPointError, ArithmeticError, np.linalg.LinAlgError) as error:
                item["validation_log_likelihood"] = None
                item["validation_status"] = "failed"
                item["validation_error"] = f"{type(error).__name__}: {error}"
        validation_cost[name] = time.process_time() - begin
        item["validation_cpu_seconds"] = validation_cost[name]
        item["training_data_sha256"] = training["sha256"]
        item["validation_data_sha256"] = validation["sha256"]
    alias_started = time.process_time()
    models["hmm_same_matrix"] = {
        "candidate": "hmm_same_matrix", "status": "reused_fitted_matrix" if models["hx"]["payload"] else "failed",
        "payload": copy.deepcopy(models["hx"]["payload"]),
        "training_log_likelihood": models["hx"]["training_log_likelihood"],
        "validation_log_likelihood": models["hx"]["validation_log_likelihood"],
        "training_data_sha256": training["sha256"], "validation_data_sha256": validation["sha256"],
        "calibration_source": "hx", "independent_training": False,
        "cost_rule": "Reused calibration is charged once in shared execution and fully in standalone deployment"}
    alias_cpu = time.process_time() - alias_started
    eligible = [name for name in ("hmm_same_matrix", "free")
                if models[name]["validation_log_likelihood"] is not None]
    selected = max(eligible, key=lambda name: models[name]["validation_log_likelihood"]) if eligible else None
    hx_cpu, free_cpu = models["hx"]["fit_cpu_seconds"], models["free"]["fit_cpu_seconds"]
    accounting = {
        "common_public_data_cpu_seconds": common_cpu,
        "hx_calibration_cpu_seconds": hx_cpu, "free_calibration_cpu_seconds": free_cpu,
        "validation_cpu_seconds": validation_cost, "matrix_alias_cpu_seconds": alias_cpu,
        "itemized_calibration_cpu_seconds": common_cpu + hx_cpu + free_cpu + sum(validation_cost.values()) + alias_cpu,
        "standalone_hx_cpu_seconds": common_cpu + hx_cpu + validation_cost["hx"],
        "standalone_free_cpu_seconds": common_cpu + free_cpu + validation_cost["free"],
        "standalone_same_matrix_hmm_cpu_seconds": common_cpu + hx_cpu + validation_cost["hx"] + alias_cpu,
        "equal_calibration_hx_cpu_seconds": common_cpu + hx_cpu + validation_cost["hx"],
        "equal_calibration_hmm_cpu_seconds": common_cpu + hx_cpu + validation_cost["hx"] + alias_cpu,
        "shared_reuse_hmm_incremental_cpu_seconds": alias_cpu,
        "scope": "Calibration fit-function CPU only; parent must meter interpreter/imports and JSON saving; no deployment communication, recovery I/O or energy included",
        "common_charge_rule": "Common data charged once per complete search; standalone columns are alternatives, not addends",
    }
    total_cpu = time.process_time() - started_cpu
    accounting["all_search_cpu_seconds"] = total_cpu
    accounting["unallocated_function_overhead_cpu_seconds"] = total_cpu - accounting["itemized_calibration_cpu_seconds"]
    return {"schema": "hcsn.observed_calibration.v1", "seed": seed, "config": effective,
            "training": training, "validation": validation, "models": models,
            "selection": {"ordinary": selected, "criterion": "Highest public validation raw-sequence log likelihood",
                          "tie_order": ["hmm_same_matrix", "free"], "candidate_order": order,
                          "confirmation_used": False},
            "accounting": accounting,
            "timing": {"total_cpu_seconds": total_cpu,
                       "total_wall_seconds": time.perf_counter() - started_wall}}
