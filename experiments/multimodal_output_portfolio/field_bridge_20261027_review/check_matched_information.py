"""Read frozen bridge evidence and audit matched observations without model execution."""

import argparse
import collections
import datetime
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import struct


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inputs = {
        "rows.jsonl": args.run / "rows.jsonl",
        "RESULT.json": args.run / "RESULT.json",
        "EVALUATION_COMPLETE.json": args.run / "EVALUATION_COMPLETE.json",
        "PROTOCOL.json": args.study / "PROTOCOL.json",
    }
    hashes_before = {name: sha256(path) for name, path in inputs.items()}
    protocol = json.loads(inputs["PROTOCOL.json"].read_text())
    result = json.loads(inputs["RESULT.json"].read_text())
    complete = json.loads(inputs["EVALUATION_COMPLETE.json"].read_text())
    arm_specs = {**protocol["canonical_arms"], **protocol["supplementary_arms"]}
    profile_arms = collections.defaultdict(set)
    for arm, (profile, _) in arm_specs.items():
        profile_arms[profile].add(arm)
    groups = collections.defaultdict(dict)
    resources = collections.defaultdict(lambda: collections.defaultdict(list))
    arm_rows = collections.Counter()
    errors = []
    rows = 0
    timing_keys = ("decision_wall_ns", "decision_python_cpu_ns", "native_kernel_ns", "native_tick_calls")
    with inputs["rows.jsonl"].open() as stream:
        for line in stream:
            row = json.loads(line)
            rows += 1
            arm = row["arm"]
            profile = arm_specs[arm][0]
            key = (row["seed"], row["split"], row["corruption"], row["pair"], profile)
            if arm in groups[key]:
                errors.append({"type": "duplicate_arm_row", "key": key, "arm": arm})
            for feature_name in ("public_features0", "public_features1"):
                values = row[feature_name]
                if len(values) != 8 or not all(math.isfinite(x) for x in values):
                    errors.append({"type": "invalid_public_features", "key": key, "arm": arm})
            row["artifacts"] = {item["phase"]: item for item in row["artifacts"]}
            for item in row["artifacts"].values():
                item.pop("public_text_logits", None)
            groups[key][arm] = row
            summary_key = f"{row['split']}/{arm}"
            arm_rows[summary_key] += 1
            for name in timing_keys:
                resources[summary_key][name].append(row["resources"][name])

    expected_keys = set()
    for split in ("test", "retention"):
        for seed, condition, pair, profile in itertools.product(
            protocol["seeds"], protocol[f"{split}_conditions"],
            range(protocol[f"{split}_pairs"]), profile_arms,
        ):
            expected_keys.add((seed, split, condition, pair, profile))
    if set(groups) != expected_keys:
        errors.append({"type": "unexpected_group_grid", "missing": sorted(expected_keys - set(groups)),
                       "extra": sorted(set(groups) - expected_keys)})
    counts = collections.Counter()
    profile_counts = collections.defaultdict(collections.Counter)
    arm_pair_counts = collections.defaultdict(collections.Counter)
    observation_mismatches, final_mismatches = [], []
    reset = collections.defaultdict(lambda: {"paired_rows": 0, "action_changes": 0,
                                           "same_controller_sha": 0, "transition_counts": collections.Counter()})
    identity_fields = ("model_sha", "source_ids", "batch_seed", "noise_seed", "batch_start", "batch_size")
    for key, group in sorted(groups.items()):
        profile = key[-1]
        if set(group) != profile_arms[profile]:
            errors.append({"type": "incorrect_group_arms", "key": key, "arms": sorted(group)})
        profile_counts[profile]["groups"] += 1
        if len(group) > 1:
            counts["multiarm_groups"] += 1
        for (arm_a, a), (arm_b, b) in itertools.combinations(sorted(group.items()), 2):
            counts["arm_pair_comparisons"] += 1
            profile_counts[profile]["arm_pair_comparisons"] += 1
            pair_name = f"{arm_a}|{arm_b}"
            arm_pair_counts[pair_name]["observation_comparisons"] += 1
            mismatched = [name for name in identity_fields if a[name] != b[name]]
            for name in ("public_features0", "public_features1"):
                if struct.pack("<8d", *a[name]) != struct.pack("<8d", *b[name]):
                    mismatched.append(name)
            for phase in ("preview0", "preview1"):
                for medium in ("image", "text"):
                    if a["artifacts"][phase]["sha256"][medium] != b["artifacts"][phase]["sha256"][medium]:
                        mismatched.append(f"{phase}.{medium}.sha256")
                if a["artifacts"][phase]["public_text_logits_sha256"] != b["artifacts"][phase]["public_text_logits_sha256"]:
                    mismatched.append(f"{phase}.public_text_logits_sha256")
            if mismatched:
                observation_mismatches.append({"key": key, "arms": [arm_a, arm_b], "fields": mismatched})
            if a["action"] == b["action"]:
                counts["same_action_arm_pair_comparisons"] += 1
                profile_counts[profile]["same_action_arm_pair_comparisons"] += 1
                arm_pair_counts[pair_name]["same_action_final_comparisons"] += 1
                differing_media = [name for name in ("image", "text") if
                    a["artifacts"]["final"]["sha256"][name] != b["artifacts"]["final"]["sha256"][name]]
                if differing_media:
                    final_mismatches.append({"key": key, "arms": [arm_a, arm_b], "action": a["action"],
                                             "media": differing_media, "a": a["artifacts"]["final"],
                                             "b": b["artifacts"]["final"]})
        if profile == "field":
            a, b = group["E_field_native"], group["I_field_reset"]
            diagnostic = reset[key[1]]
            diagnostic["paired_rows"] += 1
            diagnostic["action_changes"] += int(a["action"] != b["action"])
            diagnostic["same_controller_sha"] += int(a["controller_sha"] == b["controller_sha"])
            diagnostic["transition_counts"][f"{a['action']}->{b['action']}"] += 1

    reset_matches = True
    for split, diagnostic in reset.items():
        diagnostic["action_change_percent"] = 100 * diagnostic["action_changes"] / diagnostic["paired_rows"]
        expected = result["native_state_reset_action_diagnostic"][split]
        matches = all(diagnostic[k] == expected[k] for k in ("paired_rows", "action_changes"))
        diagnostic["matches_RESULT"] = matches
        reset_matches &= matches
        diagnostic["transition_counts"] = dict(sorted(diagnostic["transition_counts"].items()))

    cost_summaries = {}
    resource_mismatches = []
    for key, measured in sorted(resources.items()):
        summary = result["summaries"][key]["descriptive_resources"]
        cost_summaries[key] = {}
        for name in timing_keys:
            original = summary[name]
            ordered = sorted(measured[name])
            h = (len(ordered) - 1) * 0.95
            lo, hi = math.floor(h), math.ceil(h)
            recomputed = {"mean": statistics.fmean(ordered), "median": statistics.median(ordered),
                          "p95": ordered[lo] + (ordered[hi] - ordered[lo]) * (h - lo),
                          "rows_with_measurement": len(ordered)}
            if not all(math.isclose(recomputed[k], original[k], rel_tol=1e-12, abs_tol=1e-7)
                       for k in recomputed):
                resource_mismatches.append({"key": key, "metric": name,
                                            "RESULT": original, "recomputed": recomputed})
            cost_summaries[key][name] = original
            if name.endswith("_ns"):
                cost_summaries[key][name[:-3] + "_us"] = {
                    k: v if k == "rows_with_measurement" else v / 1000 for k, v in original.items()
                }
    ratios = {}
    for split in ("test", "retention"):
        for profile, native_arm, history_arm in (
            ("field", "E_field_native", "F_field_history"),
            ("frozen", "D_frozen_native", "H_frozen_history"),
        ):
            n = cost_summaries[f"{split}/{native_arm}"]
            h = cost_summaries[f"{split}/{history_arm}"]
            ratios[f"{split}/{profile}"] = {
                "native_arm": native_arm, "history_arm": history_arm,
                "mean_decision_wall_ratio": n["decision_wall_ns"]["mean"] / h["decision_wall_ns"]["mean"],
                "mean_decision_wall_difference_us": (n["decision_wall_ns"]["mean"] - h["decision_wall_ns"]["mean"]) / 1000,
                "native_kernel_fraction_of_native_decision_wall": n["native_kernel_ns"]["mean"] / n["decision_wall_ns"]["mean"],
            }
    hashes_after = {name: sha256(path) for name, path in inputs.items()}
    passed = (not errors and not observation_mismatches and not final_mismatches
              and not resource_mismatches and reset_matches and hashes_before == hashes_after
              and complete["rows"] == rows and complete["row_sha256"] == hashes_before["rows.jsonl"])
    report = {
        "schema": "hepta.field-bridge.matched-information-audit.v1",
        "created_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "passed": passed,
        "scope": "Post-execution evidence comparison only; no model execution, fitting, source edits or result edits.",
        "inputs_sha256": hashes_before,
        "input_hashes_unchanged": hashes_before == hashes_after,
        "row_hash_and_count_match_EVALUATION_COMPLETE": complete["rows"] == rows and complete["row_sha256"] == hashes_before["rows.jsonl"],
        "group_key": ["seed", "split", "corruption", "pair", "profile"],
        "rows": rows, "groups": len(groups), "expected_groups": len(expected_keys),
        "rows_by_split_arm": dict(sorted(arm_rows.items())),
        "profile_arms": {k: sorted(v) for k, v in sorted(profile_arms.items())},
        "comparison_counts": dict(counts),
        "profile_comparison_counts": {k: dict(v) for k, v in sorted(profile_counts.items())},
        "arm_pair_comparison_counts": {k: dict(v) for k, v in sorted(arm_pair_counts.items())},
        "coverage_errors": errors,
        "observation_mismatch_count": len(observation_mismatches),
        "observation_mismatches": observation_mismatches,
        "observation_check": "Both preview image and UTF-8 SHA256 values; both public 8-vectors packed as little-endian float64 for exact identity; both preview public-logit SHA256 values; same model, source IDs, noise seed, batch seed/start/size.",
        "same_action_final_media_mismatch_count": len(final_mismatches),
        "same_action_final_media_mismatches": final_mismatches,
        "artifact_check_scope": "Recorded SHA256 comparison over every row. Raw artifact revalidation is covered by the separate complete independent audit. Final unquantized neural tensors were not compared; the conclusion is persisted PNG and UTF-8 equality.",
        "same_information_conclusion": "All matched arms within each shared model profile received exactly identical recorded public observations; generic and richer profiles each have only one arm and provide no between-arm matching evidence." if not observation_mismatches else "See observation mismatches.",
        "native_state_reset_action_diagnostic": dict(reset),
        "reset_interpretation": "Same E/I frozen controller SHA and same public observations. Changed actions establish state sensitivity for this controller; action-change frequency alone does not establish better control or memory benefit.",
        "decision_costs": cost_summaries,
        "decision_cost_ratios": ratios,
        "resource_recomputation_mismatches": resource_mismatches,
        "cost_scope": result["cost_scope"],
        "cost_interpretation": [
            "Wall and Python process CPU times cover runtime feature construction plus readout choice. Native timing includes IPC, feature hashing, receipt serialization and writing; history uses an in-process NumPy feature map.",
            "Native kernel time is the sum of durations measured immediately around the two original sparse_tick calls. Python process CPU does not include the native subprocess CPU time.",
            "Recorded timings are batch totals divided by batch size, repeated for each row. Their median and p95 describe batch-amortized costs, not independently timed per-case latency.",
            "Descriptive timings are measured for this implementation and host. They are separate from the objective's logical refinement tariff and do not establish optimized production latency.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("passed", "rows", "groups", "comparison_counts",
                                          "observation_mismatch_count", "same_action_final_media_mismatch_count",
                                          "native_state_reset_action_diagnostic", "decision_cost_ratios")}, indent=2))


if __name__ == "__main__":
    main()
