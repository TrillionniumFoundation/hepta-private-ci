"""Shared-observation critic probes; no new-RL or production benefit claim."""

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


@dataclass(frozen=True)
class Panel:
    name: str = "base"
    dimension: int = 2
    noise: float = 0.2
    adjustment: float = 0.03
    complementarity: float = 0.6
    capacity: int = 2
    resident: int = 2
    load_cost: float = 0.0
    model_bias: float = 0.0
    reset_probability: float = 0.5

    def __post_init__(self):
        if (
            type(self.dimension) is not int
            or not 2 <= self.dimension <= 8
            or type(self.capacity) is not int
            or not 1 <= self.capacity <= self.dimension
            or type(self.resident) is not int
            or not 0 <= self.resident <= self.dimension
            or not self.name
            or any(
                not math.isfinite(x)
                for x in (
                    self.noise,
                    self.adjustment,
                    self.complementarity,
                    self.load_cost,
                    self.model_bias,
                    self.reset_probability,
                )
            )
            or min(self.noise, self.adjustment, self.load_cost) < 0
            or not 0 <= self.complementarity < 1
            or not 0 <= self.reset_probability <= 1
        ):
            raise ValueError("Invalid bounded structural panel")


def panels():
    p = Panel()
    return [
        p,
        replace(p, name="noise_zero", noise=0.0),
        replace(p, name="noise_small", noise=1e-6),
        replace(p, name="noise_large", noise=0.7),
        replace(p, name="dimension_four", dimension=4, resident=4),
        replace(p, name="adjustment_high", adjustment=0.5),
        replace(p, name="complementarity_zero", complementarity=0.0),
        replace(p, name="resource_residency", capacity=1, resident=1, load_cost=0.15),
        replace(p, name="model_error", model_bias=0.3),
        replace(p, name="reset_always", reset_probability=1.0),
        replace(p, name="reset_never", reset_probability=0.0),
    ]


def protocol():
    return {
        "schema": "ndu-critic-structure-v1",
        "seeds": [101, 211, 307, 401, 503],
        "panels": [asdict(p) for p in panels()],
        "train_n": 96,
        "test_n": 128,
        "mc_replicates": 8,
        "stencil_step": 0.02,
        "sensor_sd": 0.002,
        "action_step": 0.45,
        "reset_cost": 0.08,
        "hidden": 12,
        "neural_updates": 160,
        "neural_lr": 0.025,
        "ridge": 1e-5,
        "families": ["linear", "quadratic", "neural"],
        "targets": ["value", "direct_gradient", "z_gradient"],
        "shared_information": "All critics may access the identical full value stencil; labels are representations of it.",
        "conditioning": "Z labels equal sigma times paired gradient labels; no extra noise is injected in a competing arm.",
        "scope": "Supervised one-decision structural probe, not actor-critic RL or a multi-step resource benchmark.",
        "budget": "Identical observations, separate measured training/inference costs; capacity and CPU are not matched.",
        "selection": "No heldout tuning or winner selection; all seeds, models and zero-noise rejections retained.",
        "objective": "Expected terminal quality less adjustment/load/reset fees; measured CPU has no utility tariff.",
        "open_gates": [
            "matched effective capacity and CPU",
            "multi-step RL and rsEAC comparison",
            "independent real tasks",
            "full physical cost net gain",
            "future time window",
        ],
    }


def quality(x, panel, bias=0.0):
    """Physical terminal quality; last axis is the internal state."""
    b = np.linspace(-0.25, 0.45, panel.dimension) + bias
    a = np.linspace(0.5, 1.0, panel.dimension) / math.sqrt(panel.dimension)
    return (
        -0.5 * np.mean((x - b) ** 2, axis=-1)
        + panel.complementarity * x[..., 0] * x[..., 1] / panel.dimension
        + 0.15 * np.sin(x @ a)
    )


