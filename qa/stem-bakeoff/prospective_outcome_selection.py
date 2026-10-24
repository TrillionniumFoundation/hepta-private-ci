"""Predeclare an entire Luigi replacement before any repaired command can start."""

import argparse
import copy
import json
from pathlib import Path
import time

from operational_cohort_plan import canonical, digest
from operational_region_evidence import capture, verify_pins
from prospective_action_inputs import sha_file
from prospective_action_run import verify_inventory


PROJECT = "luigi"
CODE = ("prospective_outcome_selection.py", "reconcile_prospective_outcomes.py",
        "prospective_action_dataset.py", "prospective_action_execution.py", "prospective_action_inputs.py",
        "prospective_action_run.py", "operational_cohort_plan.py", "operational_region_evidence.py",
        "long_document_sources.py", "operational_source_regions.py")


def code_hashes():
    return {name: sha_file(Path(__file__).with_name(name)) for name in CODE}


def read_json(path, pins, expected=None):
    raw = capture(Path(path).absolute(), pins)
    if expected is not None and digest(raw) != expected:
        raise ValueError("independent selection input pin differs")
    return json.loads(raw)


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def validate_projection(original, projected):
    groups = {key: value for key, value in original["case_bindings"].items() if value["project"] == PROJECT}
    if (not groups or original["project_roles"].get(PROJECT) != "tuning"
            or projected["case_bindings"] != groups or projected["project_roles"] != {PROJECT: "tuning"}
            or projected["rows"] != [r for r in original["rows"] if r["repo"] == PROJECT]
            or projected["proposal_registry"] != [g for g in original["proposal_registry"] if g["repo"] == PROJECT]
            or projected["selected_tasks"] != original["selected_tasks"]
            or projected["governing_protocol_sha256"] != original["governing_protocol_sha256"]
            or original.get("all_labels_unobserved") is not True or projected.get("all_labels_unobserved") is not True
            or any(v is not None for r in projected["rows"] for v in r["labels"].values())):
        raise ValueError("replacement must contain the entire unchanged Luigi project, never a case-level subset")
    return groups


def validate_completed(plan, summary, groups, inputs_sha256, plan_sha256):
    slots = 2*sum(len(binding["actions"]) for binding in groups.values())
    if (plan["inputs_sha256"] != inputs_sha256 or summary["execution_plan_sha256"] != plan_sha256
            or set(summary["case_results"]) != set(groups) or summary["proposed_groups"] != len(groups)
            or summary["completed_groups"] != len(groups) or summary["proposed_physical_command_slots"] != slots
            or summary["all_frozen_files_unchanged"] is not True or summary["all_runtime_files_unchanged"] is not True
            or summary["outcome_dependent_stopping"] is not False or summary["no_model_fit_or_score"] is not True
            or plan["all_frozen_actions_executed"] is not True or plan["outcome_dependent_stopping"] is not False
            or plan["same_test_tree_on_both_implementations"] is not True):
        raise ValueError("complete unchanged all-candidate execution condition required")


def runtime_inventory(config, groups, original_plan, pins):
    profiles = set(config["group_profiles"].values())
    if (set(config["group_profiles"]) != set(groups) or len(profiles) != 1 or set(config["profiles"]) != profiles
            or config["source_stores"] != {PROJECT: original_plan["runtime_config"]["source_stores"][PROJECT]}):
        raise ValueError("one uniform runtime and unchanged source store for the entire project required")
    replacement_profile = config["profiles"][next(iter(profiles))]
    for group in groups:
        before = original_plan["runtime_config"]
        original_profile = before["profiles"][before["group_profiles"][group]]
        if any(replacement_profile.get(key, [] if key == "source_paths" else None) !=
               original_profile.get(key, [] if key == "source_paths" else None)
               for key in ("plain_pytest", "source_paths", "python_sha256")):
            raise ValueError("dependency repair changed the runner adapter, source path or interpreter bytes")
    for path, expected in config["file_pins"].items():
        capture(path, pins)
        if pins[str(Path(path))] != expected:
            raise ValueError("configured runtime/source prerequisite differs")
    result = {}
    for name, record in config["inventories"].items():
        capture(record["manifest"], pins)
        result[name] = verify_inventory(record["root"], record["manifest"], record["sha256"])
    for profile in config["profiles"].values():
        raw = capture(Path(profile["python"]).resolve(), pins)
        if digest(raw) != profile["python_sha256"] or not any(
                Path(profile["python"]).is_relative_to(Path(v["root"])) for v in config["inventories"].values()):
            raise ValueError("replacement interpreter is outside its pinned inventory")
    return result


def derived_config(base, selection_path, selection_sha256):
    result = copy.deepcopy(base)
    name = str(Path(selection_path).absolute())
    if name in result["file_pins"]:
        raise ValueError("base runtime already contains the future selection pin")
    result["file_pins"][name] = selection_sha256
    return result


