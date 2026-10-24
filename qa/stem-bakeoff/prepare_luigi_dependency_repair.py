"""Prepare and authenticate a whole-project, dependency-only Luigi repair.

This helper never executes benchmark commands. The existing runtime builder
constructs a new environment between prepare and finalize; all attempts remain
separate evidence. Root must freeze attachment selection before replay.
"""

import argparse
import copy
import json
from pathlib import Path
import time

from build_prospective_runtimes import verify_pins
from operational_cohort_plan import canonical, digest
from prospective_action_run import CODE_FILES, verify_inventory
from prospective_runtime_plan import exact_pins, sha


PROFILE = "luigi-dependencies-v1"
ADDITIONS = {"pyparsing": "2.4.7", "sqlalchemy": "1.3.17"}


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value))


def captured(path, pins, expected=None):
    path = Path(path).resolve()
    raw = path.read_bytes()
    value = digest(raw)
    if (expected is not None and value != expected) or pins.setdefault(str(path), value) != value:
        raise ValueError("repair source differs from its independently captured pin")
    return raw


def exact_repair_lock(original, installed=None):
    before = exact_pins(original)
    if set(before) & set(ADDITIONS):
        raise ValueError("the approved additions must be absent from the original lock")
    expected = {**before, **ADDITIONS}
    if installed is not None and exact_pins(installed) != expected:
        raise ValueError("installed lock changed or added a dependency outside the two approved additions")
    return expected


def project_inputs(inputs, expected_groups):
    groups = {key: value for key, value in inputs["case_bindings"].items() if value["project"] == "luigi"}
    if (set(groups) != set(expected_groups) or len(groups) != 33
            or sum(len(g["actions"]) for g in groups.values()) != 134
            or inputs.get("all_labels_unobserved") is not True
            or any(any(v is not None for v in r["labels"].values()) for r in inputs["rows"])):
        raise ValueError("all33 original source-only Luigi groups and134 actions required")
    result = copy.deepcopy(inputs)
    result["case_bindings"] = copy.deepcopy(groups)
    result["rows"] = [copy.deepcopy(r) for r in inputs["rows"] if r["group_id"] in groups]
    result["proposal_registry"] = [copy.deepcopy(g) for g in inputs["proposal_registry"] if g["group_id"] in groups]
    result["project_roles"] = {"luigi": inputs["project_roles"]["luigi"]}
    sources = [a["source_id"] for g in groups.values() for a in g["actions"] if a["source_id"] is not None]
    if (len(sources) != len(set(sources)) or {r["source_id"] for r in result["rows"]} != set(sources)
            or len(result["rows"]) != len(sources) or len(result["proposal_registry"]) != len(groups)
            or {g["group_id"] for g in result["proposal_registry"]} != set(groups)
            or any(g["actions"] != groups[g["group_id"]]["actions"] for g in result["proposal_registry"])):
        raise ValueError("project projection changed an action/source/registry binding")
    return result


