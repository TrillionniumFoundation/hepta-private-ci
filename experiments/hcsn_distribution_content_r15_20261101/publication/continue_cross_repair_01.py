"""Continue only the registered LV cross after a preserved JSON-write failure.

This operational entry point uses the unchanged disk/process-group guard.
It delegates every scientific operation to the frozen cross through a scalar
JSON adapter. No training, original evaluation, online run or recovery reruns.
"""

import argparse
from pathlib import Path
import re
import shutil
import signal
import sys
import time

try:
    from . import guarded_continuation as guard
except ImportError:
    import guarded_continuation as guard


SOURCE = Path(__file__).resolve()
REPO = SOURCE.parents[3]
STUDY = SOURCE.parent.parent
MODULE = "experiments.hcsn_distribution_content_r15_20261101.publication.cross_serialization_adapter"
REPAIR_RECORD = SOURCE.parent / "CROSS_SERIALIZATION_REPAIR_01.json"
ATTEMPT = "attempts/train_execution_cross_01_serialization/PRESERVATION.json"
OPERATIONS = "operational_cross_repair_guarded_01"


def commands(output):
    return [
        ("cross_launch", [sys.executable, "-m", MODULE, "launch", "--output", str(output), "--workers", "2"]),
        ("cross_index", [sys.executable, "-m", MODULE, "index", "--output", str(output)]),
    ]


def check_repair(output, record_sha256):
    guard.require(output == STUDY / "results/formal_03", "This continuation is scoped to formal_03")
    guard.require(guard.digest(REPAIR_RECORD) == record_sha256, "Repair record differs from the published pin")
    record = guard.read(REPAIR_RECORD)
    guard.require(record["schema"] == "hcsn.r15.cross-serialization-repair.v1", "Unknown repair record schema")
    guard.require(record["post_confirmation_operational_repair"] is True, "Repair chronology is not explicit")
    guard.require(record["scientific_changes"] is False, "Scientific changes are outside this repair")
    for relative, expected in record["source_files_sha256"].items():
        path = (REPO / relative).resolve()
        guard.require(path.is_relative_to(REPO), "Unsafe repair source path")
        guard.require(guard.digest(path) == expected, "Repair source changed: " + relative)
    guard.require(guard.digest(output / ATTEMPT) == record["preservation_sha256"], "Preserved failed attempt changed")
    guard.check_identity(output)
    primary = output / "operational_continuation_guarded_01/COMPLETE.json"
    guard.require(guard.digest(primary) == record["primary_complete_sha256"], "Original primary completion changed")
    guard.require(guard.read(primary)["all_exit_zero"] is True, "Original primary stages did not complete")
    for relative, expected in record["completed_scientific_outputs_sha256"].items():
        path = (output / relative).resolve()
        guard.require(path.is_relative_to(output), "Unsafe prerequisite output path")
        guard.require(guard.digest(path) == expected, "Completed prerequisite changed: " + relative)
    return record


def run(output, operational_source_commit, repair_record_sha256):
    check_repair(output, repair_record_sha256)
    planned = commands(output)
    guard.no_existing_targets(output, planned)
    directory = output / OPERATIONS
    directory.mkdir(exist_ok=False)
    events = guard.Events(directory / "events")
    registration = dict(
        schema="hcsn.r15.cross-repair-continuation.v1", utc=guard.utc(),
        output=str(output), helper_sha256=guard.digest(SOURCE),
        operational_source_commit=operational_source_commit,
        original_report_source_commit="10e8b6e11a259bf6db14f93c1eae5f1ad7b2eff1",
        repair_record_sha256=repair_record_sha256,
        preserved_failed_attempt=ATTEMPT, commands=planned,
        low_free_bytes=guard.GIB, high_free_bytes=2 * guard.GIB,
        wall_scope=guard.WALL_NOTE, cpu_seconds=None,
        scope="Same registered 240 LV conditions; two workers; external scalar JSON conversion only. Failed execution CPU remains additional.",
    )
    guard.atomic_json(directory / "START.json", registration)
    events("cross_repair_started", **registration)
    (directory / "stages").mkdir()
    previous = {sig: signal.signal(sig, guard.interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    start = time.monotonic()
    rows = []
    try:
        for index, (name, command) in enumerate(planned, 1):
            check_repair(output, repair_record_sha256)
            guard.no_existing_targets(output, [(name, command)])
            rows.append(guard.execute_stage(
                directory / "stages" / f"{index:02d}_{name}", name, command, events,
                lambda: shutil.disk_usage(output).free, guard.GIB, 2 * guard.GIB,
                poll=.25, cwd=REPO,
            ))
        guard.atomic_json(directory / "STAGES.json", rows)
        complete = dict(
            utc=guard.utc(), stages=len(rows), all_exit_zero=True,
            elapsed_span_seconds=time.monotonic() - start,
            stage_pause_seconds=sum(row["pause_seconds"] for row in rows),
            wall_scope=guard.WALL_NOTE, cpu_seconds=None,
            note="Completion is not a claim of positive scientific effects.",
        )
        guard.atomic_json(directory / "COMPLETE.json", complete)
        events("cross_repair_complete", **complete)
    except BaseException as error:
        failure = dict(utc=guard.utc(), error=repr(error), all_exit_zero=False, wall_scope=guard.WALL_NOTE)
        try:
            guard.atomic_json(directory / "FAILURE.json", failure)
            events("cross_repair_failed", **failure)
        except (OSError, ValueError):
            pass
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operational-source-commit")
    parser.add_argument("--repair-record-sha256")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(commands(args.output.resolve()), indent=2))
    else:
        if re.fullmatch(r"[0-9a-f]{40}", args.operational_source_commit or "") is None:
            parser.error("A published 40-character operational source commit is required")
        if re.fullmatch(r"[0-9a-f]{64}", args.repair_record_sha256 or "") is None:
            parser.error("The published repair record SHA256 is required")
        run(args.output.resolve(), args.operational_source_commit, args.repair_record_sha256)
