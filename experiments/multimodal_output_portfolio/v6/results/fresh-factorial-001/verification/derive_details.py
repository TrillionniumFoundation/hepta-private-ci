"""Recompute registered descriptive tables and aggregate recorded nested costs."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


ARMS = ("b0g0", "b0g1", "b1g0", "b1g1")
SEEDS = (17, 29, 43)


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")


def main(packet, costs, output):
    packet, out = Path(packet), Path(output)
    owner = packet / "unpacked" / "owner"
    summary = read(owner / "evaluation/summary.json")
    scored = read(owner / "evaluation/scored-rows.json")["rows"]
    rows = read(owner / "inference/rows.json")["rows"]
    lookup = {(x["split"], x["seed"], x["arm"], x["index"]): x for x in scored}
    if len(lookup) != len(scored) or len(scored) != 1080:
        raise ValueError("scored row census differs")
    differences = []
    for split, start, count in (("future", 120, 60), ("retention", 60, 30)):
        for arm in ARMS:
            by_source = [[lookup[split, seed, arm, index]["metrics"]["joint_loss"] for seed in SEEDS]
                         for index in range(start, start + count)]
            fact_source = [[lookup[split, seed, arm, index]["metrics"]["joint_fact_correct"] for seed in SEEDS]
                           for index in range(start, start + count)]
            means = np.array(by_source, dtype=np.float64).mean(axis=1)
            got = {"case_count": count, "joint_loss": float(means.mean()),
                   "joint_fact_correct": float(np.array(fact_source, dtype=np.float64).mean(axis=1).mean()),
                   "joint_loss_CVaR90": float(np.sort(means)[-int(count * .1):].mean())}
            expected = summary["secondary"][split][arm]
            if expected["interval"] is not None:
                raise ValueError("unexpected secondary confidence interval")
            differences.extend(abs(got[k] - expected[k]) for k in got)
            for seed in SEEDS:
                values = [lookup[split, seed, arm, index]["metrics"] for index in range(start, start + count)]
                losses = np.array([x["joint_loss"] for x in values])
                per = {"joint_loss": float(losses.mean()),
                       "joint_fact_correct": float(np.mean([x["joint_fact_correct"] for x in values])),
                       "joint_loss_CVaR90": float(np.sort(losses)[-int(count * .1):].mean())}
                expected_per = summary["per_seed"][f"{split}-seed{seed}"]["arms"][arm]
                differences.extend(abs(per[k] - expected_per[k]) for k in per)
    if max(differences) > 1e-15:
        raise ValueError("descriptive summaries differ from scored rows")
    breakdown = read(Path(costs))
    cost_rows = []

    def add(level, stage, values, source, prefix, group, scope):
        for field, value in values.items():
            if type(value) not in (int, float):
                continue
            unit = "ns" if field.endswith("_ns") or "_ns_" in field else "s" if field.endswith("seconds") else "bytes" if field.endswith("bytes") else "count"
            cost_rows.append({"level": level, "stage_or_fit": stage, "field": field, "raw_value": value,
                "raw_unit": unit, "seconds_if_time": value / 1e9 if unit == "ns" else value if unit == "s" else "",
                "additive_group": group if unit in ("ns", "s") else "not_additive",
                "scope": scope, "original_file": source, "original_field": prefix + field})

    add("outer", "harness", breakdown["outer_harness"], "owner/harness-summary.json", "", "headline_distinct_quantities", "includes all stages; child CPU excludes harness CPU; memory not additive")
    for row in breakdown["outer_stages"]:
        add("process", row["stage"], row, f"owner/{row['stage']}-process.json", "", "six_stage_processes", "child import/execution/exit; do not add inner timers; cumulative RSS may refer to earlier stage")
    stage_files = {"prepare": "data/data-receipt.json", "bootstrap": "bootstrap/bootstrap.json", "gates": "training/training.json",
                   "inference": "inference/run.json", "replay": "replay/run.json", "evaluate": "evaluation/summary.json"}
    for stage, values in breakdown["inner_stage_costs"].items():
        add("inner_stage", stage, values, "owner/" + stage_files[stage], "cost.", "inner_stage_subsets", "nested inside outer process; excludes some final sealing/writes")
    for name, row in breakdown["observer_fits"].items():
        add("observer", name, row["cost"], f"owner/bootstrap/{name}-observer.json", "cost.", "two_observer_wrapper_fits", "nested inside bootstrap; fit/calibration before checkpoint save/reload")
    for row in breakdown["base_fits"]:
        name = f"seed-{row['seed']}-{row['profile']}"
        add("base_profile", name, {"elapsed_seconds": row["elapsed_seconds"]}, f"owner/bootstrap/{name}-training.json", "", "six_base_profile_timers", "nested inside paired base timer")
    for seed, values in breakdown["base_paired_costs_once_per_seed"].items():
        add("base_pair", "seed" + seed, values, f"owner/bootstrap/seed-{seed}-supervised-training.json", "paired_execution_cost.", "three_base_pairs_once_each", "same timer repeated in paired report; count exactly once per seed")
    for row in breakdown["gate_fits"]:
        name = f"seed{row['seed']}-{row['arm']}"
        source = f"owner/training/{name}-training.json"
        add("gate_fit", name, row["factorial_cost"], source, "factorial_cost.", "twelve_gate_wrapper_fits", "includes separately executed candidate enumeration; nested inside gate stage")
        add("gate_detail", name, row["costs"], source, "costs.", "gate_detail_nested_not_joint_sum", "enumeration/optimization/total are nested scopes, not additive to wrapper")
    for stage in ("inference", "replay"):
        rr = read(owner / stage / "rows.json")["rows"]
        values = {"wall_ns": sum(x["cost"]["wall_ns"] for x in rr), "cpu_ns": sum(x["cost"]["cpu_ns"] for x in rr)}
        add("row_aggregate", stage, values, f"owner/{stage}/rows.json", "sum(rows[].cost.)", stage + "_rows", "includes output writes/reads and integrity checks; not pure model latency")
    scoring = {"wall_ns": sum(x["evaluation_cost"]["wall_ns"] for x in scored),
               "cpu_ns": sum(x["evaluation_cost"]["cpu_ns"] for x in scored)}
    add("row_aggregate", "evaluation", scoring, "owner/evaluation/scored-rows.json", "sum(rows[].evaluation_cost.)", "scoring_rows", "output reads, frozen Audit B and arithmetic; nested inside evaluation")
    out.mkdir(parents=True, exist_ok=False)
    with (out / "costs.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(cost_rows[0]))
        writer.writeheader()
        writer.writerows(cost_rows)
    inputs = {str(path.relative_to(packet / "unpacked")): {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
              for path in (owner / "evaluation/summary.json", owner / "evaluation/scored-rows.json", owner / "inference/rows.json")}
    result = {"schema": "hepta.ndu-fresh.descriptive-and-cost-review.v1", "status": "passed", "input_identities": inputs,
        "secondary_cells_verified": 8, "per_seed_arm_summaries_verified": 24,
        "maximum_descriptive_difference": max(differences), "new_intervals_or_comparisons": False,
        "fixed_seed_average_CVaR_tail_counts": {"future": 6, "retention": 3},
        "scoring_row_costs_sum": scoring, "cost_table_rows": len(cost_rows),
        "scope": "existing registered descriptive summaries and measured timer fields only; no target/OCR/model rerun",
        "new_model_executed": False, "final_targets_opened": False}
    write(out / "descriptive-review.json", result)
    print(json.dumps({"status": "passed", "maximum_descriptive_difference": max(differences), "cost_rows": len(cost_rows), "scoring_row_costs": scoring}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--costs", required=True)
    parser.add_argument("--output", required=True)
    main(**vars(parser.parse_args()))
