"""Read retained ledger-fault evidence without executing fixture or lifted AST."""

import argparse
import ast
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

SCENARIOS = (
    "known_zero",
    "no_child",
    "missing_result",
    "malformed_result",
    "unbound_result",
    "wrong_pid",
    "wrong_source",
    "wrong_exit",
    "noninteger_counter",
    "pre_popen_kill",
    "post_spawn_pre_pid_kill",
    "post_pid_kill",
    "starting_no_pid",
)
POINTS = {
    "pre_popen_kill": "after_STARTING_persist_before_real_Popen",
    "post_spawn_pre_pid_kill": "after_real_spawn_before_PID_return",
    "post_pid_kill": "after_PID_persist_before_wait_return",
}
ZERO = {"forwards": 0, "adjoints": 0, "adam_updates": 0}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text())


def source_ast(path):
    tree = ast.parse(path.read_text())
    main = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    result = {}
    for name in ("write", "require", "actor"):
        node = next(
            n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == name
        )
        result[name] = sha(ast.dump(node, include_attributes=False).encode())
    assignments = [
        next(
            n
            for n in main.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        )
        for name in ("unknown", "exact_calls")
    ]
    result["aggregate_assignments"] = sha(
        "\n".join(ast.dump(n, include_attributes=False) for n in assignments).encode()
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--frozen-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    archive_bytes = (args.root / "ORIGINAL.zip").read_bytes()
    require(
        sha(archive_bytes)
        == "591680f81beb90e6509f529b74ddda31d9b1099b7d10a5c6474ee5a65a022222",
        "original archive identity",
    )
    with zipfile.ZipFile(args.root / "ORIGINAL.zip") as archive:
        require(
            len(archive.infolist()) == len(set(archive.namelist())) == 119
            and archive.testzip() is None,
            "119 CRCs and unique members",
        )
        for name in archive.namelist():
            require(
                archive.read(name) == (args.root / "raw" / name).read_bytes(),
                "loose member bytes " + name,
            )
    root = args.root / "raw" / "ledger-fixture"
    result = read(root / "RESULT.json")
    source = read(args.root / "raw" / "ledger-fixture-source.json")
    inventory = read(args.frozen_source)
    require(
        source == result["source"]
        and source["source_commit"] == "e6d989320e6ad9310b68f650bc8805618cba34fc",
        "admitted source and result binding",
    )
    require(
        source["source_sha256"] == inventory["source_sha256"]
        and source["source_inventory_sha256"] == sha(args.frozen_source.read_bytes()),
        "frozen source inventory",
    )
    for name, expected in inventory["source_sha256"].items():
        require(
            sha((args.repo / name).read_bytes()) == expected,
            "local frozen source " + name,
        )
    original_ast = source_ast(
        args.repo / "qualification/hcsn_adjoint_adam_resume/native_probe.py"
    )
    require(
        original_ast
        == source["selected_AST_sha256"]
        == inventory["selected_AST_sha256"],
        "independent original AST hash recomputation",
    )
    require(result["status"] == "PASS" and result["error"] is None, "producer terminal")
    admissions = read(root / "SUPERVISOR-ADMISSIONS.json")
    require(
        admissions == result["supervisor_admissions"],
        "raw authoritative supervisor admissions",
    )
    require(
        tuple(a["scenario"] for a in admissions) == SCENARIOS,
        "all13 scenarios in order",
    )
    pids = [a["pid"] for a in admissions]
    require(
        len(set(pids)) == 13 and all(type(pid) is int for pid in pids),
        "13 actual unique controller PIDs",
    )
    cases = {r["scenario"]: r for r in result["scenarios"]}
    require(
        set(cases) == set(SCENARIOS) and len(result["scenarios"]) == 13,
        "13 actual result cases",
    )
    summaries, toy_pids, kills = [], [], []
    for admission in admissions:
        scenario = admission["scenario"]
        directory = root / scenario
        case = cases[scenario]
        require(admission["state"] == "TERMINAL", "worker authoritative terminal")
        expected_exit = -9 if scenario in POINTS else 0
        require(
            admission["exit_code"] == expected_exit == case["controller_exit"]
            and admission["pid"] == case["controller_pid"],
            "worker exit and PID bindings",
        )
        require(
            case["passed"] is True and case["selected_AST_sha256"] == original_ast,
            "per-case identity and passed status",
        )
        actors = read(directory / "ACTORS.json")
        require(len(actors) == 1, "one ledger intent per case")
        entry = actors[0]
        event_path = directory / "FIXTURE-EVENTS.json"
        events = read(event_path) if event_path.exists() else []
        kinds = [event["kind"] for event in events]
        spawned = scenario not in ("no_child", "pre_popen_kill", "starting_no_pid")
        order = (
            [] if scenario == "starting_no_pid" else ["target_Popen_adapter_entered"]
        )
        if spawned:
            order += ["actual_stdlib_toy_spawned", "toy_reaped"]
        if scenario in POINTS:
            order += ["intentional_controller_SIGKILL"]
        require(
            kinds == order and len(events) == case["event_count"],
            "actual event ordering " + scenario,
        )
        if scenario in POINTS:
            require(
                events[-1]
                == {
                    "kind": "intentional_controller_SIGKILL",
                    "point": POINTS[scenario],
                    "pid": admission["pid"],
                },
                "unique exact kill point/PID",
            )
            require(
                not (directory / "WORKER.json").exists(),
                "dead worker emits no terminal worker report",
            )
            kills.append(
                {
                    "scenario": scenario,
                    "pid": admission["pid"],
                    "exit_code": expected_exit,
                }
            )
        else:
            worker = read(directory / "WORKER.json")
            require(
                worker["pid"] == admission["pid"]
                and worker["scenario"] == scenario
                and worker["selected_AST_sha256"] == original_ast,
                "worker report identity",
            )
            require(
                worker["actual_fixture_numerical_calls"] == ZERO
                and worker["numerical_modules_loaded"] is False,
                "worker true zero model counters",
            )
        unknown = entry["calls_status"] not in ("KNOWN", "START_FAILED_NO_CHILD")
        expected_unknown = scenario not in ("known_zero", "no_child")
        require(unknown == expected_unknown, "independent ledger classification")
        projection = (
            []
            if not unknown
            else [
                {
                    "label": entry["label"],
                    "nonce": entry["admission_nonce"],
                    "pid": entry["pid"],
                    "started": entry["started"],
                    "launch_state": entry["launch_state"],
                    "calls_status": entry["calls_status"],
                    "terminal": entry["terminal"],
                    "exit_code": entry["exit_code"],
                    "maximum_calls": entry["expected_maximum_calls"],
                }
            ]
        )
        expected_calls = None if unknown else ZERO
        require(
            case["ledger_unknown"] == projection
            and case["actual_calls_under_test"] == expected_calls,
            "independently derived UNKNOWN/null vs known zero",
        )
        require(
            case["second_admission_blocked"] is unknown,
            "reconciliation readmission result",
        )
        require(
            not any(directory.glob("*second-must-not-spawn*")),
            "no second admission artifacts",
        )
        if scenario not in POINTS:
            require(
                worker["unknown"] == projection
                and worker["actual_calls_under_test"] == expected_calls,
                "worker and independent aggregate agree",
            )
            if unknown:
                require(
                    worker["second_admission_blocked"] is True,
                    "live worker readmission blocked",
                )
        if scenario == "starting_no_pid":
            require(
                entry["expected_maximum_calls"]
                == {"forwards": 3, "adjoints": 3, "adam_updates": 2}
                and entry["observed_calls"] is None,
                "nonzero reservation only",
            )
            require(
                entry["pid"] is None and entry["started"] is None and not events,
                "synthetic seed executed no toy",
            )
        else:
            require(
                entry["expected_maximum_calls"] == ZERO,
                "real toys never fabricate numerical counts",
            )
            require(
                entry == read(directory / "toy-ADMISSION.json"),
                "ledger/admission raw bytes semantics",
            )
            require(
                entry["admission_nonce"] == source["identity"] + ":43233514011:1:toy",
                "admitted run/attempt nonce",
            )
        if scenario in ("pre_popen_kill", "post_spawn_pre_pid_kill", "starting_no_pid"):
            require(
                entry["pid"] is None
                and entry["started"] is None
                and entry["calls_status"] == "UNKNOWN_STARTING"
                and entry["terminal"] is False,
                "unresolved startup cannot mean zero",
            )
        elif scenario == "post_pid_kill":
            require(
                entry["started"] is True
                and entry["calls_status"] == "UNKNOWN_PENDING_RESULT"
                and entry["terminal"] is False,
                "persisted PID still unknown",
            )
        elif scenario == "no_child":
            require(
                entry["started"] is False
                and entry["terminal"] is True
                and entry["observed_calls"] == ZERO,
                "definite spawn failure known zero",
            )
            require(
                entry["launch_or_wait_error"]["type"] == "FileNotFoundError",
                "one real failed-exec witness",
            )
        elif scenario == "known_zero":
            require(
                entry["calls_status"] == "KNOWN" and entry["observed_calls"] == ZERO,
                "bound zero report known",
            )
        else:
            require(
                entry["terminal"] is True
                and entry["started"] is True
                and entry["exit_code"] == 0
                and entry["observed_calls"] is None,
                "unreported/unbound toy remains unknown despite zero OS exit",
            )
        if spawned:
            spawn, reap = events[1:3]
            pid = spawn["pid"]
            toy_pids.append(pid)
            require(
                reap == {"kind": "toy_reaped", "pid": pid, "exit_code": 0},
                "real toy reaped before kill or classification",
            )
            argv = spawn["actual_command"]
            require(
                argv[1:4]
                == ["-B", "-m", "qualification.hcsn_controller_ledger_faults.probe"]
                and argv[4] == "--toy",
                "actual argv executes only toy",
            )
            require(
                read(directory / "toy/TOY-DONE.json")
                == {"pid": pid, "actual_numerical_calls": ZERO},
                "actual toy body completed with true zero counters",
            )
            path = directory / "toy/RESULT.json"
            if scenario == "missing_result":
                require(not path.exists(), "true missing report")
            elif scenario == "malformed_result":
                require(
                    path.read_bytes() == b"{invalid-json\n", "true malformed report"
                )
            else:
                report = read(path)
                expected = {
                    "pid": pid,
                    "admission_nonce": entry["admission_nonce"],
                    "source": dict(source, request_identity=source["identity"]),
                    "source_before": source["source_sha256"],
                    "source_after": source["source_sha256"],
                    "exit_code": 0,
                    "status": "PASS",
                    "calls": ZERO.copy(),
                    "input_checkpoint_sha_before": None,
                    "input_checkpoint_sha_after": None,
                    "pure_stdlib_toy_not_a_model": True,
                }
                if scenario == "unbound_result":
                    expected["admission_nonce"] = "WRONG_NONCE"
                if scenario == "wrong_pid":
                    expected["pid"] += 100000
                if scenario == "wrong_source":
                    expected["source"]["unexpected_source_binding"] = True
                if scenario == "wrong_exit":
                    expected["exit_code"] = 123
                if scenario == "noninteger_counter":
                    expected["calls"]["forwards"] = 0.0
                require(report == expected, "only predeclared report corruption")
                require(
                    type(report["calls"]["forwards"])
                    is (float if scenario == "noninteger_counter" else int),
                    "strict count type control",
                )
        require(
            case["toy_children_spawned"] == case["toy_children_reaped"] == int(spawned),
            "derived actual toy counts",
        )
        summaries.append(
            {
                "scenario": scenario,
                "worker_pid": admission["pid"],
                "authoritative_exit": expected_exit,
                "event_kinds": kinds,
                "actual_toy_body": int(spawned),
                "ledger_unknown": unknown,
                "exact_calls_under_test": expected_calls,
                "readmission_blocked": unknown,
                "nonzero_reserved_only": scenario == "starting_no_pid",
            }
        )
    require(
        len(set(toy_pids)) == len(toy_pids) == 10 and not (set(toy_pids) & set(pids)),
        "10 distinct real toy PIDs separate from workers",
    )
    require(
        result["observed_authoritative_SIGKILL_exits"] == kills
        and len(kills) == 3
        and result["planned_intentional_SIGKILL_cases"] == 3,
        "three verified hooks distinct from plan",
    )
    require(
        result["actual_stdlib_controller_processes"] == 13
        and result["actual_stdlib_toy_processes"] == 10
        and result["actual_numerical_calls"] == ZERO
        and result["torch_numpy_scipy_imports"] == 0,
        "actual top-level denominators",
    )
    require(
        not {"torch", "numpy", "scipy"} & set(sys.modules),
        "stdlib-only independent inspector",
    )
    receipt = {
        "schema": "hcsn-ledger-fault-independent-actual-review-v1",
        "reviewer": "/root/review_spatial",
        "passed": True,
        "run_id": 43233514011,
        "job_id": 131234720335,
        "artifact_id": 13951651852,
        "source_commit": source["source_commit"],
        "original_zip": {
            "bytes": len(archive_bytes),
            "sha256": sha(archive_bytes),
            "crc_members": 119,
        },
        "selected_AST_sha256_independently_recomputed": original_ast,
        "source_hashes_equal_count": 5,
        "actual_worker_PIDs": pids,
        "actual_toy_PIDs": toy_pids,
        "verified_intentional_kill_exits": kills,
        "cases": summaries,
        "independently_derived_unknown_cases": sum(
            x["ledger_unknown"] for x in summaries
        ),
        "actual_fixture_worker_processes": 13,
        "actual_fixture_toy_bodies": 10,
        "actual_failed_exec_attempts": 1,
        "actual_fixture_numerical_calls": ZERO,
        "review_new_fixture_worker_toy_model_numeric_import_or_api_executions": 0,
        "producer_costs": {
            "child_cpu_seconds": result["child_cpu_seconds"],
            "supervisor_body_cpu_seconds": result["supervisor_body_cpu_seconds"],
            "supervisor_startup_imports_included_in_cpu": result[
                "supervisor_startup_imports_included_in_cpu"
            ],
            "wall_seconds": result["wall_seconds"],
            "child_reported_max_rss_kib": result["child_reported_max_rss_kib"],
        },
        "review_cpu_seconds": time.process_time() - cpu,
        "review_wall_seconds": time.perf_counter() - wall,
        "inspector": {
            "bytes": Path(__file__).stat().st_size,
            "sha256": sha(Path(__file__).read_bytes()),
        },
        "limits": [
            "No fixture or lifted AST was re-executed by this reviewer. Aggregate classification was independently derived from JSON values, not by eval/exec or candidate imports.",
            "Second-admission rejection is checked through producer worker/results, lack of additional admission/spawn artifacts and the pinned original guard AST; reviewer did not call actor.",
            "The three controller self-kills follow planned hooks after any toy was already reaped. This is not active-child cleanup, power loss or an optimizer interruption test.",
            "Final ACTORS/admissions are snapshots; intermediate event history is supplied by explicit fixture events. External reconstruction is distinct from a final report by a killed worker.",
            "Injected zero-work namespace is not the complete original numerical controller. Nonzero reservation is synthetic metadata only and no historical UNKNOWN job or model qualification is resolved.",
            "A preliminary inventory read attempted to parse the intentionally malformed control RESULT and got JSONDecodeError; the full inspector instead checks that control as raw bytes. No fixture/process was executed by either read.",
        ],
    }
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "cases": 13,
                "workers": 13,
                "toys": 10,
                "kill_hooks": 3,
                "unknown_null_cases": 11,
                "new_fixture_or_numeric_executions": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
