"""Preregistered frozen-content ablations and repeated CPU inference timings."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp

from content import Model
from content_audit import file_hash, source_hashes, write_json
from content_tasks import TASKS, array_hash, digits_data, sample_batch


def metrics(logits, labels):
    return {"accuracy": float(np.mean(logits.argmax(axis=1) == labels)),
            "nll": float(np.mean(logsumexp(logits, axis=1)
                                 - logits[np.arange(len(labels)), labels]))}


def diagnose(run, candidate):
    config = json.loads((run / "run_config.json").read_text())
    receipt = json.loads((run / "FINAL_CHECKPOINT_RECEIPT.json").read_text())
    if source_hashes() != config["source_sha256"] or file_hash(run / "final.npz") != receipt["checkpoint_sha256"]:
        raise RuntimeError("checkpoint or training source changed")
    model = Model.load(run / "final.npz")
    task = config["task"]
    rng = np.random.default_rng(1700000 + 10000 * list(TASKS).index(task))
    ids = digits_data()[2]["test"] if task == "digits_rows" else None
    count = len(ids) if ids is not None else 512
    items = []
    for offset in range(0, count, 64):
        size = min(64, count - offset)
        items.append(sample_batch(task, rng, size, split="test",
                                  indices=None if ids is None else ids[offset:offset + size]))
    labels = np.concatenate([item["y"] for item in items])
    all_full, all_last, all_zero, prefixes = [], [], [], []
    for item in items:
        state = model.initial(len(item["y"]))
        seq_logits = []
        for x, dt in zip(item["x"], item["dt"]):
            state = model.step(x, state, dt)
            seq_logits.append(model.logits(state))
        prefixes.append(np.asarray(seq_logits))
        all_full.append(model.logits(state))
        last = model.step(item["x"][-1], model.initial(len(item["y"])), item["dt"][-1])
        all_last.append(model.logits(last))
        all_zero.append(model.logits(model.initial(len(item["y"]))))
    logits = {"full_history": np.concatenate(all_full), "last_observation_only": np.concatenate(all_last),
              "initial_state": np.concatenate(all_zero)}
    prefix = np.concatenate(prefixes, axis=1)
    predictions = {key: value.argmax(axis=1) for key, value in logits.items()}
    paired = ((predictions["full_history"] == labels).astype(int)
              - (predictions["last_observation_only"] == labels).astype(int))
    timing = []
    for batch in (1, 64):
        x = items[0]["x"][:, :batch]
        dt = items[0]["dt"][:, :batch]
        for _ in range(2):
            model.logits(model.forward(x, dt)[0])
        rows = []
        for _ in range(7):
            cpu, wall = time.process_time(), time.perf_counter()
            for _ in range(3):
                result = model.logits(model.forward(x, dt)[0])
            rows.append({"cpu_seconds_per_forward": (time.process_time() - cpu) / 3,
                         "wall_seconds_per_forward": (time.perf_counter() - wall) / 3})
        timing.append({"batch": batch, "sequence_length": len(x), "repeats": rows,
                       "median_cpu_seconds_per_forward": float(np.median([r["cpu_seconds_per_forward"] for r in rows])),
                       "median_wall_seconds_per_forward": float(np.median([r["wall_seconds_per_forward"] for r in rows])),
                       "output_sha256": array_hash(result)})
    out = run / "diagnostics"
    out.mkdir(exist_ok=False)
    np.savez_compressed(out / "predictions.npz", labels=labels, prefix_logits=prefix, **logits)
    report = {"candidate_commit": candidate, "checkpoint_sha256": receipt["checkpoint_sha256"],
              "task": task, "family": model.family, "width": model.width, "seed": model.seed,
              "examples": count, "raw_batch_sha256": [array_hash(i["x"], i["y"], i["dt"], i["ids"]) for i in items],
              "metrics": {key: metrics(value, labels) for key, value in logits.items()},
              "full_minus_last_accuracy": float(paired.mean()),
              "paired_example_standard_error": float(paired.std(ddof=1) / np.sqrt(count)),
              "prefix_metrics": [metrics(value, labels) for value in prefix],
              "timing": timing, "parameter_count": model.parameter_count,
              "parameter_array_bytes": sum(p.nbytes for p in model.params.values()),
              "timing_scope": "cached raw input, forward plus readout; excludes data construction and serialization",
              "interpretation": "frozen-model content ablations, not separately trained last-input baselines; no hyperparameter selection"}
    write_json(out / "summary.json", report)
    return {key: report[key] for key in ("task", "family", "width", "seed", "full_minus_last_accuracy")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-commit", required=True)
    args = parser.parse_args()
    for run in sorted(Path("evidence/content/runs").glob("*/*")):
        print(json.dumps(diagnose(run, args.candidate_commit)), flush=True)


if __name__ == "__main__":
    main()
