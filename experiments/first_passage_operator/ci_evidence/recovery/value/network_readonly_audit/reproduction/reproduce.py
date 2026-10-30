"""Replay the original fixed bootstrap from retained confirmation arrays only.

This executable was reconstructed after an execution-workspace reset. It does
not claim byte identity with the lost supplementary executable. The original
three-file audit, its manifest, training sources, models, protocols and results
remain read-only. No model is imported or executed, and no new hypothesis test
or additional confirmation sample is introduced.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np


AUDIT = Path("experiments/first_passage_operator/ci_evidence/recovery/value/network_readonly_audit")
STUDY = Path("experiments/first_passage_operator")
TOLERANCE = 1e-12


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(repo, item):
    path = repo / item["path"]
    assert path.stat().st_size == item["bytes"], item["path"]
    assert digest(path) == item["sha256"], item["path"]


def close(actual, expected):
    actual = np.asarray(actual, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    assert actual.shape == expected.shape, (actual.shape, expected.shape)
    error = float(np.max(np.abs(actual - expected)))
    assert np.isfinite(actual).all() and error <= TOLERANCE, error
    return error


def reproduce(repo):
    audit_manifest_path = repo / AUDIT / "checkpoint_paths.json"
    audit_manifest = json.loads(audit_manifest_path.read_text())
    for item in audit_manifest["files"]:
        checked_file(repo, item)
    statistics_path = repo / AUDIT / "STATISTICS.json"
    statistics = json.loads(statistics_path.read_text())
    for item in statistics["input_files"]:
        checked_file(repo, item)

    study = repo / STUDY
    evidence = study / "network_evidence"
    protocol = json.loads((study / "NETWORK_PROTOCOL.json").read_text())
    freeze_path = evidence / "FREEZE.json"
    freeze = json.loads(freeze_path.read_text())
    summary = json.loads((evidence / "CONFIRMATION_SUMMARY.json").read_text())
    for name, expected in freeze["sources"].items():
        assert digest(study / name) == expected, name

    expected_names = {
        f"fit_{task}_{kind}_{seed}.json"
        for task in protocol["tasks"]
        for kind in protocol["models"]
        for seed in protocol["seeds"]
    }
    assert set(freeze["fits"]) == expected_names
    updates = protocol["epochs"] * (
        (protocol["train_examples"] + protocol["batch_size"] - 1) // protocol["batch_size"]
    )
    fitted = []
    for name, expected in freeze["fits"].items():
        path = evidence / name
        assert digest(path) == expected, name
        fit = json.loads(path.read_text())
        assert fit["source_sha256"] == freeze["sources"], name
        assert fit["optimizer_updates"] == updates, name
        assert fit["parameters"] == protocol["active_parameters_per_model"], name
        assert set(fit["checkpoint"]) == set(fit["initial"]), name
        total = changed = 0
        for group, values in fit["checkpoint"].items():
            final = np.asarray(values, dtype=np.float64)
            initial = np.asarray(fit["initial"][group], dtype=np.float64)
            assert final.shape == initial.shape
            assert np.isfinite(final).all() and np.isfinite(initial).all()
            difference = final - initial
            count = int(np.count_nonzero(difference))
            assert count == fit["selected_parameter_deltas"][group]["changed"]
            assert difference.size == fit["selected_parameter_deltas"][group]["total"]
            assert count == difference.size, (name, group)
            gradient = fit["gradient_squared_sum"][group]
            assert np.isfinite(gradient) and gradient > 0, (name, group)
            total += int(difference.size)
            changed += count
        assert total == protocol["active_parameters_per_model"]
        fitted.append({"file": name, "parameters": total, "changed": changed, "updates": updates})

    means = {}
    array_checks = []
    for task in protocol["tasks"]:
        with np.load(evidence / f"confirmation_arrays_{task}.npz", allow_pickle=False) as arrays:
            for seed in protocol["seeds"]:
                labels = arrays[f"{task}_{seed}_labels"]
                assert labels.shape == (protocol["confirmation_examples"],)
                assert np.isin(labels, [0.0, 1.0]).all()
                for kind in protocol["models"]:
                    key = f"{task}_{kind}_{seed}"
                    row = json.loads((evidence / f"confirmation_{key}.json").read_text())
                    assert row["freeze_sha256"] == digest(freeze_path)
                    assert row["checkpoint_sha256"] == freeze["fits"][f"fit_{key}.json"]
                    assert row["task"] == task and row["kind"] == kind and row["seed"] == seed
                    for suffix, field in (
                        ("loss", "loss_by_example"),
                        ("correct", "accuracy_by_example"),
                        ("probability", "probability_by_example"),
                    ):
                        values = arrays[f"{key}_{suffix}"]
                        assert values.shape == (
                            protocol["confirmation_repeats"], protocol["confirmation_examples"]
                        )
                        assert np.isfinite(values).all()
                        close(values.mean(axis=0), row[field])
                    losses = arrays[f"{key}_loss"]
                    correct = arrays[f"{key}_correct"]
                    probability = arrays[f"{key}_probability"]
                    assert np.isin(correct, [0.0, 1.0]).all()
                    assert ((probability >= 0) & (probability <= 1)).all()
                    close(losses.mean(), row["mean_loss"])
                    close(correct.mean(), row["mean_single_rollout_accuracy"])
                    close(((probability.mean(axis=0) >= 0.5) == labels).mean(), row["ensemble_accuracy"])
                    means[(task, kind, seed)] = losses.mean(axis=0)
                    array_checks.append(key)

    # Preserve the registered iteration order and RNG stream across all six
    # comparisons. Resample seeds, then complete paired examples; the eight
    # stochastic repetitions are averaged within each existing example.
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    tail = protocol["simultaneous_tail_probability"]
    assert tail == protocol["family_alpha"] / (2 * 6)
    comparisons = []
    for task in protocol["tasks"]:
        for baseline in ("lif", "rnn"):
            improvements = np.asarray([
                means[(task, baseline, seed)] - means[(task, "first_passage", seed)]
                for seed in protocol["seeds"]
            ])
            replicates = []
            for _ in range(protocol["bootstrap_replicates"]):
                chosen = rng.integers(len(improvements), size=len(improvements))
                samples = [
                    improvements[i, rng.integers(improvements.shape[1], size=improvements.shape[1])].mean()
                    for i in chosen
                ]
                replicates.append(float(np.mean(samples)))
            interval = np.quantile(replicates, [tail, 1 - tail])
            seed_means = improvements.mean(axis=1)
            passed = bool(interval[0] > protocol["advantage_margin"] and np.all(seed_means > 0))
            original = next(
                item for item in summary["comparisons"]
                if item["task"] == task and item["baseline"] == baseline
            )
            audited = next(
                item for item in statistics["comparisons"]
                if item["task"] == task and item["baseline"] == baseline
            )
            original_error = close(interval, original["simultaneous_empirical_interval"])
            audit_error = close(interval, audited["empirical_interval"])
            close(seed_means, original["seed_means"])
            close(seed_means, audited["seed_means"])
            close(improvements.mean(), original["loss_improvement"])
            close(improvements.mean(), audited["mean_improvement"])
            assert passed == original["passes_advantage_gate"] == audited["passes"]
            comparisons.append({
                "task": task, "baseline": baseline,
                "mean_improvement": float(improvements.mean()),
                "seed_means": seed_means.tolist(), "empirical_interval": interval.tolist(),
                "passes": passed, "original_interval_max_abs_error": original_error,
                "audit_interval_max_abs_error": audit_error,
            })

    passes = sum(item["passes"] for item in comparisons)
    assert passes == statistics["cross_task_advantage_passes"]
    assert all(item["passes"] for item in comparisons) == summary["cross_task_advantage_established"]
    # Recheck all immutable inputs after computation, without changing them.
    for item in audit_manifest["files"] + statistics["input_files"]:
        checked_file(repo, item)
    return {
        "input_files": statistics["input_files"],
        "audit_files": audit_manifest["files"],
        "audit_manifest_sha256": digest(audit_manifest_path),
        "fit_source_freeze_verified": True, "fits": fitted,
        "confirmation_array_groups_verified": len(array_checks),
        "bootstrap_seed": protocol["bootstrap_seed"],
        "bootstrap_replicates": protocol["bootstrap_replicates"],
        "comparison_order": [[item["task"], item["baseline"]] for item in comparisons],
        "comparisons": comparisons, "cross_task_advantage_passes": passes,
        "max_original_interval_error": max(item["original_interval_max_abs_error"] for item in comparisons),
        "max_audit_interval_error": max(item["audit_interval_max_abs_error"] for item in comparisons),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    started = time.perf_counter()
    receipt = {
        "schema": "hepta.network-bootstrap-reproduction.recovered.v1",
        "command": sys.argv, "python": platform.python_version(), "numpy": np.__version__,
        "script_sha256": digest(Path(__file__)), "numerical_comparison_tolerance": TOLERANCE,
        "scope": "Read-only replay of the original fixed bootstrap; no model execution or new statistical test.",
        "provenance": "Newly reconstructed supplementary executable; no claim of byte identity with the lost prior script.",
    }
    try:
        receipt.update(reproduce(args.repo.resolve()))
        receipt["status"] = "passed"
    except Exception as error:
        receipt.update({"status": "failed", "error_type": type(error).__name__, "error": str(error)})
    receipt["wall_seconds"] = time.perf_counter() - started
    with args.output.open("x") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps({
        "status": receipt["status"], "output": str(args.output),
        "advantage_passes": receipt.get("cross_task_advantage_passes"),
        "max_interval_error": receipt.get("max_original_interval_error"),
    }))
    raise SystemExit(0 if receipt["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
