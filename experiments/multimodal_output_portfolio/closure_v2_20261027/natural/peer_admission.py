"""Read-only independent statistics/media chronology for strict native admission."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.stats import beta


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(experiment, output):
    rows, result = read(experiment / "ROWS.json"), read(experiment / "RESULT.json")
    seal, spec = read(experiment / "QUALIFICATION_SEAL.json"), read(experiment / "PROTOCOL.json")
    if sha(experiment / "ROWS.json") != result["rows_sha256"] or sha(experiment / "QUALIFICATION_SEAL.json") != result["seal_sha256"]:
        raise ValueError("Qualified rows or seal changed")
    for name, key in (("PROTOCOL.json", "protocol_sha256"), ("CALIBRATOR.json", "calibrator_sha256"), ("SOURCE_ALLOCATION.json", "allocation_sha256")):
        if sha(experiment / name) != seal[key]:
            raise ValueError("A frozen input identity differs")
    sources, grid, media = set(), set(), set()
    maximum = 0.
    for row in rows:
        key = (row["role"], row["index"])
        if key in grid or any(identity in sources for identity in row["source_ids"]):
            raise ValueError("Repeated qualification episode or source image")
        grid.add(key)
        sources.update(row["source_ids"])
        chronology = row["chronology"]
        ordered = [chronology[key] for key in ("initial_delivery", "scalar_arrived", "process_restart", "late_native_decision", "public_prediction", "terminal_host_decision", "private_grade")]
        if ordered != sorted(set(ordered)) or chronology["candidate_readback"] > chronology["public_prediction"]:
            raise ValueError("Private score or feedback chronology is invalid")
        should_correct = row["native_proposed"] and row["expires"] >= 7 and row["budget"] >= 2
        if row["actual_correction"] != should_correct or row["native_refused"] != bool(row["native_proposed"] and not should_correct):
            raise ValueError("Native expiry/generation-budget outcome differs")
        if row["actual_correction"] and chronology["candidate_readback"] <= chronology["late_native_decision"]:
            raise ValueError("Later generation occurred before its owner decision")
        if not row["actual_correction"] and row["candidate"] != row["initial"]:
            raise ValueError("A refused or unnecessary generation changed the candidate")
        if row["native_authority"] != "DENY_ALL" or row["production_authorization"] or row["private_target_received"]:
            raise ValueError("Qualification exceeded the declared public research boundary")
        if row["bound_admission_sha256"] != seal["bound_admission_sha256"] or row["fitted_probability_uses_this_calibration_cohort"]:
            raise ValueError("Qualification changed its fitted model")
        episode = experiment / "episodes" / f"{row['role']}-{row['index']:04}"
        transcript = read(episode / "TRANSCRIPT.json")
        ticks = [item["request"] for item in transcript if item["request"]["command"] == "Tick"]
        if [item["feedback_q24"] for item in ticks if item["phase"] in (1, 2, 3)] != [row["feedback"] * (1 << 24), 0, 0]:
            raise ValueError("A later drive or hidden feedback entered the native continuation")
        if row["before_cold_close"] != row["cold_restored_state"]:
            raise ValueError("Actual cold restart did not recover the same state")
        fields = ("activation_q24", "eligibility_after_q24", "readout_logit", "proposed_repair", "native_abstain", "confidence_ppm", "ood_ppm")
        future = row["forecast_branches"][str(row["feedback"])]["ticks"]
        if [[r[f] for f in fields] for r in future] != [[r[f] for f in fields] for r in row["actual_ticks"]]:
            raise ValueError("Recorded forecast state differs from the realized policy")
        if (row["actual_owner_api_ticks"], row["forecast_replay_kernel_executions"], row["cold_recovery_kernel_executions"], row["actual_original_kernel_executions"]) != (16, 24, 10, 50):
            raise ValueError("Forecast/recovery cost is not fully accounted")
        for delivery in (row["initial"], row["candidate"], row["confirmed"]):
            if delivery is None:
                continue
            for kind, filename in delivery["paths"].items():
                path = Path(filename)
                if sha(path) != delivery["sha256"][kind]:
                    raise ValueError("Actual delivered media changed")
                if path not in media:
                    if kind == "image":
                        with Image.open(path) as picture:
                            picture.load()
                    elif path.read_text().strip() != delivery["caption"]:
                        raise ValueError("Actual caption readback differs")
                    media.add(path)
        if bool(row["confirmed"]) != row["commit"] or row["commit"] and row["confirmed"]["sha256"] != row["candidate"]["sha256"]:
            raise ValueError("Terminal confirmation does not copy the chosen candidate")
        utility = spec["final_utility"]
        probability = row["probability"]
        confidence = 1000000 - ((1 << 24) - math.floor(probability * (1 << 24) + .5)) * 1000000 // (1 << 24)
        moment = probability * math.exp(-utility["gamma"] * (utility["correct_commit"] - utility["commit_cost"])) + (1 - probability) * math.exp(-utility["gamma"] * (utility["incorrect_commit"] - utility["commit_cost"]))
        commit = row["category"] == "selected_by_public_head" and moment < 1.
        if row["confidence_ppm"] != confidence or row["commit"] != commit or row["strict_success"] != row["private_grade"]["strict_success"]:
            raise ValueError("Semantic event, quantization, or entropic action differs")
        fees = spec["task_sunk_fee"]
        sunk = 50 * fees["kernel"] + (1 + row["actual_correction"]) * fees["generator"] + fees["initial_delivery"] + row["native_refused"] * fees["refused_neural_proposal"]
        payoff = (utility["correct_commit"] if row["strict_success"] else utility["incorrect_commit"]) - utility["commit_cost"] if commit else 0.
        expected = {"sunk_resource_fee": sunk, "terminal_payoff": payoff, "total_net_utility": payoff - sunk,
            "predicted_commit_moment": moment, "predicted_total_policy_moment": math.exp(utility["gamma"] * sunk) * (moment if commit else 1.),
            "actual_total_policy_moment": math.exp(-utility["gamma"] * (payoff - sunk))}
        maximum = max(maximum, max(abs(row[k] - value) for k, value in expected.items()))
    expected_grid = {(role, index) for role, size in (("qualification_id", 424), ("qualification_ood", 600)) for index in range(size)}
    if grid != expected_grid or maximum > 1e-10:
        raise ValueError("Incomplete qualification or inconsistent accounting")
    id_rows = [r for r in rows if not r["declared_ood"]]
    ood_rows = [r for r in rows if r["declared_ood"]]

    def ece(selected):
        error = 0.
        for index in range(10):
            group = [r for r in selected if min(r["confidence_ppm"] // 100000, 9) == index]
            error += abs(sum(r["strict_success"] for r in group) - sum(r["confidence_ppm"] for r in group) / 1e6)
        return error / len(selected)

    legacy = lambda r: r["confidence_ppm"] >= 750000 and 1000000 - r["confidence_ppm"] <= 500000
    incorrect = sum(r["commit"] and not r["strict_success"] for r in id_rows)
    commits = sum(r["commit"] for r in id_rows)
    false_ood = sum(legacy(r) for r in ood_rows)
    metrics = {"ece_full": ece(rows), "ece_id": ece(id_rows),
        "legacy_id_coverage": sum(legacy(r) for r in id_rows) / len(id_rows),
        "legacy_ood_false_acceptances": false_ood, "legacy_ood_far": false_ood / len(ood_rows),
        "legacy_ood_one_sided_95_upper": 1 - .05 ** (1 / len(ood_rows)) if not false_ood else None,
        "selective_id_coverage": commits / len(id_rows), "incorrect_semantic_commits_id": incorrect,
        "incorrect_semantic_commit_per_id_case": incorrect / len(id_rows),
        "incorrect_semantic_commit_per_id_one_sided_95_upper": float(beta.ppf(.95, incorrect + 1, len(id_rows) - incorrect)),
        "error_among_selective_id_commits": incorrect / commits}
    if any(value is None or abs(result[key] - value) > 1e-12 for key, value in metrics.items()):
        raise ValueError("Reported legacy or additional semantic metrics differ")
    actual = np.asarray([r["actual_total_policy_moment"] for r in rows])
    abstain = np.exp(2 * np.asarray([r["sunk_resource_fee"] for r in rows]))
    difference = actual - abstain
    rng = np.random.default_rng(27207001)
    interval = np.quantile(difference[rng.integers(len(rows), size=(5000, len(rows)))].mean(1), [.025, .975])
    report = {"passed": True, "imports_producer_statistics_scorer_or_model": False,
        "native_or_neural_model_reexecutions": 0, "scope": "Independent recorded-statistics, numerical trajectory, actual media identity, chronology and fee/terminal-moment audit; the separate full owner audit replays kernels and the semantic observer.",
        "source_pairs": len(rows), "distinct_source_images": len(sources), "actual_media_paths_reopened": len(media),
        "actual_kernel_executions_accounted": sum(r["actual_original_kernel_executions"] for r in rows),
        "actual_generation_calls": sum(1 + r["actual_correction"] for r in rows),
        "actual_generation_refusals": sum(r["native_refused"] for r in rows),
        "maximum_fee_or_moment_discrepancy": maximum, "metrics": metrics,
        "unchanged_original_legacy_shaped_gates_pass": all(result["legacy_shaped_gates"].values()),
        "additional_incorrect_commit_gate_pass": result["additional_selective_gates"]["incorrect_commit_rate"],
        "posthoc_matched_sunk_cost_abstention_diagnostic": {"mean_actual_policy_moment": float(actual.mean()),
            "mean_always_abstain_moment": float(abstain.mean()), "difference": float(difference.mean()),
            "pair_CI95": interval.tolist(), "larger_moment_is_worse": True,
            "not_a_new_gate_or_a_reoptimized_generation_policy": True},
        "limits": ["OOD is the declared both-inputs-missing distribution, not general semantic OOD", "Candidate probability is post-codec, not a before-generation pixel forecast", "Terminal host confirmation copies existing bytes and does not reopen an expired owner", "Low ECE does not imply the additional incorrect-commit target is met", "No production permission or global dynamic optimality follows"],
        "rows_sha256": sha(experiment / "ROWS.json"), "qualification_seal_sha256": sha(experiment / "QUALIFICATION_SEAL.json")}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.experiment, args.output)
