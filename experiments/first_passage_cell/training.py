"""Joint likelihood training of drift, input weights, diffusion, barrier and reset."""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

from .cell import CellParameters, canonical_bytes, sample_hitting_time
from .kernels import first_passage, first_passage_gradients
from .task import REFRACTORY, named_seed, true_parameters

PARAMETER_NAMES = ("drift", "weight_0", "weight_1", "log_sigma", "barrier", "log_reset_gap")
BOUNDS = [(-1.3, 0.2), (-0.6, 0.6), (-0.6, 0.6),
          (math.log(0.15), math.log(0.75)), (-0.1, 0.4),
          (math.log(0.25), math.log(1.6))]


def parameters_from_vector(vector):
    values = np.asarray(vector, dtype=np.float64)
    if values.shape not in {(6,), (7,)} or not np.isfinite(values).all():
        raise ValueError("Expected six or seven finite physical coefficients")
    return CellParameters(float(values[0]), (float(values[1]), float(values[2])),
                          float(np.exp(values[3])), float(values[4]),
                          float(np.exp(values[5])), REFRACTORY,
                          float(values[6]) if len(values) == 7 else 0.0)


def generate_renewal_data(seed, trajectories=512, phase="training"):
    """Independent inverse-Gaussian generator; no likelihood CDF is called.

    Every trajectory starts at a measured absolute level. After a spike the
    learned reset gap determines the next interspike distribution. Initial
    levels distinguish barrier from reset gap; no time/voltage scale is free.
    """
    if phase not in {"training", "development", "diagnostic"}:
        raise ValueError("Confirmation trajectories are not training data")
    truth = true_parameters()
    rng = np.random.Generator(np.random.Philox(named_seed(seed, "renewal:" + phase)))
    rows = []
    for trajectory in range(trajectories):
        initial_level = float(rng.uniform(0.65, 1.9))
        remaining = float(rng.uniform(2.4, 4.0))
        after_reset = False
        while remaining > 0:
            inputs = rng.uniform(-1, 1, size=2)
            distance = truth.reset_gap if after_reset else initial_level - truth.barrier
            waiting = sample_hitting_time(distance, truth.mu(inputs), truth.sigma, rng)
            event = waiting <= remaining
            duration = waiting if event else remaining
            rows.append((trajectory, initial_level, inputs[0], inputs[1],
                         after_reset, duration, event))
            if not event:
                break
            remaining -= waiting + truth.refractory
            after_reset = True
    array = np.asarray(rows, dtype=np.float64)
    return {"trajectory": array[:, 0].astype(np.int64), "initial_level": array[:, 1],
            "inputs": array[:, 2:4], "after_reset": array[:, 4].astype(bool),
            "duration": array[:, 5], "event": array[:, 6].astype(bool),
            "trajectories": int(trajectories), "seed": int(seed), "phase": phase}


def dataset_digest(data):
    digest = hashlib.sha256()
    for name in ("trajectory", "initial_level", "inputs", "after_reset", "duration", "event"):
        array = np.ascontiguousarray(data[name])
        digest.update(canonical_bytes([name, str(array.dtype), list(array.shape)]))
        digest.update(array.tobytes())
    digest.update(canonical_bytes({k: data[k] for k in ("trajectories", "seed", "phase")}))
    return digest.hexdigest()


def objective_and_gradient(vector, data):
    parameters = parameters_from_vector(vector)
    inputs = data["inputs"]
    drift = parameters.drift + inputs @ np.asarray(parameters.weights)
    if len(vector) == 7:
        drift += parameters.interaction * inputs[:, 0] * inputs[:, 1]
    reset = data["after_reset"]
    distance = np.where(reset, parameters.reset_gap, data["initial_level"] - parameters.barrier)
    if np.any(distance <= 0) or np.any(data["duration"] <= 0):
        raise ValueError("Training likelihood requires positive distances and durations")
    result = first_passage(distance, drift, parameters.sigma, data["duration"])
    derivatives = first_passage_gradients(distance, drift, parameters.sigma, data["duration"])
    event = data["event"]
    log_likelihood = np.where(event, result["log_f"], result["log_S"])
    component = {name: np.where(event, derivatives["log_f"][name], derivatives["log_S"][name])
                 for name in ("x", "mu", "sigma")}
    denom = data["trajectories"]
    gradient = np.array([
        -np.sum(component["mu"]) / denom,
        -np.sum(component["mu"] * inputs[:, 0]) / denom,
        -np.sum(component["mu"] * inputs[:, 1]) / denom,
        -np.sum(component["sigma"]) * parameters.sigma / denom,
        np.sum(component["x"] * ~reset) / denom,
        -np.sum(component["x"] * reset) * parameters.reset_gap / denom,
    ])
    if len(vector) == 7:
        gradient = np.append(gradient,
                             -np.sum(component["mu"] * inputs[:, 0] * inputs[:, 1]) / denom)
    loss = -float(np.sum(log_likelihood)) / denom
    if not math.isfinite(loss) or not np.isfinite(gradient).all():
        raise ArithmeticError("Non-finite joint event-time likelihood or gradient")
    return loss, gradient


