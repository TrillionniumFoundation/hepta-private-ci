"""Single-process scalar worker with complete wait4 costs and fail-closed caps."""

import time

STARTED = time.monotonic()

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import traceback
import zipfile


WALL, MEMORY = 120., 268435456


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def verify(program, digest):
    path = program / "PROGRAM-MANIFEST.json"
    require(identity(path)["sha256"] == digest, "manifest SHA changed")
    entries = json.loads(path.read_text())["files"]
    for name, expected in entries.items():
        path = program / name
        require(path.resolve().is_relative_to(program) and not path.is_symlink(), "unsafe source")
        require(identity(path) == expected, "source bytes changed")
    return entries


def rss(pid):
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        return next((int(line.split()[1]) * 1024 for line in status.splitlines() if line.startswith("VmRSS:")), 0)
    except FileNotFoundError:
        return 0


def child_limits():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))


def main(args):
    program, output = args.program.resolve(), args.output.resolve()
    require(not output.exists(), "exclusive execution directory already exists; no retry")
    entries = verify(program, args.manifest_sha256)
    roster = json.loads((program / "ROSTER.json").read_text())["cases"]
    output.mkdir(exist_ok=False)
    work = output / "worker"
    work.mkdir()
    save(output / "INTENT.json", {"schema": "hcsn-fixed48-single-launch-intent-v1", "key": "hcsn-p1-short-time-scalar-c385-v1", "program_manifest_sha256": args.manifest_sha256, "whole_wall_cap_seconds": WALL, "memory_cap_bytes": MEMORY, "roster": roster, "automatic_retry": False})
    report = {"schema": "hcsn-fixed48-whole-child-execution-v1", "process_started": False, "spawn_attempted": False, "exit_code": None,
              "whole_wall_cap_seconds": WALL, "memory_cap_bytes": MEMORY, "program_manifest_sha256": args.manifest_sha256,
              "child_full_wall_seconds": None, "child_wait4_CPU_seconds": None, "child_peak_RSS_bytes": None,
              "sampled_combined_RSS_bytes": 0, "roster_count": len(roster), "scientific_admission": "HOLD", "training_domain_admission": "HOLD"}
    process, usage, child_started = None, None, None
    timed_out, cap_reason, failure = False, None, None
    try:
        grant = WALL - (time.monotonic() - STARTED)
        require(grant > 0, "whole budget exhausted before dispatch")
        command = [sys.executable, "-B", str(program / "run_toys.py"), "--program", str(program), "--output", str(work), "--manifest-sha256", args.manifest_sha256, "--wall-seconds", str(grant)]
        report["command"] = command
        env = dict(os.environ, PYTHONHASHSEED="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        with (output / "stdout").open("xb") as stdout, (output / "stderr").open("xb") as stderr:
            child_started = time.monotonic()
            report["spawn_attempted"] = True
            # Keep the worker in the external timeout process group. This
            # stdlib-only worker creates no descendants; only its PID is killed
            # by the inner monitor, and the120s shell timeout can kill all.
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, preexec_fn=child_limits)
            report.update(process_started=True, pid=process.pid)
            save(output / "STARTED.json", {"pid": process.pid, "command": command, "program_manifest_sha256": args.manifest_sha256})
            while True:
                waited, wait_status, waited_usage = os.wait4(process.pid, os.WNOHANG)
                if waited:
                    usage = waited_usage
                    process.returncode = os.waitstatus_to_exitcode(wait_status)
                    report["exit_code"] = process.returncode
                    break
                combined = rss(os.getpid()) + rss(process.pid)
                report["sampled_combined_RSS_bytes"] = max(report["sampled_combined_RSS_bytes"], combined)
                if time.monotonic() - STARTED >= WALL or combined > MEMORY:
                    timed_out = time.monotonic() - STARTED >= WALL
                    cap_reason = "whole_wall" if timed_out else "combined_RSS"
                    os.kill(process.pid, signal.SIGKILL)
                    _, wait_status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(wait_status)
                    report["exit_code"] = process.returncode
                    break
                time.sleep(.005)
        report["child_full_wall_seconds"] = time.monotonic() - child_started
        require(not cap_reason and process.returncode == 0, "worker failed or exceeded cap")
        worker_path = work / "RESULT.json"
        require(worker_path.is_file(), "rc0 without result artifact")
        worker = json.loads(worker_path.read_text())
        require(worker["status"] == "completed_fixed48_scalar_roster" and worker["computed_cases"] == 48, "incomplete scalar roster")
        require(worker["program_manifest_sha256"] == args.manifest_sha256 and worker["source_unchanged"] is True, "worker source identity failure")
        require([row["id"] for row in worker["cases"]] == [row["id"] for row in roster], "case identity/order mismatch")
        journal = [json.loads(line) for line in (work / "cases.jsonl").read_text().splitlines()]
        require(journal == worker["cases"], "case journal differs from result")
        require(worker["model_oracle_training_calls"] == 0 and worker["model_probability_or_E_access"] is False, "wrong execution scope")
        report["worker_result_identity"] = identity(worker_path)
        report["model_oracle_E_operations"] = 0
    except Exception:
        failure = traceback.format_exc()
    finally:
        if process is not None and process.returncode is None:
            try:
                os.kill(process.pid, signal.SIGKILL)
                _, wait_status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(wait_status)
                report["exit_code"] = process.returncode
            except Exception:
                report["cleanup_error"] = traceback.format_exc()
            report["child_full_wall_seconds"] = time.monotonic() - child_started
        if usage is not None:
            report.update(child_wait4_CPU_seconds=usage.ru_utime + usage.ru_stime,
                          child_user_CPU_seconds=usage.ru_utime, child_system_CPU_seconds=usage.ru_stime,
                          child_peak_RSS_bytes=usage.ru_maxrss * 1024)
        else:
            report["child_CPU_completeness"] = "unknown_if_spawn_attempted"
        own_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        report["own_peak_RSS_bytes"] = own_peak
        report["sum_of_per_process_peak_RSS_upper_bound_bytes"] = own_peak + (report["child_peak_RSS_bytes"] or 0)
        try:
            require(verify(program, args.manifest_sha256) == entries, "source changed at completion")
            report["source_unchanged"] = True
        except Exception:
            report["source_unchanged"] = False
            failure = (failure or "") + traceback.format_exc()
        if report["sum_of_per_process_peak_RSS_upper_bound_bytes"] > MEMORY:
            failure = (failure or "") + "\nConservative combined peak upper bound exceeds memory cap."
        if time.monotonic() - STARTED > WALL:
            failure = (failure or "") + "\nWhole wall exceeded envelope."
        report.update(status="admitted_scalar_execution_only" if failure is None else "failed_or_unknown_preserved_no_retry",
                      error=failure, resource_stop_reason=cap_reason, whole_wall_prefix_seconds=time.monotonic() - STARTED,
                      own_CPU_prefix_seconds=time.process_time(), automatic_retry=False,
                      cost_scope="wait4 CPU and child wall include complete worker import/computation/serialization/exit. Per-case timers nest inside these. Launcher own CPU is separate; external GNU covers complete launcher plus waited child and overlaps those views.")
        observed = {}
        if (work / "cases.jsonl").is_file():
            for line in (work / "cases.jsonl").read_text().splitlines():
                try:
                    row = json.loads(line)
                    observed[row["id"]] = row
                except (json.JSONDecodeError, KeyError):
                    break
        report["fixed_case_admission_roster"] = [{"id": case["id"], "observed_execution_status": observed.get(case["id"], {}).get("execution_status", "unobserved_not_assumed_unrun" if report["process_started"] else "unrun_launch_failed")} for case in roster]
        save(output / "EXECUTION.json", report)
    archive = output.with_suffix(".zip")
    archive_receipt = {"schema": "hcsn-fixed48-archive-receipt-v1", "archive_finalized": False, "program_manifest_sha256": args.manifest_sha256}
    try:
        require(failure is None, "execution did not admit; raw output remains preserved")
        members = {}
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for prefix, directory in (("program", program), ("execution", output)):
                for path in sorted(directory.rglob("*")):
                    if path.is_file():
                        member = prefix + "/" + str(path.relative_to(directory))
                        members[member] = identity(path)
                        zipped.write(path, member)
            zipped.writestr("MEMBER-MANIFEST.json", json.dumps(members, sort_keys=True) + "\n")
        with zipfile.ZipFile(archive) as zipped:
            require(zipped.testzip() is None and len(zipped.namelist()) == len(members) + 1, "ZIP integrity failure")
            for member, expected in members.items():
                payload = zipped.read(member)
                require({"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} == expected, "ZIP member mismatch")
        require(verify(program, args.manifest_sha256) == entries, "source changed during archive")
        archive_receipt["post_archive_combined_peak_RSS_upper_bound_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 + (report["child_peak_RSS_bytes"] or 0)
        require(archive_receipt["post_archive_combined_peak_RSS_upper_bound_bytes"] <= MEMORY, "archive phase exceeded memory bound")
        require(time.monotonic() - STARTED <= WALL, "archive verification exceeded whole envelope")
        archive_receipt.update(archive_finalized=True, archive={"path": str(archive), **identity(archive)}, members=len(members) + 1)
    except Exception:
        archive_receipt["error"] = traceback.format_exc()
    archive_receipt.update(whole_wall_prefix_seconds=time.monotonic() - STARTED,
                           finality="External complete process terminal/GNU time must also satisfy the120s cap; internal flag is not sufficient.")
    save(output / "ARCHIVE-RECEIPT.json", archive_receipt)
    print(json.dumps({"status": report["status"], "archive_finalized": archive_receipt["archive_finalized"]}), flush=True)
    return 0 if failure is None and archive_receipt["archive_finalized"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    raise SystemExit(main(parser.parse_args()))