def prepare(proposal_path, output, *, expected_proposal_sha256):
    started, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), {}
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("new repair root required; preserve every prior attempt")
    proposal = json.loads(captured(proposal_path, pins, expected_proposal_sha256))
    if proposal["condition_id"] != PROFILE or proposal["proposed_additions"] != ["pyparsing==2.4.7", "SQLAlchemy==1.3.17"]:
        raise ValueError("exact approved two-dependency repair proposal required")
    sources = proposal["parent_inputs"], proposal["parent_execution_plan"], proposal["original_lock"]
    original, execution, original_lock = [captured(v["path"], pins, v["sha256"]) for v in sources]
    inputs, parent_plan = json.loads(original), json.loads(execution)
    original_manifest = Path(sources[0]["path"]).with_name("manifest.json")
    manifest = json.loads(captured(original_manifest, pins))
    if manifest["inputs_sha256"] != sources[0]["sha256"] or parent_plan["inputs_sha256"] != sources[0]["sha256"]:
        raise ValueError("original execution/input seal differs")
    projected = project_inputs(inputs, proposal["uniform_scope"]["groups"])
    expected = exact_repair_lock(original_lock.decode())
    for item in proposal["metadata"]:
        raw = captured(item["path"], pins, item["sha256"])
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8")
        if any(line not in {s.strip() for s in text.splitlines()} for line in item["core_dependency_lines"]):
            raise ValueError("static dependency metadata no longer supports the proposed exact pins")
    code = Path(__file__).resolve().parent
    for name, expected_sha in parent_plan["code_sha256"].items():
        captured(code/name, pins, expected_sha)
    for name in (Path(__file__).name, "build_prospective_runtimes.py", "prospective_runtime_plan.py"):
        captured(code/name, pins)
    parent_config = parent_plan["runtime_config"]
    shared = parent_config["inventories"]["shared-python-base"]
    old = parent_config["inventories"]["development-compat-v3"]
    original_runtime = parent_config["profiles"]["development-compat-v3"]
    for record in (shared, old):
        captured(record["manifest"], pins, record["sha256"])
        verify_inventory(record["root"], record["manifest"], record["sha256"])
    for group, binding in projected["case_bindings"].items():
        captured(binding["path"], pins, binding["sha256"])
        if parent_config["group_profiles"][group] != "development-compat-v3":
            raise ValueError("Luigi original runtime profile differs")
    interpreter = Path(original_runtime["python"]).resolve()
    captured(interpreter, pins, original_runtime["python_sha256"])
    output.mkdir(parents=True)
    (output/"inputs").mkdir()
    projected["dependency_repair_projection"] = {"parent_inputs_sha256": sources[0]["sha256"],
        "all_project_groups_and_actions_unchanged": True, "proposal_sha256": expected_proposal_sha256}
    write(output/"inputs/inputs.json", projected)
    write(output/"inputs/manifest.json", {"schema": manifest["schema"],
        "inputs_sha256": sha(output/"inputs/inputs.json"), "proposed_groups": 33,
        "proposed_unique_actions": 134, "source_available_rows": len(projected["rows"]),
        "case_source_sha256": {g: b["sha256"] for g, b in projected["case_bindings"].items()},
        "labels_provided_to_input_builder": False, "before_any_new_benchmark_execution": True,
        "parent_inputs_sha256": sources[0]["sha256"]})
    profile = {"project": "luigi", "requirements": [k+"=="+v for k, v in sorted(expected.items())],
        "smoke_imports": ["pytest", "pyparsing", "sqlalchemy", "sqlalchemy.ext.declarative", "sqlalchemy.orm.collections", "sqlalchemy.engine.reflection"],
        "source_paths": original_runtime["source_paths"], "plain_pytest": original_runtime["plain_pytest"]}
    plan = {"schema": "hepta.prospective-runtime-plan.v1", "profiles": {PROFILE: profile},
        "group_profiles": {g: PROFILE for g in projected["case_bindings"]}, "file_pins": pins,
        "interpreter": str(interpreter), "interpreter_sha256": original_runtime["python_sha256"],
        "bootstrap": [k+"=="+expected[k] for k in ("pip", "setuptools", "wheel")],
        "builder_policy": {"minimum_free_disk_bytes": 250000000, "target_packages_forbidden": ["luigi"],
            "benchmark_commands_permitted": False, "no_changes_to_old_environments": True,
            "same_environment_for_both_revisions": True, "import_smoke_only": True},
        "repair": {"proposal_path": str(Path(proposal_path).resolve()), "proposal_sha256": expected_proposal_sha256,
            "original_lock_path": sources[2]["path"], "original_lock_sha256": sources[2]["sha256"],
            "original_package_count": len(expected)-2, "only_added_packages": ADDITIONS,
            "original_runtime": old, "shared_base_inventory": shared,
            "source_store": parent_config["source_stores"]["luigi"], "parent_inputs_sha256": sources[0]["sha256"],
            "parent_execution_plan_sha256": sources[1]["sha256"], "execution_code_sha256": parent_plan["code_sha256"],
            "limits": parent_plan["limits"], "workers": parent_plan["workers"],
            "projected_inputs_sha256": sha(output/"inputs/inputs.json"),
            "projected_manifest_sha256": sha(output/"inputs/manifest.json"),
            "expected_execution_output": str(output/"executions"), "work_root": str(output/"worktrees")}}
    verify_pins(pins)
    write(output/"runtime-build-plan.json", plan)
    write(output/"source-preparation-receipt.json", {"plan_sha256": sha(output/"runtime-build-plan.json"),
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "benchmark_commands_run": 0, "scope": "Source capture/projection and full unchanged original/shared-runtime inventory checks; excludes this receipt serialization."})
    return plan