def exact_value_gradient(x, panel):
    """Independent analytic Gaussian expectation, for evaluation/references only."""
    b = np.linspace(-0.25, 0.45, panel.dimension)
    a = np.linspace(0.5, 1.0, panel.dimension) / math.sqrt(panel.dimension)
    damp = math.exp(-0.5 * panel.noise**2 * float(a @ a))
    value = (
        -0.5 * np.mean((x - b) ** 2, axis=-1)
        - 0.5 * panel.noise**2
        + panel.complementarity * x[..., 0] * x[..., 1] / panel.dimension
        + 0.15 * damp * np.sin(x @ a)
    )
    grad = -(x - b) / panel.dimension + 0.15 * damp * np.cos(x @ a)[..., None] * a
    grad[..., 0] += panel.complementarity * x[..., 1] / panel.dimension
    grad[..., 1] += panel.complementarity * x[..., 0] / panel.dimension
    return value, grad


def array_digest(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a, dtype="<f8")
        h.update(json.dumps(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def observations(panel, seed, n, settings):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 17, panel.dimension]))
    x = rng.uniform(-1, 1, (n, panel.dimension))
    offsets = [np.zeros(panel.dimension)]
    for axis in np.eye(panel.dimension):
        offsets.extend([settings["stencil_step"] * axis, -settings["stencil_step"] * axis])
    locations = x[:, None, :] + np.asarray(offsets)[None, :, :]
    eps = rng.normal(size=(n, settings["mc_replicates"], panel.dimension))
    # The same actual internal noise realizes every counterfactual stencil point.
    outcomes = quality(locations[:, :, None, :] + panel.noise * eps[:, None, :, :], panel, panel.model_bias)
    outcomes += settings["sensor_sd"] * rng.normal(size=outcomes.shape)
    values = outcomes.mean(axis=2)
    gradients = (values[:, 1::2] - values[:, 2::2]) / (2 * settings["stencil_step"])
    return {
        "x": x,
        "locations": locations,
        "outcomes": outcomes,
        "values": values,
        "gradients": gradients,
        "sha256": array_digest(locations, outcomes),
    }


def features(x, family):
    cols = [np.ones(len(x))] + [x[:, i] for i in range(x.shape[1])]
    jac = [np.zeros_like(x)] + [np.broadcast_to(e, x.shape) for e in np.eye(x.shape[1])]
    if family == "quadratic":
        for i in range(x.shape[1]):
            for j in range(i, x.shape[1]):
                cols.append(x[:, i] * x[:, j])
                g = np.zeros_like(x)
                g[:, i] += x[:, j]
                g[:, j] += x[:, i]
                jac.append(g)
    return np.stack(cols, axis=1), np.stack(jac, axis=1)


def fit(family, kind, data, panel, seed, settings):
    if family not in settings["families"] or kind not in settings["targets"]:
        raise ValueError("Unknown critic family or target")
    if kind == "z_gradient" and panel.noise == 0:
        raise ValueError("Z is zero for every gradient at zero diffusion; inversion is unidentified")
    if kind == "value":
        x, y = data["locations"].reshape(-1, panel.dimension), data["values"].reshape(-1, 1)
    else:
        x, y = data["x"], data["gradients"] * (panel.noise if kind == "z_gradient" else 1)
    mean, scale = y.mean(axis=0), y.std(axis=0)
    scale = np.where(scale == 0, 1, scale)
    target = (y - mean) / scale
    if not np.isfinite(target).all():
        raise ValueError("Nonfinite training observation")
    model = {"family": family, "kind": kind, "mean": mean, "scale": scale, "noise": panel.noise}
    if family != "neural":
        f, _ = features(x, family)
        penalty = settings["ridge"] * np.eye(f.shape[1])
        penalty[0, 0] = 0
        model["parameters"] = [np.linalg.solve(f.T @ f / len(f) + penalty, f.T @ target / len(f))]
        updates = 1
    else:
        rng = np.random.default_rng(np.random.SeedSequence([seed, 719, panel.dimension]))
        width, outputs = settings["hidden"], target.shape[1]
        params = [
            rng.normal(0, 0.35, (panel.dimension, width)),
            np.zeros(width),
            rng.normal(0, 0.15, (width, outputs)),
            np.zeros(outputs),
        ]
        moments, squares = [np.zeros_like(p) for p in params], [np.zeros_like(p) for p in params]
        for t in range(1, settings["neural_updates"] + 1):
            w, b, head, bias = params
            hidden = np.tanh(x @ w + b)
            error = 2 * (hidden @ head + bias - target) / target.size
            back = (error @ head.T) * (1 - hidden**2)
            grads = [x.T @ back, back.sum(0), hidden.T @ error, error.sum(0)]
            for p, m, v, g in zip(params, moments, squares, grads):
                m *= 0.9
                m += 0.1 * g
                v *= 0.999
                v += 0.001 * g**2
                p -= settings["neural_lr"] * (m / (1 - 0.9**t)) / (np.sqrt(v / (1 - 0.999**t)) + 1e-8)
        model["parameters"], updates = params, settings["neural_updates"]
    if not all(np.isfinite(p).all() for p in model["parameters"]):
        raise ValueError("Nonfinite fitted parameters")
    model["fit"] = {
        "updates": updates,
        "observations_used": len(x),
        "outputs": y.shape[1],
        "trainable_parameters": sum(p.size for p in model["parameters"]),
        "normalization_statistics": mean.size + scale.size,
        "source_observations_sha256": data["sha256"],
        "parameter_sha256": array_digest(mean, scale, *model["parameters"]),
    }
    return model