def freeze_selection(original_inputs, original_executions, projected_inputs, runtime_config, replacement_output,
                     output, *, inputs_sha256, original_plan_sha256, original_summary_sha256,
                     projected_inputs_sha256, runtime_config_sha256):
    """Read source inputs and condition headers, never per-case outcomes, to choose all Luigi."""
    started, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), {}
    implementation = code_hashes()
    original_inputs, original_executions, projected_inputs, runtime_config, replacement_output, output = (
        Path(p).absolute() for p in (original_inputs, original_executions, projected_inputs, runtime_config, replacement_output, output))
    if replacement_output.exists() or output.exists():
        raise ValueError("selection must precede any replacement output and use a new directory")
    original = read_json(original_inputs, pins, inputs_sha256)
    projected = read_json(projected_inputs, pins, projected_inputs_sha256)
    for path, expected in ((original_inputs, inputs_sha256), (projected_inputs, projected_inputs_sha256)):
        if read_json(path.with_name("manifest.json"), pins)["inputs_sha256"] != expected:
            raise ValueError("source-only input manifest differs")
    groups = validate_projection(original, projected)
    old_plan = read_json(original_executions/"execution-plan.json", pins, original_plan_sha256)
    summary = read_json(original_executions/"summary.json", pins, original_summary_sha256)
    validate_completed(old_plan, summary, original["case_bindings"], inputs_sha256, original_plan_sha256)
    config = read_json(runtime_config, pins, runtime_config_sha256)
    inventories = runtime_inventory(config, groups, old_plan, pins)
    for binding in original["case_bindings"].values():
        read_json(binding["path"], pins, binding["sha256"])
    for name, expected in old_plan["code_sha256"].items():
        if sha_file(Path(__file__).with_name(name)) != expected:
            raise ValueError("original execution implementation changed before uniform rerun")
    plan = {"schema": "hepta.prospective-whole-project-selection.v1", "project": PROJECT,
        "selection_rule": "Use the replacement for every Luigi group regardless of any outcome; use original for all other groups.",
        "input_path": str(original_inputs), "input_sha256": inputs_sha256,
        "original": {"root": str(original_executions), "plan_sha256": original_plan_sha256, "summary_sha256": original_summary_sha256},
        "replacement": {"projected_inputs": str(projected_inputs), "projected_inputs_sha256": projected_inputs_sha256,
            "base_runtime_config": str(runtime_config), "base_runtime_config_sha256": runtime_config_sha256,
            "execution_root": str(replacement_output), "groups": sorted(groups),
            "proposed_actions": sum(len(b["actions"]) for b in groups.values()), "inventory_verified": inventories},
        "execution_policy": {key: old_plan[key] for key in ("workers", "limits", "code_sha256", "same_test_tree_on_both_implementations")},
        "group_condition": {group: "replacement" if group in groups else "original" for group in sorted(original["case_bindings"])},
        "runtime_binding": "Base config plus exactly this selection plan's file pin; existing runner verifies it before commands.",
        "case_outcomes_or_labels_used_to_select_groups": False, "case_level_replacement_allowed": False,
        "all_attempts_retained": True, "diagnostics_may_supply_labels": False,
        "source_code_sha256": implementation, "input_file_pins": pins, "authority": "SHADOW_ONLY / DENY_ALL"}
    verify_pins(pins)
    if code_hashes() != implementation or replacement_output.exists():
        raise ValueError("selection inputs/code changed or replacement started before freeze")
    output.mkdir(parents=True)
    write_json(output/"plan.json", plan)
    plan_sha = sha_file(output/"plan.json")
    write_json(output/"execution-runtime-config.json", derived_config(config, output/"plan.json", plan_sha))
    verify_pins(pins)
    if code_hashes() != implementation or replacement_output.exists():
        raise ValueError("selection changed before publication or execution started early")
    receipt = {"selection_plan_sha256": plan_sha,
        "execution_runtime_config_sha256": sha_file(output/"execution-runtime-config.json"),
        "wall_ns": time.perf_counter_ns()-started, "parent_cpu_ns": time.process_time_ns()-cpu,
        "scope": "Source/condition-header/runtime authentication, complete-project selection and config writes; excludes receipt self-write.",
        "test_commands": 0, "encoder_calls": 0, "private_updates": 0, "per_case_outcomes_read": False}
    write_json(output/"receipt.json", receipt)
    return plan


def load_selection(path, expected_sha256):
    pins = {}
    path = Path(path).absolute()
    plan = read_json(path, pins, expected_sha256)
    if (plan["source_code_sha256"] != code_hashes() or plan["project"] != PROJECT
            or plan["case_level_replacement_allowed"] or plan["diagnostics_may_supply_labels"]):
        raise ValueError("whole-project selection implementation or policy differs")
    for source, expected in plan["input_file_pins"].items():
        read = capture(source, pins)
        if digest(read) != expected:
            raise ValueError("selection prerequisite changed")
    original = read_json(plan["input_path"], pins, plan["input_sha256"])
    projected = read_json(plan["replacement"]["projected_inputs"], pins, plan["replacement"]["projected_inputs_sha256"])
    groups = validate_projection(original, projected)
    if (plan["replacement"]["groups"] != sorted(groups)
            or plan["group_condition"] != {group: "replacement" if group in groups else "original" for group in sorted(original["case_bindings"])}):
        raise ValueError("partial-project replacement or changed selected source mapping")
    base = read_json(plan["replacement"]["base_runtime_config"], pins, plan["replacement"]["base_runtime_config_sha256"])
    config = derived_config(base, path, expected_sha256)
    if read_json(path.with_name("execution-runtime-config.json"), pins) != config:
        raise ValueError("replacement launch config changed beyond the selection prerequisite")
    verify_pins(pins)
    return plan, original, projected, config, pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-inputs", "original-executions", "projected-inputs", "runtime-config", "replacement-output", "output",
                 "inputs-sha256", "original-plan-sha256", "original-summary-sha256", "projected-inputs-sha256", "runtime-config-sha256"):
        parser.add_argument("--"+name, required=True)
    freeze_selection(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
