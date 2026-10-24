"""Read-only closure audit of frozen pandas artifacts and recorded outcomes."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


EXECUTION_COMMIT = "3257b035e5dc3c381e1a2342ba69d55a0a35293b"
PLAN_SHA = "a603b66f98c65581237544d8103ab99eb46fc101d031c6015248c24994798c7c"
PRIMARY = "7f12347b92eb23b26627"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    repo = Path(__file__).resolve().parents[5]
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    checks, inputs, checked_files = {}, {}, 0

    def check(name, condition):
        checks[name] = bool(condition)

    def read(path):
        path = Path(path)
        inputs[str(path)] = {"sha256": sha(path), "bytes": path.stat().st_size}
        return json.loads(path.read_bytes())

    def records(directory, values):
        nonlocal checked_files
        for value in values:
            path = Path(directory) / value["path"]
            if not path.is_file() or path.is_symlink() or path.stat().st_size != value["bytes"] or sha(path) != value["sha256"]:
                return False
            checked_files += 1
        return True

    plan = read(root / "execution-plan.json")
    check("externally_selected_plan", sha(root / "execution-plan.json") == PLAN_SHA)
    for path, expected in plan["file_pins"].items():
        check("pin:" + path, sha(path) == expected)
        inputs[path] = {"sha256": sha(path), "bytes": Path(path).stat().st_size}
        if Path(path).is_relative_to(repo):
            relative = Path(path).relative_to(repo).as_posix()
            raw = subprocess.check_output(["git", "-C", str(repo), "show", EXECUTION_COMMIT + ":" + relative])
            check("git_commit:" + relative, hashlib.sha256(raw).hexdigest() == expected)
    current_head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    ancestor = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", EXECUTION_COMMIT, current_head], check=False)
    check("execution_commit_retained_in_current_history", ancestor.returncode == 0)
    source = read(root / "source-acquisition.json")
    check("source_git_pack_hashes", records(root, source["packs"]))
    runtime = read(root / "runtime-complete.json")
    runtime_files = read(root / "runtime-files.json")
    check("runtime_manifest_pin", sha(root / "runtime-files.json") == runtime["runtime_inventory_sha256"])
    check("resolved_dependencies_pin", sha(root / "resolved-requirements.txt") == runtime["resolved_requirements_sha256"])
    check("runtime_files_unchanged", records(runtime["root"], runtime_files))
    build_plan = read(root / "pilot-plan.json")
    dependency = read(root / "dependency-plan.json")
    check("original_build_protocol_unchanged", sha(build_plan["protocol"]) == build_plan["protocol_sha256"])
    builds = {}
    for role in ("base", "candidate"):
        original = read(root / ("source-files-" + role + ".json"))
        builds[role] = read(root / ("build-complete-" + role + ".json"))
        check(role + ":original_source_bytes", records(root / "checkouts" / role, original))
        check(role + ":qualified_native_bytes", records(root / "checkouts" / role, builds[role]["extension_files"]))
        check(role + ":source_revision_and_tree", builds[role]["source"] == source["revisions"][role])
    snapshots = {"pandas_source_pilot_measured_snapshot.py": build_plan["source_code_sha256"],
                 "pandas_pilot_build_measured_snapshot.py": dependency["builder_source_sha256"]}
    for name, expected in snapshots.items():
        path = Path(__file__).with_name(name)
        check("measured_source_snapshot:" + name, sha(path) == expected)
        inputs[str(path)] = {"sha256": sha(path), "bytes": path.stat().st_size}
    prepared = read(root / "prepared-actions/inputs.json")
    check("source_inputs_remain_train_and_unlabelled", len(prepared["rows"]) == 4 and all(
        r["split"] == "train" and r["labels"] == {"action_usefulness": None} for r in prepared["rows"]))
    report = read(root / "execution-attempt-1/report.json")
    check("execution_report_plan", report["plan_sha256"] == PLAN_SHA)
    check("exact_eight_launches", report["physical_benchmark_launches"] == 8 and
          len(list((root / "execution-attempt-1").glob("commands/*/*/launch.json"))) == 8)
    summary = {}
    for action in plan["actions"]:
        key = action["key"]
        entry = report["actions"][key]
        item = {"label": entry["label"], "args": action["args"], "revisions": {}}
        ordinary_ids = []
        for role in ("base", "candidate"):
            recorded = entry["pairs"][role]
            directory = root / "execution-attempt-1/commands" / key / role
            observed = read(directory / "execution.json")
            check(key + ":" + role + ":embedded_execution", observed == recorded)
            check(key + ":" + role + ":raw_files", records(directory,
                [{"path": name, **record} for name, record in observed["files"].items()]))
            check(key + ":" + role + ":literal_arguments", observed["original_args"] == action["args"] and
                  observed["effective_args"] == ["--assert=plain", *action["args"]])
            check(key + ":" + role + ":no_timeout_or_live_group", not observed["timed_out"] and
                  not observed["owned_process_group_cleanup"]["process_group_still_present"])
            calls = [o for o in observed["observation"]["observations"] if o["phase"] == "call"]
            ordinary = [o for o in calls if not o.get("expected_failure") and o["status"] in ("passed", "failed")]
            ordinary_ids.append(sorted(o["id"] for o in ordinary))
            item["revisions"][role] = {"outcome": observed["outcome"], "returncode": observed["returncode"],
                "ordinary_passes": sum(o["status"] == "passed" for o in ordinary),
                "ordinary_failures": sum(o["status"] == "failed" for o in ordinary),
                "expected_failures": sum(bool(o.get("expected_failure")) for o in calls),
                "ordinary_skips": sum(o["status"] == "skipped" and not o.get("expected_failure") for o in calls),
                "failed_calls": [{"id": o["id"], "exception": o.get("exception")} for o in ordinary if o["status"] == "failed"],
                "ordinary_test_call_ids": sorted(o["id"] for o in ordinary)}
        item["ordinary_call_ids_match"] = ordinary_ids[0] == ordinary_ids[1]
        if key == PRIMARY:
            base, candidate = item["revisions"]["base"], item["revisions"]["candidate"]
            check("primary_real_assertion_fail_to_pass", base["ordinary_passes"] == 13 and base["ordinary_failures"] == 2
                  and candidate["ordinary_passes"] == 15 and candidate["ordinary_failures"] == 0
                  and {f["id"].rsplit("[", 1)[-1] for f in base["failed_calls"]} == {"sem]", "std]"}
                  and all(f["exception"] == "AssertionError" for f in base["failed_calls"]))
            check("primary_frozen_rule_keeps_null", item["label"] is None and item["ordinary_call_ids_match"] and
                  all(r["expected_failures"] == 6 and r["ordinary_skips"] == 3 for r in item["revisions"].values()))
        else:
            check(key + ":valid_negative_comparator", item["label"] == 0 and item["ordinary_call_ids_match"] and
                  all(r["outcome"] == "pass" and r["ordinary_failures"] == r["expected_failures"] == r["ordinary_skips"] == 0
                      for r in item["revisions"].values()))
        summary[key] = item
    check("one_train_group_no_learning_claim", report["split"] == "train" and report["independent_bug_groups_attempted"] == 1
          and report["valid_action_labels"] == 3 and report["trained_models"] == report["encoder_calls"] == 0
          and report["quality_qualified"] is False and report["authority"] == "DENY_ALL")
    check("owned_workspaces_removed", not report["quarantined_workspaces"] and
          not list((root / "checkouts/action-work").glob("*")))
    commands = {p.parent.name: read(p) for p in sorted((root / "commands").glob("*/receipt.json"))}
    native = {k: v for k, v in commands.items() if k.startswith("21-native-build-")}
    check("native_build_history_preserved", len(native) == 2 and native["21-native-build-base"]["exit_code"] == 0
          and native["21-native-build-candidate"]["failure_reason"] == "resource_cap")
    check("controlled_reuse_history", builds["candidate"]["build_artifact_reuse"] is True
          and builds["candidate"]["independent_native_build_succeeded"] is False
          and len(builds["candidate"]["reused_extensions"]) == 3
          and builds["candidate"]["new_native_build_launches"] == 0)
    child1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta.pandas-pilot-closure-verification.v1", "status": "passed" if all(checks.values()) else "failed",
        "scope": "Separate read-only verification logic by the implementation agent; no independently authored or third-party review claim. No benchmark rerun or numerical model computation.",
        "execution_commit": EXECUTION_COMMIT, "current_repository_head": current_head, "checks": checks,
        "inputs": inputs, "file_records_checked": checked_files, "observed_action_summary": summary,
        "finding": "The original primary demonstrates ordinary sem/std AssertionError failure-to-pass; its whole-action label remains null because both original runs contain6 expected failures and3 skips. Three fixed comparators are valid negatives.",
        "new_train_bug_groups_attempted": 1, "valid_positive_action_labels": 0, "valid_negative_action_labels": 3,
        "unknown_action_labels": 1, "new_holdout_groups": 0, "n128_supported": False, "quality_qualified": False,
        "build_history": "2 native launches:1 complete success+1 resource failure;38 candidate binaries matched before3 controlled copies; no third native build.",
        "measured_costs": {"qualification_command_receipts": [str(root / "commands" / n / "receipt.json") for n in commands],
            "qualification_command_child_cpu_subtotal_ns": sum(r.get("child_cpu_ns") or 0 for r in commands.values()),
            "qualification_command_parent_cpu_subtotal_ns": sum(r.get("parent_cpu_ns") or 0 for r in commands.values()),
            "qualification_command_wall_sum_ns": sum(r.get("wall_ns") or 0 for r in commands.values()),
            "qualification_wall_scope": "Command sums are not elapsed end-to-end duration; metadata queries/preparation overlapped base build.",
            "candidate_interrupted_descendant_cpu_unknown": True,
            "benchmark_inclusive_receipt": str(root / "execution-attempt-1/report.json"),
            "benchmark_wall_ns": report["wall_ns"], "benchmark_parent_cpu_ns": report["parent_cpu_ns"],
            "benchmark_child_cpu_ns": report["child_cpu_ns"],
            "no_double_count": "Benchmark totals contain nested setup/command receipts. Candidate qualification contains command23 import; choose qualification outer or its nested import once. Early exploratory/freeze/import-startup overhead is not fully measured."},
        "source_version_boundary": "Qualification stored early code pins without enforcing all on every call. Exact original driver/builder snapshots are retained. Benchmark execution enforced all frozen code/input pins before and after.",
        "closure_cost": {"wall_ns_before_serialization": time.perf_counter_ns() - start,
            "parent_cpu_ns_before_serialization": time.process_time_ns() - cpu,
            "child_cpu_ns": round((child1.ru_utime + child1.ru_stime - child0.ru_utime - child0.ru_stime) * 1e9),
            "scope": "This verification, including local read-only Git calls; separate from research/benchmark receipts."},
        "authority": "DENY_ALL", "remote_ci_queried": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical(result))
    print(json.dumps({"status": result["status"], "checks": len(checks), "files_checked": checked_files,
        "output": str(output), "sha256": sha(output), "cost": result["closure_cost"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    verify(args.root, args.output)
