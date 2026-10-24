"""Seal and run one complete all-candidate, immutable-runtime local condition."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import resource
import threading
import time

from operational_cohort_plan import canonical, digest
from prospective_action_execution import run_case
from prospective_action_inputs import sha_file


CODE_FILES = ("prospective_action_run.py", "prospective_action_execution.py",
              "prospective_action_inputs.py", "operational_cohort_plan.py",
              "operational_source_regions.py", "operational_observer.py", "prospective_action_observer.py")


def checked_json(path, pins):
    path = Path(path).resolve()
    raw = path.read_bytes()
    pins[str(path)] = digest(raw)
    return json.loads(raw)


def verify_pins(pins):
    for path, expected in pins.items():
        if sha_file(path) != expected:
            raise ValueError("frozen execution input changed: " + path)


def verify_inventory(root, manifest_path, expected_sha):
    """Check complete runtime files, with only bytecode caches excluded."""
    root, manifest_path = Path(root), Path(manifest_path)
    raw = manifest_path.read_bytes()
    if digest(raw) != expected_sha:
        raise ValueError("runtime inventory differs from declared pin")
    inventory = json.loads(raw)
    if isinstance(inventory, dict):
        inventory = inventory["files"]
    expected = set()
    for record in inventory:
        name = Path(record["path"])
        if name.is_absolute() or ".." in name.parts or str(name) in expected:
            raise ValueError("invalid or duplicate runtime inventory path")
        expected.add(str(name))
        p = root / name
        if not p.is_file() or p.stat().st_size != record["bytes"] or sha_file(p) != record["sha256"]:
            raise ValueError("runtime file differs from immutable inventory: " + str(p))
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and "__pycache__" not in p.parts}
    if actual != expected:
        raise ValueError("runtime file inventory has extra or missing non-cache files")
    return {"files": len(inventory), "bytes": sum(p["bytes"] for p in inventory),
            "manifest_sha256": expected_sha}


def run(inputs_path, runtime_config, output, work_root, *, workers=2, limits=None):
    limits = limits or {"cpu_seconds": 40, "wall_timeout_seconds": 45,
                        "address_space_bytes": 1536 * 1024 ** 2, "log_file_bytes": 2 * 1024 ** 2}
    if type(workers) is not int or not 1 <= workers <= 2 or min(limits.values()) <= 0:
        raise ValueError("bounded one/two-worker execution and positive limits required")
    started, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    inputs_path, runtime_config, output, work_root = [Path(p).resolve() for p in (inputs_path, runtime_config, output, work_root)]
    pins = {}
    inputs = checked_json(inputs_path, pins)
    seal = checked_json(inputs_path.with_name("manifest.json"), pins)
    config = checked_json(runtime_config, pins)
    if (pins[str(inputs_path.resolve())] != seal["inputs_sha256"]
            or inputs["all_labels_unobserved"] is not True
            or any(any(v is not None for v in row["labels"].values()) for row in inputs["rows"])):
        raise ValueError("pre-outcome source-only input seal required")
    groups = inputs["case_bindings"]
    if set(config["group_profiles"]) != set(groups):
        raise ValueError("each frozen group must have exactly one runtime profile")
    if set(config["source_stores"]) != {case["project"] for case in groups.values()}:
        raise ValueError("exact frozen source-store coverage required")
    code = Path(__file__).resolve().parent
    pins.update({str(code / name): sha_file(code / name) for name in CODE_FILES})
    for path, value in config.get("file_pins", {}).items():
        if str(Path(path).resolve()) in pins and pins[str(Path(path).resolve())] != value:
            raise ValueError("runtime config contradicts an input pin")
        pins[str(Path(path).resolve())] = value
    for case in groups.values():
        pins[case["path"]] = case["sha256"]
    inventory_before = {}
    for name, record in config["inventories"].items():
        inventory_before[name] = verify_inventory(record["root"], record["manifest"], record["sha256"])
        pins[str(Path(record["manifest"]).resolve())] = record["sha256"]
    for group, name in config["group_profiles"].items():
        profile = config["profiles"][name]
        if sha_file(profile["python"]) != profile["python_sha256"]:
            raise ValueError("runtime interpreter executable changed")
        if not any(Path(profile["python"]).is_relative_to(Path(r["root"])) for r in config["inventories"].values()):
            raise ValueError("runtime profile is outside declared inventories")
    verify_pins(pins)
    plan = {"schema": "hepta.prospective-action-execution-plan.v1",
        "inputs_sha256": seal["inputs_sha256"], "runtime_config_sha256": pins[str(runtime_config.resolve())],
        "runtime_config": config, "code_sha256": {name: pins[str(code / name)] for name in CODE_FILES},
        "frozen_file_pins": pins, "workers": workers, "limits": limits,
        "work_root": str(work_root.resolve()), "same_test_tree_on_both_implementations": True,
        "all_frozen_actions_executed": True, "outcome_dependent_stopping": False,
        "post_exit_group_cleanup": "Kill/reap remaining owned group members via process-local subreaper; such observations are unavailable. Escaped session CPU remains outside measured scope.",
        "source_roles": inputs["project_roles"], "inventory_before": inventory_before,
        "authority": "SHADOW_ONLY / DENY_ALL"}
    output.mkdir(parents=True, exist_ok=False)
    work_root.mkdir(parents=True, exist_ok=True)
    plan_path = output / "execution-plan.json"
    plan_path.write_bytes(canonical(plan))
    plan_sha = sha_file(plan_path)
    print(json.dumps({"execution_plan_sha256": plan_sha, "proposed_groups": len(groups),
                      "proposed_actions": seal["proposed_unique_actions"], "before_commands": True}), flush=True)
    locks = {project: threading.Lock() for project in config["source_stores"]}
    def execute(group, binding):
        with locks[binding["project"]]:
            directory = output / (binding["project"] + "-" + str(binding["bug_id"]))
            result = run_case(binding, config["source_stores"][binding["project"]],
                config["profiles"][config["group_profiles"][group]], directory, work_root, limits, plan_sha)
            counts = {key: result[key] for key in ("physical_command_executions", "complete_command_observations",
                      "observer_call_attempts", "observer_attempts_without_launch_receipt")}
            return group, sha_file(directory / "result.json"), counts, len(result["errors"])
    results, totals = {}, {key: 0 for key in ("physical_command_executions", "complete_command_observations",
                                           "observer_call_attempts", "observer_attempts_without_launch_receipt")}
    # Round-robin projects by numeric bug number avoids queueing both workers on
    # one source-bank lock while another project is ready.
    ordered = sorted(groups.items(), key=lambda pair: (int(pair[1]["bug_id"]), pair[1]["project"]))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, group, binding) for group, binding in ordered]
        for future in as_completed(futures):
            group, result_sha, counts, errors = future.result()
            results[group] = result_sha
            for key, value in counts.items():
                totals[key] += value
            print(json.dumps({"completed_groups": len(results), "group": group,
                              "physical_commands": counts["physical_command_executions"], "orchestration_errors": errors}), flush=True)
    inventory_after = {name: verify_inventory(record["root"], record["manifest"], record["sha256"])
                       for name, record in config["inventories"].items()}
    verify_pins(pins)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary = {"schema": "hepta.prospective-action-execution-summary.v1", "execution_plan_sha256": plan_sha,
        "case_results": results, "proposed_groups": len(groups), "completed_groups": len(results),
        **totals, "proposed_physical_command_slots": 2 * seal["proposed_unique_actions"], "inventory_after": inventory_after,
        "all_frozen_files_unchanged": True, "all_runtime_files_unchanged": inventory_before == inventory_after,
        "wall_ns": time.perf_counter_ns() - started, "parent_process_cpu_ns": time.process_time_ns() - parent_cpu,
        "all_reaped_children_cpu_ns": round((children_after.ru_utime + children_after.ru_stime
            - children_before.ru_utime - children_before.ru_stime) * 1e9),
        "cost_scope": "Whole condition including source checkouts, command observations and full runtime verification; excludes summary serialization. Inclusive of nested case/command costs: do not sum them again.",
        "peak_child_rss_bytes": children_after.ru_maxrss * 1024,
        "peak_rss_scope": "Largest waited child max RSS; neither concurrent aggregate nor incremental peak.",
        "no_model_fit_or_score": True, "outcome_dependent_stopping": False}
    (output / "summary.json").write_bytes(canonical(summary))
    print(json.dumps({"completed_groups": len(results), "physical_commands": totals["physical_command_executions"],
                      "summary_sha256": sha_file(output / "summary.json")}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "runtime-config", "output", "work-root"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    run(args.inputs, args.runtime_config, args.output, args.work_root)


if __name__ == "__main__":
    main()