def finalize(output):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output).resolve()
    plan_path, pins = output/"runtime-build-plan.json", {}
    plan = json.loads(captured(plan_path, pins))
    repair = plan["repair"]
    verify_pins(plan["file_pins"])
    built_path = output/"runtime/runtime-config.json"
    built = json.loads(captured(built_path, pins))
    if not built["all_profiles_completed"] or built["failures"] or set(built["profiles"]) != {PROFILE}:
        raise ValueError("complete new immutable runtime required before finalizing")
    verify_pins(built["file_pins"])
    receipts = output/"runtime/receipts"/PROFILE
    complete = json.loads(captured(receipts/"complete.json", pins))
    if complete["plan_sha256"] != sha(plan_path) or built["group_profiles"] != plan["group_profiles"]:
        raise ValueError("new runtime belongs to a different frozen build plan")
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
    config = {"schema": "hepta.prospective-runtime-config.v1", "profiles": built["profiles"],
        "group_profiles": built["group_profiles"], "inventories": inventories,
        "file_pins": {**plan["file_pins"], **built["file_pins"], **pins},
        "source_stores": {"luigi": repair["source_store"]}, "benchmark_commands_run": 0,
        "dependency_repair": {"proposal_sha256": repair["proposal_sha256"], "only_added_packages": ADDITIONS,
            "original_lock_unchanged": True, "original_environment_unchanged": True,
            "all33_groups_all134_actions_both_revisions": True, "attachment_selection_not_yet_authorized": True}}
    verify_pins(config["file_pins"])
    write(output/"runtime-config.json", config)
    final_plan = {"schema": "hepta.luigi-dependency-repair-ready.v1", "preparation_only": True,
        "root_attachment_selection_required_before_execution": True, "benchmark_commands_run": 0,
        "inputs_path": str(output/"inputs/inputs.json"), "inputs_sha256": repair["projected_inputs_sha256"],
        "runtime_config_path": str(output/"runtime-config.json"), "runtime_config_sha256": sha(output/"runtime-config.json"),
        "runtime_build_plan_sha256": sha(plan_path), "repair": repair,
        "groups": list(plan["group_profiles"]), "actions": 134, "physical_command_slots": 268,
        "installed_package_count": len(expected), "installed_lock_sha256": complete["resolved_lock_sha256"],
        "runtime_inventory_checks": checks, "original_runtime_unchanged_check": old_check,
        "cost_bindings": {"source_preparation": sha(output/"source-preparation-receipt.json"),
            "builder_config": sha(built_path), "builder_subprocesses": sha(receipts/"complete.json")}}
    write(output/"plan.json", final_plan)
    write(output/"finalization-receipt.json", {"plan_sha256": sha(output/"plan.json"),
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "benchmark_commands_run": 0, "scope": "Post-build exact lock-delta and new/original/shared inventories, all pins and final config/plan writes; excludes this receipt serialization."})
    return final_plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finalize"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--proposal")
    parser.add_argument("--expected-proposal-sha256")
    args = parser.parse_args()
    report = (prepare(args.proposal, args.output, expected_proposal_sha256=args.expected_proposal_sha256)
              if args.phase == "prepare" else finalize(args.output))
    print(json.dumps({"phase": args.phase, "benchmark_commands_run": 0,
        "root": str(Path(args.output).resolve()), "profiles": len(report.get("profiles", {PROFILE: None}))}))
