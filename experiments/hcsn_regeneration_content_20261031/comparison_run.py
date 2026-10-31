"""Secondary baselines: development audits, fit evidence, frozen-model evaluation."""

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.special import logsumexp

try:
    from .comparison_models import LIF, Transformer, load_model, make_model
    from .content import Adam
    from .content_audit import file_hash, protocol as primary_protocol, write_json
    from .content_tasks import TASKS, array_hash, digits_data, sample_batch
except ImportError:
    from comparison_models import LIF, Transformer, load_model, make_model
    from content import Adam
    from content_audit import file_hash, protocol as primary_protocol, write_json
    from content_tasks import TASKS, array_hash, digits_data, sample_batch


FAMILIES = ("transformer", "lif_surrogate")


def source_hashes():
    base = Path(__file__).parent
    return {name: file_hash(base / name) for name in
            ("comparison_models.py", "comparison_run.py", "content.py", "content_audit.py",
             "content_tasks.py", "renewal.py")}


def protocol():
    value = primary_protocol()
    value.update({"experiment": "secondary traditional baselines", "families": list(FAMILIES),
                  "parameter_matching": False, "capacity_comparison": "report parameter counts and CPU versus quality",
                  "transformer": {"blocks": 1, "heads": 1, "normalization": "pre-LN eps1e-5",
                                  "position": "sin/cos of cumulative dt, base10000",
                                  "ffn_ratio": 2, "activation": "exact GELU", "attention": "causal softmax",
                                  "dropout": 0, "QKV_bias": False, "gradient": "exact hand backprop"},
                  "lif_surrogate": {"tau_membrane": 2, "tau_read": 4, "threshold": 1,
                                    "reset": "subtract threshold; differentiate through reset with declared surrogate",
                                    "forward": "hard 0/1; at most one spike per observed slot",
                                    "surrogate": "1/(1+abs(pre_voltage-1))**2",
                                    "readout": "exponentially filtered spikes",
                                    "gradient": "surrogate, not true forward-loss derivative"}})
    value.pop("analytic_gate")
    value.pop("ordinary_gate")
    value["interpretation"] = "small CPU classification encoders; no energy, generative-model or SOTA conclusion"
    return value


def finite_difference(model, x, y, dt, key):
    parameter = model.params[key]
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
    return numerical


