"""Seal one explicit successful Luigi build attempt, preserving failed attempts."""

import argparse
import json
from pathlib import Path
import time

from build_prospective_runtimes import verify_pins
from prepare_luigi_dependency_repair import ADDITIONS, PROFILE, captured, exact_repair_lock, write
from prospective_action_run import verify_inventory
from prospective_runtime_plan import sha


def merge_pins(*mappings):
    result = {}
    for mapping in mappings:
        for path, value in mapping.items():
            if result.setdefault(path, value) != value:
                raise ValueError("conflicting independently captured pin: " + path)
    return result


def finalize(output, runtime_directory, build_plan):
    started, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), {}
    output, runtime = Path(output).resolve(), Path(runtime_directory).resolve()
    if not runtime.is_relative_to(output) or runtime == output:
        raise ValueError("explicit new runtime attempt inside the repair root required")
    plan_path = Path(build_plan).resolve()
    if not plan_path.is_relative_to(output):
        raise ValueError("frozen construction plan must belong to this repair root")
    plan = json.loads(captured(plan_path, pins))
    repair = plan["repair"]
    captured(Path(__file__), pins)
    verify_pins(plan["file_pins"])
    built_path = runtime/"runtime-config.json"
    built = json.loads(captured(built_path, pins))
    if not built["all_profiles_completed"] or built["failures"] or set(built["profiles"]) != {PROFILE}:
        raise ValueError("complete new immutable runtime required before finalizing")
    verify_pins(built["file_pins"])
    receipts = runtime/"receipts"/PROFILE
    complete = json.loads(captured(receipts/"complete.json", pins))
    if complete["plan_sha256"] != sha(plan_path) or built["group_profiles"] != plan["group_profiles"]:
        raise ValueError("runtime belongs to a different frozen build plan")
    original = captured(repair["original_lock_path"], pins, repair["original_lock_sha256"]).decode()
    installed = captured(receipts/"resolved-lock.txt", pins, complete["resolved_lock_sha256"]).decode()
    expected = exact_repair_lock(original, installed)
    for relative, expected_sha in (("inputs/inputs.json", repair["projected_inputs_sha256"]),
                                  ("inputs/manifest.json", repair["projected_manifest_sha256"])):
        captured(output/relative, pins, expected_sha)
    inventories = {**built["inventories"], "shared-python-base": repair["shared_base_inventory"]}
    checks = {name: verify_inventory(r["root"], r["manifest"], r["sha256"]) for name, r in inventories.items()}
    old = repair["original_runtime"]
    old_check = verify_inventory(old["root"], old["manifest"], old["sha256"])
    if (output/"executions").exists():
        raise ValueError("benchmark output must remain absent until root freezes attachment selection")
    attempts = []
    for path in sorted(output.glob("runtime-build*process.command.json")):
        record = json.loads(captured(path, pins))
        log = path.with_name(path.name.replace(".command.json", ".log"))
        captured(log, pins, record["log_sha256"])
        attempts.append({"receipt": str(path), "sha256": pins[str(path)],
            "wall_ns": record["wall_ns"], "parent_cpu_ns": record["parent_cpu_ns"],
            "child_cpu_ns": record["child_user_cpu_ns"]+record["child_system_cpu_ns"],
            "exit_code": record["exit_code"], "timed_out": record["timed_out"],
            "scope": "inclusive whole builder process; its nested install costs must not be added again"})
    if not attempts:
        raise ValueError("preserved outer construction-attempt observations required")
    preflight = output/"attempts/preflight-1/receipt.json"
    captured(preflight, pins)
    captured(output/"source-preparation-receipt.json", pins)
    merged = merge_pins(plan["file_pins"], built["file_pins"], pins)
    verify_pins(merged)
    config = {"schema": "hepta.prospective-runtime-config.v1", "profiles": built["profiles"],
        "group_profiles": built["group_profiles"], "inventories": inventories, "file_pins": merged,
        "source_stores": {"luigi": repair["source_store"]}, "benchmark_commands_run": 0,
        "dependency_repair": {"proposal_sha256": repair["proposal_sha256"], "only_added_packages": ADDITIONS,
            "successful_attempt": str(runtime), "original_lock_unchanged": True,
            "original_environment_unchanged": True, "all33_groups_all134_actions_both_revisions": True,
            "attachment_selection_not_yet_authorized": True}}
    write(output/"runtime-config.json", config)
    final_plan = {"schema": "hepta.luigi-dependency-repair-ready.v2", "preparation_only": True,
        "root_attachment_selection_required_before_execution": True, "benchmark_commands_run": 0,
        "inputs_path": str(output/"inputs/inputs.json"), "inputs_sha256": repair["projected_inputs_sha256"],
        "runtime_config_path": str(output/"runtime-config.json"), "runtime_config_sha256": sha(output/"runtime-config.json"),
        "runtime_build_plan_sha256": sha(plan_path), "repair": repair, "successful_attempt": str(runtime),
        "groups": list(plan["group_profiles"]), "actions": 134, "physical_command_slots": 268,
        "installed_package_count": len(expected), "installed_lock_sha256": complete["resolved_lock_sha256"],
        "runtime_inventory_checks": checks, "original_runtime_unchanged_check": old_check,
        "construction_attempts": attempts, "failed_preflight_receipt_sha256": sha(preflight),
        "cost_bindings": {"source_preparation": sha(output/"source-preparation-receipt.json"),
            "builder_config": sha(built_path), "builder_subprocesses": sha(receipts/"complete.json")}}
    verify_pins(merged)
    write(output/"plan.json", final_plan)
    write(output/"finalization-receipt.json", {"plan_sha256": sha(output/"plan.json"),
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "benchmark_commands_run": 0, "scope": "Post-build exact lock delta, new/original/shared inventories, strict conflict-free pin merge and final writes; excludes this receipt serialization."})
    return final_plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runtime-directory", required=True)
    parser.add_argument("--build-plan", required=True)
    args = parser.parse_args()
    result = finalize(args.output, args.runtime_directory, args.build_plan)
    print(json.dumps({k: result[k] for k in ("inputs_sha256", "runtime_config_sha256", "installed_package_count", "benchmark_commands_run")}))
