"""Finite renewal content readout refitting, not full analytic-network training."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from .renewal_numpy import Physics, content_from_counts, renewal_counts, sample_counts
from .transforms import transform_counts

HERE = Path(__file__).parent
MODES = ("original", "mean_two_point", "single_transition")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def source_identity():
    return {p.name: sha(p) for p in sorted(HERE.glob("*.py"))}


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hcsn-v9-renewal-content-readout-refit.v2",
        "evidence_role": "synthetic_fixed_horizon_content_only",
        "fit_scope": "30-parameter multinomial readout; analytic physical kernel remains frozen",
        "not_full_analytic_network_retraining": True,
        "real_AV_confirmation": False,
        "source_sha256": source_identity(),
        "fit_seeds": [92003, 92009, 92019, 92021, 92033],
        "train_size": 2048, "validation_size": 512, "test_size": 1024,
        "test_seed": 20261101943,
        "modes": MODES,
        "l2_candidates": [0.001, 0.01],
        "optimizer": "L-BFGS-B analytic gradient, maxiter=1200, ftol=1e-9, gtol=1e-6",
        "selection": "lowest validation NLL then lowest L2; never test score",
        "features": "log clipped predicted five-class distribution plus intercept",
        "labels": "independent inverse-Gaussian event simulation then public Markov transitions",
        "information": "identical initial revealed class, gap, horizon, drift, volatility, reset and refractory packet",
        "physics": "known shared synthetic law; no learned physical parameter or content-network state",
        "actions": "fixed reveal of initial content followed by one mandatory output; no READ control or decision benefit",
        "reference": "unfitted full analytic distribution; uses known task law",
        "primary": "refitted ablation minus refitted original test NLL, paired worlds and fits",
        "secondary": "same-original-weight execution ablation vs independently refitted ablation",
        "bootstrap": {"replicates": 2000, "seed": 91941, "unit": "crossed fit and test world resampling"},
        "adoption_acceptance": False,
        "timestamp_unix": time.time(),
    }
    write(output / "PLAN.json", plan)
    print(json.dumps({"plan": str(output / "PLAN.json"), "sha256": sha(output / "PLAN.json")}))


def dataset(seed, size):
    rng = np.random.default_rng(seed)
    packets, counts, labels, initials, features, oracle, diagnostics = [], [], [], [], {}, [], []
    for mode in MODES:
        features[mode] = []
    transition = np.zeros((5, 5))
    for index in range(5):
        transition[index, index] = 0.15
        transition[(index + 1) % 5, index] = 0.55
        transition[(index - 1) % 5, index] = 0.30
    for _ in range(size):
        physics = Physics(-rng.uniform(0.3, 1.0), rng.uniform(0.2, 0.65),
                          rng.uniform(0.4, 1.0), rng.uniform(0.16, 0.28))
        x, horizon = rng.uniform(0.1, 1.4), rng.uniform(0.03, 3.0)
        initial = int(rng.integers(5))
        count = int(sample_counts(rng, physics, x, horizon, 1)[0])
        label = initial
        for _ in range(count):
            label = int(rng.choice(5, p=transition[:, label]))
        probabilities, work = renewal_counts(x, horizon, physics)
        for mode in MODES:
            p = content_from_counts(transform_counts(probabilities, mode), np.eye(5)[initial], transition)
            features[mode].append(np.r_[np.log(np.clip(p, 1e-6, 1)), 1.0])
            if mode == "original":
                oracle.append(p)
        diagnostics.append([float(probabilities[2:].sum()),
                            float(probabilities @ np.arange(len(probabilities)))])
        packets.append([x, horizon, physics.nu, physics.sigma, physics.reset, physics.refractory])
        counts.append(count)
        labels.append(label)
        initials.append(initial)
    return {"packets": np.array(packets), "counts": np.array(counts),
            "labels": np.array(labels), "initials": np.array(initials),
            "oracle": np.array(oracle), "diagnostics": np.array(diagnostics),
            **{"X_" + k: np.array(v) for k, v in features.items()}}


def probabilities(weights, x):
    logits = x @ weights.reshape(6, 5)
    return np.exp(logits - logsumexp(logits, axis=1, keepdims=True))


def objective(weights, x, labels, l2):
    p = probabilities(weights, x)
    loss = -np.log(np.clip(p[np.arange(len(labels)), labels], 1e-300, 1)).mean()
    residual = p.copy()
    residual[np.arange(len(labels)), labels] -= 1
    gradient = x.T @ residual / len(labels)
    w = weights.reshape(6, 5)
    loss += 0.5 * l2 * np.square(w[:5]).sum()
    gradient[:5] += l2 * w[:5]
    return float(loss), gradient.ravel()


def metrics(p, labels):
    return {"nll": float(-np.log(np.clip(p[np.arange(len(labels)), labels], 1e-300, 1)).mean()),
            "accuracy": float(np.mean(p.argmax(1) == labels)),
            "brier": float(np.square(p - np.eye(5)[labels]).sum(1).mean())}


def execute(output):
    plan = json.loads((output / "PLAN.json").read_text())
    if plan["source_sha256"] != source_identity():
        raise RuntimeError("sources changed after plan freeze")
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    # The held-out worlds are generated once after plan freeze and never fit.
    test = dataset(plan["test_seed"], plan["test_size"])
    np.savez_compressed(output / "test_data.npz", **test)
    fits, predictions = [], []
    with gzip.open(output / "predictions.jsonl.gz", "xt") as stream:
        for seed in plan["fit_seeds"]:
            fit_start_cpu, fit_start_wall = time.process_time(), time.perf_counter()
            dest = output / f"fit_{seed}"
            dest.mkdir(exist_ok=False)
            train = dataset(seed, plan["train_size"])
            valid = dataset(seed + 1000000, plan["validation_size"])
            np.savez_compressed(dest / "data.npz", **{"train_"+k:v for k,v in train.items()},
                                **{"validation_"+k:v for k,v in valid.items()})
            rng = np.random.default_rng(seed + 2000000)
            initial_weights = np.vstack([np.eye(5), np.zeros((1, 5))]) + rng.normal(0, 0.01, (6, 5))
            weights, reports = {}, {}
            for mode in plan["modes"]:
                candidates = []
                for l2 in plan["l2_candidates"]:
                    cpu, wall = time.process_time(), time.perf_counter()
                    result = minimize(objective, initial_weights.ravel(),
                        args=(train["X_"+mode], train["labels"], l2), jac=True,
                        method="L-BFGS-B", options={"maxiter": 1200, "ftol": 1e-9, "gtol": 1e-6})
                    validation = metrics(probabilities(result.x, valid["X_"+mode]), valid["labels"])
                    candidate = {"l2": l2, "validation": validation,
                        "optimizer_success": bool(result.success), "optimizer_message": str(result.message),
                        "iterations": int(result.nit), "evaluations": int(result.nfev),
                        "gradient_max_abs": float(np.abs(result.jac).max()),
                        "final_regularized_training_loss": float(result.fun),
                        "cpu_seconds": time.process_time()-cpu, "wall_seconds": time.perf_counter()-wall}
                    candidates.append((candidate, result.x.copy()))
                    print(json.dumps({"fit_seed": seed, "mode": mode, **candidate}), flush=True)
                selected, weight = min(candidates, key=lambda row: (row[0]["validation"]["nll"], row[0]["l2"]))
                weights[mode] = weight
                reports[mode] = {"selected": selected, "all_candidates": [x[0] for x in candidates]}
            np.savez_compressed(dest / "weights.npz", **weights)
            arms = {"refit_original": probabilities(weights["original"], test["X_original"]),
                    "unfitted_analytic": test["oracle"]}
            for mode in MODES[1:]:
                arms["same_weight_"+mode] = probabilities(weights["original"], test["X_"+mode])
                arms["refit_"+mode] = probabilities(weights[mode], test["X_"+mode])
            for arm, p in arms.items():
                for index, row in enumerate(p):
                    stream.write(json.dumps({"fit_seed": seed, "world": index, "arm": arm,
                        "truth": int(test["labels"][index]), "probabilities": row.tolist()})+"\n")
            predictions.append(arms)
            report = {"seed": seed, "modes": reports,
                "test": {name: metrics(p, test["labels"]) for name,p in arms.items()},
                "data_sha256": sha(dest / "data.npz"), "weights_sha256": sha(dest / "weights.npz"),
                "cpu_seconds_inclusive": time.process_time()-fit_start_cpu,
                "wall_seconds_inclusive": time.perf_counter()-fit_start_wall}
            write(dest / "FIT.json", report)
            fits.append(report)
            stream.flush()
    rng = np.random.default_rng(plan["bootstrap"]["seed"])
    effects = {}
    labels = test["labels"]
    def nll_rows(p):
        return -np.log(np.clip(p[np.arange(len(labels)), labels], 1e-300, 1))
    for mode in MODES[1:]:
        for contrast,left,right in (("refit_minus_original", "refit_"+mode, "refit_original"),
                                    ("refit_minus_same_weight", "refit_"+mode, "same_weight_"+mode)):
            diff = np.array([nll_rows(arms[left])-nll_rows(arms[right]) for arms in predictions])
            boot = []
            for _ in range(plan["bootstrap"]["replicates"]):
                ii = rng.integers(len(predictions), size=len(predictions))
                jj = rng.integers(len(labels), size=len(labels))
                boot.append(float(diff[ii][:,jj].mean()))
            effects[mode+"_"+contrast] = {"nll_difference": float(diff.mean()),
                "lower95": float(np.quantile(boot, .025)), "upper95": float(np.quantile(boot, .975)),
                "per_fit": diff.mean(1).tolist(), "direction": "lower NLL is better"}
    summary = {"scope": plan["evidence_role"], "fit_scope": plan["fit_scope"],
        "real_AV_confirmation": False, "full_analytic_network_retraining": False,
        "mechanism_necessity_proven": False, "control_net_advantage_proven": False,
        "worlds": len(labels), "fit_seeds": plan["fit_seeds"],
        "prediction_rows": len(labels)*len(predictions)*6,
        "test_data_sha256": sha(output / "test_data.npz"),
        "raw_sha256": sha(output / "predictions.jsonl.gz"),
        "fits": fits, "contrasts": effects,
        "test_multi_event_count_fraction": float((test["counts"]>=2).mean()),
        "test_multi_event_mass_mean": float(test["diagnostics"][:,0].mean()),
        "cpu_seconds_inclusive": time.process_time()-started_cpu,
        "wall_seconds_inclusive": time.perf_counter()-started_wall,
        "device_energy_joules": None,
        "limitations": ["known public renewal law and public content transition matrix",
            "frozen analytic dynamics; only readout retrained", "fixed sensing schedule",
            "finite synthetic perfect-initial-sensor assay", "no continuous AV state or multimodal head"]}
    write(output / "SUMMARY.json", summary)
    print(json.dumps({"summary": str(output/"SUMMARY.json"), "contrasts": effects}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.command == "prepare" else execute)(args.output)


if __name__ == "__main__":
    main()
