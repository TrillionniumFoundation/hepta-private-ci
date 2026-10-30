"""Gate-protected new cohorts and label-preserving, generator-only challenges."""
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.data import make_data, fingerprint
from third.confirmation.contract import atomic_json, require_development, sha
from third.memory.data import historical_inputs, input_hashes, make_suite as development_suite
from third.memory.execution import atomic_checkpoint


def unpack(path):
    with np.load(path) as raw:
        names = sorted({key.rsplit("_", 1)[0] for key in raw.files})
        return {name: {key: raw[name + "_" + key] for key in ("x", "dt", "y")} for name in names}


def challenge(clean, task, mode, seed):
    rng = np.random.default_rng(seed)
    result = {key: value.copy() for key, value in clean.items()}
    if mode == "async":
        result["dt"] = np.clip(rng.lognormal(-.25, .8, clean["dt"].shape), .05, 4).astype(np.float32)
    elif mode == "gaussian":
        result["x"] += rng.normal(0, .1, clean["x"].shape).astype(np.float32)
    elif mode == "missing":
        # Task knowledge is confined to this evaluation generator.
        markers = (4, 5) if task == "memory" else (12, 13)
        informative = np.any(clean["x"][:, :, list(markers)] != 0, axis=2)
        filler_counts = (~informative).sum(1)
        if not np.all(filler_counts == filler_counts[0]):
            raise RuntimeError("Fixed-shape deletion requires equal filler counts")
        dropped = int(np.floor(.25 * filler_counts[0]))
        xs, gaps = [], []
        for index in range(len(clean["y"])):
            keep = np.ones(clean["x"].shape[1], bool)
            keep[rng.choice(np.flatnonzero(~informative[index]), dropped, replace=False)] = False
            if not keep[-1] or np.any(~keep & informative[index]):
                raise RuntimeError("An informative token would be dropped")
            xs.append(clean["x"][index, keep])
            elapsed = np.cumsum(clean["dt"][index], dtype=np.float64)
            gaps.append(np.diff(np.r_[0.0, elapsed[keep]]).astype(np.float32))
        result["x"], result["dt"] = np.stack(xs), np.stack(gaps)
        if not np.allclose(result["dt"].sum(1), clean["dt"].sum(1), rtol=1e-6):
            raise RuntimeError("Deletion changed the original total duration")
    else:
        raise ValueError(mode)
    if not np.array_equal(result["y"], clean["y"]) or np.any(result["dt"] <= 0):
        raise RuntimeError("Challenge changed latent labels or produced nonpositive gaps")
    return result


def make_cohort(task, seed, protocol):
    require_development()
    task_index = protocol["tasks"].index(task)
    base = protocol["data_seed_base"] + task_index * protocol["data_task_offset"] + 1000 * seed
    datasets = {"train" + str(n): make_data(task, base + n, protocol["training_examples_per_length"], n)
                for n in protocol["training_lengths"]}
    datasets["validation32"] = make_data(task, base + 201, protocol["evaluation_examples"], 32)
    for length in protocol["primary_lengths"] + [protocol["challenge_length"]]:
        datasets["clean" + str(length)] = make_data(task, base + 300 + length,
                                                    protocol["evaluation_examples"], length)
    for index, mode in enumerate(("async", "gaussian", "missing"), 1):
        datasets[mode + "128"] = challenge(datasets["clean128"], task, mode, base + 1000 + index)
    return datasets


def historical(task, length):
    seen = historical_inputs(task, length)
    for base_prefix in (10000, 900000):
        for seed in range(5):
            base = base_prefix + 100 * seed
            specs = [(base, 2048), (base + 1, 512), (base + 2, 512)] if length == 32 else []
            if length == 64:
                specs.append((base + 3, 512))
            for rng, count in specs:
                seen.update(input_hashes(make_data(task, rng, count, length)))
    old = json.loads((ROOT / "third/memory/protocol.json").read_text())
    for seed in old["seeds"]:
        training, suite, _ = development_suite(task, seed, old)
        for dataset in training + list(suite.values()):
            if dataset["x"].shape[1] == length:
                seen.update(input_hashes(dataset))
    if length == 32:
        prior = json.loads((ROOT / "next/ridge/development_protocol.json").read_text())
        base = prior["data_seed_base"] + 1000 * prior["tasks"].index(task)
        for offset, count in ((32, prior["training_examples_per_length"]), (201, prior["validation_examples"])):
            seen.update(input_hashes(make_data(task, base + offset, count, 32)))
    return seen


def main():
    prerequisite = require_development()
    protocol = json.loads((HERE / "protocol.json").read_text())
    output = HERE / "data_manifest.json"
    result = json.loads(output.read_text()) if output.exists() else dict(
        prerequisite=prerequisite, complete=False, cohorts=[], freshness=[])
    if result["prerequisite"] != prerequisite:
        raise RuntimeError("Data preparation belongs to a different prerequisite")
    if result["complete"]:
        for row in result["cohorts"]:
            if sha(HERE / row["file"]) != row["sha256"]:
                raise RuntimeError("Prepared confirmation data changed")
        return
    folder = HERE / "data"
    folder.mkdir(exist_ok=True)
    started = time.perf_counter()
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            if any(row["task"] == task and row["seed"] == seed for row in result["cohorts"]):
                continue
            datasets = make_cohort(task, seed, protocol)
            path = folder / f"{task}_seed{seed}.npz"
            atomic_checkpoint(path, {name + "_" + key: value for name, dataset in datasets.items()
                                     for key, value in dataset.items()})
            result["cohorts"].append(dict(task=task, seed=seed, file=str(path.relative_to(HERE)),
                sha256=sha(path), fingerprints={name: fingerprint(d) for name, d in datasets.items()},
                shapes={name: list(d["x"].shape) for name, d in datasets.items()}))
            atomic_json(output, result)
    # Complete freshness checks before any worker may train.
    checks = []
    for task in protocol["tasks"]:
        rows = [row for row in result["cohorts"] if row["task"] == task]
        train32 = set()
        for row in rows:
            train32.update(input_hashes(unpack(HERE / row["file"])["train32"]))
        for length in protocol["primary_lengths"] + [protocol["challenge_length"]]:
            previous, new_seen = historical(task, length), set()
            for row in rows:
                datasets = unpack(HERE / row["file"])
                names = ["clean" + str(length)] + (["validation32"] if length == 32 else [])
                for name in names:
                    current = input_hashes(datasets[name])
                    overlap = len(current & previous) + len(current & new_seen)
                    if length == 32:
                        overlap += len(current & train32)
                    checks.append(dict(task=task, seed=row["seed"], split=name,
                        exact_input_overlap=overlap, unique_examples=len(current),
                        expected_examples=protocol["evaluation_examples"]))
                    new_seen.update(current)
    result["freshness"] = checks
    result["complete"] = all(row["exact_input_overlap"] == 0 and
                             row["unique_examples"] == row["expected_examples"] for row in checks)
    result["preparation_wall_seconds_this_attempt"] = time.perf_counter() - started
    atomic_json(output, result)
    if not result["complete"]:
        raise RuntimeError("Freshness check failed; retain data and do not train")
    print("CONFIRMATION_DATA_READY", len(result["cohorts"]), flush=True)


if __name__ == "__main__":
    main()
