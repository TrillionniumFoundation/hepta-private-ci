"""Read-only aggregation of the frozen roster, costs, and independent test phase."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import mean, median


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def stats(values):
    return {"n": len(values), "mean": mean(values), "median": median(values), "min": min(values), "max": max(values)} if values else {"n": 0}


def main(root):
    root = Path(root)
    protocol_path = root / "FORMAL_PROTOCOL_v2.json"
    protocol = json.loads(protocol_path.read_text())
    records, terminals, receipts = {}, [], []
    for shard in range(4):
        terminal_path = root / "formal_v2_training" / f"TRAINING_TERMINALS_shard_{shard}.json"
        terminal = json.loads(terminal_path.read_text())
        if terminal["protocol_sha256"] != sha(protocol_path) or not terminal["all_assigned_slots_terminal"]:
            raise ValueError("Missing or mismatched terminal shard")
        expected = protocol["execution"]["shards"][str(shard)]
        if [row["case"] for row in terminal["rows"]] != expected:
            raise ValueError("Shard roster differs from protocol")
        for binding in terminal["rows"]:
            path = root / "formal_v2_training" / binding["case"] / "RESULT.json"
            if sha(path) != binding["result_sha256"]:
                raise ValueError("Training result changed")
            row = json.loads(path.read_text())
            if row.get("candidate_sha256") and sha(path.with_name("candidate.pt")) != row["candidate_sha256"]:
                raise ValueError("Candidate changed")
            if binding["case"] in records:
                raise ValueError("Duplicate candidate")
            records[binding["case"]] = row
        terminals.append(terminal)
        receipts.append(json.loads((root / f"WORKER_{shard}_EXECUTION.json").read_text()))
    if len(records) != len(protocol["cases"]):
        raise ValueError("Incomplete global roster")
    identity = defaultdict(set)
    for row in records.values():
        identity[(row["case"]["width"], row["case"]["seed"])].add(row.get("initial_physical_sha256"))
    initialization_checks = [{"width": n, "seed": s, "distinct_initial_physical_hashes": len(v),
                              "pass": len(v) == 1 and None not in v} for (n, s), v in sorted(identity.items())]
    successful = [row for row in records.values() if row["status"] != "FAILED"]
    by_width = []
    for width in (8, 16, 32, 64):
        rows = [r for r in successful if r["case"]["width"] == width and r["case"]["group"] == "main_factorial"]
        by_width.append({"width": width, "count": len(rows), "updates": stats([r["updates"] for r in rows]),
                         "selected_steps": stats([r["selected_step"] for r in rows]),
                         "selected_dev_accuracy": stats([r["selected_dev"]["accuracy"] for r in rows]),
                         "case_wall_s": stats([r["cost"]["total_case_wall_s"] for r in rows]),
                         "optimization_cpu_s": stats([r["cost"]["optimization_cpu_s"] for r in rows]),
                         "state_tensor_bytes": sorted({r["state_tensor_bytes"] for r in rows}),
                         "allocated_parameters": sorted({r["parameters"]["allocated"] for r in rows})})
    first = min(datetime.fromisoformat(r["started_utc"]) for r in receipts)
    last = max(datetime.fromisoformat(r["completed_utc"]) for r in receipts)
    cost_totals = defaultdict(float)
    for row in records.values():
        for name, value in row["cost"].items():
            cost_totals[name] += value
    training = {"protocol_sha256": sha(protocol_path), "record_count": len(records),
                "statuses": dict(Counter(r["status"] for r in records.values())),
                "initialization_checks": initialization_checks, "all_initialization_checks_passed": all(r["pass"] for r in initialization_checks),
                "by_width": by_width, "sum_case_costs": dict(cost_totals),
                "campaign_wall_span_s": (last - first).total_seconds(),
                "sum_worker_child_cpu_s": sum(r["child_cpu_s"] for r in receipts),
                "worker_peak_rss_kib": [r["child_peak_rss_kib"] for r in receipts],
                "max_concurrent_workers": 4, "single_threaded_independent_processes": True,
                "wall_times_include_shared_host_contention": True,
                "test_used_for_training": False, "summary_source_sha256": sha(__file__)}
    dump(root / "TRAINING_SUMMARY.json", training)
    evaluation_path = root / "formal_v2_test/RESULT.json"
    if not evaluation_path.exists():
        print(json.dumps({"training": training["statuses"], "rows": len(records), "test_available": False}))
        return
    evaluation = json.loads(evaluation_path.read_text())
    if evaluation["protocol_sha256"] != sha(protocol_path) or len(evaluation["rows"]) != len(records):
        raise ValueError("Evaluation roster or protocol mismatch")
    rows = {r["name"]: r for r in evaluation["rows"]}
    if set(rows) != set(records) or len(rows) != len(evaluation["rows"]):
        raise ValueError("Evaluation names differ from training")
    evaluated = [r for r in rows.values() if r["status"] == "EVALUATED"]
    groups = defaultdict(list)
    for row in evaluated:
        c = row["case"]
        if c["group"] == "main_factorial":
            groups[(c["width"], c["bank"], c["message"], c["connection"])].append(row)
    grouped = []
    for key, values in sorted(groups.items()):
        grouped.append({"width": key[0], "bank": key[1], "message": key[2], "connection": key[3],
                        "seeds": sorted(r["case"]["seed"] for r in values),
                        "selected_accuracy": stats([r["selected"]["accuracy"] for r in values]),
                        "pre_late_accuracy": stats([r["selected"]["pre_late_accuracy"] for r in values]),
                        "initial_scaled_accuracy": stats([r["baselines"]["standardized"]["accuracy"] for r in values]),
                        "raw_same_penalty_accuracy": stats([r["baselines"]["raw_same_penalty"]["accuracy"] for r in values]),
                        "raw_old_penalty_accuracy": stats([r["baselines"]["raw_old_penalty"]["accuracy"] for r in values])})
    main_rows = [r for r in evaluated if r["case"]["group"] == "main_factorial"]
    paired = []
    for row in main_rows:
        c = row["case"]
        if c["bank"] != "value_risk":
            continue
        others = [r for r in main_rows if all(r["case"][key] == c[key]
                  for key in ("width", "seed", "message", "connection")) and r["case"]["bank"] == "tanh"]
        if len(others) != 1:
            raise ValueError("Missing feature-control partner")
        other = others[0]
        paired.append({"width": c["width"], "seed": c["seed"], "message": c["message"],
                       "connection": c["connection"], "accuracy_difference_value_minus_tanh": row["selected"]["accuracy"] - other["selected"]["accuracy"],
                       "paired_updates_equal": row["updates"] == other["updates"]})
    connectivity = []
    for row in main_rows:
        c = row["case"]
        if c["connection"] != "learned":
            continue
        others = [r for r in main_rows if all(r["case"][key] == c[key]
                  for key in ("width", "seed", "message", "bank")) and r["case"]["connection"] == "fixed"]
        if len(others) == 1:
            connectivity.append({"width": c["width"], "seed": c["seed"], "message": c["message"], "bank": c["bank"],
                "accuracy_difference_learned_minus_fixed": row["selected"]["accuracy"] - others[0]["selected"]["accuracy"],
                "paired_updates_equal": row["updates"] == others[0]["updates"]})
    sample_groups = defaultdict(list)
    for row in evaluated:
        c = row["case"]
        if c["width"] in (16, 32) and c["message"] == "full" and c["connection"] == "learned":
            sample_groups[(c["width"], c["bank"], c["train_n"])].append(row)
    sample_efficiency = [{"width": k[0], "bank": k[1], "distinct_training_labels": k[2],
                         "seeds": sorted(r["case"]["seed"] for r in v),
                         "selected_accuracy": stats([r["selected"]["accuracy"] for r in v]),
                         "initial_scaled_accuracy": stats([r["baselines"]["standardized"]["accuracy"] for r in v])}
                        for k, v in sorted(sample_groups.items())]
    repair = [{"case": r["name"], "width": r["case"]["width"], "seed": r["case"]["seed"],
               "bank": r["case"]["bank"], "message": r["case"]["message"], "connection": r["case"]["connection"],
               "raw_same_penalty_accuracy": r["baselines"]["raw_same_penalty"]["accuracy"],
               "raw_old_penalty_accuracy": r["baselines"]["raw_old_penalty"]["accuracy"],
               "standardized_accuracy": r["baselines"]["standardized"]["accuracy"],
               "selected_accuracy": r["selected"]["accuracy"]} for r in main_rows]
    final = {"scope": "new synthetic held-out tasks; three initialization seeds, fixed data seed",
             "protocol_sha256": sha(protocol_path), "evaluation_sha256": sha(evaluation_path),
             "training_summary_sha256": sha(root / "TRAINING_SUMMARY.json"),
             "statuses": dict(Counter(r["status"] for r in rows.values())), "grouped_main_factorial": grouped,
             "quality_reached_rows": sum(r["test_quality_reached"] for r in evaluated),
             "quality_threshold_accuracy": protocol["test_quality_threshold_accuracy"],
             "feature_pairs": paired, "connectivity_pairs": connectivity, "sample_efficiency": sample_efficiency,
             "feature_pair_descriptive_difference": stats([r["accuracy_difference_value_minus_tanh"] for r in paired]),
             "connectivity_pair_descriptive_difference": stats([r["accuracy_difference_learned_minus_fixed"] for r in connectivity]),
             "scaling_repair_initial_descriptive_gain": stats([r["standardized_accuracy"] - r["raw_same_penalty_accuracy"] for r in repair]),
             "optimizer_selected_descriptive_gain": stats([r["selected_accuracy"] - r["standardized_accuracy"] for r in repair]),
             "max_probability_mass_error": max(r["physical_diagnostics"]["mass_error"] for r in evaluated),
             "max_signed_mark_excess": max(r["physical_diagnostics"]["mark_excess"] for r in evaluated),
             "test_total_wall_s": evaluation["total_wall_s"], "test_total_cpu_s": evaluation["total_cpu_s"],
             "inferential_limit": "descriptive paired results; cases sharing a held-out set are not independent replications",
             "no_real_cross_user_or_full_LLM_inversion_claim": True}
    dump(root / "READOUT_REPAIR_PAIRS.json", repair)
    dump(root / "FINAL_SUMMARY.json", final)
    print(json.dumps({"rows": len(rows), "statuses": final["statuses"],
                      "feature_difference": final["feature_pair_descriptive_difference"],
                      "scaling_gain": final["scaling_repair_initial_descriptive_gain"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    main(p.parse_args().root)
