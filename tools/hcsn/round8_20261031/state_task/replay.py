"""Independent NumPy replay of all frozen predictors and published cost gates.

This is a read-only audit of the original confirmation. It does not retrain,
replace timing measurements, or count a replay as new confirmation samples.
"""

import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.special import expit, log_ndtr, softmax

from .data import make_data

HERE = Path(__file__).resolve().parent


def predict(name, state, history, lengths, query):
    """Only public deployment inputs enter this independent implementation."""
    history = history.astype(np.float32).astype(float)
    query = query.astype(np.float32).astype(float)
    dy, dt, sensor = np.moveaxis(history, -1, 0)
    variance = np.where(sensor > 0, sensor**2, 1.)
    features = np.stack([dy / variance, dt / variance, dy, dt, sensor], -1)
    a, b = features[:, :, :2].sum(1).T
    params = {key: np.asarray(value, dtype=float) for key, value in state.items()}
    if name in ("analytic_filter", "fixed_ordinary_filter"):
        modes, prior = np.array([-.8, 0., .8]), np.array([.3, .4, .3])
        scales = np.exp(params.get("log_scales", np.zeros(2)))
        logits = a[:, None] * modes * scales[0] - .5 * b[:, None] * modes**2 * scales[1]
        posterior = softmax(logits + np.log(prior) + params.get("prior_shift", np.zeros(3)), axis=1)
        d, sigma, horizon, slope = query[:, :4].T
        mu = modes - slope[:, None]
        scale = sigma[:, None] * np.sqrt(horizon[:, None])
        exponent = 2 * mu * d[:, None] / sigma[:, None]**2
        log_f = np.logaddexp(log_ndtr((mu * horizon[:, None] - d[:, None]) / scale),
            exponent + log_ndtr((-mu * horizon[:, None] - d[:, None]) / scale))
        return np.sum(posterior * np.exp(np.minimum(log_f, 0.)), axis=1)
    if name == "gru":
        hidden = np.zeros((len(lengths), 24))
        for index in range(int(lengths.max())):
            x = features[:, index] @ params["recurrent.weight_ih_l0"].T + params["recurrent.bias_ih_l0"]
            h = hidden @ params["recurrent.weight_hh_l0"].T + params["recurrent.bias_hh_l0"]
            xr, xz, xn = np.split(x, 3, axis=1)
            hr, hz, hn = np.split(h, 3, axis=1)
            reset, retain = expit(xr + hr), expit(xz + hz)
            candidate = np.tanh(xn + reset * hn)
            next_hidden = (1 - retain) * candidate + retain * hidden
            hidden = np.where((index < lengths)[:, None], next_hidden, hidden)
    elif name == "sufficient_mlp":
        hidden = np.stack([a / 5, b / 5, a / np.sqrt(b + 1)], axis=1)
    elif name == "memoryless":
        hidden = features[np.arange(len(lengths)), lengths - 1]
    else:
        raise ValueError(name)
    value = np.concatenate([hidden, query[:, :4]], axis=1)
    for layer in (0, 2, 4):
        value = value @ params[f"head.{layer}.weight"].T + params[f"head.{layer}.bias"]
        value = expit(value) if layer == 4 else np.tanh(value)
    return value[:, 0]


def metrics(prediction, data):
    probability, event, cost = data["probability"], data["event"], data["query"][:, 4]
    action = prediction >= cost
    utility = np.where(action, -cost, -probability)
    bins = np.minimum((prediction * 10).astype(int), 9)
    ece = sum(abs(np.mean(prediction[bins == b] - event[bins == b])) * np.mean(bins == b)
        for b in range(10) if np.any(bins == b))
    return {"mse": float(np.mean((prediction - probability)**2)),
        "brier": float(np.mean((prediction - event)**2)), "ece10": float(ece),
        "regret": float(np.mean(-np.minimum(cost, probability) - utility)),
        "expected_utility": float(np.mean(utility)),
        "realized_utility": float(np.mean(np.where(action, -cost, -event))),
        "action_error": float(np.mean(action != (probability >= cost)))}


