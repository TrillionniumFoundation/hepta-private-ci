"""Independent raw-record and saved-weight replay; no campaign import."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    directory = args.output
    plan = json.loads((directory / "PLAN.json").read_text())
    summary = json.loads((directory / "SUMMARY.json").read_text())
    test = np.load(directory / "test_data.npz")
    observed, expected = {}, {}
    max_error = 0.0
    all_converged = True
    for seed in plan["fit_seeds"]:
        fitdir = directory / f"fit_{seed}"
        fit = json.loads((fitdir / "FIT.json").read_text())
        assert digest(fitdir / "weights.npz") == fit["weights_sha256"]
        assert digest(fitdir / "data.npz") == fit["data_sha256"]
        weights = np.load(fitdir / "weights.npz")
        for arm in fit["test"]:
            if arm == "unfitted_analytic":
                expected[seed, arm] = test["oracle"]
            else:
                mode = arm.removeprefix("refit_").removeprefix("same_weight_")
                weight_mode = "original" if arm.startswith("same_weight_") else mode
                logits = test["X_"+mode] @ weights[weight_mode].reshape(6, 5)
                unnormalized = np.exp(logits - np.max(logits, axis=1, keepdims=True))
                expected[seed, arm] = unnormalized / unnormalized.sum(axis=1, keepdims=True)
            observed[seed, arm] = []
        for mode in plan["modes"]:
            candidates = fit["modes"][mode]["all_candidates"]
            selected = min(candidates, key=lambda r: (r["validation"]["nll"], r["l2"]))
            assert selected == fit["modes"][mode]["selected"]
            all_converged &= selected["optimizer_success"]
    seen = set()
    with gzip.open(directory / "predictions.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            key = (row["fit_seed"], row["arm"], row["world"])
            assert key not in seen
            seen.add(key)
            assert row["truth"] == int(test["labels"][row["world"]])
            probabilities = np.array(row["probabilities"])
            assert np.isfinite(probabilities).all() and (probabilities >= 0).all()
            assert abs(probabilities.sum()-1) < 1e-12
            error = float(np.abs(probabilities-expected[key[:2]][key[2]]).max())
            max_error = max(max_error, error)
            assert error < 1e-12
            observed[key[:2]].append((key[2], probabilities))
    assert len(seen) == plan["test_size"] * len(plan["fit_seeds"]) * 6
    assert len(seen) == summary["prediction_rows"]
    for (seed, arm), records in observed.items():
        records.sort(key=lambda row: row[0])
        assert [x[0] for x in records] == list(range(plan["test_size"]))
        values = np.array([x[1] for x in records])
        labels = test["labels"]
        nll = float(-np.log(np.maximum(values[np.arange(len(labels)), labels], 1e-300)).mean())
        accuracy = float(np.mean(np.argmax(values, axis=1) == labels))
        brier = float(np.sum((values-np.eye(5)[labels])**2, axis=1).mean())
        fit = next(x for x in summary["fits"] if x["seed"] == seed)
        for metric, value in (("nll", nll), ("accuracy", accuracy), ("brier", brier)):
            assert abs(value-fit["test"][arm][metric]) < 1e-12
    assert digest(directory / "test_data.npz") == summary["test_data_sha256"]
    assert digest(directory / "predictions.jsonl.gz") == summary["raw_sha256"]
    report = {"status": "PASS", "raw_rows": len(seen), "unique_rows": len(seen),
        "max_saved_weight_probability_replay_error": max_error,
        "all_selected_optimizers_converged": all_converged,
        "scientific_scope_unchanged": "finite fixed-horizon readout refitting, not AV or full analytic-network training",
        "audit_source_sha256": digest(Path(__file__)),
        "audited_plan_sha256": digest(directory / "PLAN.json"),
        "audited_summary_sha256": digest(directory / "SUMMARY.json")}
    path = directory / "INDEPENDENT_RAW_AUDIT.json"
    with path.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
