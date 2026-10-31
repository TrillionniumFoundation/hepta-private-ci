"""Frozen paired confirmation and complete predictor costs, without refitting."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .models import RiskModel, load_state, tensor_data

HERE = Path(__file__).resolve().parent


def score(prediction, data):
    p, event, cost = data["probability"], data["event"], data["query"][:, 4]
    action = prediction >= cost
    utility = np.where(action, -cost, -p)
    best = -np.minimum(cost, p)
    bins = np.minimum((prediction * 10).astype(int), 9)
    ece = sum(abs(np.mean(prediction[bins == b] - event[bins == b])) * np.mean(bins == b)
        for b in range(10) if np.any(bins == b))
    return {"mse": float(np.mean((prediction - p)**2)),
        "brier": float(np.mean((prediction - event)**2)), "ece10": float(ece),
        "regret": float(np.mean(best - utility)), "expected_utility": float(np.mean(utility)),
        "realized_utility": float(np.mean(np.where(action, -cost, -event))),
        "action_error": float(np.mean(action != (p >= cost)))}


def paired_interval(values, seed):
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(10):
        indices = rng.integers(0, len(values), (100, len(values)))
        draws.extend(values[indices].mean(axis=1).tolist())
    return {"mean": float(np.mean(values)),
        "descriptive_paired_95_percent": np.quantile(draws, [.025, .975]).tolist()}


def benchmark(model, raw):
    # Include raw input conversion, all history transforms, model and decision,
    # and output JSON. Loading compressed test fixtures is separately reported.
    def execute(sample):
        x = tensor_data(sample)
        with torch.no_grad():
            prediction = model(*x[:3]).numpy()
        return json.dumps({"risk": prediction.tolist(),
            "protect": (prediction >= sample["query"][:, 4]).tolist()})
    execute(raw)
    batch = []
    for _ in range(7):
        start, wall = time.process_time(), time.perf_counter()
        result = execute(raw)
        batch.append([time.process_time() - start, time.perf_counter() - wall, len(result)])
    scalar = []
    for i in range(64):
        sample = {k: v[i:i+1] for k, v in raw.items()}
        start, wall = time.process_time(), time.perf_counter()
        result = execute(sample)
        scalar.append([time.process_time() - start, time.perf_counter() - wall, len(result)])
    return {"batch_raw_seconds_bytes": batch, "scalar_raw_seconds_bytes": scalar,
        "batch_cpu_seconds_per_episode": float(np.median(np.array(batch)[:, 0]) / len(raw["probability"])),
        "scalar_cpu_seconds_per_episode": float(np.mean(np.array(scalar)[:, 0]))}


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    frozen = json.loads((HERE / "FREEZE.json").read_text())
    for relative, expected in frozen["source_and_checkpoint_sha256"].items():
        if hashlib.sha256((HERE / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen input changed: " + relative)
    out = HERE / "evidence"
    if (out / "confirmation.json").exists():
        raise FileExistsError("confirmation already exists")
    protocol = json.loads((HERE / "protocol.json").read_text())
    models, loading_cost = {}, {}
    for name in protocol["models"]:
        for seed in protocol["model_seeds"]:
            start = time.process_time()
            saved = json.loads((out / "models" / f"{name}_{seed}.json").read_text())
            models[f"{name}_{seed}"] = load_state(name, saved["state"])
            loading_cost[f"{name}_{seed}"] = time.process_time() - start
    models["fixed_ordinary_filter"] = RiskModel("fixed_ordinary_filter").eval()
    training = json.loads((out / "training.json").read_text())
    report = {"source_freeze_sha256": hashlib.sha256((HERE / "FREEZE.json").read_bytes()).hexdigest(),
        "model_load_cpu_seconds": loading_cost, "training_cpu_seconds_total": sum(x["cpu_seconds"] for x in training),
        "regimes": {}, "cost": {}, "comparisons": {}, "scope": protocol["gates"]["scope"]}
    for regime in ("iid", "long_history", "low_noise", "moving_boundary"):
        load_start = time.process_time()
        with np.load(out / "data" / (regime + ".npz"), allow_pickle=False) as loaded:
            raw = {k: loaded[k] for k in loaded.files}
        load_cpu = time.process_time() - load_start
        data = tensor_data(raw)
        predictions, metrics = {}, {}
        for name, model in models.items():
            with torch.no_grad():
                pred = model(*data[:3]).numpy().astype(float)
            if not np.all(np.isfinite(pred)) or np.any((pred < 0) | (pred > 1)):
                raise ArithmeticError("invalid predicted risk")
            predictions[name] = pred
            metrics[name] = score(pred, raw)
            if regime == "iid":
                report["cost"][name] = benchmark(model, raw)
        averaged = {}
        for name in protocol["models"]:
            averaged[name] = np.mean([predictions[f"{name}_{s}"] for s in protocol["model_seeds"]], axis=0)
        averaged["fixed_ordinary_filter"] = predictions["fixed_ordinary_filter"]
        # Inference uses each frozen seed model separately. Seed-averaged losses
        # below do not deploy an unpriced ensemble or average before deciding.
        losses, regrets = {}, {}
        for name in averaged:
            ps = [predictions[f"{name}_{s}"] for s in protocol["model_seeds"]] if name in protocol["models"] else [predictions[name]]
            losses[name] = np.mean([(p - raw["probability"])**2 for p in ps], axis=0)
            regrets[name] = np.mean([np.where(p >= raw["query"][:, 4], raw["query"][:, 4], raw["probability"])
                - np.minimum(raw["query"][:, 4], raw["probability"]) for p in ps], axis=0)
        comparisons = {}
        for index, other in enumerate(("memoryless", "sufficient_mlp", "gru", "fixed_ordinary_filter")):
            comparisons[other] = {"analytic_minus_other_mse": paired_interval(losses["analytic_filter"] - losses[other], 700 + index),
                "analytic_minus_other_regret": paired_interval(regrets["analytic_filter"] - regrets[other], 900 + index)}
        report["comparisons"][regime] = comparisons
        report["regimes"][regime] = {"metrics_by_checkpoint": metrics, "fixture_load_cpu_seconds": load_cpu,
            "metrics_mean_over_seeds": {name: {k: float(np.mean([metrics[f"{name}_{s}"][k] for s in protocol["model_seeds"]]))
                for k in next(iter(metrics.values()))} for name in protocol["models"]}}
        np.savez_compressed(out / (regime + "_raw_predictions.npz"), probability=raw["probability"],
            event=raw["event"], protect_cost=raw["query"][:, 4], **predictions)
    report["verdict"] = {"analytic_state_irreplaceable": False,
        "reason": "A nonspiking two-accumulator filter computes the exact same sufficient posterior and Brownian-risk operator; novelty or task necessity of spikes is not established.",
        "ordinary_control_uses_same_closed_form_operator": True,
        "learned_control_comparisons": "See all frozen seed and shifted-regime measurements, including complete predictor cost.",
        "production_claim": False}
    (out / "confirmation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"training_cpu_seconds_total": report["training_cpu_seconds_total"],
        "regimes": {k: v["metrics_mean_over_seeds"] for k, v in report["regimes"].items()},
        "verdict": report["verdict"]}, indent=2))


if __name__ == "__main__":
    main()
