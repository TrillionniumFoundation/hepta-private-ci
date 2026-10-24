"""Attach outcomes under a pre-execution whole-project selection; retain all attempts."""

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import time

from operational_cohort_plan import digest
from operational_region_evidence import capture, verify_pins
from prospective_action_dataset import observed_label
from prospective_action_execution import validate_case
from prospective_action_inputs import TASK, sha_file
from prospective_outcome_selection import (code_hashes, load_selection, read_json, validate_completed, write_json)


def capture_condition(root, groups, inputs_sha256, plan_sha256, summary_sha256, pins):
    """Authenticate every case, including original cases superseded for labels."""
    root = Path(root)
    plan = read_json(root/"execution-plan.json", pins, plan_sha256)
    summary = read_json(root/"summary.json", pins, summary_sha256)
    validate_completed(plan, summary, groups, inputs_sha256, plan_sha256)
    cases = {}
    for group, binding in groups.items():
        directory = root/(binding["project"]+"-"+str(binding["bug_id"]))
        result = read_json(directory/"result.json", pins, summary["case_results"][group])
        for name, record in result["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
                raise ValueError("case artifact escapes its recorded directory")
            path = str((directory/relative).absolute())
            if pins.setdefault(path, record["sha256"]) != record["sha256"]:
                raise ValueError("contradictory original case artifact pin")
        if (validate_case(directory, binding, plan_sha256) != result
                or result["group_id"] != group or result["project"] != binding["project"]
                or result["bug_id"] != binding["bug_id"] or result["split"] != binding["role"]
                or set(result["action_launch_counts"]) != {a["key"] for a in binding["actions"]}
                or result["physical_command_executions"] != sum(result["action_launch_counts"].values())
                or result["complete_command_observations"] != sum(len(pair) for pair in result["pairs"].values())):
            raise ValueError("case source/plan or actual execution counts differ")
        cases[group] = result
    for field in ("physical_command_executions", "complete_command_observations", "observer_call_attempts",
                  "observer_attempts_without_launch_receipt"):
        if summary[field] != sum(case[field] for case in cases.values()):
            raise ValueError("condition totals do not reproduce every actual case")
    return {"root": str(root.absolute()), "plan_sha256": plan_sha256, "summary_sha256": summary_sha256,
        "inputs_sha256": inputs_sha256, "plan": plan, "summary": summary, "cases": cases}


def reconcile(selection_plan, output, *, selection_plan_sha256, replacement_plan_sha256,
              replacement_summary_sha256, diagnostic_receipts=()):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    plan, inputs, projected, config, pins = load_selection(selection_plan, selection_plan_sha256)
    replacement = plan["replacement"]
    conditions = {
        "original": capture_condition(plan["original"]["root"], inputs["case_bindings"], plan["input_sha256"],
            plan["original"]["plan_sha256"], plan["original"]["summary_sha256"], pins),
        "replacement": capture_condition(replacement["execution_root"], projected["case_bindings"],
            replacement["projected_inputs_sha256"], replacement_plan_sha256, replacement_summary_sha256, pins)}
    new_plan = conditions["replacement"]["plan"]
    if (new_plan["runtime_config"] != config
            or new_plan["runtime_config_sha256"] != sha_file(Path(selection_plan).with_name("execution-runtime-config.json"))
            or new_plan["frozen_file_pins"].get(str(Path(selection_plan).absolute())) != selection_plan_sha256
            or any(new_plan[key] != value for key, value in plan["execution_policy"].items())
            or new_plan["source_roles"] != projected["project_roles"]):
        raise ValueError("replacement was not executed under the pre-frozen uniform selection policy")
    diagnostics = []
    for record in diagnostic_receipts:
        if set(record) != {"path", "sha256"}:
            raise ValueError("diagnostics supply receipt references only, never selected cases")
        path = Path(record["path"]).absolute()
        raw = capture(path, pins)
        if digest(raw) != record["sha256"]:
            raise ValueError("diagnostic receipt pin differs")
        diagnostics.append({"path": str(path), "sha256": record["sha256"], "bytes": len(raw),
            "use": "diagnostic_only_in_all_attempt_costs", "supplies_labels": False})
    if len({r["path"] for r in diagnostics}) != len(diagnostics):
        raise ValueError("duplicate diagnostic cost receipt")
    rows = {r["source_id"]: copy.deepcopy(r) for r in inputs["rows"]}
    registry, reasons, selected_counts, projects, case_bindings = [], Counter(), Counter(), {}, {}
    for group, binding in inputs["case_bindings"].items():
        name = plan["group_condition"][group]
        condition, result = conditions[name], conditions[name]["cases"][group]
        result_sha = condition["summary"]["case_results"][group]
        for key in ("physical_command_executions", "complete_command_observations", "observer_call_attempts",
                    "observer_attempts_without_launch_receipt"):
            selected_counts[key] += result[key]
        project = projects.setdefault(binding["project"], Counter())
        project["proposed_groups"] += 1
        actions = []
        case_bindings[group] = {"condition": name, "execution_root": condition["root"],
            "execution_plan_sha256": condition["plan_sha256"], "case_result_sha256": result_sha,
            "prepared_case_sha256": binding["sha256"]}
        for candidate in binding["actions"]:
            key, pair = candidate["key"], result["pairs"].get(candidate["key"], {})
            label, unknown = observed_label(pair)
            project["proposed_actions"] += 1
            project["source_available_actions"] += candidate["source_id"] is not None
            project["valid_outcome_actions"] += label is not None
            if label is not None: project["positive_actions" if label else "negative_actions"] += 1
            if unknown: reasons[unknown] += 1
            actions.append({**candidate, "label": label, "outcome_unavailable": unknown,
                "observed_outcomes": {role: value["outcome"] for role, value in pair.items()},
                "recorded_pair_wall_ns": sum(p["wall_ns"] for p in pair.values()),
                "physical_command_executions": result["action_launch_counts"][key],
                "complete_command_observations": len(pair),
                "pair_cost_complete": len(pair) == 2 and result["action_launch_counts"][key] == 2,
                "known_unreturned_observer_wall_ns": sum(error["partial_observation"]["wall_ns"]
                    for error in result["errors"] if error.get("action") == key and "partial_observation" in error),
                "source_condition": name, "case_result_sha256": result_sha,
                "execution_plan_sha256": condition["plan_sha256"]})
            if candidate["source_id"] is not None:
                row = rows[candidate["source_id"]]
                if row["labels"] != {TASK: None}:
                    raise ValueError("original source-only input already contains a label")
                row["labels"] = {TASK: label}
                row["outcome_provenance"] = {**case_bindings[group], "candidate_key": key,
                    "effective_selection_plan_sha256": selection_plan_sha256, "unavailable_reason": unknown}
        registry.append({"group_id": group, "repo": binding["project"], "split": binding["role"], "actions": actions})
    ordered = [rows[r["source_id"]] for r in inputs["rows"]]
    for before, after in zip(inputs["rows"], ordered, strict=True):
        compared = {key: value for key, value in after.items() if key != "outcome_provenance"}
        compared["labels"] = {TASK: None}
        if before != compared:
            raise ValueError("reconciliation changed a pre-observation predictor/source version")
    sources = {name: {"root": value["root"], "inputs_sha256": value["inputs_sha256"],
        "execution_plan_sha256": value["plan_sha256"], "summary_sha256": value["summary_sha256"],
        "complete_original_summary": value["summary"],
        "selected_groups": [group for group, selected in plan["group_condition"].items() if selected == name]}
        for name, value in conditions.items()}
    data = {"schema": "hepta.prospective-action-dataset.v1", "selected_tasks": [TASK], "rows": ordered,
        "proposal_registry": registry, "project_roles": inputs["project_roles"],
        "input_dataset_sha256": plan["input_sha256"],
        "input_manifest_sha256": pins[str(Path(plan["input_path"]).with_name("manifest.json"))],
        "governing_protocol_sha256": inputs["governing_protocol_sha256"],
        "effective_selection_plan_sha256": selection_plan_sha256, "source_condition_bindings": sources,
        "selected_case_execution_bindings": case_bindings, "additional_all_attempt_diagnostic_receipts": diagnostics,
        "execution_scope": "Mixture fixed by whole-project pre-execution selection; each case retains its actual execution-plan pin.",
        "source_code_sha256": plan["source_code_sha256"], "all_proposed_actions_retained": True,
        "post_outcome_candidate_selection": False, "no_model_scoring_performed": True, "authority": "SHADOW_ONLY / DENY_ALL"}
    verify_pins(pins)
    if code_hashes() != plan["source_code_sha256"]:
        raise ValueError("reconciliation implementation changed")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"dataset.json", data)
    verify_pins(pins)
    for name, condition in conditions.items():
        source_groups = inputs["case_bindings"] if name == "original" else projected["case_bindings"]
        for group, binding in source_groups.items():
            directory = Path(condition["root"])/(binding["project"]+"-"+str(binding["bug_id"]))
            if validate_case(directory, binding, condition["plan_sha256"]) != condition["cases"][group]:
                raise ValueError("case inventory changed before final reconciliation seal")
    if code_hashes() != plan["source_code_sha256"]:
        raise ValueError("reconciliation implementation changed before final seal")
    audit = {"schema": "hepta.prospective-reconciled-outcome-audit.v1", "dataset_sha256": sha_file(output/"dataset.json"),
        "input_dataset_sha256": plan["input_sha256"], "effective_selection_plan_sha256": selection_plan_sha256,
        "proposed_groups": len(registry), "proposed_actions": sum(len(g["actions"]) for g in registry),
        "source_available_rows": len(ordered), "selected_execution_counts": dict(selected_counts),
        "both_complete_condition_counts": {key: sum(c["summary"][key] for c in conditions.values()) for key in selected_counts},
        "all_attempt_source_conditions": sources, "additional_diagnostic_cost_receipts": diagnostics,
        "cost_count_scope": "Both complete execution conditions include superseded original Luigi work; diagnostic receipt counts are additional, not silently included in these totals.",
        "unavailable_outcome_reasons": dict(reasons), "by_project": {p: dict(v) for p, v in projects.items()},
        "all_predictor_fields_unchanged": True, "observed_unknowns_relabelled_negative": False,
        "wall_ns": time.perf_counter_ns()-started, "parent_cpu_ns": time.process_time_ns()-cpu,
        "cost_scope": "Inclusive authentication/reconciliation/dataset write; excludes audit/manifest self-writes. Prior execution costs are referenced, not charged again.",
        "new_test_commands": 0, "new_encoder_calls": 0, "new_private_updates": 0}
    write_json(output/"audit.json", audit)
    write_json(output/"manifest.json", {"schema": "hepta.prospective-action-dataset-seal.v1", "files": {
        p.name: {"sha256": sha_file(p), "bytes": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()}})
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection-plan", "selection-plan-sha256", "replacement-plan-sha256", "replacement-summary-sha256", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--diagnostic-receipts-json")
    args = vars(parser.parse_args())
    extra = args.pop("diagnostic_receipts_json")
    args["diagnostic_receipts"] = json.loads(Path(extra).read_bytes()) if extra else ()
    reconcile(**args)


if __name__ == "__main__":
    main()
