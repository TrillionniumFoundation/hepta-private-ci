"""Validation-only selection with matched tensor/utility work in every arm."""

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path

import numpy as np

from control import fit_controller
from data import CLASSES, SIDE, SPLIT_SEEDS, dataset, decoded_metrics, manifest, outcome_table, templates
from model import JointModel
from utility import joint_value_and_grad

ROOT = Path(__file__).resolve().parent


def thread_evidence():
    declared = {name: os.environ.get(name) for name in
                ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}
    try:
        from threadpoolctl import threadpool_info
        observed = [{"api": item["internal_api"], "threads": item["num_threads"]}
                    for item in threadpool_info()]
    except ImportError:
        observed = None
    return {"declared": declared, "observed": observed,
            "single_thread_verified": bool(observed) and all(row["threads"] == 1 for row in observed)}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def summary(model, data, rho):
    p, q = model.forward(data["full"])
    r = outcome_table(model)[data["labels"]]
    values, _, _ = joint_value_and_grad(p, q, r, rho)
    metrics = decoded_metrics(model, p, q, data["labels"])
    metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, r, q)
    metrics["ndu"] = values
    return {key: float(value.mean()) for key, value in metrics.items()}


def train_candidate(base, data, plan, arm, lr, seed):
    model = base.clone()
    reward = outcome_table(model)
    rng = np.random.default_rng(seed + 9000)
    started = time.perf_counter()
    for _ in range(plan["adapt_steps"]):
        rows = rng.integers(len(data["labels"]), size=plan["batch_size"])
        use_full = rng.random(len(rows)) < 0.5
        x = np.where(use_full[:, None], data["full"][rows], data["low"][rows])
        y = data["labels"][rows]
        p, q = model.forward(x)
        ce_p, ce_q = p.copy(), q.copy()
        ce_p[np.arange(len(y)), y] -= 1
        ce_q[np.arange(len(y)), y] -= 1
        ce_p, ce_q = ce_p / (2 * len(y)), ce_q / (2 * len(y))
        # Compute BOTH fixed utility diagnostics and gradients in EVERY arm.
        # Hence model MACs, utility work, minibatches and update counts match.
        _, add_p, add_q = joint_value_and_grad(p, q, reward[y], 0)
        _, ndu_p, ndu_q = joint_value_and_grad(p, q, reward[y], plan["rho"])
        weights = {"supervised": (1.0, 0.0, 0.0),
                   "additive": (plan["ce_anchor"], 1.0, 0.0),
                   "ndu": (plan["ce_anchor"], 0.0, 1.0)}[arm]
        dt = weights[0] * ce_p + weights[1] * add_p + weights[2] * ndu_p
        di = weights[0] * ce_q + weights[1] * add_q + weights[2] * ndu_q
        model.train_step(x, dt, di, lr)
    d, k, _, h = model.dimensions
    n = plan["adapt_steps"] * plan["batch_size"]
    return model, {"updates": model.updates, "examples": n,
                   "tensor_macs": n * (3 * d * h + 8 * h * k),
                   "joint_outcome_cells": 2 * n * k * k,
                   "utility_profiles_per_update": [0, plan["rho"]],
                   "wall_seconds": time.perf_counter() - started}


