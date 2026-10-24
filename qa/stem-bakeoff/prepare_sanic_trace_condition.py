"""Prepare an explicitly repeated, stack-only whole-project diagnostic condition.

This command creates inputs and launchers. It never executes benchmark commands.
The existing observer, executor, dependency environments and limits stay pinned.
"""

import argparse
import copy
import json
from pathlib import Path
import time

from operational_cohort_plan import canonical, digest
from prospective_action_inputs import sha_file
from prospective_action_run import verify_inventory, verify_pins


def launcher_source(python, observer, observer_sha256, delay=30):
    """Keep the lexical venv interpreter path; resolving its symlink loses the venv."""
    python, observer = Path(python).absolute(), Path(observer).absolute()
    if any(c.isspace() for c in str(python)) or not 0 < delay < 45:
        raise ValueError("ordinary shebang interpreter and pre-deadline dump required")
    return f'''#!{python}
import faulthandler
import hashlib
from pathlib import Path
import runpy
import sys

observer = Path({str(observer)!r})
if len(sys.argv) < 2 or Path(sys.argv[1]).absolute() != observer:
    raise ValueError("launcher is bound to the original observer")
if hashlib.sha256(observer.read_bytes()).hexdigest() != {observer_sha256!r}:
    raise ValueError("original observer changed")
arguments = sys.argv[2:]
boundary = arguments.index("--") if "--" in arguments else len(arguments)
options = arguments[:boundary]
if options.count("--output") != 1:
    raise ValueError("one observer output is required")
output = Path(options[options.index("--output") + 1]).absolute()
sys.argv = [str(observer), *arguments]
sys.path[0] = str(observer.parent)
with output.with_name("stack.log").open("xb", buffering=0) as stack:
    faulthandler.dump_traceback_later({delay!r}, file=stack, repeat=False)
    try:
        runpy.run_path(str(observer), run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()
'''