def development_check(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(71239)
    x = rng.normal(0, 0.5, (4, 2, 3))
    y = np.array([0, 1])
    dt = np.array([[0.5, 1.1], [1.0, 0.8], [1.5, 0.4], [0.7, 1.3]])
    transformer = Transformer(3, 4, 2, 951)
    _, grad = transformer.loss_grad(x, y, dt)
    report = {"scope": "tiny random development inputs; no task test score", "transformer_exact_gradient": []}
    for key in transformer.params:
        numerical = finite_difference(transformer, x, y, dt, key)
        error = float(np.max(np.abs(numerical - grad[key])))
        rel = float(np.linalg.norm(numerical - grad[key]) /
                    max(1e-12, np.linalg.norm(numerical) + np.linalg.norm(grad[key])))
        report["transformer_exact_gradient"].append({"parameter": key, "count": numerical.size,
                                                       "absolute_error": error, "relative_l2_error": rel})
        if error > 2e-6 or rel > 5e-4:
            raise AssertionError((key, error, rel))
    _, full = transformer.forward(x, dt, cache=True)
    _, prefix = transformer.forward(x[:2], dt[:2], cache=True)
    prefix_error = float(np.max(np.abs(full[7][:, :2] - prefix[7])))
    future_mass = float(np.sum(np.triu(full[6], k=1)))
    if prefix_error > 1e-12 or future_mass != 0:
        raise AssertionError("attention is not causal")
    report["causal_attention"] = {"prefix_mixed_state_error": prefix_error, "future_probability_mass": future_mass}
    lif = LIF(3, 4, 2, 951)
    lif.params["b"][:] = np.array([1.8, 0.4, 1.4, -0.3])
    _, sg = lif.loss_grad(x, y, dt)
    report["lif_forward"] = dict(lif.last_diagnostics)
    report["lif_surrogate_tangent"] = []
    report["lif_hard_loss_fd"] = []
    for key in lif.params:
        direction = {name: np.zeros_like(value) for name, value in lif.params.items()}
        direction[key] = rng.normal(size=lif.params[key].shape)
        reverse = float(sum(np.sum(sg[name] * tangent) for name, tangent in direction.items()))
        forward = lif.surrogate_directional_derivative(x, y, direction, dt)
        if abs(reverse - forward) > 1e-11:
            raise AssertionError("surrogate forward/reverse tangent mismatch")
        report["lif_surrogate_tangent"].append({"parameter": key, "reverse": reverse, "forward": forward,
                                                "difference": abs(reverse - forward)})
        numerical = finite_difference(lif, x, y, dt, key)
        error = float(np.max(np.abs(numerical - sg[key])))
        exact = key in ("Wread", "bread")
        if exact and error > 2e-6:
            raise AssertionError("LIF readout gradient is incorrect")
        report["lif_hard_loss_fd"].append({"parameter": key, "max_difference_from_surrogate": error,
                                            "true_gradient_expected": exact,
                                            "interpretation": "exact readout" if exact else "mismatch expected; SG is not hard-forward derivative"})
    if not any(row["max_difference_from_surrogate"] > 1e-6 for row in report["lif_hard_loss_fd"] if not row["true_gradient_expected"]):
        raise AssertionError("development example did not expose surrogate mismatch")
    for model in (transformer, lif):
        path = out / ("development_" + model.family + ".npz")
        model.save(path)
        if not np.array_equal(model.forward(x, dt)[0], load_model(path).forward(x, dt)[0]):
            raise AssertionError("checkpoint round trip changed model")
    report["source_sha256"] = source_hashes()
    write_json(out / "development_checks.json", report)
    return report


def train_run(task, family, width, seed, out):
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("existing/interrupted run is preserved")
    out.mkdir(parents=True, exist_ok=True)
    train_seed = 700000 + 10000 * list(TASKS).index(task) + seed
    rng = np.random.default_rng(train_seed)
    model = make_model(family, width=width, seed=seed, **TASKS[task])
    initial = {key: value.copy() for key, value in model.params.items()}
    model.save(out / "initial.npz")
    optimizer = Adam(model)
    config = {"task": task, "family": family, "width": width, "seed": seed,
              "train_seed": train_seed, "parameter_count": model.parameter_count,
              "parameter_matching": False, "protocol": protocol(), "source_sha256": source_hashes(),
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}}
    write_json(out / "run_config.json", config)
    start, cpu, sequence_steps = time.perf_counter(), time.process_time(), 0
    with (out / "training_steps.jsonl").open("w") as stream:
        for step in range(300):
            item = sample_batch(task, rng, 32, split="train")
            loss, grads = model.loss_grad(item["x"], item["y"], item["dt"])
            norm, scale = optimizer.step(model, grads)
            sequence_steps += item["x"].shape[0] * 32
            row = {"step": step + 1, "loss_before_update": loss, "gradient_norm": norm, "clip_scale": scale,
                   "gradient_kind": "surrogate" if family == "lif_surrogate" else "exact",
                   "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
                   "examples_seen": (step + 1) * 32, "sequence_steps": sequence_steps,
                   "batch_sha256": array_hash(item["x"], item["y"], item["dt"], item["ids"]),
                   "gradient_norm_by_parameter": {key: float(np.linalg.norm(g)) for key, g in grads.items()},
                   "diagnostics": getattr(model, "last_diagnostics", {})}
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            if step in (0, 299):
                np.savez_compressed(out / ("train_batch_%04d.npz" % (step + 1)), **item)
    elapsed, cpu_elapsed = time.perf_counter() - start, time.process_time() - cpu
    changes = {key: float(np.linalg.norm(value - initial[key])) for key, value in model.params.items()}
    model.save(out / "final.npz", {"task": task, "updates": 300, "train_seed": train_seed})
    optimizer.save(out / "optimizer_final.npz")
    if source_hashes() != config["source_sha256"]:
        raise RuntimeError("source changed during training")
    receipt = {"checkpoint_sha256": file_hash(out / "final.npz"), "initial_sha256": file_hash(out / "initial.npz"),
               "training_log_sha256": file_hash(out / "training_steps.jsonl"),
               "training_wall_seconds": elapsed, "training_cpu_seconds": cpu_elapsed,
               "parameter_delta_l2": changes, "all_parameter_arrays_changed": all(v > 0 for v in changes.values()),
               "examples_seen": 9600, "sequence_steps": sequence_steps,
               "test_evaluations_before_freeze": 0, "source_sha256": source_hashes()}
    write_json(out / "FINAL_CHECKPOINT_RECEIPT.json", receipt)
    return receipt