def run(out):
    lifecycle_started = time.perf_counter()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "selection.json").exists():
        raise ValueError("selection already frozen; use a new run directory")
    sources = {p.name: sha256(p) for p in ROOT.glob("*.py")}
    plan_digest = sha256(ROOT / "plan.json")
    plan = json.loads((ROOT / "plan.json").read_text())
    if plan["dataset_seeds"] != SPLIT_SEEDS:
        raise ValueError("plan seed profile differs from the dataset implementation")
    train, val = dataset("train", plan["variants"]), dataset("validation", plan["variants"])
    if set(train["groups"]) & set(val["groups"]):
        raise ValueError("source leakage")
    all_results, bases = [], {}
    for seed in plan["model_seeds"]:
        base = JointModel(train["full"].shape[1], CLASSES, SIDE * SIDE * 3,
                          hidden=plan["hidden"], seed=seed)
        decoder_started = time.perf_counter()
        decoder_loss = base.fit_decoder(templates(), steps=plan["decoder_steps"])
        decoder_seconds = time.perf_counter() - decoder_started
        rng = np.random.default_rng(seed + 1000)
        started = time.perf_counter()
        for _ in range(plan["pretrain_steps"]):
            rows = rng.integers(len(train["labels"]), size=plan["batch_size"])
            full = rng.random(len(rows)) < 0.5
            x = np.where(full[:, None], train["full"][rows], train["low"][rows])
            base.supervised_step(x, train["labels"][rows], lr=0.003)
        pretrain_seconds = time.perf_counter() - started
        base.save(out / f"base-{seed}.npz")
        validation_started = time.perf_counter()
        base_validation = summary(base, val, plan["rho"])
        bases[seed] = {"digest": base.digest(), "validation": base_validation,
                       "decoder_mse": decoder_loss, "decoder_seconds": decoder_seconds,
                       "pretrain_seconds": pretrain_seconds,
                       "validation_seconds": time.perf_counter() - validation_started,
                       "pretrain_updates": plan["pretrain_steps"], "decoder_updates": plan["decoder_steps"]}
        print(json.dumps({"seed": seed, "base_validation": bases[seed]["validation"]}), flush=True)
        for arm in plan["arms"]:
            for lr in plan["learning_rates"]:
                model, cost = train_candidate(base, train, plan, arm, lr, seed)
                name = f"{arm}-{seed}-{lr}"
                model.save(out / (name + ".npz"))
                validation_started = time.perf_counter()
                validation = summary(model, val, plan["rho"])
                row = {"arm": arm, "seed": seed, "learning_rate": lr, "name": name,
                       "cost": cost, "validation": validation,
                       "validation_seconds": time.perf_counter() - validation_started,
                       "content_parameters_changed": any(not np.array_equal(model.params[key], base.params[key])
                                                         for key in ("encoder", "text", "image"))}
                all_results.append(row)
                print(json.dumps(row), flush=True)
    selected = []
    for arm in plan["arms"]:
        lr = max(plan["learning_rates"], key=lambda rate: np.mean([
            row["validation"]["task_utility"] for row in all_results
            if row["arm"] == arm and row["learning_rate"] == rate]))
        for row in all_results:
            if row["arm"] != arm or row["learning_rate"] != lr:
                continue
            model_path = out / (row["name"] + ".npz")
            model = JointModel.load(model_path)
            controller_started = time.perf_counter()
            pl, ql = model.forward(train["low"])
            pf, qf = model.forward(train["full"])
            reward = outcome_table(model)[train["labels"]]
            vl = joint_value_and_grad(pl, ql, reward, plan["rho"])[0]
            vf = joint_value_and_grad(pf, qf, reward, plan["rho"])[0]
            controller = fit_controller(pl, ql, vf - vl)
            controller_seconds = time.perf_counter() - controller_started
            control_path = out / (row["name"] + "-controller.npz")
            np.savez_compressed(control_path, **controller.to_arrays())
            bundle = {**row, "model_file": model_path.name, "controller_file": control_path.name,
                      "model_sha256": sha256(model_path), "controller_sha256": sha256(control_path),
                      "artifact_sha256": model.digest(), "compute_price": plan["compute_price"],
                      "rho": plan["rho"], "capabilities": ["text", "image"],
                      "controller_training": {"rows": len(train["labels"]),
                          "model_forward_rows": 2 * len(train["labels"]),
                          "outcome_cells": 2 * len(train["labels"]) * CLASSES**2,
                          "ridge_features": 2 * CLASSES + 7,
                          "wall_seconds": controller_seconds},
                      "qualification_only": True}
            write_json(out / (row["name"] + "-manifest.json"), bundle)
            selected.append(bundle)
    if any(sha256(ROOT / name) != value for name, value in sources.items()) or sha256(ROOT / "plan.json") != plan_digest:
        raise ValueError("source or plan changed while training")
    selection = {"plan": plan, "plan_sha256": sha256(ROOT / "plan.json"), "sources": sources,
                 "datasets": {"train": manifest(train), "validation": manifest(val)},
                 "environment": {"python": platform.python_version(), "numpy": np.__version__,
                                 "platform": platform.platform(), "device": "CPU",
                                 "thread_evidence": thread_evidence()},
                 "lifecycle": {"total_training_selection_seconds": time.perf_counter() - lifecycle_started,
                               "base_cost": "shared initial checkpoint per seed; reported separately, not free",
                               "selection_cost": "all learning-rate candidate adaptation and validation rows retained",
                               "controller_cost": "training-fold model passes, utility cells and ridge fit reported per selected bundle"},
                 "bases": bases, "all_validation_candidates": all_results, "selected": selected,
                 "test_opened": False}
    write_json(out / "selection.json", selection)
    print(json.dumps({"selection_frozen": str(out / "selection.json"),
                      "selected": [row["name"] for row in selected]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    run(parser.parse_args().out)