def predict(model, x, gradient=False):
    if model["family"] == "neural":
        w, b, head, bias = model["parameters"]
        h = np.tanh(x @ w + b)
        y = (h @ head + bias) * model["scale"] + model["mean"]
        if gradient and model["kind"] == "value":
            return ((1 - h**2) * head[:, 0]) @ w.T * model["scale"][0]
    else:
        f, jac = features(x, model["family"])
        beta = model["parameters"][0]
        y = (f @ beta) * model["scale"] + model["mean"]
        if gradient and model["kind"] == "value":
            return np.einsum("nkd,k->nd", jac, beta[:, 0]) * model["scale"][0]
    return y / model["noise"] if model["kind"] == "z_gradient" else y


def actions(x, panel, settings):
    directions, names = [np.zeros(panel.dimension)], ["STOP_keep"]
    for j, axis in enumerate(np.eye(panel.dimension)):
        directions.extend([settings["action_step"] * axis, -settings["action_step"] * axis])
        names.extend([f"adjust_{j}_plus", f"adjust_{j}_minus"])
    if panel.capacity >= 2:
        joint = settings["action_step"] * (np.eye(panel.dimension)[0] + np.eye(panel.dimension)[1])
        directions.extend([joint, -joint])
        names.extend(["joint_plus", "joint_minus"])
    shifts = np.asarray(directions)
    charges = panel.adjustment * np.sum(shifts**2, axis=1)
    charges += panel.load_cost * np.count_nonzero(shifts[:, panel.resident :], axis=1)
    targets = np.concatenate([x[:, None, :] + shifts[None, :, :], np.zeros((len(x), 1, panel.dimension))], axis=1)
    return (
        targets,
        np.append(charges, settings["reset_cost"]),
        np.append(np.ones(len(shifts)), panel.reset_probability),
        names + ["reset"],
    )


def action_values(x, panel, settings):
    targets, cost, probability, names = actions(x, panel, settings)
    base = exact_value_gradient(x, panel)[0]
    values = exact_value_gradient(targets, panel)[0]
    quality_mean = probability * values + (1 - probability) * base[:, None]
    return quality_mean - cost, quality_mean, cost, names


def select(model, x, panel, settings):
    targets, cost, probability, _ = actions(x[None, :], panel, settings)
    targets = targets[0]
    if model["kind"] == "value":
        delta = predict(model, targets)[:, 0] - predict(model, x[None, :])[0, 0]
    else:
        nodes = np.asarray([0.0694318442029737, 0.3300094782075719, 0.6699905217924281, 0.9305681557970262])
        weights = np.asarray([0.1739274225687269, 0.3260725774312731, 0.3260725774312731, 0.1739274225687269])
        shift = targets - x
        points = x + shift[:, None, :] * nodes[None, :, None]
        g = predict(model, points.reshape(-1, panel.dimension), gradient=True).reshape(points.shape)
        delta = np.sum(np.sum(g * shift[:, None, :], axis=2) * weights, axis=1)
    score = probability * delta - cost
    if not np.isfinite(score).all():
        raise ValueError("Nonfinite action scores")
    return int(np.argmax(score))


