"""Complete the resource-interrupted candidate using three proven-equal native artifacts."""

import argparse
import json
from pathlib import Path
import resource
import shutil
import time

from pandas_pilot_build import dependency_plan, verify_files
from pandas_source_pilot import command, exceeded, resources, sha, write_new


def check(root, proof):
    root = Path(root)
    for name, expected in proof["pins"].items():
        if sha(root / name) != expected:
            raise ValueError("native equality evidence input changed")
    dependency_plan(root)
    runtime = json.loads((root / "runtime-complete.json").read_bytes())
    verify_files(runtime["root"], json.loads((root / "runtime-files.json").read_bytes()))
    for role in ("base", "candidate"):
        verify_files(root / "checkouts" / role, json.loads((root / ("source-files-" + role + ".json")).read_bytes()))
        verify_files(root / "checkouts" / role, proof["identical_remaining_source_inventory"])
    verify_files(root / "checkouts/candidate", proof["identical_compiled_extensions"])
    verify_files(root / "checkouts/base", proof["missing_candidate_extensions"])
    expected_differences = ["doc/source/whatsnew/v1.1.0.rst", "pandas/core/groupby/groupby.py",
                            "pandas/tests/groupby/test_function.py"]
    if (proof["full_original_source_differences"] != expected_differences
            or len(proof["identical_compiled_extensions"]) != 38
            or len(proof["missing_candidate_extensions"]) != 3):
        raise ValueError("unexpected recovery scope")
    return runtime


def freeze(root, expected_audit_sha256):
    root = Path(root).resolve()
    audit = root / "native-input-equivalence-audit.json"
    if sha(audit) != expected_audit_sha256:
        raise ValueError("external native equality audit pin mismatch")
    proof = json.loads(audit.read_bytes())
    check(root, proof)
    for record in proof["missing_candidate_extensions"]:
        if (root / "checkouts/candidate" / record["path"]).exists():
            raise ValueError("recovery target already exists")
    pins = {str(audit): expected_audit_sha256}
    for name in ("pandas_pilot_reuse.py", "pandas_source_pilot.py", "pandas_pilot_build.py"):
        path = Path(__file__).with_name(name)
        pins[str(path)] = sha(path)
    for role in ("base", "candidate"):
        for compiler in ("gcc", "g++"):
            path = root / "commands" / ("20-" + role + "-" + compiler) / "stdout.log"
            pins[str(path)] = sha(path)
    plan = {"schema": "hepta.pandas-pilot-native-reuse-plan.v1", "input_pins": pins,
        "copy_from": "base", "copy_to": "candidate", "files": proof["missing_candidate_extensions"],
        "copied_bytes": sum(r["bytes"] for r in proof["missing_candidate_extensions"]),
        "authorization": "Original build protocol permits reuse after complete native-input/ABI/compiler/dependency equality proof; root accepted this exact audit.",
        "prior_native_build_launches": 2, "prior_complete_native_build_successes": 1,
        "prior_candidate_build_failed": True, "new_native_build_launches": 0,
        "benchmark_commands_permitted": False, "root_selection_sha256": expected_audit_sha256}
    write_new(root / "native-reuse-plan.json", plan)
    return {"plan_sha256": sha(root / "native-reuse-plan.json"), "files": len(plan["files"]),
            "copied_bytes": plan["copied_bytes"]}