def fit_cell(seed, data, interaction=False, max_iterations=120):
    if data["phase"] != "training":
        raise ValueError("Only explicitly labeled training data may fit physical parameters")
    rng = np.random.Generator(np.random.Philox(named_seed(seed, "initialization")))
    initial = np.array([-0.38 + rng.uniform(-0.04, 0.04), *rng.uniform(-0.04, 0.04, size=2),
                        math.log(0.45), 0.02, math.log(1.1)])
    bounds = list(BOUNDS)
    if interaction:
        initial = np.append(initial, 0.02)
        bounds.append((-0.5, 0.5))
    trace = []
    started = time.perf_counter()

    def objective(vector):
        loss, gradient = objective_and_gradient(vector, data)
        trace.append({"evaluation": len(trace), "loss": loss,
                      "gradient_norm": float(np.linalg.norm(gradient))})
        return loss, gradient

    initial_loss, initial_gradient = objective_and_gradient(initial, data)
    fit = minimize(objective, initial, method="L-BFGS-B", jac=True, bounds=bounds,
                   options={"maxiter": max_iterations, "maxfun": 400,
                            "ftol": 1e-11, "gtol": 1e-7, "maxls": 30})
    selected = parameters_from_vector(fit.x)
    final_loss, final_gradient = objective_and_gradient(fit.x, data)
    names = PARAMETER_NAMES + (("interaction",) if interaction else ())
    receipt = {
        "profile": "hepta-first-passage-joint-likelihood-v1",
        "seed": seed, "dataset_sha256": dataset_digest(data),
        "trajectories": data["trajectories"], "likelihood_rows": len(data["event"]),
        "observed_events": int(np.count_nonzero(data["event"])),
        "right_censored_rows": int(np.count_nonzero(~data["event"])),
        "parameter_names": list(names), "active_parameter_count": len(fit.x),
        "initial_vector": initial.tolist(), "selected_vector": fit.x.tolist(),
        "initial_loss": initial_loss, "selected_loss": final_loss,
        "initial_gradient": initial_gradient.tolist(), "selected_gradient": final_gradient.tolist(),
        "absolute_parameter_change": dict(zip(names, np.abs(fit.x - initial).tolist())),
        "optimizer": "scipy L-BFGS-B with analytic chain-rule gradient",
        "optimizer_success": bool(fit.success), "optimizer_message": str(fit.message),
        "iterations": int(fit.nit), "function_evaluations": int(fit.nfev),
        "max_iterations": max_iterations, "max_function_evaluations": 400,
        "wall_seconds": time.perf_counter() - started, "trace": trace,
        "selected_parameters": asdict(selected), "model_digest": selected.digest(),
        "loss_scope": "joint renewal trajectory likelihood, not independent interval samples",
        "hard_spike_backpropagation": False,
    }
    return selected, receipt


def save_dataset(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {k: v for k, v in data.items() if isinstance(v, np.ndarray)}
    metadata = {k: v for k, v in data.items() if not isinstance(v, np.ndarray)}
    arrays["metadata_utf8"] = np.frombuffer(canonical_bytes(metadata), dtype=np.uint8)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path):
    with np.load(path, allow_pickle=False) as values:
        metadata = json.loads(values["metadata_utf8"].tobytes())
        data = {k: values[k].copy() for k in values.files if k != "metadata_utf8"}
    return {**data, **metadata}