def calibration(model, x, panel):
    v, g = exact_value_gradient(x, panel)
    estimate = predict(model, x, gradient=True)
    curl = []
    for i in range(panel.dimension):
        for j in range(i + 1, panel.dimension):
            ei, ej = np.eye(panel.dimension)[i] * 1e-5, np.eye(panel.dimension)[j] * 1e-5
            di = (predict(model, x + ei, True) - predict(model, x - ei, True)) / 2e-5
            dj = (predict(model, x + ej, True) - predict(model, x - ej, True)) / 2e-5
            curl.extend(np.abs(di[:, j] - dj[:, i]).tolist())
    return {
        "gradient_mse": float(np.mean((estimate - g) ** 2)),
        "mean_abs_curl": float(np.mean(curl)),
        "value_mse": float(np.mean((predict(model, x)[:, 0] - v) ** 2)) if model["kind"] == "value" else None,
    }


def conditioning():
    """An algebraic sensor-error sensitivity example, not a learned efficacy trial."""
    epsilon, g = 1e-8, np.asarray([0.4, -0.7])
    return [
        {
            "sigma": s,
            "z": (s * g).tolist(),
            "absolute_z_error": epsilon,
            "recovered_gradient_error": None if s == 0 else float(np.max(np.abs((s * g + epsilon) / s - g))),
            "identifiable": s != 0,
        }
        for s in (1.0, 0.1, 1e-3, 1e-6, 0.0)
    ]


def run_case(panel, seed, settings):
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    data = observations(panel, seed, settings["train_n"], settings)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 911, panel.dimension]))
    x = rng.uniform(-1.25, 1.25, (settings["test_n"], panel.dimension))
    eps, reset = rng.normal(size=x.shape), rng.random(len(x)) < panel.reset_probability
    truth, expected_quality, cost, names = action_values(x, panel, settings)
    targets = actions(x, panel, settings)[0]
    targets[:, -1, :] = np.where(reset[:, None], 0.0, x)
    realized = quality(targets + panel.noise * eps[:, None, :], panel)
    fixed = int(np.argmax(action_values(data["x"], panel, settings)[0].mean(axis=0)))
    shared = {
        "cpu_ns": time.process_time_ns() - c0,
        "wall_ns": time.perf_counter_ns() - w0,
        "synthetic_quality_evaluations": int(data["outcomes"].size),
        "observations_sha256": data["sha256"],
        "evaluation_sha256": array_digest(x, eps, reset),
    }
    records = []
    for family, kind in [(f, k) for f in settings["families"] for k in settings["targets"]] + [
        ("reference", "exact"),
        ("reference", "fixed_known_model"),
        ("action_ablation", "frozen"),
    ]:
        start_c, start_w = time.process_time_ns(), time.perf_counter_ns()
        rec = {"family": family, "kind": kind, "status": "complete"}
        try:
            model = (
                None if family in ("reference", "action_ablation") else fit(family, kind, data, panel, seed, settings)
            )
            rec["training"] = {
                "cpu_ns": time.process_time_ns() - start_c,
                "wall_ns": time.perf_counter_ns() - start_w,
                **(model["fit"] if model else {"updates": 0, "trainable_parameters": 0}),
            }
            if model:
                rec["calibration"] = calibration(model, x, panel)
                rec["model"] = {
                    "family": family,
                    "kind": kind,
                    "noise": panel.noise,
                    "mean": model["mean"].tolist(),
                    "scale": model["scale"].tolist(),
                    "parameters": [p.tolist() for p in model["parameters"]],
                }
            chosen, cpu, wall = [], [], []
            for state in x:
                tc, tw = time.process_time_ns(), time.perf_counter_ns()
                choice = (
                    select(model, state, panel, settings)
                    if model
                    else int(np.argmax(action_values(state[None, :], panel, settings)[0][0]))
                    if kind == "exact"
                    else fixed
                    if kind == "fixed_known_model"
                    else 0
                )
                cpu.append(time.process_time_ns() - tc)
                wall.append(time.perf_counter_ns() - tw)
                chosen.append(choice)
            indices, chosen = np.arange(len(x)), np.asarray(chosen)
            selected_cost, mean_value = cost[chosen], truth[indices, chosen]
            observed_quality = realized[indices, chosen]
            net = observed_quality - selected_cost
            rec["metrics"] = {
                "expected_net_value": float(mean_value.mean()),
                "expected_quality": float(expected_quality[indices, chosen].mean()),
                "observed_quality": float(observed_quality.mean()),
                "mean_fee": float(selected_cost.mean()),
                "expected_regret": float(np.mean(truth.max(axis=1) - mean_value)),
                "observed_net_value": float(net.mean()),
                "observed_net_p05": float(np.quantile(net, 0.05)),
                "stop_no_update_fraction": float(np.mean(chosen == 0)),
                "wall_p95_ns": float(np.quantile(wall, 0.95)),
                "wall_p99_ns": float(np.quantile(wall, 0.99)),
                "inference_cpu_ns": sum(cpu),
            }
            rec["raw"] = {
                "choices": chosen.tolist(),
                "expected_net": mean_value.tolist(),
                "observed_quality": observed_quality.tolist(),
                "fees": selected_cost.tolist(),
                "cpu_ns": cpu,
                "wall_ns": wall,
            }
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            rec.update(
                status="unidentified" if kind == "z_gradient" and panel.noise == 0 else "failed",
                error=str(exc),
                failed_cpu_ns=time.process_time_ns() - start_c,
                failed_wall_ns=time.perf_counter_ns() - start_w,
            )
        records.append(rec)
    return {
        "panel": asdict(panel),
        "seed": seed,
        "shared_acquisition_and_truth": shared,
        "action_names": names,
        "fixed_action": fixed,
        "public_test_states": x.tolist(),
        "records": records,
        "training_observations": {"states": data["x"].tolist(), "outcomes": data["outcomes"].tolist()},
        "evaluation_noise": eps.tolist(),
        "evaluation_reset_success": reset.tolist(),
        "whole_case": {"cpu_ns": time.process_time_ns() - c0, "wall_ns": time.perf_counter_ns() - w0},
    }


