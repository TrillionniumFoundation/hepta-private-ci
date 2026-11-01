"""Budgeted CPU training, common-data provenance and frozen model selection."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from .cell import Cell
from .data import generate_sequences
from .estimators import HXFilter, posterior_ce
from .recurrent import RecurrentEstimator


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def array_hash(data):
    digest = hashlib.sha256()
    for key in sorted(data):
        value = np.ascontiguousarray(data[key])
        digest.update(key.encode())
        digest.update(str((value.shape, value.dtype.str)).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def prepare(seed, output):
    start, wall = time.process_time(), time.perf_counter()
    path = Path(output) / str(seed)
    path.mkdir(parents=True, exist_ok=True)
    truth = Cell()
    train = generate_sequences(truth, seed + 1000000, 384)
    validation = generate_sequences(truth, seed + 2000000, 96)
    np.savez_compressed(path / "common_data.npz", **{"train_" + k: v for k, v in train.items()},
                        **{"validation_" + k: v for k, v in validation.items()})
    record = {"seed": seed, "train_seed": seed + 1000000,
              "validation_seed": seed + 2000000,
              "train_hash": array_hash(train), "validation_hash": array_hash(validation),
              "common_preparation_cpu_seconds": time.process_time() - start,
              "common_preparation_wall_seconds": time.perf_counter() - wall,
              "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
              "note": "Training labels and teacher posterior are never inference features."}
    atomic_json(path / "data_manifest.json", record)
    return record


def train_one(seed, kind, output, cpu_seconds=20.):
    path = Path(output) / str(seed)
    # Data load is separately timed and included in total fit CPU.
    started, wall = time.process_time(), time.perf_counter()
    with np.load(path / "common_data.npz") as archive:
        train = {name: archive["train_" + name] for name in ("inputs", "teacher", "labels")}
        validation = {name: archive["validation_" + name] for name in ("inputs", "teacher", "labels")}
    load_cpu = time.process_time() - started
    model_start = time.process_time()
    model = HXFilter(seed) if kind == "hx_distribution" else RecurrentEstimator(kind, seed)
    learning_rate = .03 if kind == "hx_distribution" else .01
    moment = {k: np.zeros_like(v) for k, v in model.params.items()}
    variance = {k: np.zeros_like(v) for k, v in model.params.items()}
    rng = np.random.default_rng(seed + 3000000)
    permutation = rng.permutation(len(train["inputs"]))
    position = 0
    updates = 0
    history = []
    best = None
    best_ce = float("inf")
    validation_cpu = 0.
    max_operation = 0.
    best_update = 0
    last_loss = None

    def validate():
        nonlocal best, best_ce, best_update, validation_cpu, max_operation
        op = time.process_time()
        predicted = model.forward(validation["inputs"])
        score = posterior_ce(predicted, validation["teacher"])
        if not np.isfinite(score):
            raise FloatingPointError("Nonfinite validation loss")
        if score < best_ce:
            best_ce, best_update, best = score, updates, model.export()
        elapsed = time.process_time() - op
        validation_cpu += elapsed
        max_operation = max(max_operation, elapsed)
        history.append({"updates": updates, "cpu_seconds": time.process_time() - model_start,
                        "validation_joint_ce": score, "last_training_loss": last_loss})

    validate()
    while time.process_time() - model_start < cpu_seconds:
        op = time.process_time()
        if position >= len(permutation):
            permutation = rng.permutation(len(train["inputs"]))
            position = 0
        indices = permutation[position:position + 32]
        position += 32
        last_loss, gradients = model.loss_grad(train["inputs"][indices], train["teacher"][indices], train["labels"][indices])
        if not np.isfinite(last_loss) or not all(np.isfinite(g).all() for g in gradients.values()):
            raise FloatingPointError("Nonfinite loss or gradient")
        norm = np.sqrt(sum(np.sum(g * g) for g in gradients.values()))
        scale = min(1., 5. / max(norm, 1e-300))
        updates += 1
        for key, parameter in model.params.items():
            gradient = gradients[key] * scale
            moment[key] = .9 * moment[key] + .1 * gradient
            variance[key] = .999 * variance[key] + .001 * gradient * gradient
            corrected_m = moment[key] / (1 - .9 ** updates)
            corrected_v = variance[key] / (1 - .999 ** updates)
            parameter -= learning_rate * corrected_m / (np.sqrt(corrected_v) + 1e-8)
        max_operation = max(max_operation, time.process_time() - op)
        if updates % 10 == 0 and time.process_time() - model_start < cpu_seconds:
            validate()
    final = model.export()
    # Both selected and final checkpoint remain reviewable. Export is charged.
    payload = {"schema": "hcsn-r13-fit-v1", "seed": seed, "kind": kind,
               "budget_cpu_seconds": cpu_seconds, "updates": updates,
               "selected_update": best_update, "selected_validation_joint_ce": best_ce,
               "selected_model": best, "final_model": final, "history": history,
               "data_load_cpu_seconds": load_cpu, "validation_cpu_seconds": validation_cpu,
               "max_operation_cpu_seconds": max_operation,
               "training_cpu_seconds": time.process_time() - model_start,
               "total_fit_cpu_seconds": time.process_time() - started,
               "wall_seconds": time.perf_counter() - wall,
               "status": "completed", "inference_uses_teacher": False}
    destination = path / (kind + ".json")
    export_started = time.process_time()
    atomic_json(destination, payload)
    payload["checkpoint_export_cpu_seconds"] = time.process_time() - export_started
    payload["training_cpu_seconds"] = time.process_time() - model_start
    payload["total_fit_cpu_seconds"] = time.process_time() - started
    payload["wall_seconds"] = time.perf_counter() - wall
    payload["budget_overshoot_cpu_seconds"] = max(0., payload["training_cpu_seconds"] - cpu_seconds)
    atomic_json(destination, payload)
    return {k: payload[k] for k in ("seed", "kind", "updates", "selected_validation_joint_ce", "total_fit_cpu_seconds", "budget_overshoot_cpu_seconds")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "train"))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--kind", choices=("hx_distribution", "gru", "continuous_diagonal_ssm"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--cpu-seconds", type=float, default=20.)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.operation == "prepare":
            result = prepare(args.seed, args.output)
        else:
            result = train_one(args.seed, args.kind, args.output, args.cpu_seconds)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