def prepare(inputs_path, execution_plan, output, *, inputs_sha256, execution_plan_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    inputs_path, execution_plan, output = map(lambda p: Path(p).absolute(), (inputs_path, execution_plan, output))
    raw_inputs, raw_plan = inputs_path.read_bytes(), execution_plan.read_bytes()
    if digest(raw_inputs) != inputs_sha256 or digest(raw_plan) != execution_plan_sha256:
        raise ValueError("independently pinned parent inputs and execution plan required")
    inputs, parent = json.loads(raw_inputs), json.loads(raw_plan)
    if (parent["inputs_sha256"] != inputs_sha256 or inputs["all_labels_unobserved"] is not True
            or any(v is not None for r in inputs["rows"] for v in r["labels"].values())):
        raise ValueError("the projection may only read original unlabelled proposals")
    groups = {key: value for key, value in inputs["case_bindings"].items() if value["project"] == "sanic"}
    if set(groups) != {f"bugsinpy/sanic/{i}" for i in range(1, 6)}:
        raise ValueError("the entire five-group Sanic project is required")
    original = parent["runtime_config"]
    pins = dict(original["file_pins"])
    pins.update({str(inputs_path): inputs_sha256, str(execution_plan): execution_plan_sha256,
                 str(Path(__file__).absolute()): sha_file(__file__)})
    observer = Path(__file__).with_name("prospective_action_observer.py").absolute()
    pins[str(observer)] = parent["code_sha256"][observer.name]
    verify_pins(pins)
    output.mkdir(parents=True, exist_ok=False)
    source_root, runtime_root = output/"inputs", output/"runtime"
    source_root.mkdir(); runtime_root.mkdir()
    projection = copy.deepcopy(inputs)
    projection.update(case_bindings=groups, project_roles={"sanic": "holdout"},
        rows=[r for r in inputs["rows"] if r["repo"] == "sanic"],
        proposal_registry=[g for g in inputs["proposal_registry"] if g["repo"] == "sanic"],
        diagnostic_repeat={"parent_inputs_sha256": inputs_sha256,
            "parent_execution_plan_sha256": execution_plan_sha256, "fresh_holdout": False,
            "purpose": "stack-only infrastructure diagnosis; excluded from learning/model selection",
            "all_project_actions_and_source_rows_unchanged": True})
    actions = sum(len(g["actions"]) for g in groups.values())
    if actions != 17 or len(projection["rows"]) != 17:
        raise ValueError("exact original whole-project action denominator required")
    (source_root/"inputs.json").write_bytes(canonical(projection))
    (source_root/"manifest.json").write_bytes(canonical({
        "schema": "hepta.diagnostic-source-projection-seal.v1",
        "inputs_sha256": sha_file(source_root/"inputs.json"), "proposed_unique_actions": actions,
        "proposed_groups": len(groups), "before_this_diagnostic_execution": True,
        "before_any_new_benchmark_execution": False, "fresh_holdout": False,
        "parent_inputs_sha256": inputs_sha256,
        "case_source_sha256": {key: value["sha256"] for key, value in groups.items()}}))
    profiles, assignments, inventories = {}, {}, {}
    for name in sorted({original["group_profiles"][g] for g in groups}):
        profile = original["profiles"][name]
        python = Path(profile["python"]).absolute()
        if sha_file(python) != profile["python_sha256"]:
            raise ValueError("original environment interpreter changed")
        directory = runtime_root/(name+"-trace")/"bin"
        directory.mkdir(parents=True)
        for command in sorted(python.parent.iterdir()):
            if command.is_file():
                (directory/command.name).symlink_to(command.absolute())
        launcher = directory/"hepta-trace-python"
        launcher.write_text(launcher_source(python, observer, pins[str(observer)]))
        launcher.chmod(0o755)
        derived = name+"-trace"
        profiles[derived] = {**profile, "python": str(launcher), "python_sha256": sha_file(launcher)}
        assignments.update({g: derived for g in groups if original["group_profiles"][g] == name})
        pins[str(python)] = profile["python_sha256"]
        pins[str(launcher)] = sha_file(launcher)
        for key, record in original["inventories"].items():
            root = Path(record["root"])
            if python.is_relative_to(root) or python.resolve().is_relative_to(root):
                verify_inventory(root, record["manifest"], record["sha256"])
                inventories[key] = record
    files = [{"path": p.relative_to(runtime_root).as_posix(), "bytes": p.stat().st_size, "sha256": sha_file(p)}
             for p in sorted(runtime_root.rglob("*")) if p.is_file()]
    inventory_path = output/"launcher-inventory.json"
    inventory_path.write_bytes(canonical(files))
    inventories["diagnostic-launchers"] = {"root": str(runtime_root), "manifest": str(inventory_path),
                                           "sha256": sha_file(inventory_path)}
    for record in inventories.values():
        pins[record["manifest"]] = record["sha256"]
    config = {"schema": "hepta.sanic-stack-diagnostic-runtime.v1", "profiles": profiles,
        "group_profiles": assignments, "inventories": inventories, "file_pins": pins,
        "source_stores": {"sanic": original["source_stores"]["sanic"]},
        "diagnostic_repeat": projection["diagnostic_repeat"], "benchmark_commands_run": 0}
    (output/"runtime-config.json").write_bytes(canonical(config))
    plan = {"schema": "hepta.sanic-stack-diagnostic-plan.v1", "preparation_only": True,
        "initial_full_summary_required_before_execution": True, "root_go_required": True,
        "parent_inputs_sha256": inputs_sha256, "parent_execution_plan_sha256": execution_plan_sha256,
        "inputs_path": str(source_root/"inputs.json"), "inputs_sha256": sha_file(source_root/"inputs.json"),
        "runtime_config_path": str(output/"runtime-config.json"),
        "runtime_config_sha256": sha_file(output/"runtime-config.json"),
        "limits": parent["limits"], "groups": sorted(groups), "actions": actions,
        "physical_command_slots": 2*actions, "profiles": len(profiles), "dump_after_seconds": 30,
        "only_observation_change": "one watchdog stack dump to dedicated stack.log, outside pytest capture",
        "path_policy": "Original bin command names symlink to original environment; only hepta-trace-python is additional.",
        "original_environment_observer_source_and_arguments_unchanged": True,
        "fresh_holdout": False, "use_for_learning_or_model_selection": False,
        "new_dependency_installs": 0, "benchmark_commands_run": 0}
    verify_pins(pins)
    verify_inventory(runtime_root, inventory_path, sha_file(inventory_path))
    (output/"plan.json").write_bytes(canonical(plan))
    receipt = {"plan_sha256": sha_file(output/"plan.json"), "wall_ns": time.perf_counter_ns()-started,
        "cpu_ns": time.process_time_ns()-cpu, "scope": "Source-only projection, launcher materialization, full retained-runtime checks and plan write; excludes this receipt write.",
        "benchmark_commands_run": 0}
    (output/"preparation-receipt.json").write_bytes(canonical(receipt))
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "execution-plan", "output", "inputs-sha256", "execution-plan-sha256"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = prepare(args.inputs, args.execution_plan, args.output,
        inputs_sha256=args.inputs_sha256, execution_plan_sha256=args.execution_plan_sha256)
    print(json.dumps(result))