def run_study(seeds=None, panel_names=None, train_n=None, test_n=None, neural_updates=None):
    settings = protocol()
    for key, override in (
        ("seeds", seeds),
        ("train_n", train_n),
        ("test_n", test_n),
        ("neural_updates", neural_updates),
    ):
        if override is not None:
            settings[key] = override
    if (
        not settings["seeds"]
        or len(settings["seeds"]) > 20
        or len(set(settings["seeds"])) != len(settings["seeds"])
        or any(type(s) is not int or s < 0 for s in settings["seeds"])
        or any(
            type(settings[k]) is not int or not 1 <= settings[k] <= cap
            for k, cap in (("train_n", 512), ("test_n", 512), ("neural_updates", 1000))
        )
    ):
        raise ValueError("Invalid finite study size or seed roster")
    selected = panels()
    if panel_names is not None:
        if (
            not panel_names
            or len(set(panel_names)) != len(panel_names)
            or not set(panel_names) <= {p.name for p in selected}
        ):
            raise ValueError("Unknown or duplicate panel")
        selected = [p for p in selected if p.name in panel_names]
    c, w = time.process_time_ns(), time.perf_counter_ns()
    results = [run_case(p, s, settings) for p in selected for s in settings["seeds"]]
    return {
        "protocol": settings,
        "formal_roster": settings == protocol() and panel_names is None,
        "cases": results,
        "conditioning": conditioning(),
        "scientific_benefit_qualified": False,
        "record_count": sum(len(case["records"]) for case in results),
        "failed_count": sum(r["status"] == "failed" for case in results for r in case["records"]),
        "unidentified_count": sum(r["status"] == "unidentified" for case in results for r in case["records"]),
        "whole_run": {"cpu_ns": time.process_time_ns() - c, "wall_ns": time.perf_counter_ns() - w},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = run_study()
    cases = result.pop("cases")
    result["case_files"] = []
    for case in cases:
        name = f"{case['panel']['name']}_{case['seed']}.json"
        payload = json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        (args.out / name).write_text(payload)
        result["case_files"].append({"path": name, "sha256": hashlib.sha256(payload.encode()).hexdigest()})
    (args.out / "INDEX.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
