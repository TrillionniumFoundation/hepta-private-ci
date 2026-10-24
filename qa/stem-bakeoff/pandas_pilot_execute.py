"""Execute only the separately frozen pandas5 actions with bound native artifacts."""

import argparse
import json
from pathlib import Path
import resource
import shutil
import time

from operational_cohort_plan import canonical, digest
from pandas_pilot_build import dependency_plan, verify_files
from pandas_source_pilot import REVISIONS, exceeded, resources, sha, write_new
from prospective_action_execution import CommandObservationError, observe


LIMITS = {"wall_timeout_seconds": 45, "cpu_seconds": 40,
          "address_space_bytes": 1610612736, "log_file_bytes": 2097152}
CODE_NAMES = ("pandas_pilot_execute.py", "pandas_pilot_build.py", "pandas_source_pilot.py",
    "prospective_action_execution.py", "prospective_action_observer.py", "operational_observer.py",
    "operational_cohort_plan.py", "prospective_action_inputs.py", "operational_source_regions.py")


def safe(root, name):
    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("unsafe source record path")
    target = Path(root) / path
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("source record has symlink ancestor")
    return target


def copy_records(origin, target, records):
    for record in records:
        source = safe(origin, record["path"])
        destination = safe(target, record["path"])
        if source.stat().st_size != record["bytes"] or sha(source) != record["sha256"]:
            raise ValueError("source or native artifact changed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if sha(destination) != record["sha256"]:
            raise ValueError("copied artifact differs")


def paired_label(pair):
    identifiers = []
    for role in ("base", "candidate"):
        result = pair.get(role)
        if not result or result.get("outcome") not in ("pass", "test_failure"):
            return None
        observation = result.get("observation")
        if not isinstance(observation, dict):
            return None
        observations = observation.get("observations", [])
        calls = [o for o in observations if o["phase"] == "call"]
        if (not calls or any(o.get("expected_failure") or o["status"] not in ("passed", "failed")
                for o in calls) or any(o["phase"] != "call" and o["status"] == "failed" for o in observations)):
            return None
        identifiers.append(sorted(o["id"] for o in calls))
    if identifiers[0] != identifiers[1]:
        return None
    return int(pair["base"]["outcome"] == "test_failure" and pair["candidate"]["outcome"] == "pass")


def freeze(root, protocol):
    root = Path(root).resolve()
    dep = dependency_plan(root)
    files = [root / name for name in ("pilot-plan.json", "dependency-plan.json", "source-acquisition.json",
        "runtime-complete.json", "runtime-files.json", "resolved-requirements.txt", "source-files-base.json",
        "source-files-candidate.json", "build-complete-base.json", "build-complete-candidate.json",
        "prepared-actions/manifest.json", "prepared-actions/case.json", "prepared-actions/inputs.json",
        "native-reuse-plan.json", "native-input-equivalence-audit.json",
        "commands/21-native-build-base/receipt.json", "commands/21-native-build-candidate/receipt.json")]
    files += sorted((root / "native-reuse-copies").glob("*.json"))
    files.append(Path(protocol).resolve())
    files += [Path(__file__).with_name(n) for n in CODE_NAMES]
    pins = {str(p): sha(p) for p in files}
    inputs = json.loads((root / "prepared-actions/inputs.json").read_bytes())
    seal = json.loads((root / "prepared-actions/manifest.json").read_bytes())
    case = json.loads((root / "prepared-actions/case.json").read_bytes())
    binding = inputs["case_bindings"]["bugsinpy/pandas/5"]
    if (seal["inputs_sha256"] != sha(root / "prepared-actions/inputs.json")
            or seal["case_sha256"] != sha(root / "prepared-actions/case.json")
            or len(binding["actions"]) != 4 or binding["role"] != "train"
            or binding["source_revisions"] != REVISIONS or inputs["all_labels_unobserved"] is not True
            or any(r["split"] != "train" or r["labels"] != {"action_usefulness": None} for r in inputs["rows"])):
        raise ValueError("source-only TRAIN proposal binding changed")
    candidate = json.loads((root / "source-files-candidate.json").read_bytes())
    lookup = {r["path"]: r for r in candidate}
    overlay = [lookup[name] for name in sorted(case["fixed_test_paths"])]
    builds = {role: json.loads((root / ("build-complete-" + role + ".json")).read_bytes()) for role in REVISIONS}
    if (builds["candidate"]["native_reuse_plan_sha256"] != sha(root / "native-reuse-plan.json")
            or builds["candidate"]["native_equality_audit_sha256"] != sha(root / "native-input-equivalence-audit.json")):
        raise ValueError("native recovery qualification binding changed")
    for role, build in builds.items():
        if build["source"] != dep["source_revisions"][role] or build["benchmark_commands_run"] != 0:
            raise ValueError("native build source mismatch")
        verify_files(root / "checkouts" / role, build["extension_files"])
    result = {"schema": "hepta.pandas-pilot-execution-plan.v1", "group_id": "bugsinpy/pandas/5",
        "role": "train", "root": str(root), "file_pins": pins, "actions": binding["actions"],
        "source_revisions": REVISIONS, "fixed_test_roots": case["test_tree_roots"],
        "fixed_test_files": overlay, "fixed_test_files_sha256": digest(canonical(overlay)),
        "limits": LIMITS, "workers": 1, "expected_max_benchmark_launches": 8,
        "plain_pytest": True, "authority": "DENY_ALL", "no_outcome_dependent_selection": True,
        "execution_gate": "Caller must separately authorize this immutable plan SHA after root protocol/code commit."}
    write_new(root / "execution-plan.json", result)
    return {"plan_sha256": sha(root / "execution-plan.json"), "actions": len(binding["actions"]),
            "overlay_files": len(overlay), "overlay_sha256": result["fixed_test_files_sha256"]}


def check_pins(pins):
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("execution input or code pin changed: " + path)


def materialize(root, role, destination, plan):
    source_files = json.loads((root / ("source-files-" + role + ".json")).read_bytes())
    build = json.loads((root / ("build-complete-" + role + ".json")).read_bytes())
    destination.mkdir(parents=True, exist_ok=False)
    copy_records(root / "checkouts" / role, destination, source_files)
    for name in plan["fixed_test_roots"]:
        target = safe(destination, name)
        if target.exists():
            shutil.rmtree(target)
    copy_records(root / "checkouts/candidate", destination, plan["fixed_test_files"])
    copy_records(root / "checkouts" / role, destination, build["extension_files"])


def _run(root, expected_plan_sha256):
    root = Path(root).resolve()
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    if sha(root / "execution-plan.json") != expected_plan_sha256:
        raise ValueError("external execution plan pin mismatch")
    plan = json.loads((root / "execution-plan.json").read_bytes())
    check_pins(plan["file_pins"])
    runtime = json.loads((root / "runtime-complete.json").read_bytes())
    verify_files(runtime["root"], json.loads((root / "runtime-files.json").read_bytes()))
    output = root / "execution-attempt-1"
    output.mkdir(exist_ok=False)
    work = root / "checkouts/action-work"
    profile = {"python": runtime["python"], "source_paths": [], "plain_pytest": plan["plain_pytest"]}
    results, setup, quarantined = {}, [], []
    for action in plan["actions"]:
        pair = {}
        for role in ("base", "candidate"):
            directory = work / (action["key"] + "-" + role)
            setup_start, setup_cpu = time.perf_counter_ns(), time.process_time_ns()
            safe_cleanup = True
            try:
                if quarantined:
                    raise RuntimeError("prior owned process group remains; further observations stay unknown")
                if exceeded(resources(root)):
                    raise RuntimeError("resource preflight cap; outcome remains unknown")
                materialize(root, role, directory, plan)
                if exceeded(resources(root)):
                    raise RuntimeError("resource cap after source copy; no benchmark launched")
                setup.append({"action": action["key"], "role": role, "prepared": True,
                    "wall_ns": time.perf_counter_ns() - setup_start,
                    "parent_cpu_ns": time.process_time_ns() - setup_cpu})
                safe_cleanup = False
                pair[role] = observe(action, profile, directory,
                    output / "commands" / action["key"] / role, plan["limits"])
                safe_cleanup = not pair[role]["owned_process_group_cleanup"]["process_group_still_present"]
            except Exception as error:
                record = {"action": action["key"], "role": role, "error": type(error).__name__ + ": " + str(error),
                    "wall_ns": time.perf_counter_ns() - setup_start,
                    "parent_cpu_ns": time.process_time_ns() - setup_cpu,
                    "cost_scope": "Inclusive setup plus any attempted observation before exception; do not add nested observation costs."}
                if isinstance(error, CommandObservationError):
                    record["partial_observation"] = error.record
                    safe_cleanup = error.record.get("cleanup") is not None and not error.record["cleanup"]["process_group_still_present"]
                setup.append(record)
            finally:
                if safe_cleanup and directory.exists():
                    shutil.rmtree(directory)
                elif directory.exists():
                    quarantined.append(str(directory))
        results[action["key"]] = {"pairs": pair, "label": paired_label(pair)}
    check_pins(plan["file_pins"])
    verify_files(runtime["root"], json.loads((root / "runtime-files.json").read_bytes()))
    for role in REVISIONS:
        verify_files(root / "checkouts" / role, json.loads((root / ("source-files-" + role + ".json")).read_bytes()))
        build = json.loads((root / ("build-complete-" + role + ".json")).read_bytes())
        verify_files(root / "checkouts" / role, build["extension_files"])
    child1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    launches = list(output.glob("commands/*/*/launch.json"))
    report = {"schema": "hepta.pandas-pilot-action-execution.v1", "plan_sha256": expected_plan_sha256,
        "group_id": plan["group_id"], "split": "train", "actions": results,
        "setup": setup, "quarantined_workspaces": quarantined,
        "physical_benchmark_launches": len(launches), "valid_action_labels": sum(r["label"] is not None for r in results.values()),
        "independent_bug_groups_attempted": 1, "trained_models": 0, "encoder_calls": 0,
        "quality_qualified": False, "authority": "DENY_ALL", "wall_ns": time.perf_counter_ns() - started,
        "parent_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_ns": round((child1.ru_utime + child1.ru_stime - child0.ru_utime - child0.ru_stime) * 1e9),
        "cost_scope": "Inclusive preparation, eight attempted observations and cleanup; nested observe/setup receipts must not be added to these totals.",
        "resources": resources(root), "source_and_runtime_final_recheck": True}
    write_new(output / "report.json", report)
    return {"report_sha256": sha(output / "report.json"), "physical_benchmark_launches": len(launches),
        "valid_action_labels": report["valid_action_labels"], "quality_qualified": False}


def run(root, expected_plan_sha256):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        return _run(root, expected_plan_sha256)
    except BaseException as error:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write_new(Path(root) / "execution-attempt-1-failure.json", {
            "error": type(error).__name__ + ": " + str(error), "plan_sha256": expected_plan_sha256,
            "wall_ns": time.perf_counter_ns() - start, "parent_cpu_ns": time.process_time_ns() - cpu,
            "child_cpu_ns": round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9),
            "scope": "Inclusive failed run including preserved command receipts; nested costs not additive.",
            "unconfirmed_workspaces_preserved": [str(p) for p in
                sorted((Path(root) / "checkouts/action-work").glob("*")) if p.is_dir()],
            "benchmark_outcomes_not_completed_are_unknown": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--protocol")
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.action == "freeze" and not args.protocol or args.action == "run" and not args.expected_plan_sha256:
        parser.error("freeze needs protocol; run needs externally selected plan SHA")
    print(json.dumps(freeze(args.root, args.protocol) if args.action == "freeze" else run(args.root, args.expected_plan_sha256)))
