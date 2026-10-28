"""Verify the external serial continuation ledger without launching children."""

import json

from online_audit_common import canonical, check, close, sha
from run_remaining import plan_cases


def audit_remaining_execution(study, package, protocol, seals):
    jobs = json.loads((package / "RUNS.json").read_text())
    plan = plan_cases(jobs, protocol)
    by_id = {case["id"]: case for case in plan}
    invocations = sorted(study.glob("REMAINING_START_*.json"))
    check(bool(invocations), "external continuation controller invocation")
    starts = {}
    for path in invocations:
        row = json.loads(path.read_text())
        check(row["source_seals"] == seals, "continuation scientific source identity")
        check(row["inventory_sha256"] == canonical(jobs), "continuation inventory SHA")
        check(
            row["case_plan_sha256"] == canonical(plan) and row["cases"] == plan,
            "outcome-independent 5+55 continuation plan",
        )
        check(
            row["min_memory_mb"] >= 450 and row["min_disk_mb"] >= 1,
            "resource scheduling guards",
        )
        index = int(path.stem.rsplit("_", 1)[1])
        starts[index] = row
    readiness = sorted(study.glob("REMAINING_TRAINING_READY_*.json"))
    check(bool(readiness), "verified training-ready gate")
    last_training_end = 0.0
    for path in readiness:
        ready = json.loads(path.read_text())
        check(
            ready["source_seals"] == seals
            and ready["inventory_sha256"] == canonical(jobs),
            "training-ready identities",
        )
        check(
            set(ready["verified_jobs"]) == {row["id"] for row in jobs},
            "all 215 top-level training jobs gated",
        )
        check(
            ready["training_lock_held_until_continuation_exit"],
            "declared training/continuation exclusion",
        )
        for case, identity in ready["verified_jobs"].items():
            directory = study / case
            check(
                not (directory / "FAILED.json").exists(), "no current training failure"
            )
            check(
                sha(directory / "RESULT.json") == identity["result_sha256"],
                "gated training result unchanged",
            )
            receipt_path = study / identity["execution_path"]
            check(
                sha(receipt_path) == identity["execution_sha256"],
                "gated external training receipt unchanged",
            )
            receipt = json.loads(receipt_path.read_text())
            check(
                receipt["id"] == case
                and receipt["exit_code"] == 0
                and receipt["result_exists"],
                "successful exact training child",
            )
            last_training_end = max(last_training_end, receipt["ended_unix"])
    rows, current = [], {}
    for path in (study / "remaining_execution").rglob("EXECUTION_*.json"):
        row = json.loads(path.read_text())
        case = row["id"]
        check(
            case in by_id and row["source_seals"] == seals,
            "planned continuation child identity",
        )
        start_path = path.parent / f"ATTEMPT_START_{row['attempt']:02d}.json"
        started = json.loads(start_path.read_text())
        check(
            all(row[key] == value for key, value in started.items()),
            "exact attempted command/PID/start evidence",
        )
        close(
            row["child_cpu_seconds"],
            row["child_user_cpu_seconds"] + row["child_system_cpu_seconds"],
            "exact wait4 user/system CPU arithmetic",
            atol=0,
            rtol=0,
        )
        check(
            row["wall_seconds"] >= 0 and row["child_cpu_seconds"] >= 0,
            "nonnegative external costs",
        )
        check(
            row["ended_unix"] >= row["started_unix"] >= last_training_end,
            "remaining work starts after training exits",
        )
        check(
            row["command"][1] == "-m" and "--development" not in row["command"],
            "frozen formal CLI invocation",
        )
        descriptor = by_id[case]
        expected_module = (
            "boundary_online" if descriptor["kind"] == "boundary" else "stream_measure"
        )
        check(
            row["command"][2]
            == "experiments.continuous_spiking_followup." + expected_module,
            "actual frozen experiment entry point",
        )
        check(
            ("--cross-process" in row["command"])
            == descriptor.get("cross_process", False),
            "seven preselected child replays",
        )
        check(
            ("--native-binary" in row["command"])
            == (
                descriptor["kind"] == "boundary"
                and descriptor["seed"] == protocol["boundary"]["native"]["actor_seed"]
            ),
            "native owner only in prespecified actor case",
        )
        enriched = {
            **row,
            "receipt_path": str(path.relative_to(study)),
            "receipt_sha256": sha(path),
        }
        rows.append(enriched)
        if case not in current or row["attempt"] > current[case]["attempt"]:
            current[case] = enriched
    check(set(current) == set(by_id), "all 60 current continuation receipts")
    ordered = sorted(rows, key=lambda item: item["started_unix"])
    for previous, following in zip(ordered, ordered[1:]):
        check(
            following["started_unix"] >= previous["ended_unix"],
            "serial remaining children do not overlap",
        )
    for case, row in current.items():
        check(
            row["exit_code"] == 0
            and row["result_exists"]
            and not row["failed_marker_exists"],
            "current continuation attempt succeeded",
        )
        output = study / case
        result_path = output / by_id[case]["result_name"]
        check(
            sha(result_path) == row["result_sha256"],
            "external receipt binds current complete result",
        )
        check(
            json.loads((output / f"EXECUTION_{row['attempt']:02d}.json").read_text())
            == {
                key: value
                for key, value in row.items()
                if key not in {"receipt_path", "receipt_sha256"}
            },
            "outer execution receipt equals immutable ledger",
        )
    failed = [
        row
        for row in rows
        if row["exit_code"] != 0
        or not row["result_exists"]
        or row["failed_marker_exists"]
    ]
    return {
        "invocations": len(starts),
        "planned_cases": len(plan),
        "current_successful_cases": len(current),
        "all_attempts": len(rows),
        "failed_attempts": failed,
        "all_attempt_child_cpu_seconds": sum(row["child_cpu_seconds"] for row in rows),
        "all_attempt_child_wall_seconds": sum(row["wall_seconds"] for row in rows),
        "all_attempts_serial": True,
        "last_training_child_ended_unix": last_training_end,
        "first_remaining_child_started_unix": ordered[0]["started_unix"],
        "receipts": rows,
        "scope": "POSIX wait4 direct-child CPU may include descendants that child reaped; do not add nested native or replay child CPU again. All attempts are retained; launch-to-reap wall includes startup/shutdown.",
    }
