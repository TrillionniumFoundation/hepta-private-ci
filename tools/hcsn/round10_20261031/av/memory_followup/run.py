"""Followup with matched long-delay training/selection and same-actor donors."""
import time
START = time.perf_counter()
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from scipy.special import logsumexp

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from models import Model, Adam
from study import load_split, inputs, digest

PROTOCOL = json.loads((ROOT / "PROTOCOL.json").read_text())


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def donor_plan(data, split):
    rng = np.random.default_rng({"train": 71009, "validation": 71011, "test": 71017}[split])
    plan = np.arange(len(data["y"]))
    for actor in np.unique(data["actor"]):
        group = np.flatnonzero(data["actor"] == actor)
        order = rng.permutation(group)
        plan[order] = np.roll(order, 1)
    assert (plan != np.arange(len(plan))).all()
    assert (data["actor"][plan] == data["actor"]).all()
    return plan


def sequence(data, ids, gap, plan=None, rng=None, target_zero=False):
    x, dt = inputs(data, ids, "full")
    if target_zero:
        x[:, :32, :259] = 0
        dt[:, :32] = 0.1
    if gap:
        if plan is None:
            donor = np.array([rng.choice(np.flatnonzero((data["actor"] == data["actor"][i]) & (np.arange(len(data["y"])) != i))) for i in ids])
        else:
            donor = plan[ids]
        assert (data["actor"][donor] == data["actor"][ids]).all()
        assert (donor != ids).all()
        offsets = np.arange(gap) % 32
        distract = np.concatenate((data["audio"][donor][:, offsets].astype(float),
                                   data["video"][donor][:, offsets].astype(float),
                                   np.ones((len(ids), gap, 2)), np.zeros((len(ids), gap, 3))), axis=2)
        x = np.concatenate((x[:, :32], distract, x[:, 32:]), axis=1)
        dt = np.concatenate((dt[:, :32], np.full((len(ids), gap), 0.1), dt[:, 32:]), axis=1)
    return x, dt


def evaluate(model, data, plan, condition):
    gap = 0 if condition == "full" else (32 if condition == "delay32" else 96)
    values = []
    for start in range(0, len(data["y"]), 32):
        ids = np.arange(start, min(start + 32, len(data["y"])))
        x, dt = sequence(data, ids, gap, plan, target_zero=condition.endswith("target_zero"))
        values.append(model.forward(x, dt)[0])
    logits = np.concatenate(values); y = data["y"]
    acc = (logits.argmax(axis=1) == y).astype(float)
    ce = logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]
    actors = {str(a): {"accuracy": float(acc[data["actor"] == a].mean()), "ce": float(ce[data["actor"] == a].mean())} for a in np.unique(data["actor"])}
    return {"accuracy": float(acc.mean()), "ce": float(ce.mean()), "actors": actors}, logits


