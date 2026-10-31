"""Registered real-AV training; complete small recurrent models, no Torch dependency."""
import time
PROCESS_START = time.perf_counter()
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from scipy.special import logsumexp
from models import Model, Adam

ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "PROTOCOL.json").read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def load_split(data, split):
    manifest = json.loads((data / "DATASET.json").read_text())
    spec = manifest["splits"][split]
    path = data / spec["path"]
    assert digest(path) == spec["sha256"]
    with np.load(path, allow_pickle=False) as arrays:
        result = {key: arrays[key].copy() for key in arrays.files}
    assert len(result["y"]) == spec["examples"]
    assert set(result["actor"]) == set(spec["actors"])
    return result


def inputs(data, indices, condition="full", gap=0, rng=None):
    audio = data["audio"][indices].astype(np.float64).copy()
    video = data["video"][indices].astype(np.float64).copy()
    n, steps = audio.shape[:2]
    elapsed = 0.1 * data["dt"][indices].astype(np.float64)
    masks = np.ones((n, steps, 2))
    if condition == "train":
        coins = rng.random(n)
        masks[coins < 0.1, :, 0] = 0
        masks[(coins >= 0.1) & (coins < 0.2), :, 1] = 0
    elif condition == "missing_audio":
        masks[:, :, 0] = 0
    elif condition == "missing_video":
        masks[:, :, 1] = 0
    elif condition == "block_missing":
        masks[:, 8:24, 0] = 0
        masks[:, 16:32, 1] = 0
    elif condition == "video_shift4":
        video = np.concatenate((np.zeros_like(video[:, :4]), video[:, :-4]), axis=1)
        masks[:, :4, 1] = 0
    elif condition == "within_actor_mispair":
        mapping = np.arange(len(data["y"]))
        for actor in np.unique(data["actor"]):
            group = np.flatnonzero(data["actor"] == actor)
            mapping[group] = np.roll(group, 1)
        video = data["video"][mapping[indices]].astype(np.float64)
    audio *= masks[:, :, :1]
    video *= masks[:, :, 1:]
    x = np.concatenate((audio, video, masks, np.log(elapsed[:, :, None] / 0.1),
                        np.ones((n, steps, 1)), np.zeros((n, steps, 1))), axis=2)
    if gap:
        if rng is None:
            donor = (indices + 37) % len(data["y"])
        else:
            donor = rng.integers(0, len(data["y"]), n)
        offset = np.arange(gap) % steps
        distract_audio = data["audio"][donor][:, offset].astype(np.float64)
        distract_video = data["video"][donor][:, offset].astype(np.float64)
        distract = np.concatenate((distract_audio, distract_video, np.ones((n, gap, 2)),
                                   np.zeros((n, gap, 3))), axis=2)
        x = np.concatenate((x, distract), axis=1)
        elapsed = np.concatenate((elapsed, np.full((n, gap), 0.1)), axis=1)
    query = np.zeros((n, 1, 261)); query[:, :, -1] = 1
    x = np.concatenate((x, query), axis=1)
    elapsed = np.concatenate((elapsed, np.full((n, 1), 0.1)), axis=1)
    return x, elapsed


def evaluate(model, data, condition):
    gap = int(condition[5:]) if condition.startswith("delay") else 0
    selected = "full" if gap else condition
    logits = []
    for start in range(0, len(data["y"]), 32):
        ids = np.arange(start, min(start + 32, len(data["y"])))
        x, dt = inputs(data, ids, selected, gap)
        logits.append(model.forward(x, dt)[0])
    logits = np.concatenate(logits)
    prob = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
    y = data["y"]
    correct = (logits.argmax(axis=1) == y).astype(float)
    losses = logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]
    brier = np.sum((prob - np.eye(6)[y]) ** 2, axis=1)
    by_actor = {str(actor): {"accuracy": float(correct[data["actor"] == actor].mean()),
                            "ce": float(losses[data["actor"] == actor].mean()),
                            "brier": float(brier[data["actor"] == actor].mean())}
                for actor in np.unique(data["actor"])}
    return {"accuracy": float(correct.mean()), "ce": float(losses.mean()),
            "brier": float(brier.mean()), "actors": by_actor}, logits