def apply(root, expected_plan_sha256):
    root = Path(root).resolve()
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    if sha(root / "native-reuse-plan.json") != expected_plan_sha256:
        raise ValueError("external native reuse plan pin mismatch")
    plan = json.loads((root / "native-reuse-plan.json").read_bytes())
    for path, expected in plan["input_pins"].items():
        if sha(path) != expected:
            raise ValueError("native reuse code/evidence pin changed")
    proof = json.loads((root / "native-input-equivalence-audit.json").read_bytes())
    runtime = check(root, proof)
    if exceeded(resources(root)):
        raise RuntimeError("native reuse/import resource preflight cap")
    for record in plan["files"]:
        name = Path(record["path"])
        if name.is_absolute() or ".." in name.parts or "\\" in str(name) or ":" in str(name):
            raise ValueError("unsafe native artifact path")
        source, destination = root / "checkouts/base" / name, root / "checkouts/candidate" / name
        if source.is_symlink() or any(p.is_symlink() for p in destination.parents):
            raise ValueError("native artifact symlink boundary")
        with source.open("rb") as incoming, destination.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if sha(destination) != record["sha256"]:
            raise ValueError("copied native artifact differs")
        write_new(root / "native-reuse-copies" / (name.name + ".json"), record)
    checkout = root / "checkouts/candidate"
    base = json.loads((root / "build-complete-base.json").read_bytes())
    modules = [r["path"].split(".cpython-", 1)[0].replace("/", ".") for r in base["extension_files"]]
    script = ("import importlib,json,pathlib,sys,sysconfig;root=pathlib.Path(" + repr(str(checkout)) + ");"
        "sys.path.insert(0,str(root));import pandas,numpy;"
        "names=" + repr(modules) + ";[importlib.import_module(n) for n in names];"
        "native={n:m.__file__ for n,m in sys.modules.items() if n.startswith('pandas.') and getattr(m,'__file__','') and m.__file__.endswith('.so')};"
        "assert root in pathlib.Path(pandas.__file__).resolve().parents;assert set(names)<=set(native);"
        "assert all(root in pathlib.Path(p).resolve().parents for p in native.values());"
        "print(json.dumps({'pandas_file':pandas.__file__,'pandas_version':pandas.__version__,'numpy_version':numpy.__version__,"
        "'python_version':sys.version,'soabi':sysconfig.get_config_var('SOABI'),'imported_native':native},sort_keys=True))")
    dep = dependency_plan(root)
    log = command(root, "23-source-import-candidate-recovered", [runtime["python"], "-I", "-B", "-c", script],
        cwd=checkout, env=dep["build_environment"], timeout=60)
    check(root, proof)
    verify_files(checkout, base["extension_files"])
    for path, expected in plan["input_pins"].items():
        if sha(path) != expected:
            raise ValueError("native reuse code/evidence pin changed during qualification")
    child1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"role": "candidate", "source": dep["source_revisions"]["candidate"], "checkout": str(checkout),
        "source_inventory_sha256": dep["source_file_inventories"]["candidate"]["sha256"],
        "runtime_complete_sha256": sha(root / "runtime-complete.json"),
        "dependency_plan_sha256": sha(root / "dependency-plan.json"), "build_environment": dep["build_environment"],
        "extension_files": base["extension_files"], "extension_bytes": base["extension_bytes"],
        "import": json.loads(log.read_bytes()), "import_log_sha256": sha(log), "build_artifact_reuse": True,
        "independent_native_build_succeeded": False, "independently_compiled_identical_extensions": 38,
        "reused_extensions": plan["files"], "native_reuse_plan_sha256": expected_plan_sha256,
        "native_equality_audit_sha256": sha(root / "native-input-equivalence-audit.json"),
        "retained_failed_build_receipt_sha256": sha(root / "commands/21-native-build-candidate/receipt.json"),
        "new_native_build_launches": 0, "benchmark_commands_run": 0,
        "wall_ns": time.perf_counter_ns() - start, "parent_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_ns": round((child1.ru_utime + child1.ru_stime - child0.ru_utime - child0.ru_stime) * 1e9),
        "cost_scope": "Inclusive equality revalidation, three copies and one import command; nested import cost is already included.",
        "resources": resources(root), "authority": "DENY_ALL"}
    write_new(root / "build-complete-candidate.json", result)
    return {"qualification_sha256": sha(root / "build-complete-candidate.json"),
            "reused_files": 3, "native_build_launches": 0, "benchmark_commands_run": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "apply"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.root, args.expected_sha256) if args.action == "freeze" else apply(args.root, args.expected_sha256)))