def worker(args):
    out = ROOT / "results" / f"{args.model}_{args.seed}"; out.mkdir(parents=True, exist_ok=False)
    save(out / "START.json", {"protocol_sha256": digest(ROOT / "PROTOCOL.json"), "source_sha256": digest(__file__),
                              "parent_models_sha256": digest(ROOT.parent / "models.py"), "test_opened": False})
    train, val = load_split(args.data, "train"), load_split(args.data, "validation")
    vp = donor_plan(val, "validation")
    save(out / "VALIDATION_DONORS.json", {"indices": vp.tolist(), "actor": val["actor"].tolist(), "clip": val["clip"].tolist()})
    kind = "cfc" if args.model.startswith("cfc") else args.model
    model = Model(kind, PROTOCOL["models"][args.model], seed=args.seed)
    initial = {k: v.copy() for k, v in model.p.items()}
    opt = Adam(model, PROTOCOL["learning_rate"]); rng = np.random.default_rng(args.seed + 130007)
    cpu_total, wall_total, count, midpoint = 0.0, 0.0, 0, False
    best, selected, selected_update = float("inf"), None, None
    trace, validation = [], []
    while True:
        cpu, wall = time.process_time(), time.perf_counter()
        ids = rng.integers(0, len(train["y"]), PROTOCOL["batch_size"])
        gap = int(rng.choice(PROTOCOL["training_gaps"]))
        x, dt = sequence(train, ids, gap, rng=rng)
        loss, grad = model.loss(x, dt, train["y"][ids]); norm = opt.update(model, grad)
        cpu_total += time.process_time() - cpu; wall_total += time.perf_counter() - wall; count += 1
        trace.append({"update": count, "gap": gap, "loss": loss, "gradient_norm": norm, "train_cpu": cpu_total, "train_wall": wall_total})
        complete = cpu_total >= PROTOCOL["training_cpu_seconds"]
        if (not midpoint and cpu_total >= PROTOCOL["training_cpu_seconds"] / 2) or complete:
            midpoint = True
            metrics = {c: evaluate(model, val, vp, c)[0] for c in ("delay32", "delay96")}
            objective = np.mean([m["ce"] for m in metrics.values()])
            validation.append({"update": count, "train_cpu": cpu_total, "objective": float(objective), "metrics": metrics})
            if objective < best:
                best, selected_update = float(objective), count
                selected = {k: v.copy() for k, v in model.p.items()}
        if complete:
            break
    np.savez_compressed(out / "final.npz", **model.p); model.p = selected
    np.savez_compressed(out / "selected.npz", **model.p)
    save(out / "SELECTION.json", {"update": selected_update, "validation_objective": best,
                                  "checkpoint_sha256": digest(out / "selected.npz"), "test_opened": False})
    test = load_split(args.data, "test")
    assert not (set(train["actor"]) | set(val["actor"])) & set(test["actor"])
    tp = donor_plan(test, "test")
    save(out / "TEST_DONORS.json", {"indices": tp.tolist(), "actor": test["actor"].tolist(), "clip": test["clip"].tolist()})
    metrics, raw = {}, {"y": test["y"], "actor": test["actor"], "clip": test["clip"], "donor": tp}
    for condition in PROTOCOL["test_conditions"]:
        metrics[condition], raw[condition] = evaluate(model, test, tp, condition)
    np.savez_compressed(out / "predictions.npz", **raw)
    save(out / "TRACE.json", trace); save(out / "VALIDATION.json", validation)
    result = {"model": args.model, "seed": args.seed, "parameters": model.parameters, "updates": count,
              "selected_update": selected_update, "train_cpu": cpu_total, "train_wall": wall_total,
              "process_cpu_until_receipt": time.process_time(), "process_wall_until_receipt": time.perf_counter() - START,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "metrics": metrics, "all_blocks_updated": {k: bool(np.any(v != initial[k])) for k, v in model.p.items()},
              "checkpoint_sha256": digest(out / "selected.npz"), "predictions_sha256": digest(out / "predictions.npz")}
    save(out / "RESULT.json", result)
    print(json.dumps({"model": args.model, "seed": args.seed, "updates": count, "delay96": metrics["delay96"]["accuracy"]}), flush=True)


def launch(args):
    (ROOT / "results").mkdir(exist_ok=True)
    save(ROOT / "REGISTRATION.json", {"source": {"run.py": digest(__file__), "PROTOCOL.json": digest(ROOT / "PROTOCOL.json"),
                                               "../models.py": digest(ROOT.parent / "models.py"), "../study.py": digest(ROOT.parent / "study.py")},
                                     "unix": time.time(), "new_exploratory_supplement": True, "original_eight_gates_unchanged": True})
    def one(job):
        name, seed = job; start = time.perf_counter()
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--data", str(args.data), "--model", name, "--seed", str(seed)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if hasattr(os, "wait4"):
            _, status, usage = os.wait4(process.pid, 0); process.returncode = os.waitstatus_to_exitcode(status)
            cpu = usage.ru_utime + usage.ru_stime
        else:
            process.wait(); cpu = None
        stdout, stderr = process.communicate()
        result = {"model": name, "seed": seed, "exit_code": process.returncode, "complete_cpu": cpu,
                  "launch_to_exit_wall": time.perf_counter() - start, "stdout": stdout, "stderr": stderr}
        print(json.dumps(result), flush=True); return result
    jobs = [(model, seed) for model in PROTOCOL["models"] for seed in PROTOCOL["seeds"]]
    receipts = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(one, job) for job in jobs]):
            receipts.append(future.result()); save(ROOT / "LAUNCH_RECEIPTS.json", receipts)
    assert all(r["exit_code"] == 0 for r in receipts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("worker", "launch"))
    parser.add_argument("--data", type=Path, required=True); parser.add_argument("--model", choices=list(PROTOCOL["models"]))
    parser.add_argument("--seed", type=int); arguments = parser.parse_args()
    (worker if arguments.command == "worker" else launch)(arguments)