def evaluate_run(run, split="test"):
    run = Path(run)
    receipt = json.loads((run / "FINAL_CHECKPOINT_RECEIPT.json").read_text())
    config = json.loads((run / "run_config.json").read_text())
    if file_hash(run / "final.npz") != receipt["checkpoint_sha256"] or source_hashes() != config["source_sha256"]:
        raise ValueError("evaluation identity differs from frozen training")
    model = load_model(run / "final.npz")
    task, out = config["task"], run / ("evaluation_" + split)
    out.mkdir(parents=True, exist_ok=False)
    report = {"task": task, "family": model.family, "width": model.width, "seed": model.seed,
              "parameter_count": model.parameter_count, "checkpoint_sha256": receipt["checkpoint_sha256"],
              "data_partition": split, "splits": {}}
    for variant in ("iid", "long_delay", "clock_shift"):
        base_seed = 1200000 if split == "dev" else 1700000
        data_seed = base_seed + 10000 * list(TASKS).index(task) + (100 if variant == "long_delay" else 0)
        rng = np.random.default_rng(data_seed)
        ids = digits_data()[2][split] if task == "digits_rows" else None
        count = len(ids) if ids is not None else (512 if split == "dev" else 2048)
        outputs, targets, indices, hashes = [], [], [], []
        start, cpu = time.perf_counter(), time.process_time()
        for offset in range(0, count, 64):
            size = min(64, count - offset)
            item = sample_batch(task, rng, size, variant, split, None if ids is None else ids[offset:offset + size])
            h, _ = model.forward(item["x"], item["dt"])
            outputs.append(model.logits(h))
            targets.append(item["y"])
            indices.append(item["ids"])
            hashes.append(array_hash(item["x"], item["y"], item["dt"], item["ids"]))
        logits, labels = np.concatenate(outputs), np.concatenate(targets)
        prediction = logits.argmax(axis=1)
        accuracy = float(np.mean(prediction == labels))
        report["splits"][variant] = {"n": count, "accuracy": accuracy,
            "nll": float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(count), labels])),
            "accuracy_standard_error": float(np.sqrt(accuracy * (1 - accuracy) / count)),
            "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
            "data_seed": data_seed, "batch_sha256": hashes}
        np.savez_compressed(out / (variant + "_predictions.npz"), logits=logits, labels=labels,
                            predictions=prediction, ids=np.concatenate(indices))
    write_json(out / "metrics.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("protocol", "check", "train", "evaluate"))
    parser.add_argument("--out", default="evidence/comparison")
    parser.add_argument("--task", choices=list(TASKS) + ["all"], default="all")
    parser.add_argument("--family", choices=list(FAMILIES) + ["all"], default="all")
    parser.add_argument("--widths", default="16,32,64")
    parser.add_argument("--seeds", default="11,23,37")
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    parser.add_argument("--run")
    args = parser.parse_args()
    if args.phase == "protocol":
        write_json(Path(args.out) / "comparison_protocol.json", protocol())
    elif args.phase == "check":
        print(json.dumps(development_check(args.out)))
    elif args.phase == "evaluate":
        runs = [Path(args.run)] if args.run else sorted(Path(args.out).glob("runs/*/*"))
        for run in runs:
            print(json.dumps(evaluate_run(run, args.split)), flush=True)
    else:
        for task in list(TASKS) if args.task == "all" else [args.task]:
            for family in FAMILIES if args.family == "all" else [args.family]:
                for width in map(int, args.widths.split(",")):
                    for seed in map(int, args.seeds.split(",")):
                        run = Path(args.out) / "runs" / task / f"{family}_w{width}_s{seed}"
                        print(json.dumps({"run": str(run), "receipt": train_run(task, family, width, seed, run)}), flush=True)


if __name__ == "__main__":
    main()