def audit():
    start = time.process_time()
    read = lambda name: json.loads((HERE / name).read_text())
    freeze, protocol = read("FREEZE.json"), read("protocol.json")
    for name, expected in freeze["source_and_checkpoint_sha256"].items():
        actual = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("frozen input changed: " + name)
    manifest = json.loads((HERE.parent / "bundles/state_task.json").read_text())
    for name, meta in manifest["files"].items():
        data = (HERE.parent / name).read_bytes()
        if len(data) != meta["bytes"] or hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError("recovered evidence differs from archived bytes: " + name)
    protocol["data_seeds"].update(read("CONFIRMATION_AMENDMENT.json")["replacement_seeds"])
    original, costs = read("evidence/confirmation.json"), read("evidence/cost_and_gates.json")
    states = {}
    for family in protocol["models"]:
        for seed in protocol["model_seeds"]:
            name = f"{family}_{seed}"
            saved = read(f"evidence/models/{name}.json")
            if len(saved["trace"]) != 9 or saved["trace"][-1]["step"] != 800:
                raise ValueError("registered fit budget was not recorded: " + name)
            states[name] = (family, saved["state"])
    states["fixed_ordinary_filter"] = ("fixed_ordinary_filter", {})
    rows, measured = [], {}
    for regime in ("iid", "long_history", "low_noise", "moving_boundary"):
        with np.load(HERE / "evidence/data" / f"{regime}.npz", allow_pickle=False) as stored:
            raw = {name: stored[name] for name in stored.files}
        regenerated = make_data(regime, protocol)
        for name in raw:
            np.testing.assert_allclose(raw[name], regenerated[name], rtol=2e-13, atol=2e-14)
        measured[regime] = {}
        with np.load(HERE / "evidence" / f"{regime}_raw_predictions.npz", allow_pickle=False) as stored:
            for name, (family, state) in states.items():
                recorded = stored[name]
                replayed = predict(family, state, raw["history"], raw["lengths"], raw["query"])
                maximum = float(np.max(np.abs(recorded - replayed)))
                np.testing.assert_allclose(recorded, replayed, rtol=0, atol=3e-6)
                actions_differ = int(np.sum((recorded >= raw["query"][:, 4]) != (replayed >= raw["query"][:, 4])))
                if actions_differ:
                    raise AssertionError(f"independent forward changed actions for {name}: {actions_differ}")
                measured[regime][name] = metrics(recorded, raw)
                for metric, value in measured[regime][name].items():
                    np.testing.assert_allclose(value, original["regimes"][regime]["metrics_by_checkpoint"][name][metric], rtol=2e-12, atol=2e-15)
                rows.append({"regime": regime, "model": name, "examples": len(recorded),
                    "max_abs_prediction_difference": maximum, "action_differences": actions_differ})
    summaries = costs["cpu_cost_summary"]
    for family in protocol["models"] + ["fixed_ordinary_filter"]:
        members = [f"{family}_{seed}" for seed in protocol["model_seeds"]] if family in protocol["models"] else [family]
        for workload in ("scalar", "batch"):
            value = np.mean([np.median([row["cpu_per_episode"] for row in costs["raw_timings"]
                if row["model"] == member and row["workload"] == workload]) for member in members])
            np.testing.assert_allclose(value, summaries[family][workload], rtol=1e-13, atol=1e-16)
    def average(regime, family, metric):
        members = [f"{family}_{seed}" for seed in protocol["model_seeds"]] if family in protocol["models"] else [family]
        return float(np.mean([measured[regime][member][metric] for member in members]))
    for other, gate in costs["quality_cost_gates"].items():
        quality = {}
        for regime in measured:
            quality[regime] = {metric + "_noninferior": average(regime, other, metric) <= average(regime, "analytic_filter", metric) + protocol["gates"]["ordinary_noninferiority_margin_" + metric]
                for metric in ("mse", "regret")}
        assert quality == gate["quality_by_regime"]
        equal = all(all(values.values()) for values in quality.values())
        assert equal == gate["all_regimes_noninferior"]
        for workload in ("batch", "scalar"):
            cheaper = summaries[other][workload] <= summaries["analytic_filter"][workload]
            assert cheaper == gate["cost_at_most_analytic"][workload]
            assert (equal and cheaper) == gate["empirical_counterexample_by_workload"][workload]
    for row in costs["amortization"]:
        other, workload, regime = row["other"], row["workload"], row["regime"]
        utility = average(regime, "analytic_filter", "expected_utility") - average(regime, other, "expected_utility")
        cpu = summaries["analytic_filter"][workload] - summaries[other][workload]
        cpu += (summaries["analytic_filter"]["standalone_fit_and_setup_cpu"] - summaries[other]["standalone_fit_and_setup_cpu"]) / row["sessions"]
        np.testing.assert_allclose(row["net_at_preregistered_cpu_price"], utility - protocol["cost"]["compute_price_per_cpu_second"] * cpu, rtol=2e-12, atol=1e-15)
    return {"schema": "hepta.r8.state-independent-replay.v1", "passed": True,
        "source_freeze_sha256": hashlib.sha256((HERE / "FREEZE.json").read_bytes()).hexdigest(),
        "frozen_hashes_verified": len(freeze["source_and_checkpoint_sha256"]),
        "original_evidence_hashes_verified": len(manifest["files"]),
        "predictor_episodes_replayed": sum(row["examples"] for row in rows),
        "unique_confirmation_examples": 8192, "new_confirmation_examples": 0,
        "max_abs_prediction_difference": max(row["max_abs_prediction_difference"] for row in rows),
        "all_actions_identical": True, "rows": rows,
        "cost_gates_recomputed_from_original_raw_timings": True,
        "amortization_rows_recomputed": len(costs["amortization"]),
        "new_hardware_timing_claim": False, "production_activation": False,
        "scope": "Independent NumPy float64 forward replay of frozen PyTorch float32 weights; original model and data bytes preserved. Exact ordinary filter still matches risk and actions; necessity of spikes remains unproved.",
        "audit_cpu_seconds": time.process_time() - start,
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
            "scipy": scipy.__version__, "platform": platform.platform()}}


if __name__ == "__main__":
    result = audit()
    destination = HERE / "evidence/RECOVERY_REPLAY_20261031.json"
    with destination.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
