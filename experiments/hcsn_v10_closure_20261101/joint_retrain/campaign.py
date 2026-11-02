"""Separately metered stages for genuine finite joint dynamics/content fitting."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

from . import joint_model as joint
from . import ordinary
from .simulator import Physics, sample_counts

HERE = Path(__file__).parent
ARMS = ("joint_original", "same_weight_mean_two_point", "joint_mean_two_point",
        "same_weight_single_transition", "joint_single_transition", "ordinary_mlp")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def sources():
    return {p.name: sha(p) for p in sorted(HERE.glob("*.py"))}


def plan_at(output):
    plan = json.loads((output/"PLAN.json").read_text())
    if sources() != plan["source_sha256"]:
        raise RuntimeError("source changed after PLAN freeze")
    return plan


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hcsn-v10-finite-joint-retraining.v1", "created_unix": time.time(),
        "source_sha256": sources(), "source_extraction_sha256": sha(HERE/"SOURCE_EXTRACTION.json"),
        "evidence_role": "development_only_finite_known_renewal_family",
        "fit_seeds": [101003, 101009, 101019, 101021, 101033],
        "train_size": 2048, "validation_size": 512, "test_size": 1024,
        "test_seed": 202611011043,
        "joint_parameters": {"count": 6, "dynamics": "two log calibration scales on supplied drift/sigma",
            "content": "four logits of common five-way cyclic Markov transition",
            "dynamics_bounds": [-0.5, 0.5], "content_logit_bounds": [-8.0, 8.0]},
        "ordinary_parameters": ordinary.PARAMETERS, "ordinary_width": ordinary.WIDTH,
        "ordinary_information": "same six-scalar physical packet, same known class-translation equivariance; larger capacity",
        "joint_l2": [0.0, 0.001], "ordinary_l2": [0.001, 0.01],
        "optimizer": {"method": "L-BFGS-B", "maxiter": 800, "ftol": 1e-9, "gtol": 1e-6},
        "selection": "lowest validation NLL then lowest L2; one shared seed initialization per family, test never loaded by train",
        "modes": joint.MODES, "arms": ARMS,
        "information": "perfect initial revealed class and common gap/horizon/drift/sigma/reset/refractory packet",
        "labels": "independent IG event times/counts then stochastic public-family content transitions",
        "joint_training": "final content NLL differentiates through count probability AND learned per-event content transition",
        "single_transition_scope": "support exactly N=0 or1; learned dense T executes once and may approximate a multi-event marginal",
        "mean_two_point_scope": "preserves fitted full-law mean, generally changes count shape; piecewise gradients away from integer knots",
        "primary": "jointly retrained ablation minus jointly retrained full heldout NLL",
        "secondary": "fixed-full-weight execution ablation, larger ordinary MLP, accuracy and Brier",
        "cost": "prepare/data/train/evaluate/audit separate metered stages; failed attempts charged and retained",
        "bootstrap": {"replicates": 2000, "seed": 101943, "unit": "crossed fit and heldout-world resampling"},
        "limitations": ["known finite renewal family", "shared structurally correct stochastic model family",
            "constant learned calibration map", "fixed perfect initial observation, one mandatory output",
            "no action/control net benefit", "no real AV or deep multimodal content network", "ordinary MLP strength remains empirically limited"],
        "real_AV_confirmation": False, "production_or_architecture_acceptance": False}
    write(output/"PLAN.json", plan)
    print(json.dumps({"PLAN": str(output/"PLAN.json"), "sha256": sha(output/"PLAN.json")}))


def make_data(seed, size):
    rng = np.random.default_rng(seed)
    packets, counts, labels, initials, truth = [], [], [], [], []
    transition = np.array([.15, .55, 0.0, 0.0, .30])
    for _ in range(size):
        physics = Physics(-rng.uniform(.3, 1.0), rng.uniform(.2, .65),
                          rng.uniform(.4, 1.0), rng.uniform(.16, .28))
        x, horizon = rng.uniform(.1, 1.4), rng.uniform(.03, 3.0)
        initial = int(rng.integers(5))
        count = int(sample_counts(rng, physics, x, horizon, 1)[0])
        displacement = 0
        for _ in range(count):
            displacement += int(rng.choice(5, p=transition))
        packets.append([x, horizon, physics.nu*np.exp(-.12), physics.sigma*np.exp(.08),
                        physics.reset, physics.refractory])
        counts.append(count)
        labels.append((initial+displacement)%5)
        initials.append(initial)
        truth.append([physics.nu, physics.sigma])
    return {"packets": np.array(packets), "counts_for_scoring_only": np.array(counts),
            "labels": np.array(labels), "initials": np.array(initials),
            "delta_labels": (np.array(labels)-np.array(initials))%5,
            "true_dynamics_for_diagnostics_only": np.array(truth)}


def data(output):
    plan = plan_at(output)
    records = {}
    for seed in plan["fit_seeds"]:
        for split, size, source_seed in (("train", plan["train_size"], seed),
                ("validation", plan["validation_size"], seed+1000000)):
            dest = output/f"{split}_{seed}.npz"
            np.savez_compressed(dest, **make_data(source_seed, size))
            records[dest.name] = sha(dest)
    dest = output/"test.npz"
    np.savez_compressed(dest, **make_data(plan["test_seed"], plan["test_size"]))
    records[dest.name] = sha(dest)
    write(output/"DATA.json", {"files_sha256": records, "test_not_used_by_train": True})
    print(json.dumps({"generated_files": len(records)}))


def load_data(output, filename):
    record = json.loads((output/"DATA.json").read_text())
    path = output/filename
    if sha(path) != record["files_sha256"][filename]:
        raise RuntimeError("dataset changed")
    return np.load(path)


def train(output):
    plan = plan_at(output)
    opts = {k: plan["optimizer"][k] for k in ("maxiter", "ftol", "gtol")}
    fits = []
    for seed in plan["fit_seeds"]:
        directory = output/f"fit_{seed}"
        directory.mkdir(exist_ok=False)
        train_set = load_data(output, f"train_{seed}.npz")
        valid_set = load_data(output, f"validation_{seed}.npz")
        x, y = train_set["packets"], train_set["delta_labels"]
        vx, vy = valid_set["packets"], valid_set["delta_labels"]
        initial = np.random.default_rng(seed+2000000).normal(0, .1, 6)
        saved, reports = {"joint_initial": initial}, {}
        for mode in plan["modes"]:
            candidates = []
            for index, l2 in enumerate(plan["joint_l2"]):
                cpu, wall = time.process_time(), time.perf_counter()
                initial_loss, initial_grad = joint.objective(initial, x, y, mode, l2)
                result = minimize(joint.objective, initial, args=(x, y, mode, l2), jac=True,
                    method="L-BFGS-B", bounds=[(-.5, .5)]*2+[(-8, 8)]*4, options=opts)
                validation = joint.metrics(joint.predict(result.x, vx, mode)[0], vy)
                report = {"l2": l2, "validation": validation, "optimizer_success": bool(result.success),
                    "optimizer_message": str(result.message), "iterations": int(result.nit),
                    "gradient_max_abs": float(np.abs(result.jac).max()),
                    "initial_training_loss": initial_loss, "final_training_loss": float(result.fun),
                    "initial_dynamic_gradient_norm": float(np.linalg.norm(initial_grad[:2])),
                    "initial_content_gradient_norm": float(np.linalg.norm(initial_grad[2:])),
                    "dynamics_parameter_change_norm": float(np.linalg.norm(result.x[:2]-initial[:2])),
                    "content_parameter_change_norm": float(np.linalg.norm(result.x[2:]-initial[2:])),
                    "parameters": result.x.tolist(),
                    "dynamic_bound_active": [abs(float(z))>.49999 for z in result.x[:2]],
                    "cpu_seconds": time.process_time()-cpu, "wall_seconds": time.perf_counter()-wall}
                candidates.append(report)
                saved[f"candidate_{mode}_{index}"] = result.x
                print(json.dumps({"seed": seed, "mode": mode, **report}), flush=True)
            selected = min(range(len(candidates)), key=lambda i: (candidates[i]["validation"]["nll"], candidates[i]["l2"]))
            saved[mode] = saved[f"candidate_{mode}_{selected}"]
            reports[mode] = {"selected_index": selected, "selected": candidates[selected], "candidates": candidates}
        mean, scale = x.mean(0), x.std(0)
        if (scale<=0).any():
            raise ValueError("ordinary training normalization singular")
        normalized, validation_x = (x-mean)/scale, (vx-mean)/scale
        initial_mlp = ordinary.initialize(seed+3000000)
        saved.update(ordinary_mean=mean, ordinary_scale=scale, ordinary_initial=initial_mlp)
        candidates = []
        for index, l2 in enumerate(plan["ordinary_l2"]):
            cpu, wall = time.process_time(), time.perf_counter()
            result = minimize(ordinary.objective, initial_mlp, args=(normalized, y, l2), jac=True,
                method="L-BFGS-B", options=opts)
            report = {"l2": l2, "validation": joint.metrics(ordinary.predict(result.x, validation_x), vy),
                "optimizer_success": bool(result.success), "optimizer_message": str(result.message),
                "iterations": int(result.nit), "gradient_max_abs": float(np.abs(result.jac).max()),
                "parameter_change_norm": float(np.linalg.norm(result.x-initial_mlp)),
                "cpu_seconds": time.process_time()-cpu, "wall_seconds": time.perf_counter()-wall}
            candidates.append(report)
            saved[f"candidate_ordinary_{index}"] = result.x
            print(json.dumps({"seed": seed, "mode": "ordinary_mlp", **report}), flush=True)
        selected = min(range(len(candidates)), key=lambda i: (candidates[i]["validation"]["nll"], candidates[i]["l2"]))
        saved["ordinary_mlp"] = saved[f"candidate_ordinary_{selected}"]
        reports["ordinary_mlp"] = {"selected_index": selected, "selected": candidates[selected], "candidates": candidates}
        np.savez_compressed(directory/"weights.npz", **saved)
        report = {"seed": seed, "reports": reports, "weights_sha256": sha(directory/"weights.npz"),
                  "test_not_loaded_by_training_stage": True}
        write(directory/"FIT.json", report)
        fits.append(report)
    write(output/"TRAINING_COMPLETE.json", {"fits": fits, "source_sha256": sources(),
        "test_not_loaded_by_training_stage": True})


def evaluate(output):
    plan = plan_at(output)
    frozen = json.loads((output/"TRAINING_COMPLETE.json").read_text())
    test = load_data(output, "test.npz")
    labels, initials, delta_labels = test["labels"], test["initials"], test["delta_labels"]
    expected, fits = [], []
    with gzip.open(output/"predictions.jsonl.gz", "xt") as stream:
        for fit in frozen["fits"]:
            seed = fit["seed"]
            path = output/f"fit_{seed}"/"weights.npz"
            if sha(path) != fit["weights_sha256"]:
                raise RuntimeError("checkpoint changed")
            weights = np.load(path)
            distributions = {"joint_original": joint.predict(weights["original"], test["packets"], "original")[0]}
            for mode in plan["modes"][1:]:
                distributions["same_weight_"+mode] = joint.predict(weights["original"], test["packets"], mode)[0]
                distributions["joint_"+mode] = joint.predict(weights[mode], test["packets"], mode)[0]
            normalized = (test["packets"]-weights["ordinary_mean"])/weights["ordinary_scale"]
            distributions["ordinary_mlp"] = ordinary.predict(weights["ordinary_mlp"], normalized)
            expected.append(distributions)
            metrics = {arm: joint.metrics(p, delta_labels) for arm,p in distributions.items()}
            fits.append({"seed": seed, "test": metrics})
            for arm, p in distributions.items():
                actual_class_p = np.take_along_axis(p, (np.arange(5)[None]-initials[:,None])%5, axis=1)
                for world, row in enumerate(actual_class_p):
                    stream.write(json.dumps({"fit_seed": seed, "world": world, "arm": arm,
                        "initial_class": int(initials[world]), "truth": int(labels[world]),
                        "probabilities": row.tolist()})+"\n")
    rng = np.random.default_rng(plan["bootstrap"]["seed"])
    contrasts = {}
    for name,left,right in (("mean_retrained_minus_full", "joint_mean_two_point", "joint_original"),
            ("single_retrained_minus_full", "joint_single_transition", "joint_original"),
            ("mean_retrained_minus_same_weight", "joint_mean_two_point", "same_weight_mean_two_point"),
            ("single_retrained_minus_same_weight", "joint_single_transition", "same_weight_single_transition"),
            ("full_minus_ordinary", "joint_original", "ordinary_mlp")):
        rows = np.arange(len(labels))
        diffs = np.array([-np.log(np.maximum(x[left][rows, delta_labels], 1e-15))
                          +np.log(np.maximum(x[right][rows, delta_labels], 1e-15)) for x in expected])
        boot = []
        for _ in range(plan["bootstrap"]["replicates"]):
            ii = rng.integers(len(expected), size=len(expected))
            jj = rng.integers(len(labels), size=len(labels))
            boot.append(float(diffs[ii][:,jj].mean()))
        contrasts[name] = {"NLL_difference": float(diffs.mean()), "per_fit": diffs.mean(1).tolist(),
            "lower95": float(np.quantile(boot, .025)), "upper95": float(np.quantile(boot, .975)),
            "lower_NLL_better": True}
    summary = {"scope": plan["evidence_role"], "fit_scope": plan["joint_parameters"],
        "real_AV_confirmation": False, "architecture_acceptance": False, "mechanism_necessity_proven": False,
        "fits": fits, "contrasts": contrasts, "prediction_rows": len(labels)*len(expected)*len(ARMS),
        "test_multi_event_fraction": float((test["counts_for_scoring_only"]>=2).mean()),
        "raw_sha256": sha(output/"predictions.jsonl.gz"), "test_sha256": sha(output/"test.npz"),
        "training_complete_sha256": sha(output/"TRAINING_COMPLETE.json"), "limitations": plan["limitations"]}
    write(output/"SUMMARY.json", summary)
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "data", "train", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "data": data, "train": train, "evaluate": evaluate}[args.stage](args.output)


if __name__ == "__main__":
    main()
