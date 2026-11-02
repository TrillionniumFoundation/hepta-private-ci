"""Independently bind downloaded CI kernel receipts and frozen numerical output."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from .joint_reconstruction import joint_probabilities, metrics, mlp_probabilities


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(root):
    root = Path(root)
    repo = Path(__file__).resolve().parents[3]
    frozen = repo/"experiments/hcsn_v10_closure_20261101/joint_retrain/results/development001"
    replay = root/"joint-replay"
    commit = (root/"SOURCE_COMMIT.txt").read_text().strip()
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    receipts = {}
    for name in ("fixture", "joint-memory"):
        record = json.loads((root/name/"RECEIPT.json").read_text())
        assert record["source_commit"] == commit
        assert record["status"] == "PASS" and record["command_exit_code"] == 0
        assert record["gated_before_exec"] and record["family_empty_after_exit"]
        assert record["own_group_removed"] and record["cleanup_own_group_only"]
        assert record["initial_peak_bytes"] == 0
        assert record["memory_peak_bytes"] > 0 and record["memory_limit_bytes"] == 1024**3
        assert record["device_energy_joules"] is None
        events = dict(line.split() for line in record["memory_events"].splitlines())
        assert int(events.get("oom_kill", 0)) == int(events.get("oom_group_kill", 0)) == 0
        receipts[name] = {"receipt_sha256": sha(root/name/"RECEIPT.json"),
            "memory_peak_bytes": record["memory_peak_bytes"], "memory_events": events,
            "command": record["command"], "group_removed": True}
    assert receipts["fixture"]["memory_peak_bytes"] >= 48*1024**2
    assert receipts["fixture"]["command"][-1] == "fixture"
    assert "experiments.hcsn_v10_closure_20261101.economics.ci_joint_replay" in receipts["joint-memory"]["command"]
    provenance_path = root/"CI_PROVENANCE.json"
    provenance = None
    if provenance_path.exists():
        provenance = json.loads(provenance_path.read_text())
        assert provenance["head_sha"] == commit and provenance["conclusion"] == "success"
        assert provenance["run_id"] and provenance["run_attempt"]
    plan = json.loads((replay/"PLAN.json").read_text())
    assert sha(replay/"PLAN.json") == sha(frozen/"PLAN.json")
    training = json.loads((replay/"TRAINING_COMPLETE.json").read_text())
    attestation = json.loads((replay/"REPLAY.json").read_text())
    assert attestation["passed"] is True
    required_inputs = {"PLAN.json", "TRAINING_COMPLETE.json", "DATA.json", "test.npz"}
    required_inputs.update(f"fit_{fit['seed']}/weights.npz" for fit in training["fits"])
    assert set(attestation["inputs_sha256"]) == required_inputs
    for name, digest in attestation["inputs_sha256"].items():
        assert sha(replay/name) == digest == sha(frozen/name)
    assert attestation["source_sha256"] == plan["source_sha256"] == training["source_sha256"]
    for name, digest in plan["source_sha256"].items():
        assert sha(frozen.parents[1]/name) == digest
    summary = json.loads((replay/"SUMMARY.json").read_text())
    reference = json.loads((frozen/"SUMMARY.json").read_text())
    assert attestation["output_summary_sha256"] == sha(replay/"SUMMARY.json")
    assert summary["raw_sha256"] == sha(replay/"predictions.jsonl.gz")
    assert summary["test_sha256"] == sha(replay/"test.npz")
    assert summary["training_complete_sha256"] == sha(replay/"TRAINING_COMPLETE.json")
    compared, maximum_summary_error = 0, 0.

    def compare(a, b, path="summary"):
        nonlocal compared, maximum_summary_error
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            for key in a:
                if key != "raw_sha256":
                    compare(a[key], b[key], path+"."+key)
        elif isinstance(a, list):
            assert len(a) == len(b)
            for index, (left, right) in enumerate(zip(a, b)):
                compare(left, right, path+f"[{index}]")
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            error = float(abs(a-b))
            assert error <= 1e-8, (path, a, b)
            maximum_summary_error = max(maximum_summary_error, error)
            compared += 1
        else:
            assert a == b, (path, a, b)
    compare(summary, reference)
    test = np.load(replay/"test.npz")
    predictions = {}
    for fit in training["fits"]:
        seed = fit["seed"]
        assert sha(replay/f"fit_{seed}/weights.npz") == fit["weights_sha256"]
        saved = np.load(replay/f"fit_{seed}/weights.npz")
        predictions[seed] = {
            "joint_original": joint_probabilities(saved["original"], test["packets"], "original"),
            "ordinary_mlp": mlp_probabilities(saved["ordinary_mlp"],
                (test["packets"]-saved["ordinary_mean"])/saved["ordinary_scale"])}
        for mode in ("mean_two_point", "single_transition"):
            predictions[seed]["same_weight_"+mode] = joint_probabilities(saved["original"], test["packets"], mode)
            predictions[seed]["joint_"+mode] = joint_probabilities(saved[mode], test["packets"], mode)
    seen, maximum_error = set(), 0.
    with gzip.open(replay/"predictions.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            key = row["fit_seed"], row["world"], row["arm"]
            assert key not in seen
            seen.add(key)
            seed, world, arm = key
            assert row["truth"] == test["labels"][world]
            assert row["initial_class"] == test["initials"][world]
            p = np.roll(predictions[seed][arm][world], int(test["initials"][world]))
            error = float(np.max(abs(p-row["probabilities"])))
            assert error < 2e-10
            maximum_error = max(maximum_error, error)
    assert len(seen) == summary["prediction_rows"] == 30720
    assert seen == {(seed, world, arm) for seed, arms in predictions.items()
        for arm in arms for world in range(plan["test_size"])}
    for fit in summary["fits"]:
        for arm, published in fit["test"].items():
            actual = metrics(predictions[fit["seed"]][arm], test["delta_labels"])
            for name, value in actual.items():
                assert abs(value-published[name]) < 2e-10
    return {"recorded_source_commit": commit, "external_run_provenance": provenance,
        "external_run_identity_independently_supplied": provenance is not None,
        "source_commit_file_sha256": sha(root/"SOURCE_COMMIT.txt"),
        "kernel_receipts": receipts, "frozen_reference_summary_sha256": sha(frozen/"SUMMARY.json"),
        "CI_summary_sha256": sha(replay/"SUMMARY.json"), "summary_numeric_fields_compared": compared,
        "maximum_summary_numeric_error": maximum_summary_error,
        "raw_predictions_independently_reconstructed": len(seen), "maximum_probability_error": maximum_error,
        "memory_scope": "Exact recorded cgroup memory-charge peak of this gated frozen evaluation and descendants; not RSS/PSS or unique physical memory",
        "scope": "One hosted frozen finite-model replay; no retraining/AV/deployment-wide/energy qualification",
        "device_energy_joules": None}