def worker(args):
    out = ROOT / "results" / f"{args.budget}_{args.model}_{args.seed}"
    out.mkdir(parents=True, exist_ok=False)
    save(out / "START.json", {"protocol_sha256": digest(ROOT / "PROTOCOL.json"),
                              "source_sha256": {p: digest(ROOT / p) for p in ("models.py", "study.py")},
                              "seed": args.seed, "model": args.model, "budget": args.budget,
                              "test_opened": False})
    train = load_split(args.data, "train"); val = load_split(args.data, "validation")
    assert not set(train["actor"]) & set(val["actor"])
    width = PROTOCOL["models"][args.model]
    kind = "cfc" if args.model.startswith("cfc") else args.model
    model = Model(kind, width, seed=args.seed)
    initial = {key: value.copy() for key, value in model.p.items()}
    opt = Adam(model, PROTOCOL["training"]["learning_rate"])
    rng = np.random.default_rng(args.seed + 500001)
    trace, validations, saved, best = [], [], None, float("inf")
    train_cpu, train_wall, updates = 0.0, 0.0, 0
    midpoint = False
    budget = PROTOCOL["training"]["fixed_updates" if args.budget == "fixed" else "equal_cpu_seconds"]
    while True:
        cpu, wall = time.process_time(), time.perf_counter()
        ids = rng.integers(0, len(train["y"]), PROTOCOL["training"]["batch_size"])
        gap = int(rng.choice([0, 8, 32]))
        x, dt = inputs(train, ids, "train", gap, rng)
        loss, gradient = model.loss(x, dt, train["y"][ids])
        norm = opt.update(model, gradient)
        train_cpu += time.process_time() - cpu; train_wall += time.perf_counter() - wall
        updates += 1
        progress = updates if args.budget == "fixed" else train_cpu
        trace.append({"update": updates, "ce": loss, "gradient_norm": norm,
                      "gap": gap, "training_cpu": train_cpu, "training_wall": train_wall})
        complete = progress >= budget
        if (not midpoint and progress >= budget / 2) or complete:
            metrics, _ = evaluate(model, val, "full")
            validations.append({"update": updates, "training_cpu": train_cpu, **metrics})
            midpoint = True
            if metrics["ce"] < best:
                best = metrics["ce"]; saved = {key: value.copy() for key, value in model.p.items()}
                selected_update = updates
        if complete:
            break
    np.savez_compressed(out / "final.npz", **model.p)
    model.p = saved
    np.savez_compressed(out / "selected.npz", **model.p)
    save(out / "SELECTION.json", {"selected_update": selected_update, "validation_ce": best,
                                  "checkpoint_sha256": digest(out / "selected.npz"),
                                  "test_opened": False})
    # Selection is on disk before loading the historical test arrays.
    test = load_split(args.data, "test")
    assert not (set(train["actor"]) | set(val["actor"])) & set(test["actor"])
    metrics, raw = {}, {"y": test["y"], "actor": test["actor"], "clip": test["clip"]}
    for condition in PROTOCOL["evaluation_conditions"]:
        metrics[condition], raw[condition] = evaluate(model, test, condition)
    np.savez_compressed(out / "predictions.npz", **raw)
    save(out / "TRACE.json", trace)
    save(out / "VALIDATION.json", validations)
    steps_total = sum(33 + row["gap"] for row in trace)
    heads = 4 if kind == "cfc" else 2
    per_step_affine = 2 * (261 + width) * heads * width
    result = {"model": args.model, "width": width, "parameters": model.parameters,
              "budget": args.budget, "seed": args.seed, "updates": updates,
              "selected_update": selected_update, "metrics": metrics,
              "all_parameter_blocks_updated": {key: bool(np.any(value != initial[key])) for key, value in model.p.items()},
              "training_cpu_seconds": train_cpu, "training_wall_seconds": train_wall,
              "process_cpu_until_receipt": time.process_time(), "process_wall_until_receipt": time.perf_counter() - PROCESS_START,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "training_affine_flop_estimate": 3 * 16 * steps_total * per_step_affine,
              "flop_scope": "Forward+backward affine recurrent matmuls, excludes activations/special functions/readout/Adam/memory traffic",
              "float": "float64", "energy_joules": None, "gpu": False,
              "checkpoint_sha256": digest(out / "selected.npz"), "prediction_sha256": digest(out / "predictions.npz")}
    save(out / "RESULT.json", result)
    print(json.dumps({"job": out.name, "updates": updates, "full_accuracy": metrics["full"]["accuracy"]}), flush=True)


def launch(args):
    (ROOT / "results").mkdir(exist_ok=True)
    checks = json.loads((ROOT / "GRADIENT_CHECK.json").read_text())
    assert checks["passed"] and checks["source_sha256"] == digest(ROOT / "models.py")
    source = {name: digest(ROOT / name) for name in ("PROTOCOL.json", "models.py", "study.py", "upstream_cfc_cell.py")}
    save(ROOT / "REGISTRATION.json", {"source": source, "registered_unix": time.time(),
                                       "host": platform.platform(), "numpy": np.__version__,
                                       "scope": "Registered before this run; historic aggregate test results were already known"})
    jobs = [(budget, model, seed) for budget in ("fixed", "cpu") for model in PROTOCOL["models"] for seed in PROTOCOL["seeds"]]
    def run_one(job):
        budget, model, seed = job
        started = time.perf_counter()
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--data", str(args.data),
                   "--budget", budget, "--model", model, "--seed", str(seed)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if hasattr(os, "wait4"):
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            cpu = usage.ru_utime + usage.ru_stime
        else:
            process.wait(); cpu = None
        stdout, stderr = process.communicate()
        row = {"budget": budget, "model": model, "seed": seed, "exit_code": process.returncode,
               "launch_to_exit_wall_seconds": time.perf_counter() - started,
               "complete_child_cpu_seconds": cpu, "stdout": stdout, "stderr": stderr}
        print(json.dumps(row), flush=True)
        return row
    receipts = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for future in as_completed([pool.submit(run_one, job) for job in jobs]):
            receipts.append(future.result()); save(ROOT / "LAUNCH_RECEIPTS.json", receipts)
    assert all(row["exit_code"] == 0 for row in receipts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("launch", "worker"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--budget", choices=("fixed", "cpu"))
    parser.add_argument("--model", choices=list(PROTOCOL["models"]))
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    (launch if args.command == "launch" else worker)(args)
