"""Independent gradient checks, immutable training evidence, then held-out evaluation."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.special import logsumexp

try:
    from .content import Adam, Model
    from .content_tasks import TASKS, array_hash, digits_data, sample_batch, save_dataset_identity, task_protocol
except ImportError:
    from content import Adam, Model
    from content_tasks import TASKS, array_hash, digits_data, sample_batch, save_dataset_identity, task_protocol


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protocol():
    return {"version": 1, "families": ["ordinary", "analytic"], "widths": [16, 32, 64],
            "seeds": [11, 23, 37], "updates": 300, "batch": 32, "lr": 0.003,
            "grad_clip": 1.0, "dtype": "float64", "optimizer": "Adam beta=(.9,.999), eps=1e-8",
            "objective": "mean final-token classification cross entropy; full BPTT",
            "train_seed": "700000 + 10000*task_index + model_seed",
            "dev_seed": "1200000 + 10000*task_index + (100 if long_delay else 0)",
            "test_seed": "1700000 + 10000*task_index + (100 if long_delay else 0)",
            "dev_synthetic_examples": 512, "test_synthetic_examples": 2048,
            "evaluation_digits": "entire fixed requested dev/test split once",
            "tasks": task_protocol(),
            "analytic_gate": "1-exp(-E[N]); x=softplus(-a)+.05, mu=-.25, sigma=1, reset=.8, refractory=.15",
            "ordinary_gate": "1-exp(-dt*softplus(a))",
            "interpretation": "deterministic renewal-flow gate; not expectation of a nonlinear sampled SNN"}


def source_hashes():
    base = Path(__file__).parent
    return {name: file_hash(base / name) for name in
            ("content.py", "content_tasks.py", "content_audit.py", "renewal.py")}


def gradient_check(out):
    rng = np.random.default_rng(90517)
    x = rng.normal(0, 0.4, (3, 2, 3))
    y = np.array([0, 1])
    dt = np.array([[0.3, 0.8], [1.0, 1.5], [0.4, 0.9]])
    result = {"data": "tiny random development sequence; no task test data", "checks": []}
    for family in ("ordinary", "analytic"):
        model = Model(family, 3, 2, 2, 901)
        _, analytic = model.loss_grad(x, y, dt)
        for name, parameter in model.params.items():
            numerical = np.empty_like(parameter)
            for index in np.ndindex(parameter.shape):
                original = parameter[index]
                epsilon = 1e-6 * max(1, abs(original))
                parameter[index] = original + epsilon
                plus = model.loss(x, y, dt)
                parameter[index] = original - epsilon
                minus = model.loss(x, y, dt)
                parameter[index] = original
                numerical[index] = (plus - minus) / (2 * epsilon)
            error = float(np.max(np.abs(numerical - analytic[name])))
            relative = float(np.linalg.norm(numerical - analytic[name]) /
                             max(1e-12, np.linalg.norm(numerical) + np.linalg.norm(analytic[name])))
            result["checks"].append({"family": family, "parameter": name, "count": parameter.size,
                                      "max_absolute_error": error, "relative_l2_error": relative})
            if error > 2e-6 or relative > 5e-4:
                raise AssertionError((family, name, error, relative))
        path = Path(out) / ("development_" + family + ".npz")
        model.save(path)
        restored = Model.load(path)
        if not np.array_equal(model.forward(x, dt)[0], restored.forward(x, dt)[0]):
            raise AssertionError("save/load changed the recurrent trajectory")
        old = model.initial(2)
        if not np.array_equal(model.step(x[0], old, 0.0), old):
            raise AssertionError("zero elapsed time must preserve state")
    # A hardware cost probe uses random development data and never test labels.
    probe_x = rng.normal(0, 0.3, (12, 32, 12))
    probe_y = rng.integers(0, 2, 32)
    result["cost_probe"] = []
    for width in (16, 32, 64):
        for family in ("ordinary", "analytic"):
            model = Model(family, 12, width, 2, 901)
            optimizer = Adam(model)
            start, cpu = time.perf_counter(), time.process_time()
            for _ in range(5):
                _, grads = model.loss_grad(probe_x, probe_y)
                optimizer.step(model, grads)
            result["cost_probe"].append({"family": family, "width": width, "updates": 5,
                                          "wall_seconds": time.perf_counter() - start,
                                          "cpu_seconds": time.process_time() - cpu,
                                          "parameters": model.parameter_count})
    a = np.linspace(-6, 6, 121)
    distance = np.logaddexp(0.0, -a) + 0.05
    recovered = -np.log(np.expm1(distance - 0.05))
    result["distance_coordinate_check"] = {
        "domain": [-6.0, 6.0], "max_inverse_error": float(np.max(np.abs(a - recovered))),
        "content_state": "h[batch,width] is the learned content vector",
        "distance": "coordinatewise invertible in gate preactivation a in exact arithmetic",
        "limitation": "a is a projection of input and state; distance is not an invertible encoding of their joint state; finite precision can saturate"}
    result["source_sha256"] = source_hashes()
    result["python"] = platform.python_version()
    write_json(Path(out) / "development_checks.json", result)
    return result


def train_run(task, family, width, seed, out, updates=300, batch=32):
    """Training only. Caller publishes the frozen protocol before this entry point."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("refusing to overwrite an existing or interrupted run")
    out.mkdir(parents=True, exist_ok=True)
    task_index = list(TASKS).index(task)
    train_seed = 700000 + 10000 * task_index + seed
    rng = np.random.default_rng(train_seed)
    model = Model(family, **TASKS[task], width=width, seed=seed)
    initial = {key: value.copy() for key, value in model.params.items()}
    model.save(out / "initial.npz")
    optimizer = Adam(model)
    config = {"task": task, "family": family, "width": width, "seed": seed,
              "train_seed": train_seed, "updates": updates, "batch": batch,
              "parameter_count": model.parameter_count, "protocol": protocol(),
              "source_sha256": source_hashes(), "phase": "train_only",
              "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                          "scipy": scipy.__version__, "platform": platform.platform()}}
    write_json(out / "run_config.json", config)
    start, cpu = time.perf_counter(), time.process_time()
    sequence_steps = 0
    with (out / "training_steps.jsonl").open("w") as stream:
        for step in range(updates):
            item = sample_batch(task, rng, batch, split="train")
            loss, grads = model.loss_grad(item["x"], item["y"], item["dt"])
            norm, scale = optimizer.step(model, grads)
            sequence_steps += item["x"].shape[0] * batch
            row = {"step": step + 1, "loss_before_update": loss, "gradient_norm": norm,
                   "clip_scale": scale, "wall_seconds": time.perf_counter() - start,
                   "cpu_seconds": time.process_time() - cpu,
                   "examples_seen": (step + 1) * batch, "sequence_steps": sequence_steps,
                   "recurrent_cell_updates": sequence_steps * width,
                   "batch_sha256": array_hash(item["x"], item["y"], item["dt"], item["ids"]),
                   "gradient_norm_by_parameter": {key: float(np.linalg.norm(v)) for key, v in grads.items()}}
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            if step in (0, updates - 1):
                np.savez_compressed(out / ("train_batch_%04d.npz" % (step + 1)), **item)
    total_wall, total_cpu = time.perf_counter() - start, time.process_time() - cpu
    changes = {key: float(np.linalg.norm(value - initial[key])) for key, value in model.params.items()}
    if not all(value > 0 for value in changes.values()):
        raise AssertionError("one or more trainable parameter arrays never changed")
    model.save(out / "final.npz", metadata={"task": task, "updates": updates, "train_seed": train_seed})
    optimizer.save(out / "optimizer_final.npz")
    if source_hashes() != config["source_sha256"]:
        raise RuntimeError("source changed during training; run cannot be frozen")
    receipt = {"checkpoint": "final.npz", "checkpoint_sha256": file_hash(out / "final.npz"),
               "initial_sha256": file_hash(out / "initial.npz"),
               "training_log_sha256": file_hash(out / "training_steps.jsonl"),
               "training_wall_seconds": total_wall, "training_cpu_seconds": total_cpu,
               "examples_seen": updates * batch, "sequence_steps": sequence_steps,
               "recurrent_cell_updates": sequence_steps * width,
               "parameter_delta_l2": changes, "test_evaluations_before_freeze": 0,
               "finished_unix_time": time.time(), "source_sha256": source_hashes()}
    write_json(out / "FINAL_CHECKPOINT_RECEIPT.json", receipt)
    return receipt


def evaluate_run(run, out=None, split="test"):
    """Read a frozen checkpoint. No training/selection occurs in this function."""
    run = Path(run)
    if split not in ("dev", "test"):
        raise ValueError("evaluation split must be dev or test")
    out = run / ("evaluation_" + split) if out is None else Path(out)
    receipt = json.loads((run / "FINAL_CHECKPOINT_RECEIPT.json").read_text())
    if file_hash(run / "final.npz") != receipt["checkpoint_sha256"]:
        raise ValueError("checkpoint changed after the training receipt")
    config = json.loads((run / "run_config.json").read_text())
    if source_hashes() != config["source_sha256"]:
        raise ValueError("evaluation sources differ from the frozen training implementation")
    task = config["task"]
    model = Model.load(run / "final.npz")
    task_index = list(TASKS).index(task)
    out.mkdir(parents=True, exist_ok=True)
    report = {"checkpoint_sha256": receipt["checkpoint_sha256"], "task": task,
              "family": model.family, "width": model.width, "seed": model.seed,
              "data_partition": split, "splits": {}}
    for variant_index, variant in enumerate(("iid", "long_delay", "clock_shift")):
        base_seed = 1200000 if split == "dev" else 1700000
        data_seed = base_seed + 10000 * task_index + (100 if variant == "long_delay" else 0)
        rng = np.random.default_rng(data_seed)
        ids = digits_data()[2][split] if task == "digits_rows" else None
        count = len(ids) if ids is not None else (512 if split == "dev" else 2048)
        all_logits, all_labels, all_ids, batch_hashes = [], [], [], []
        start, cpu = time.perf_counter(), time.process_time()
        for offset in range(0, count, 64):
            size = min(64, count - offset)
            item = sample_batch(task, rng, size, variant=variant, split=split,
                                indices=None if ids is None else ids[offset:offset + size])
            h, _ = model.forward(item["x"], item["dt"])
            all_logits.append(model.logits(h))
            all_labels.append(item["y"])
            all_ids.append(item["ids"])
            batch_hashes.append(array_hash(item["x"], item["y"], item["dt"], item["ids"]))
        logits, labels = np.concatenate(all_logits), np.concatenate(all_labels)
        prediction = logits.argmax(axis=1)
        accuracy = float(np.mean(prediction == labels))
        nll = float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(count), labels]))
        report["splits"][variant] = {
            "n": count, "accuracy": accuracy, "nll": nll,
            "accuracy_standard_error": float(np.sqrt(accuracy * (1 - accuracy) / count)),
            "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
            "data_seed": data_seed, "batch_sha256": batch_hashes}
        np.savez_compressed(out / (variant + "_predictions.npz"), logits=logits, labels=labels,
                            predictions=prediction, ids=np.concatenate(all_ids))
    write_json(out / "metrics.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("protocol", "check", "identity", "train", "evaluate"))
    parser.add_argument("--out", default="evidence/content")
    parser.add_argument("--task", choices=list(TASKS) + ["all"], default="all")
    parser.add_argument("--family", choices=("ordinary", "analytic", "all"), default="all")
    parser.add_argument("--widths", default="16,32,64")
    parser.add_argument("--seeds", default="11,23,37")
    parser.add_argument("--updates", type=int, default=300)
    parser.add_argument("--run")
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    args = parser.parse_args()
    if args.phase == "protocol":
        write_json(Path(args.out) / "content_protocol.json", protocol())
    elif args.phase == "identity":
        print(json.dumps(save_dataset_identity(args.out)))
    elif args.phase == "check":
        print(json.dumps(gradient_check(args.out)))
    elif args.phase == "evaluate":
        runs = [Path(args.run)] if args.run else sorted(Path(args.out).glob("runs/*/*"))
        for run in runs:
            print(json.dumps(evaluate_run(run, split=args.split)))
    else:
        tasks = list(TASKS) if args.task == "all" else [args.task]
        families = ["ordinary", "analytic"] if args.family == "all" else [args.family]
        for task in tasks:
            for family in families:
                for width in map(int, args.widths.split(",")):
                    for seed in map(int, args.seeds.split(",")):
                        run = Path(args.out) / "runs" / task / f"{family}_w{width}_s{seed}"
                        print(json.dumps({"run": str(run), "receipt": train_run(
                            task, family, width, seed, run, updates=args.updates)}), flush=True)


if __name__ == "__main__":
    main()
