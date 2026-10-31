"""Read-only cost and quality gates added before replacement confirmation.

The original benchmark included conversion of an unused target tensor. This
benchmark accepts only deployable inputs. It includes preparation of every
observation, inference, action selection, and JSON output; native journals and
recovery belong to the separate native-owner experiment.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .models import RiskModel, load_state

HERE = Path(__file__).resolve().parent


def execute(model, history, lengths, query):
    inputs = (torch.tensor(history, dtype=torch.float32),
        torch.tensor(lengths, dtype=torch.int64), torch.tensor(query, dtype=torch.float32))
    with torch.no_grad():
        risk = model(*inputs).numpy()
    return json.dumps({"risk": risk.tolist(), "protect": (risk >= query[:, 4]).tolist()})


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    report = json.loads((HERE / "evidence/confirmation.json").read_text())
    protocol = json.loads((HERE / "protocol.json").read_text())
    training = json.loads((HERE / "evidence/training.json").read_text())
    generation = json.loads((HERE / "evidence/data/training_generation.json").read_text())
    target_generation_cpu = sum(x["cpu_seconds"] for x in generation.values())
    models, setup = {}, {}
    for name in protocol["models"]:
        for seed in protocol["model_seeds"]:
            key = f"{name}_{seed}"
            start = time.process_time()
            saved = json.loads((HERE / "evidence/models" / (key + ".json")).read_text())
            models[key] = load_state(name, saved["state"])
            fit_cost = next(x["cpu_seconds"] for x in training if x["model"] == name and x["seed"] == seed)
            setup[key] = fit_cost + target_generation_cpu + time.process_time() - start
    start = time.process_time()
    models["fixed_ordinary_filter"] = RiskModel("fixed_ordinary_filter").eval()
    setup["fixed_ordinary_filter"] = time.process_time() - start
    with np.load(HERE / "evidence/data/iid.npz", allow_pickle=False) as data:
        inputs = tuple(data[k] for k in ("history", "lengths", "query"))
    for model in models.values():
        execute(model, *inputs)
    rows, rng = [], np.random.default_rng(48017)
    for repeat in range(9):
        for key in rng.permutation(list(models)):
            start, wall = time.process_time(), time.perf_counter()
            output = execute(models[key], *inputs)
            rows.append({"model": key, "repeat": repeat, "workload": "batch",
                "cpu_per_episode": (time.process_time() - start) / len(inputs[0]),
                "wall_per_episode": (time.perf_counter() - wall) / len(inputs[0]), "output_bytes": len(output)})
    for index in range(64):
        for key in rng.permutation(list(models)):
            start, wall = time.process_time(), time.perf_counter()
            output = execute(models[key], *(x[index:index+1] for x in inputs))
            rows.append({"model": key, "repeat": index, "workload": "scalar",
                "cpu_per_episode": time.process_time() - start,
                "wall_per_episode": time.perf_counter() - wall, "output_bytes": len(output)})
    costs = {}
    for family in protocol["models"] + ["fixed_ordinary_filter"]:
        members = [f"{family}_{s}" for s in protocol["model_seeds"]] if family in protocol["models"] else [family]
        costs[family] = {workload: float(np.mean([np.median([r["cpu_per_episode"] for r in rows
            if r["model"] == key and r["workload"] == workload]) for key in members]))
            for workload in ("batch", "scalar")}
        costs[family]["standalone_fit_and_setup_cpu"] = float(np.mean([setup[x] for x in members]))
    def metrics(regime, family):
        section = report["regimes"][regime]
        return section["metrics_by_checkpoint"][family] if family == "fixed_ordinary_filter" else section["metrics_mean_over_seeds"][family]
    gates, amortization = {}, []
    for other in ("sufficient_mlp", "gru", "memoryless", "fixed_ordinary_filter"):
        quality = {regime: {
            "mse_noninferior": metrics(regime, other)["mse"] <= metrics(regime, "analytic_filter")["mse"] + protocol["gates"]["ordinary_noninferiority_margin_mse"],
            "regret_noninferior": metrics(regime, other)["regret"] <= metrics(regime, "analytic_filter")["regret"] + protocol["gates"]["ordinary_noninferiority_margin_regret"]}
            for regime in report["regimes"]}
        equal_quality = all(all(q.values()) for q in quality.values())
        gates[other] = {"quality_by_regime": quality, "all_regimes_noninferior": equal_quality,
            "cost_at_most_analytic": {w: costs[other][w] <= costs["analytic_filter"][w] for w in ("batch", "scalar")},
            "empirical_counterexample_by_workload": {w: equal_quality and costs[other][w] <= costs["analytic_filter"][w] for w in ("batch", "scalar")}}
        for horizon in protocol["cost"]["training_amortization_horizons"]:
            for workload in ("batch", "scalar"):
                for regime in report["regimes"]:
                    gain = metrics(regime, "analytic_filter")["expected_utility"] - metrics(regime, other)["expected_utility"]
                    incremental_cpu = costs["analytic_filter"][workload] - costs[other][workload]
                    incremental_cpu += (costs["analytic_filter"]["standalone_fit_and_setup_cpu"] - costs[other]["standalone_fit_and_setup_cpu"]) / horizon
                    amortization.append({"other": other, "sessions": horizon, "workload": workload,
                        "regime": regime, "analytic_minus_other_expected_utility": gain,
                        "incremental_cpu_per_session": incremental_cpu,
                        "net_at_preregistered_cpu_price": gain - protocol["cost"]["compute_price_per_cpu_second"] * incremental_cpu})
    result = {"quality_cost_gates": gates, "cpu_cost_summary": costs, "raw_timings": rows,
        "amortization": amortization, "campaign_training_cpu_seconds": sum(x["cpu_seconds"] for x in training),
        "shared_train_dev_target_generation_cpu_seconds": target_generation_cpu,
        "upstream_confirmation_sha256": hashlib.sha256((HERE / "evidence/confirmation.json").read_bytes()).hexdigest(),
        "scope": "Measured predictor and compute-pricing model only; native logging/recovery and engineering labor are not included. Source-generative data and prior are known to the exact control. Timing on one CPU environment is descriptive.",
        "failed_fit_attempts": 0, "checkpoint_selection_cost_included": True,
        "structural_spiking_necessity": "not established independently of timing; the ordinary filter implements the same map"}
    (HERE / "evidence/cost_and_gates.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"gates": gates, "costs": costs}, indent=2))


if __name__ == "__main__":
    main()
