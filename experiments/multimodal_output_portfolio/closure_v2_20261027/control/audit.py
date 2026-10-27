"""Reopen actual media, reconstruct forecasts, and replay original native calls."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

import numpy as np
import torch

from ...continuation_20261027.joint.run import reference_observer
from .verify_forecasts import independent_prediction, replay
from .verify_media import byte_hash, independent_score, verify_sources


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def independent_ce(values, gamma):
    values = np.asarray(values)
    return -np.log(np.mean(np.exp(-gamma * values))) / gamma


def statistics_check(rows, reported, protocol):
    grid = {arm: sorted([row for row in rows if row["arm"] == arm], key=lambda x: x["index"]) for arm in protocol["arms"]}
    if any([row["index"] for row in group] != list(range(protocol["qualification_pairs"])) for group in grid.values()):
        raise ValueError("Actual arm/source grid is incomplete")
    rng, maximum = np.random.default_rng(protocol["bootstrap_seed"]), 0.0
    for arm, group in grid.items():
        y = np.asarray([r["final_score"]["strict_success"] for r in group])
        u = np.asarray([r["net_utility"] for r in group])
        summary = reported["summaries"][arm]
        maximum = max(maximum, abs(y.mean() - summary["strict_success"]), abs(u.mean() - summary["mean_net_utility"]),
                      abs(float(independent_ce(u, protocol["gamma"])) - summary["ce"]))
    for index, arm in enumerate(protocol["arms"][1:]):
        target = np.asarray([[r["final_score"]["strict_success"], r["net_utility"]] for r in grid["native_numeric"]])
        baseline = np.asarray([[r["final_score"]["strict_success"], r["net_utility"]] for r in grid[arm]])
        samples = []
        for _ in range(protocol["bootstrap_replicates"]):
            positions = rng.integers(len(target), size=len(target))
            samples.append([*(target[positions] - baseline[positions]).mean(0),
                independent_ce(target[positions, 1], protocol["gamma"]) - independent_ce(baseline[positions, 1], protocol["gamma"])])
        interval = np.quantile(samples, [0.0125, 0.9875], axis=0)
        compare = reported["comparisons"][index]
        for column, field in enumerate(("strict_97_5_interval", "net_utility_97_5_interval", "ce_97_5_interval")):
            maximum = max(maximum, float(np.max(np.abs(interval[:, column] - compare[field]))))
    native = grid["native_numeric"]
    labels = np.asarray([row["final_score"]["strict_success"] for row in native])
    def calibration_error(p, y):
        buckets = np.minimum(np.floor(p * 10).astype(int), 9)
        return sum(np.mean(buckets == k) * abs(p[buckets == k].mean() - y[buckets == k].mean())
                   for k in np.unique(buckets))
    for timing in ("before", "after"):
        predicted = np.asarray([row[f"prediction_{timing}"]["strict_probability"] for row in native])
        accepted = predicted >= protocol["semantic_acceptance_confidence"]
        item = reported["semantic_calibration"][timing]
        reconstructed = {"ece": float(calibration_error(predicted, labels)),
            "coverage": float(accepted.mean()), "false_acceptance_per_all_cases": float(np.mean(accepted & (labels == 0))),
            "brier": float(np.mean((predicted - labels) ** 2))}
        maximum = max(maximum, *(abs(value - item[key]) for key, value in reconstructed.items()))
        samples = []
        for _ in range(protocol["bootstrap_replicates"]):
            position = rng.integers(len(labels), size=len(labels))
            samples.append(calibration_error(predicted[position], labels[position]))
        maximum = max(maximum, float(np.max(np.abs(np.quantile(samples, [0.0125, 0.9875]) - item["ece_97_5_interval"]))))
        gate = (reconstructed["ece"] <= protocol["semantic_ece_threshold"]
            and reconstructed["false_acceptance_per_all_cases"] <= protocol["semantic_false_acceptance_threshold"]
            and reconstructed["coverage"] >= protocol["minimum_semantic_coverage"])
        if gate != item["strict_point_gate_passed"]:
            raise ValueError("Semantic calibration gate was mislabeled")
    return maximum


def run(assets, binary, development, qualification, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "native-replay").mkdir()
    (output / "executed-source").mkdir()
    for name in ("audit.py", "verify_media.py", "verify_forecasts.py"):
        shutil.copyfile(Path(__file__).with_name(name), output / "executed-source" / name)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    seal = json.loads((qualification / "QUALIFICATION_SEAL.json").read_text())
    protocol = seal["protocol"]
    if byte_hash(binary) != seal["binary_sha256"]:
        raise ValueError("Replayed owner binary differs")
    for name, digest in seal["source_sha256"].items():
        if byte_hash(qualification / "executed-source" / name) != digest:
            raise ValueError("Executed source snapshot changed")
    for name, digest in seal["input_files_sha256"].items():
        if byte_hash(qualification / "inputs" / name) != digest:
            raise ValueError("Qualification input bytes changed")
    fit = json.loads((development / "FIT.json").read_text())
    validation = json.loads((development / "VALIDATION.json").read_text())
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    selected = json.loads((development / "CRITIC_SELECTION.json").read_text())["selected_shrinkage"]
    rows = [json.loads(line) for line in (qualification / "ROWS.jsonl").read_text().splitlines()]
    result = json.loads((qualification / "RESULT.json").read_text())
    if byte_hash(qualification / "ROWS.jsonl") != result["rows_sha256"]:
        raise ValueError("Qualification rows differ from the result receipt")
    all_sources = set()
    private_splits = {}
    for split, directory in (("fit", development / "fit-inputs"), ("validation", development / "validation-inputs"),
                             ("test", qualification / "inputs")):
        metadata, _, private = verify_sources(directory, assets)
        identities = {identity for row in metadata for identity in row["source_ids"]}
        if identities & all_sources:
            raise ValueError("Fit/validation/qualification source leakage")
        all_sources |= identities
        private_splits[split] = private
    reward, audit = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    media_error = prediction_error = 0.0
    reopened = 0
    for split, records in (("fit", fit), ("validation", validation)):
        private = private_splits[split]
        for row in records:
            i = row["index"]
            for which in ("initial", "alternate"):
                scored = independent_score(reward, row[which + "_delivery"], private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist())
                reopened += 2
                media_error = max(media_error, abs(scored["utility"] - row[which]["utility"]))
                if scored["strict_success"] != row[which]["strict_success"] or (which == "initial" and scored["feedback"] != row["feedback"]):
                    raise ValueError("Fitting semantic label differs from actual media")
    private = private_splits["test"]
    permutation = json.loads((qualification / "PERMUTATION_REFERENCE.json").read_text())
    for reference in permutation["reference"]:
        i = reference["index"]
        scored = independent_score(audit, reference["delivery"], private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist())
        reopened += 2
        if scored["feedback"] != reference["feedback"]:
            raise ValueError("Permuted feedback did not originate in the recorded actual delivery")
    audit_hash, native_count, chronology = hashlib.sha256(), 0, 0
    cost_error = 0.0
    verified_rows = []
    for row in rows:
        i = row["index"]
        target, labels = private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist()
        initial = independent_score(audit, row["initial"], target, labels)
        final = independent_score(audit, row["final"], target, labels)
        reopened += 4
        media_error = max(media_error, abs(initial["utility"] - row["initial_score"]["utility"]), abs(final["utility"] - row["final_score"]["utility"]))
        if initial["feedback"] != row["true_feedback"] or final["strict_success"] != row["final_score"]["strict_success"]:
            raise ValueError("Actual qualification semantics differ")
        donor = permutation["donor_indices"][i]
        expected_feedback = (0 if row["arm"] == "native_zero" else permutation["reference"][donor]["feedback"]
                             if row["arm"] == "native_permuted" else initial["feedback"])
        if expected_feedback != row["delivered_feedback"] or donor == i:
            raise ValueError("Feedback intervention or permutation identity differs")
        t = row["chronology"]
        if not (t["initial_delivery"] < t["feedback"] < t["process_restart"] < t["late_decision"] < t["private_final_scoring"]):
            raise ValueError("Feedback was not followed by a genuinely later controllable action")
        if row["admitted"] and not t["late_decision"] < t["correction_delivery"] < t["private_final_scoring"]:
            raise ValueError("Correction predates the late control decision")
        if row["before_cold_close"] != row["cold_restored_state"]:
            raise ValueError("Cold process recovery changed the committed feedback state")
        chronology += 1
        allowed = row["proposed"] and row["budget"] >= 2 and not any(tick["native_abstain"] for tick in row["actual_ticks"])
        if bool(allowed) != row["admitted"] or row["admitted"] != bool(row["correction"]):
            raise ValueError("Real admission/refusal differs from actual media")
        cost = 50 * protocol["native_kernel_charge"] + (1 + row["admitted"]) * (protocol["generator_call_charge"] + protocol["delivery_charge"])
        cost += row["denied"] * protocol["refused_proposal_charge"]
        cost_error = max(cost_error, abs(cost - row["task_charge"]))
        for timing in ("before", "after"):
            reconstructed = independent_prediction(fit, heads, row["condition"], row["arm"], row["expires"], row["budget"],
                selected, protocol, row["delivered_feedback"] if timing == "after" else None)
            prediction_error = max(prediction_error, *(abs(value - row[f"prediction_{timing}"][key]) for key, value in reconstructed.items()))
        transcript = json.loads((qualification / "episodes" / row["name"] / "TRANSCRIPT.json").read_text())
        count, fingerprint = replay(transcript, binary, development, output / "native-replay" / row["name"])
        native_count += count
        audit_hash.update(fingerprint.encode())
        verified_rows.append({**row, "initial_score": {**row["initial_score"], **initial},
            "final_score": {**row["final_score"], **final}, "net_utility": final["utility"] - cost})
        with (output / "PROGRESS.jsonl").open("a") as progress:
            progress.write(json.dumps({"episode": row["name"], "native_ticks": count, "native_projection_sha256": fingerprint}) + "\n")
        if len(verified_rows) % 80 == 0:
            print(f"independent actual owner and media audits {len(verified_rows)}/{len(rows)}", flush=True)
    maximum_statistic = statistics_check(verified_rows, result, protocol)
    if media_error > 1e-7 or prediction_error > 1e-10 or cost_error > 1e-10 or maximum_statistic > 1e-7:
        raise ValueError("Independent reconstruction exceeded numeric tolerances")
    write_new(output / "RESULT.json", {"passed": True, "actual_qualification_episodes": len(rows),
        "actual_media_file_reopens": reopened, "unique_verified_original_sources": len(all_sources),
        "actual_native_api_ticks_replayed": native_count, "cold_recoveries_replayed": len(rows),
        "semantic_receipt_comparison_sha256": audit_hash.hexdigest(), "chronology_chains_verified": chronology,
        "maximum_actual_utility_error": media_error, "maximum_forecast_formula_error": prediction_error,
        "maximum_task_cost_error": cost_error, "maximum_statistic_error": maximum_statistic,
        "independent_statistical_unit": "128 source pairs; fixed generator seed, no writer-population claim",
        "same_machine_independent_implementation": True, "human_semantic_audit": False,
        "native_comparison_excludes": ["nondeterministic timing", "transient/resident allocation measures"],
        "run_rows_sha256": byte_hash(qualification / "ROWS.jsonl"), "run_seal_sha256": byte_hash(qualification / "QUALIFICATION_SEAL.json"),
        "audit_source_sha256": {p.name: byte_hash(p) for p in (output / "executed-source").glob("*.py")}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "binary", "development", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.binary, args.development, args.qualification, args.output)
