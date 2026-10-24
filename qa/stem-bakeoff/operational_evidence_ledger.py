"""Reconcile real operational label pools and every preserved execution attempt.

The label pool is not the number of training examples charged to a head. Two
implementation outcomes from one bug remain one independent source group.
Measured command durations are summed work, not concurrent elapsed runtime.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

from operational_cohort_plan import canonical
from operational_execute import sha_file, validate_result


CONDITIONS = (("original", "executions"), ("compatibility_v2", "compatibility-executions"),
              ("compatibility_v3", "compatibility-v3-executions"))


def label_pools(dataset):
    result = {}
    for task in dataset["selected_tasks"]:
        partitions = {}
        for split in ("train", "calibration", "holdout"):
            rows = [r for r in dataset["rows"] if r["split"] == split and task in r["labels"]]
            if any(type(r["labels"][task]) is not int or r["labels"][task] not in (0, 1) for r in rows):
                raise ValueError("applicable operational labels must be exact binary integers")
            groups = {r["group_id"] for r in rows}
            classes = [{r["group_id"] for r in rows if r["labels"][task] == value} for value in (0, 1)]
            partitions[split] = {"applicable_labelled_rows": len(rows), "independent_source_groups": len(groups),
                "class_rows": [sum(r["labels"][task] == value for r in rows) for value in (0, 1)],
                "class_source_groups": [len(c) for c in classes],
                "groups_with_both_implementation_labels": len(classes[0] & classes[1]),
                "normalized_predictor_count": len({" ".join(r["text"].split()) for r in rows}),
                "predictor_utf8_bytes": sum(len(r["text"].encode()) for r in rows),
                "repositories": sorted({r["repo"] for r in rows})}
        result[task] = {"family_id": dataset["task_definitions"][task]["family_id"],
                        "partitions": partitions}
    return result


def execution_cost(records):
    outcomes, count, wall, builds, build_wall, failed_builds = Counter(), 0, 0, 0, 0, 0
    for result in records:
        declared = result["physical_command_executions"]
        commands = [command for pair in result["pairs"].values() for command in pair.values()]
        if (type(declared) is not int or declared != len(commands) or result["harness_error"] is not None):
            raise ValueError("incomplete or inexact command counters cannot become measured costs")
        for command in commands:
            duration = command["wall_ns"]
            if type(duration) is not int or duration < 0:
                raise ValueError("actual nonnegative command duration required")
            count += 1
            wall += duration
            outcomes[command["outcome"]] += 1
            build = command.get("compatibility", {}).get("build")
            if build is not None:
                if type(build["wall_ns"]) is not int or build["wall_ns"] < 0:
                    raise ValueError("actual nonnegative build duration required")
                builds += 1
                build_wall += build["wall_ns"]
                failed_builds += int(build["returncode"] != 0)
    return {"physical_test_commands": count, "summed_observed_test_wall_ns": wall,
        "test_command_outcomes": dict(sorted(outcomes.items())), "physical_package_build_commands": builds,
        "summed_observed_build_wall_ns": build_wall, "failed_package_build_commands": failed_builds,
        "concurrent_elapsed_wall_ns": None, "child_cpu_ns": None, "child_peak_rss_bytes": None,
        "unmeasured_cost_policy": "No CPU, energy, peak memory or concurrent elapsed values inferred from wall time or limits."}


def build_ledger(root, output):
    root, output = Path(root), Path(output)
    protocol = json.loads((root / "protocol.json").read_bytes())
    prepared = json.loads((root / "prepared/manifest.json").read_bytes())
    dataset_dir = root / "dataset-final-v3"
    manifest = json.loads((dataset_dir / "manifest.json").read_bytes())
    for name, expected in manifest.items():
        path = dataset_dir / name
        if path.stat().st_size != expected["bytes"] or sha_file(path) != expected["sha256"]:
            raise ValueError("definitive dataset manifest changed")
    dataset = json.loads((dataset_dir / "dataset.json").read_bytes())
    if dataset["protocol_sha256"] != sha_file(root / "protocol.json"):
        raise ValueError("dataset is not bound to the frozen source/split protocol")
    conditions, all_records, bindings = {}, [], {}
    for name, directory in CONDITIONS:
        base = root / directory
        summary = json.loads((base / "summary.json").read_bytes())
        plan = json.loads((base / "execution-plan.json").read_bytes())
        plan_sha = sha_file(base / "execution-plan.json")
        if summary["execution_plan_sha256"] != plan_sha or plan["protocol_sha256"] != dataset["protocol_sha256"]:
            raise ValueError("execution attempt changed its frozen protocol")
        records = []
        for group, expected in sorted(summary["case_results"].items()):
            _, project, number = group.split("/")
            stem = project + "-" + number
            source = root / "prepared" / (stem + ".json")
            source_sha = sha_file(source)
            if source_sha != prepared["cases"][source.name]["sha256"]:
                raise ValueError("pre-outcome source/action preparation changed")
            record = validate_result(base / stem, source_sha, plan_sha)
            if sha_file(base / stem / "result.json") != expected:
                raise ValueError("completed case result changed")
            records.append(record)
        cost = execution_cost(records)
        if len(records) != summary["groups"] or cost["physical_test_commands"] != summary["physical_commands"]:
            raise ValueError("execution summary does not reproduce actual sealed commands")
        conditions[name] = {"source": str(base), "groups_replayed": len(records), **cost,
            "summary_sha256": sha_file(base / "summary.json"), "execution_plan_sha256": plan_sha,
            "all_case_inventories_verified": True}
        all_records.extend(records)
        bindings[str(base / "summary.json")] = sha_file(base / "summary.json")
    pools = label_pools(dataset)
    costs = execution_cost(all_records)
    for relative in ("protocol.json", "prepared/manifest.json", "dataset-final-v3/dataset.json",
                     "dataset-final-v3/audit.json", "dataset-final-v3/execution-selection.json",
                     "infrastructure-closure-v3.json"):
        bindings[str(root / relative)] = sha_file(root / relative)
    report = {"schema": "hepta.operational-label-and-execution-ledger.v1", "label_pools": pools,
        "natural_bug_groups_attempted": len(protocol["bugs"]),
        "natural_bug_groups_with_applicable_labels": len({r["group_id"] for r in dataset["rows"]}),
        "applicable_rows": len(dataset["rows"]), "distinct_decision_families": len(set(v["family_id"] for v in pools.values())),
        "source_population_scope": "The two decision families share natural bug groups; not independent source populations.",
        "training_budget_unit": "One applicable row from a distinct bug group and normalized predictor per task training draw.",
        "label_pool_is_training_budget": False, "unknown_outcomes_are_negative_labels": False,
        "conditions": conditions, "all_attempt_costs": costs,
        "cost_scope": "Source/test-execution acquisition only; encoder, head-training and serving ledgers remain separate measured stages.",
        "runtime_limits_are_not_measured_usage": protocol["execution_policy"],
        "bindings": bindings, "ledger_source_sha256": sha_file(__file__)}
    if any(sha_file(path) != expected for path, expected in bindings.items()):
        raise ValueError("evidence inputs changed during reconciliation")
    with output.open("xb") as stream:
        stream.write(canonical(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_ledger(args.root, args.output)
    print(json.dumps({"rows": result["applicable_rows"], "groups": result["natural_bug_groups_with_applicable_labels"],
                      "all_attempt_costs": result["all_attempt_costs"]}, sort_keys=True))
