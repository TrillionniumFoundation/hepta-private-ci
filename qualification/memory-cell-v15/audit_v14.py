#!/usr/bin/env python3
"""Descriptive audit of pinned V14 receipts; no training or new evaluation.

Use --list-inputs to obtain the pinned URLs and Git blob identities. Fetch those
files into a directory under the listed local names, then run:
  python audit_v14.py --input-dir /path/to/inputs --output evidence/v14_audit.json
Alternatively, --input-dir may point to a full checkout containing the pinned
repository paths. Only Python's standard library is required. Large original
receipts are deliberately not duplicated in V15. Recorded outputs are compared
with the original gold values; neither models nor the executor are rerun.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


REPO = "TrillionniumFoundation/hepta-private-ci"
REF = "6d2551388ed42355f02afbf528472ee2b4d8488b"
SOURCE = "c991ad02f1cba86471cbba59c9756a678a18ecf7"
BASE = "qualification/memory-cell-v14/"
RUN = "41261379136"
SEEDS = (17, 29, 43)
READ_HORIZONS = (1, 10, 100, 1000, 10000)
TARGETS = ("bert_lora", "bert_mlp", "bert_fast_weights")
SOURCES = {}
for seed, blob, process_blob in (
    (17, "1f31bd44f8b3730323dac9a52ed7c73d8976219f", "bc05476c7c7cdce8fb3b7b62155a38bbc8ff2040"),
    (29, "f61bcb0e76fe1fe672a3e03ebce96c38d808ffd1", "5e2d90e57fe33da1d6d482caee23f8f1b399f30d"),
    (43, "f1fc33f70858e1cd935fb9eb882271ab1c2f9a09", "c328b152834c48f5d4931f2156386d6799058c53"),
):
    prefix = BASE + f"evidence/semantic-{RUN}-1/readable/v14-semantic-{seed}-{RUN}-1/"
    SOURCES[f"semantic-{seed}.json"] = (prefix + "semantic_run.json", blob)
    SOURCES[f"process-{seed}.json"] = (prefix + "process.json", process_blob)
SOURCES.update({
    "semantic_protocol.json": (BASE + "semantic_protocol.json", "fd0de9bf95138841d1d597b7e151d920c15f3dff"),
    "semantic_holdout.json": (BASE + "semantic_holdout.json", "e9b997dc16d0a600dbbc133dfd9acd20c8eda8e4"),
    "semantic_costs.py": (BASE + "semantic_costs.py", "8f702563c438c1f68a2244b95727a59e28af2a72"),
    "native_receipt.json": (BASE + "evidence/native-41621420840-1/readable/"
        "memory-v14-native-5656702b7812dc75326342c39f4c8afcfd9ba186-41621420840-1/receipt.json",
        "69b8b4ad34d0ae769884ee6a2a6c4dc49ded1aba"),
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(left, right):
    require(math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12),
            f"aggregate mismatch: {left!r} != {right!r}")


def canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def audit(input_dir):
    inputs, identities = {}, []
    for name, (path, expected) in SOURCES.items():
        local = input_dir / name
        if not local.is_file():
            local = input_dir / path
        raw = local.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(blob == expected, f"Git blob identity mismatch: {name}")
        identities.append({"name": name, "path": path, "git_blob_sha": blob,
                           "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        inputs[name] = json.loads(raw) if name.endswith(".json") else raw.decode()
    protocol, holdout = inputs["semantic_protocol.json"], inputs["semantic_holdout.json"]
    rows, compositions = holdout["rows"], holdout["compositions"]
    require(len(rows) == 96 and len(compositions) == 12, "unexpected historical task size")
    require(protocol["seeds"] == list(SEEDS), "seed identity mismatch")
    require(protocol["target_arms"] == list(TARGETS), "target/control roles changed")
    require(protocol["paired_bugfix"]["independent_new_samples"] == 0, "holdout interpretation changed")
    runs = [inputs[f"semantic-{seed}.json"] for seed in SEEDS]
    processes = [inputs[f"process-{seed}.json"] for seed in SEEDS]
    arm_names = sorted(protocol["arms"])
    by_arm = {name: [] for name in arm_names}
    source_flags = {name: [] for name in arm_names}
    prior = {}
    for seed, run, process in zip(SEEDS, runs, processes):
        require(run["seed"] == seed and run["github_commit"] == SOURCE, "experiment identity mismatch")
        require(run["github_run_id"] == RUN and process["source_commit"] == SOURCE, "run identity mismatch")
        require(process["run_id"] == RUN and process["exit_code"] == 0, "failed or wrong process")
        require(run["data_manifest"] == runs[0]["data_manifest"], "nonidentical seed data")
        require(run["data_manifest"]["holdout_sha256"] == canonical_sha(holdout), "holdout digest mismatch")
        require(run["protocol_sha256"] == canonical_sha(protocol), "protocol digest mismatch")
        require(sorted(run["arms"]) == arm_names, "arm set changed")
        for entry in run["exploration_cost"]["prior_entries"]:
            require(entry["id"] not in prior or prior[entry["id"]] == entry, "conflicting prior ledger entry")
            prior[entry["id"]] = entry
        for name, arm in run["arms"].items():
            outcomes = arm["holdout"]["outcomes"]
            require(len(outcomes) == len(rows) == arm["holdout"]["count"], "outcome count mismatch")
            flags = []
            for row, outcome in zip(rows, outcomes):
                correct = outcome["error"] is None and outcome["output"] == row["expected"]
                require(type(outcome["correct"]) is bool and correct == outcome["correct"], "gold output mismatch")
                require((outcome["predicted_skill"] == row["skill"]) == outcome["label_correct"], "label mismatch")
                flags.append(correct)
            correct_count = sum(flags)
            accuracy = correct_count / len(rows)
            close(accuracy, arm["holdout"]["task_success"])
            close(sum(o["label_correct"] for o in outcomes) / len(rows), arm["holdout"]["label_accuracy"])
            require(len(arm["compositions"]) == len(compositions), "composition count mismatch")
            composition_flags = []
            for gold, output in zip(compositions, arm["compositions"]):
                require(gold["id"] == output["id"], "composition identity mismatch")
                value = output["output"] == gold["expected"] and not any(t.get("error") for t in output["trace"])
                require(value == output["correct"], "composition gold mismatch")
                composition_flags.append(value)
            close(sum(composition_flags) / len(compositions), arm["composition_success"])
            cost, timings = arm["cost"], arm["query_timings"]
            times = [sample["seconds"] for sample in timings["wall_samples"]]
            require(len(times) == len(timings["cpu_samples_seconds"]) == timings["count"] == 48, "timing count mismatch")
            require(all(math.isfinite(t) and t >= 0 for t in times), "invalid timing")
            mean = statistics.fmean(times)
            close(mean, timings["mean_seconds"])
            close(percentile(times, .95), timings["p95_seconds"])
            startup = sum(cost[k] for k in ("model_acquisition_load_seconds", "prepare_seconds",
                          "all_training_and_selection_seconds", "serialization_seconds", "restore_seconds"))
            retained = sum(cost[k] for k in ("base_files_bytes", "source_bytes", "all_candidate_checkpoint_bytes"))
            close(startup, cost["startup_write_seconds"])
            require(retained == cost["retained_bytes"], "retained bytes mismatch")
            utility = {str(q): accuracy - .01 * (startup / q + mean) - .001 * retained / 2**30 / q
                       for q in READ_HORIZONS}
            for q, value in utility.items():
                close(value, arm["utility_by_reads"][q])
            require(arm["research_amortized_cost_complete"] is False, "unknown research costs erased")
            by_arm[name].append({"correct": correct_count, "compositions_correct": sum(composition_flags),
                "retained_bytes": retained, "base_files_bytes": cost["base_files_bytes"],
                "source_bytes": cost["source_bytes"], "candidate_checkpoint_bytes": cost["all_candidate_checkpoint_bytes"],
                "startup_seconds": startup, "train_select_seconds": cost["all_training_and_selection_seconds"],
                "acquisition_seconds": cost["model_acquisition_load_seconds"], "read_mean_ms": mean * 1000,
                "read_p95_ms": percentile(times, .95) * 1000,
                "read_cpu_mean_ms": statistics.fmean(timings["cpu_samples_seconds"]) * 1000,
                "utility": utility, "selected_steps": arm.get("selected_steps"), "selected": arm.get("selected")})
            source_flags[name].append(flags)
    comparisons = []
    pairs = [(t, b) for t in TARGETS for b in ("minilm_ridge", "lexical_ridge", "bert_ridge")]
    pairs.append(("bert_lora", "bert_linear"))
    for target, baseline in pairs:
        counts = []
        for left, right in zip(source_flags[target], source_flags[baseline]):
            wins = sum(a and not b for a, b in zip(left, right))
            losses = sum(b and not a for a, b in zip(left, right))
            both = sum(a and b for a, b in zip(left, right))
            counts.append({"wins": wins, "losses": losses, "both_correct": both,
                           "both_wrong": 96 - wins - losses - both, "delta_correct": wins - losses})
        comparisons.append({"target": target, "baseline": baseline, "paired_counts_by_seed": counts,
                            "mean_delta_accuracy": statistics.fmean(x["delta_correct"] / 96 for x in counts)})
    baselines = [a for a in arm_names if a not in TARGETS]
    failed_scenarios = {t: sum(by_arm[t][i]["utility"][str(q)] <= max(by_arm[b][i]["utility"][str(q)] for b in baselines)
                             for i in range(3) for q in READ_HORIZONS) for t in TARGETS}
    known_prior_wall = sum(p["wall_seconds"] for p in prior.values() if p.get("wall_seconds") is not None)
    known_prior_cpu = sum(p["cpu_seconds"] for p in prior.values() if p.get("cpu_seconds") is not None)
    for run in runs:
        close(known_prior_wall, run["exploration_cost"]["known_previous_wall_seconds"])
    native = inputs["native_receipt.json"]
    require(native["passed"] is True and native["executed_cases"] == 19 and not native["failed_cases"], "native CI receipt failed")
    require(native["source_commit"] == "5656702b7812dc75326342c39f4c8afcfd9ba186", "wrong native CI source")
    require(len(native["required_lifecycle_cases"]) == 19, "missing required lifecycle cases")
    require("memory_v14_query_fence_ignores_unrelated_source_commits" in native["required_lifecycle_cases"], "missing repaired-fence case")
    return {
        "schema": "hepta.memory.v15.descriptive-v14-audit.v1", "status": "verified_historical_receipts",
        "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "repo": REPO, "preservation_ref": REF, "experiment_source": SOURCE, "experiment_run": RUN,
        "new_experiments": 0, "new_independent_queries": 0, "input_identities": identities,
        "verification": {"git_blobs": len(identities), "seed_arm_groups": 42,
            "recorded_outputs_checked_against_gold": 4032, "recorded_compositions_checked_against_gold": 504,
            "arithmetic_mismatches": 0, "models_or_executor_rerun": False,
            "train_calibration_raw_bytes_reverified": False, "checkpoint_tensor_payloads_reverified": False},
        "statistical_scope": {"seeds": list(SEEDS), "same_holdout_requests": 96, "skill_groups": 12,
            "composition_requests": 12, "timing_unique_requests": 16, "timing_repeats": 3,
            "timing_observations_per_arm_seed": 48, "independent_language_sample_count_is_not_288": True,
            "interpretation": "Paired descriptive audit of the already evaluated cue-repair holdout; no new generalization or significance claim."},
        "comparison_controls": {"common_train_calibration_hashes": True,
            "common_recorded_executor_digest": runs[0]["data_manifest"]["shared_executor_file_sha256"],
            "cpu_threads": protocol["training_and_selection"]["cpu_threads"],
            "different_pretrained_encoders_allowed": protocol["models"]["different_pretrained_encoders_allowed_as_strong_baselines"],
            "equal_total_storage_training_inference_budget_established": False,
            "note": "Same recorded input/executor identities with measured unequal costs; this historical protocol is not a new strict total-budget-matched experiment. Exact KV here maps exact request strings to skills, not the separate factual-memory task."},
        "protocol": {"sha256": canonical_sha(protocol), "holdout_sha256": canonical_sha(holdout),
            "training_and_selection": protocol["training_and_selection"], "target_arms": list(TARGETS),
            "read_horizons": list(READ_HORIZONS), "storage_window_hours": 1,
            "wall_second_penalty": .01, "gib_hour_penalty": .001,
            "task_scope": protocol["task_scope"], "information": protocol["information"]},
        "arms": {name: {"role": "prespecified_candidate" if name in TARGETS else "baseline",
                "by_seed": values, "mean_accuracy_descriptive": statistics.fmean(v["correct"] / 96 for v in values),
                "correctness_vectors_identical_across_seeds": source_flags[name][0] == source_flags[name][1] == source_flags[name][2]}
                 for name, values in by_arm.items()},
        "paired_comparisons": comparisons,
        "candidate_scenarios_not_better_than_best_baseline_out_of_15": failed_scenarios,
        "research_cost": {"complete": False, "deduplicated_prior_wall_seconds": known_prior_wall,
            "current_subprocess_wall_seconds": sum(p["wall_seconds"] for p in processes),
            "known_track_subprocess_wall_seconds": known_prior_wall + sum(p["wall_seconds"] for p in processes),
            "known_track_subprocess_cpu_seconds": known_prior_cpu + sum(p["child_cpu_seconds"] for p in processes),
            "current_internal_run_wall_seconds": sum(r["physical_run_wall_seconds"] for r in runs),
            "current_peak_process_rss_bytes_by_seed": [p["child_peak_rss_bytes"] for p in processes],
            "unknown_prior_entries": [p for p in prior.values() if p.get("wall_seconds") is None],
            "energy_joules": None, "cloud_bill_usd": None,
            "other_unmeasured_costs": ["dependency install/checkout/preservation and other CI overhead",
                "complete earlier V13 research", "distributed transport/migration and actual device energy"],
            "accounting_note": "Repeated prior ledger counted once. Internal run wall is nested inside subprocess wall, not additive. Retained bytes include source, base and every candidate checkpoint; deployment arm sums charge a shared encoder separately."},
        "native_fence_repair": {"pr": 4687, "source_commit": native["source_commit"],
            "source_tree": native["source_tree"], "run_id": native["github"]["GITHUB_RUN_ID"],
            "executed_cases": native["executed_cases"], "summary": native["nextest_summary"],
            "old_unrelated_commit_bug_is_fixed_in_scoped_candidate": True,
            "physical_multi_node_or_distributed_atomicity_proven": False,
            "full_repository_ci_or_production_qualified": False},
        "conclusion": "All three prespecified candidates remain below the strongest measured baseline under the original quality and utility protocol. This audit adds provenance/arithmetic checks, not new model quality or long-term stability evidence."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "evidence/v14_audit.json")
    parser.add_argument("--list-inputs", action="store_true")
    args = parser.parse_args()
    if args.list_inputs:
        print(json.dumps([{ "local_name": name, "git_blob_sha": blob,
            "url": f"https://github.com/{REPO}/blob/{REF}/{path}"} for name, (path, blob) in SOURCES.items()], indent=2))
        return
    if args.input_dir is None:
        parser.error("--input-dir is required unless --list-inputs is used")
    result = audit(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output), "verified_input_blobs": len(SOURCES),
        "new_experiments": 0, "candidate_failed_scenarios": result["candidate_scenarios_not_better_than_best_baseline_out_of_15"]}))


if __name__ == "__main__":
    main()
