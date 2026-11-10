"""Authorized infrastructure correction after missing GNU time; no math changes."""

import time

START = time.monotonic()

import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import traceback


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
PROGRAM = WORK / "p1-short-time-toy-program-v1"
OUTPUT = WORK / "p1-short-time-toy-execution-v2"
MANIFEST_SHA = "8b7015a93d3da6f158b11e330b3dc7e5af5d01a4521585e5f7578a7e1842e966"
WALL, MEMORY = 120., 268435456


def ident(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def save(name, value):
    with (ROOT / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def require(value, message):
    if not value:
        raise ValueError(message)


def owned_descendants(pid):
    result = []
    path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        children = [int(value) for value in path.read_text().split()]
    except FileNotFoundError:
        return result
    for child in children:
        result.extend(owned_descendants(child))
        result.append(child)
    return result


def rss(pid):
    try:
        return next((int(line.split()[1]) * 1024 for line in Path(f"/proc/{pid}/status").read_text().splitlines() if line.startswith("VmRSS:")), 0)
    except FileNotFoundError:
        return 0


def kill_tree(pid):
    for target in owned_descendants(pid) + [pid]:
        try:
            os.kill(target, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    require(not OUTPUT.exists() and not (ROOT / "RESULT.json").exists(), "attempt2 already started; no retry")
    require(ident(PROGRAM / "PROGRAM-MANIFEST.json")["sha256"] == MANIFEST_SHA, "math program manifest changed")
    own_source_before = ident(Path(__file__))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    command = [sys.executable, "-B", str(PROGRAM / "launch_once.py"), "--program", str(PROGRAM), "--output", str(OUTPUT), "--manifest-sha256", MANIFEST_SHA]
    report = {"schema": "hcsn-fixed48-external-wait4-infrastructure-v2", "infrastructure_attempt": 2, "first_infrastructure_exit": 127,
              "first_infrastructure_scalar_cases": 0, "intended_mathematical_execution_number": 1,
              "mathematical_program_manifest_sha256": MANIFEST_SHA, "command": command,
              "whole_wall_limit_seconds": WALL, "whole_RSS_limit_bytes": MEMORY,
              "outer_timeout": "External/usr/bin/timeout --signal=KILL120s over this wrapper and inherited process group",
              "spawn_attempted": False, "launcher_process_started": False, "launcher_exit_code": None,
              "complete_launcher_wall_seconds": None, "launcher_wait4_CPU_seconds": None, "launcher_wait4_peak_RSS_bytes": None,
              "sampled_combined_RSS_bytes": 0, "numeric_retry": False,
              "GNU_time_available": False, "replacement": "raw wait4 full-launcher process interval and rusage",
              "source_before": own_source_before, "scientific_admission": "HOLD", "training_domain_admission": "HOLD"}
    process, usage, child_started, error, stopped = None, None, None, None, None
    try:
        save("START-INTENT.json", report)
        with (ROOT / "launcher.stdout").open("xb") as stdout, (ROOT / "launcher.stderr").open("xb") as stderr:
            child_started = time.monotonic()
            report["spawn_attempted"] = True
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            report.update(launcher_process_started=True, launcher_pid=process.pid)
            save("STARTED.json", {"pid": process.pid, "program_manifest_sha256": MANIFEST_SHA, "source": own_source_before})
            while True:
                waited, status, observed = os.wait4(process.pid, os.WNOHANG)
                if waited:
                    usage = observed
                    process.returncode = os.waitstatus_to_exitcode(status)
                    report["launcher_exit_code"] = process.returncode
                    break
                combined = sum(rss(pid) for pid in [os.getpid(), process.pid] + owned_descendants(process.pid))
                report["sampled_combined_RSS_bytes"] = max(report["sampled_combined_RSS_bytes"], combined)
                if time.monotonic() - START >= WALL or combined > MEMORY:
                    stopped = "whole_wall" if time.monotonic() - START >= WALL else "combined_RSS"
                    kill_tree(process.pid)
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    report["launcher_exit_code"] = process.returncode
                    break
                time.sleep(.002)
        report["complete_launcher_wall_seconds"] = time.monotonic() - child_started
        require(process.returncode == 0 and stopped is None, "launcher failed or resource-stopped; no numerical retry")
        execution = json.loads((OUTPUT / "EXECUTION.json").read_text())
        archive = json.loads((OUTPUT / "ARCHIVE-RECEIPT.json").read_text())
        require(execution["status"] == "admitted_scalar_execution_only" and execution["source_unchanged"] is True, "worker/source admission failure")
        require(archive["archive_finalized"] is True and ident(Path(archive["archive"]["path"])) == {key: archive["archive"][key] for key in ("bytes", "sha256")}, "archive incomplete")
        report["execution_receipt"] = ident(OUTPUT / "EXECUTION.json")
        report["archive_receipt"] = ident(OUTPUT / "ARCHIVE-RECEIPT.json")
        report["archive"] = archive["archive"]
        report["inner_complete_worker_wall_seconds"] = execution["child_full_wall_seconds"]
        report["inner_complete_worker_CPU_seconds"] = execution["child_wait4_CPU_seconds"]
        peak_bound = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 + archive["post_archive_combined_peak_RSS_upper_bound_bytes"])
        report["conservative_all_three_process_peak_RSS_upper_bound_bytes"] = peak_bound
        require(peak_bound <= MEMORY, "whole memory upper bound exceeds cap")
        require(report["complete_launcher_wall_seconds"] <= WALL and time.monotonic() - START <= WALL, "whole wall cap exceeded")
        require(ident(PROGRAM / "PROGRAM-MANIFEST.json")["sha256"] == MANIFEST_SHA and ident(Path(__file__)) == own_source_before, "source identity changed")
    except Exception:
        error = traceback.format_exc()
    finally:
        if process is not None and process.returncode is None:
            try:
                kill_tree(process.pid)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                report["launcher_exit_code"] = process.returncode
            except Exception:
                report["cleanup_error"] = traceback.format_exc()
            report["complete_launcher_wall_seconds"] = time.monotonic() - child_started
        if usage is not None:
            report.update(launcher_wait4_CPU_seconds=usage.ru_utime + usage.ru_stime,
                          launcher_user_CPU_seconds=usage.ru_utime, launcher_system_CPU_seconds=usage.ru_stime,
                          launcher_wait4_peak_RSS_bytes=usage.ru_maxrss * 1024)
        report.update(status="admitted_first_scalar_execution_after_preserved_infrastructure_failure" if error is None else "failed_or_unknown_no_more_numeric_runs",
                      error=error, resource_stop=stopped, possible_unreaped_descendant_CPU_not_measured=stopped is not None or "cleanup_error" in report,
                      own_CPU_prefix_seconds=time.process_time(), whole_wall_prefix_seconds=time.monotonic() - START,
                      own_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      cost_scope="The complete launcher wait4 interval includes its own source checks, worker, archive and exit. It overlaps inner worker costs; do not sum. Wrapper own CPU prefix is additional, with final receipt-write/exit tail not included. First missing-time attempt has separately retained unknown complete CPU/wall.")
        save("RESULT.json", report)
        print(json.dumps({"status": report["status"], "launcher_exit": report["launcher_exit_code"], "complete_launcher_wall_seconds": report["complete_launcher_wall_seconds"]}), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
