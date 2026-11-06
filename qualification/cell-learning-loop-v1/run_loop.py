"""Run the frozen source-correction loop with complete subprocess accounting."""

import resource
import time

START = time.perf_counter()
USAGE = resource.getrusage(resource.RUSAGE_SELF)
CHILDREN = resource.getrusage(resource.RUSAGE_CHILDREN)

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from loop_common import frozen, identity, read, write
from prepare_run import PHASES, prepare
from receipt_verifier import decode_receipt, nonnegative_number, read_capture, verify_completed_receipt


HERE = Path(__file__).resolve().parent


def measured_total(records, key):
    values = [row.get("parent_observed", {}).get(key)
              if type(row.get("parent_observed")) is dict else None for row in records]
    return sum(values) if all(nonnegative_number(value) for value in values) else None


def main(args):
    run = args.output.resolve()
    if not run.is_relative_to(HERE):
        raise ValueError("Evidence must stay inside this qualification directory")
    invocation = len(list(run.glob("orchestrator-*.json"))) + 1
    failure = None
    try:
        if not args.resume:
            prepare(run, args.donor.resolve(), args.model_dir.resolve(), HERE)
        elif not run.is_dir():
            raise ValueError("No frozen run exists to resume")
        plan = frozen(run)
        if tuple(PHASES) != tuple(plan["phases"]):
            raise ValueError("Driver phase schedule differs from the frozen protocol")
        for name in ("run_loop.py", "prepare_run.py", "loop_common.py", "receipt_verifier.py"):
            if identity(HERE / name) != identity(run / "EXECUTED_SOURCE" / name):
                raise ValueError("Executing driver/helper changed since freeze: " + name)
        for directory in (run / "attempts", run / "phase_results"):
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise ValueError("Invalid phase evidence directory; no implicit retry: " + directory.name)
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1",
                       "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
        for phase in PHASES:
            prior_path = run / "phase_results" / (phase + ".json")
            if prior_path.exists() or prior_path.is_symlink():
                try:
                    prior = decode_receipt(read_capture(prior_path))
                    verify_completed_receipt(run, phase, prior)
                except (OSError, ValueError) as error:
                    raise ValueError("A failed or unverified attempt is preserved; no implicit retry: "
                                     + phase + ": " + str(error)) from error
                if phase == args.stop_after:
                    break
                continue
            frozen(run)
            attempt = run / "attempts" / phase
            marker = run / "TRAINING_STARTED.json"
            if (attempt.exists() or attempt.is_symlink()
                    or (phase == "train" and (marker.exists() or marker.is_symlink()))):
                raise ValueError("An attempt has no verified completion; no implicit retry: " + phase)
            attempt.mkdir(parents=True, exist_ok=False)
            started_at = datetime.now(timezone.utc).isoformat()
            started = time.perf_counter()
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            command = [sys.executable, "-B", str(run / "EXECUTED_SOURCE/loop_worker.py"), str(run), phase]
            try:
                child = subprocess.run(command, capture_output=True, timeout=plan["child_deadline_seconds"],
                                       env=environment, cwd=run)
                stdout, stderr, returncode = child.stdout, child.stderr, child.returncode
            except subprocess.TimeoutExpired as error:
                stdout, stderr, returncode = error.stdout or b"", error.stderr or b"", None
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            (attempt / "stdout.txt").write_bytes(stdout)
            (attempt / "stderr.txt").write_bytes(stderr)
            try:
                receipt = decode_receipt(stdout)
            except (ValueError, UnicodeError):
                receipt = {"status": "failed", "phase": phase, "error": "no complete worker receipt"}
            receipt["parent_observed"] = {
                "returncode": returncode, "wall_seconds": time.perf_counter() - started,
                "started_at_utc": started_at, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "cpu_user_seconds": after.ru_utime - before.ru_utime,
                "cpu_system_seconds": after.ru_stime - before.ru_stime,
                "scope": "entire direct child including interpreter startup and failures",
                "stdout": identity(attempt / "stdout.txt"), "stderr": identity(attempt / "stderr.txt")}
            receipt["protocol_sha256"] = identity(run / "PROTOCOL.json")["sha256"]
            try:
                verify_completed_receipt(run, phase, receipt)
            except (OSError, ValueError) as error:
                receipt["status"] = "failed"
                receipt["receipt_validation_error"] = str(error)
            write(prior_path, receipt)
            print(json.dumps({"phase": phase, "status": receipt["status"], "pid": receipt.get("pid")}), flush=True)
            if receipt["status"] != "completed":
                raise RuntimeError("Lifecycle phase did not pass: " + phase)
            if phase == args.stop_after:
                break
    except BaseException as error:
        failure = error
        if run.is_dir():
            write(run / f"failure-{invocation:02d}.json", {
                "error": type(error).__name__, "message": str(error),
                "training_attempt_marker_present": (run / "TRAINING_STARTED.json").exists()})
    finally:
        after = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(run / f"orchestrator-{invocation:02d}.json", {
            "pid": os.getpid(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": time.perf_counter() - START,
            "cpu_user_seconds": after.ru_utime - USAGE.ru_utime,
            "cpu_system_seconds": after.ru_stime - USAGE.ru_stime,
            "peak_rss_bytes": after.ru_maxrss * 1024,
            "all_child_cpu_user_seconds": children.ru_utime - CHILDREN.ru_utime,
            "all_child_cpu_system_seconds": children.ru_stime - CHILDREN.ru_stime,
            "driver_source": identity(Path(__file__)),
            "scope": "measured preparation/orchestration interval; child CPU separate; outer wait4 covers startup and finalization"})
    records, completed, unverified = [], set(), {}
    for path in sorted((run / "phase_results").glob("*.json")):
        try:
            row = decode_receipt(read_capture(path))
        except (OSError, ValueError) as error:
            row = {"phase": path.stem, "status": "unverified"}
            unverified[path.stem] = str(error)
        records.append(row)
        try:
            if path.stem not in PHASES:
                raise ValueError("unexpected phase receipt")
            verify_completed_receipt(run, path.stem, row)
        except (OSError, ValueError) as error:
            unverified.setdefault(path.stem, str(error))
        else:
            completed.add(path.stem)
    if unverified and failure is None:
        failure = ValueError("Unverified phase receipts are preserved; no implicit retry: "
                             + ", ".join(sorted(unverified)))
    orchestration = [read(path) for path in sorted(run.glob("orchestrator-*.json"))]
    final = completed == set(PHASES) and failure is None
    child_user = measured_total(records, "cpu_user_seconds")
    child_system = measured_total(records, "cpu_system_seconds")
    missing_rss = [r.get("phase") for r in records if type(r.get("worker_metrics")) is not dict
                   or type(r["worker_metrics"].get("peak_rss_bytes")) is not int
                   or r["worker_metrics"]["peak_rss_bytes"] <= 0]
    summary = {"schema": "hepta.cell-learning.engineering.result.v1", "engineering_passed": final,
               "completed_phases": sorted(completed), "unverified_phase_receipts": unverified,
               "distinct_worker_pids": sorted({r["pid"] for r in records if type(r.get("pid")) is int and r["pid"] > 0}),
               "worker_instance_ids": [r.get("process_instance_id") for r in records],
               "protocol_sha256": identity(run / "PROTOCOL.json")["sha256"] if (run / "PROTOCOL.json").exists() else None,
               "failed_invocation": None if failure is None else {"error": type(failure).__name__, "message": str(failure)},
               "scientific_benefit_claimed": False, "formal_future_adoption_qualified": False,
               "natural_future_source_groups": 0, "training_attempts": int((run / "TRAINING_STARTED.json").exists()),
               "measured_cost": {"worker_cpu_user_seconds": child_user, "worker_cpu_system_seconds": child_system,
                   "worker_wall_seconds": measured_total(records, "wall_seconds"),
                   "parent_cpu_user_seconds": sum(x["cpu_user_seconds"] for x in orchestration),
                   "parent_cpu_system_seconds": sum(x["cpu_system_seconds"] for x in orchestration),
                   "all_child_cpu_seconds": sum(x["all_child_cpu_user_seconds"] + x["all_child_cpu_system_seconds"] for x in orchestration),
                   "peak_worker_rss_bytes": None if missing_rss or not records else max(r["worker_metrics"]["peak_rss_bytes"] for r in records),
                   "unmeasured_worker_rss_phases": missing_rss,
                   "retained_new_run_bytes_at_snapshot": sum(p.stat().st_size for p in run.rglob("*") if p.is_file()),
                   "energy_joules": None, "historical_acquisition": None, "billed_usd": None,
                   "full_retained_byte_seconds": None, "host_network_bytes": None, "p99_seconds": None},
               "cost_scope": "new run includes every attempted subprocess and each orchestration invocation; unknowns are not zero",
               "limitations": ["authored Cedar engineering task, not observed future traffic",
                               "parent never trained on the superseded Cedar label",
                               "final skills revision changes provenance only; labels unchanged",
                               "nine-arm formal gate not invoked or weakened",
                               "no benefit/cost superiority or full-cost admission established"]}
    name = f"FAILED-{invocation:02d}.json" if failure is not None else ("SUMMARY.json" if final else f"PREFLIGHT-{invocation:02d}.json")
    write(run / name, summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", choices=PHASES, default="fence")
    main(parser.parse_args())
