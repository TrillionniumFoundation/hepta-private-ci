"""Select one complete execution condition per repository before model scoring.

Compatibility replay replaces every case in affected repositories, including
prior successes and newly unavailable results. No best-of-attempt label choice.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

from operational_cohort_plan import canonical, digest
from operational_dataset import TASKS, availability, rows_for_case, validate_splits
from operational_execute import sha_file, validate_result


def selected_conditions(bugs, compatibility_plan, original_results, compatibility_results):
    expected = {bug["group_id"] for bug in bugs}
    affected = set(compatibility_plan["affected_projects"])
    replayed = {bug["group_id"] for bug in bugs if bug["project"] in affected}
    if (set(original_results) != expected or set(compatibility_results) != replayed
            or set(compatibility_plan["groups"]) != replayed
            or compatibility_plan["eligibility_gate_changed"] is not False):
        raise ValueError("full fixed cohort and whole affected repositories must be present under the unchanged gate")
    return {bug["group_id"]: ("compatibility" if bug["project"] in affected else "original") for bug in bugs}


def reconcile(protocol_path, prepared, original, compatibility, output):
    protocol = json.loads(Path(protocol_path).read_bytes())
    prepared, original, compatibility, output = map(Path, (prepared, original, compatibility, output))
    roots = {"original": original, "compatibility": compatibility}
    summaries = {name: json.loads((root / "summary.json").read_bytes()) for name, root in roots.items()}
    plans = {name: json.loads((root / "execution-plan.json").read_bytes()) for name, root in roots.items()}
    choices = selected_conditions(protocol["bugs"], plans["compatibility"],
                                  summaries["original"]["case_results"], summaries["compatibility"]["case_results"])
    if (plans["compatibility"]["original_execution_summary_sha256"] != sha_file(original / "summary.json")
            or plans["compatibility"]["protocol_sha256"] != sha_file(protocol_path)
            or plans["original"]["protocol_sha256"] != sha_file(protocol_path)):
        raise ValueError("compatibility condition is not bound to this original protocol and attempt")
    for name, root in roots.items():
        if summaries[name]["execution_plan_sha256"] != sha_file(root / "execution-plan.json"):
            raise ValueError("completed execution plan changed")
    manifest = json.loads((prepared / "manifest.json").read_bytes())
    cases, rows, registry, unavailable_counts, selected_result_hashes = [], [], [], Counter(), {}
    for bug in protocol["bugs"]:
        group, stem = bug["group_id"], bug["project"] + "-" + str(bug["bug_id"])
        path = prepared / (stem + ".json")
        if sha_file(path) != manifest["cases"][path.name]["sha256"]:
            raise ValueError("pre-outcome predictor/action context changed")
        case = json.loads(path.read_bytes())
        observations = {}
        for name, root in roots.items():
            if group not in summaries[name]["case_results"]:
                continue
            result = validate_result(root / stem, sha_file(path), summaries[name]["execution_plan_sha256"])
            if sha_file(root / stem / "result.json") != summaries[name]["case_results"][group]:
                raise ValueError("sealed original or compatibility result changed")
            observations[name] = result
        condition = choices[group]
        result = observations[condition]
        applicable, unavailable = rows_for_case(case, result, protocol["context_policy"]["max_input_utf8_bytes"])
        result_sha = summaries[condition]["case_results"][group]
        for row in applicable:
            row["provenance"]["execution_condition"] = condition
            row["provenance"]["execution_case_result_sha256"] = result_sha
        selected_result_hashes[group] = {"condition": condition, "sha256": result_sha}
        cases.append(case)
        rows.extend(applicable)
        unavailable_counts.update(unavailable.values())
        registry.append({"group_id": group, "repo": bug["project"], "split": bug["split"],
            "selected_condition": condition, "selected_result_sha256": result_sha,
            "unavailable_tasks": unavailable, "applicable_rows": len(applicable),
            "attempts": {name: {"regression_observed": value["selected_primary"] is not None,
                "informative_comparator_observed": value["selected_control"] is not None,
                "harness_error": value["harness_error"], "physical_commands": value["physical_command_executions"]}
                for name, value in observations.items()}})
    rows.sort(key=lambda row: row["source_id"])
    guards = validate_splits(rows, cases)
    selection = {"schema": "hepta.operational-execution-selection.v1", "selection": "Whole repository condition replacement, never best-of-attempt results",
        "protocol_sha256": sha_file(protocol_path), "condition_summaries": {name: sha_file(root / "summary.json") for name, root in roots.items()},
        "selected_results": selected_result_hashes, "model_quality_seen": False}
    dataset = {"schema": "hepta.operational-cell-dataset.v1", "selected_tasks": list(TASKS),
        "task_definitions": protocol["task_definitions"], "rows": rows, "protocol_sha256": sha_file(protocol_path),
        "prepared_manifest_sha256": sha_file(prepared / "manifest.json"), "execution_summary_sha256": digest(canonical(selection)),
        "source_code_sha256": {name: sha_file(Path(__file__).with_name(name)) for name in
                               ("operational_reconciled_dataset.py", "operational_dataset.py")},
        "split_guards": guards, "task_applicability": "Missing labels keys mean not_applicable; no unknown results become negative labels.",
        "scientific_status": "New heldout operational decisions on pinned natural bugs. Compatibility fixes follow observed infrastructure failures, uniformly across affected repositories; no model quality observed during selection.",
        "pretraining_contamination_controlled": False,
        "family_scope": "Two distinct decision problems on shared natural bug groups; not two independent source populations."}
    audit = {"schema": "hepta.operational-cell-data-audit.v1", "groups_attempted": len(protocol["bugs"]),
        "rows": len(rows), "distinct_operational_families": 2, "availability": availability(rows), "split_guards": guards,
        "unavailable_reasons": dict(unavailable_counts), "execution_registry": registry,
        "original_physical_commands": summaries["original"]["physical_commands"],
        "compatibility_physical_commands": summaries["compatibility"]["physical_commands"],
        "compatibility_build_commands": summaries["compatibility"]["package_build_commands"],
        "labels_are_real_observed_command_outcomes": True, "model_quality_scored": False,
        "original_results_preserved": True, "eligibility_gate_changed": False}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("dataset.json", dataset), ("audit.json", audit), ("execution-selection.json", selection)):
        (output / name).write_bytes(canonical(value))
    (output / "manifest.json").write_bytes(canonical({p.name: {"bytes": p.stat().st_size, "sha256": sha_file(p)} for p in output.iterdir()}))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "prepared", "original", "compatibility", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    audit = reconcile(args.protocol, args.prepared, args.original, args.compatibility, args.output)
    print(json.dumps({k: v for k, v in audit.items() if k != "execution_registry"}, sort_keys=True))


if __name__ == "__main__":
    main()
