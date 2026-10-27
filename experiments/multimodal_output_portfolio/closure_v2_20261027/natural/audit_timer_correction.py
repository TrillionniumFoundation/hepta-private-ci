"""Reopen every corrected-timer transcript and independently rebuild speaker CIs."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(experiment, original, assets, output):
    rows, result = load(experiment / "ROWS.json"), load(experiment / "RESULT.json")
    seal, protocol = load(experiment / "FROZEN_REGISTRATION.json"), load(experiment / "PROTOCOL.json")
    model = load(experiment / "ENCODER_MODEL.json")
    if sha(original / "ROWS.json") != protocol["original_rows_sha256"] or sha(original / "ENCODER_MODEL.json") != sha(experiment / "ENCODER_MODEL.json"):
        raise ValueError("Original rows or fixed gate identity differ")
    if sha(assets / "MANIFEST.json") != protocol["source_manifest_sha256"]:
        raise ValueError("Correction used different sources")
    manifest = load(assets / "MANIFEST.json")
    sources = {r["id"]: r for r in manifest["speech"]}
    previous = {(r["id"], r["arm"], r["repetition"]): r for r in load(original / "ROWS.json")}
    grid, verified = set(), 0
    maximum_timing_identity_error = 0.
    for row in rows:
        key = (row["id"], row["arm"], row["repetition"])
        if key in grid or key not in previous or row["speaker_id"] != sources[row["id"]]["speaker_id"]:
            raise ValueError("Correction grid or source group differs")
        grid.add(key)
        prior = previous[key]
        path, before = Path(row["output_path"]), Path(prior["output_path"])
        if path.read_bytes() != before.read_bytes() or sha(path) != row["output_sha256"] or sha(path) != prior["output_sha256"]:
            raise ValueError("Actual corrected transcript bytes differ from original")
        if path.read_text().strip() != row["transcript"] or path.with_name("FIRST.txt").read_text().strip() != row["transcript"]:
            raise ValueError("Actual first/final transcript readback differs")
        public = load(path.with_name("PUBLIC_RESULT.json"))
        if any(public[key] != row[key] for key in public):
            raise ValueError("Actual outside-timer public metadata differs")
        if row["metadata_start_monotonic_ns"] < row["timer_stop_monotonic_ns"]:
            raise ValueError("JSON metadata work began before the common timer stopped")
        if row["encoder"]["encoded_sha256"] != prior["encodings"][0]["encoded_sha256"] or row["beam"] != prior["generations"][0]["beam"]:
            raise ValueError("Encoder state or beam choice changed")
        if row["encoder_calls"] != 1 or row["decoder_calls"] != 1 or row["private_reference_received"]:
            raise ValueError("The frozen inference budget or public boundary changed")
        if row["arm"] == "encoder_gate":
            features = np.asarray(row["gate"]["features"])
            weights = np.asarray(model["model"]["weights"])
            values = np.r_[1., (features - model["model"]["mean"]) / model["model"]["scale"]]
            predicted = float(values @ weights)
            if row["gate"]["features"] != prior["gate"]["features"] or abs(predicted - row["gate"]["predicted_moment_gain"]) > 1e-12:
                raise ValueError("Public gate features or frozen prediction changed")
            if row["beam"] != (5 if predicted >= model["choice"]["threshold"] else 1):
                raise ValueError("Fixed threshold no longer chooses the recorded beam")
        elif row["beam"] != 5 or row["gate"] is not None:
            raise ValueError("Fixed beam5 control changed")
        for metric in ("cpu_seconds", "wall_seconds", "metadata_cpu_seconds", "metadata_wall_seconds"):
            if row[metric] <= 0:
                raise ValueError("Nonpositive recorded execution cost")
        gap = (row["metadata_start_monotonic_ns"] - row["timer_stop_monotonic_ns"]) / 1e9
        maximum_timing_identity_error = max(maximum_timing_identity_error,
            abs(row["metadata_inclusive_wall_seconds"] - row["wall_seconds"] - row["metadata_wall_seconds"] - gap))
        if row["metadata_inclusive_cpu_seconds"] < row["cpu_seconds"] + row["metadata_cpu_seconds"]:
            raise ValueError("Metadata-inclusive CPU omitted recorded work")
        verified += 1
    expected = {(identity, arm, rep) for identity in sources for arm in ("fixed_beam5", "encoder_gate") for rep in (0, 1)}
    if grid != expected or verified != 256 or maximum_timing_identity_error > 1e-12:
        raise ValueError("Correction is incomplete or timing components do not reconcile")
    metrics = ["cpu_seconds", "wall_seconds", "metadata_cpu_seconds", "metadata_wall_seconds", "metadata_inclusive_cpu_seconds", "metadata_inclusive_wall_seconds"]
    maximum_statistics = 0.
    computed = {}
    for metric in metrics:
        differences = []
        for speaker in sorted({r["speaker_id"] for r in rows}):
            group = []
            for identity in sorted(i for i in sources if sources[i]["speaker_id"] == speaker):
                a = [r[metric] for r in rows if r["id"] == identity and r["arm"] == "encoder_gate"]
                b = [r[metric] for r in rows if r["id"] == identity and r["arm"] == "fixed_beam5"]
                group.append(np.mean(a) - np.mean(b))
            differences.append(np.mean(group))
        values = np.asarray(differences)
        rng = np.random.default_rng(2821)
        interval = np.quantile(values[rng.integers(16, size=(5000, 16))].mean(1), [.025, .975])
        record = result["encoder_minus_fixed_beam5"][metric]
        maximum_statistics = max(maximum_statistics, abs(float(values.mean()) - record["difference"]), float(np.max(np.abs(interval - record["CI95"]))))
        computed[metric] = {"difference": float(values.mean()), "CI95": interval.tolist()}
    if maximum_statistics > 1e-12:
        raise ValueError("Independent speaker timing statistics differ")
    old_quality = load(original / "RESULT.json")["encoder_vs_fixed_beam5"]
    if result["same_output_original_WER_difference_CI95"] != old_quality["WER_difference_CI95"]:
        raise ValueError("Original quality inference was changed")
    report = {"passed": True, "model_or_decoder_reexecutions": 0, "imports_producer_scorer_or_statistics": False,
        "actual_transcript_and_public_metadata_pairs_reopened": verified, "speakers": 16,
        "all_transcript_bytes_encoder_hashes_and_beam_choices_equal_original": True,
        "all_JSON_work_after_shared_timer_stop": True, "metadata_inclusive_costs_also_reported": True,
        "maximum_wall_component_reconciliation_error": maximum_timing_identity_error,
        "maximum_statistical_discrepancy": maximum_statistics, "comparisons": computed,
        "original_5arm_result_sha256": sha(original / "RESULT.json"),
        "correction_rows_sha256": sha(experiment / "ROWS.json"),
        "correction_seal_sha256": sha(experiment / "FROZEN_REGISTRATION.json"),
        "new_source_qualification_or_policy_selection": False,
        "corrected_cost_gate": result["corrected_shared_boundary_cost_gate_passed"],
        "corrected_metadata_inclusive_cost_gate": result["corrected_metadata_inclusive_cost_gate_passed"]}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("experiment", "original", "assets", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.experiment, args.original, args.assets, args.output)
