"""Linux wait4 receipts for whole worker commands; no neural-library imports.

Usage: python -m experiments.hcsn_task_value_v1.cost_meter --output NEW.json -- COMMAND ARGS
The child clock includes startup, imports, training, evaluation, checkpoints and
any codecs run by COMMAND. Inner training clocks are subtotals, never additions.
Linux /proc I/O is sampled before exit and is explicitly a measured lower bound;
wait4 block-operation counts are reported without inventing byte conversions.
"""

import argparse
from datetime import datetime, timezone
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def meter_command(command, output, timeout_seconds=None):
    if not hasattr(os, "wait4") or not Path("/proc/self/io").exists():
        raise RuntimeError("This meter requires Linux wait4 and /proc")
    if not command or (timeout_seconds is not None and
                       (not math.isfinite(timeout_seconds) or timeout_seconds <= 0)):
        raise ValueError("A command and a positive optional timeout are required")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix(output.suffix + ".log")
    if output.exists() or log.exists():
        raise FileExistsError("Meter receipts and failure logs may not be overwritten")
    usage = None
    timed_out, termination_at, io_samples, io_max, spawn_error = False, None, 0, {}, None
    io_errors = {}
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()
    with log.open("xb") as stream:
        try:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        except OSError as error:
            spawn_error = f"{type(error).__name__}: {error}"
            stream.write((spawn_error + "\n").encode())
            returncode = 127
        else:
            while True:
                try:
                    counters = dict(line.split(":", 1) for line in
                                    Path(f"/proc/{process.pid}/io").read_text().splitlines())
                    for key, value in counters.items():
                        io_max[key] = max(io_max.get(key, 0), int(value.strip()))
                    io_samples += 1
                except (OSError, ValueError) as error:
                    reason = f"{type(error).__name__}: {error}"
                    io_errors[reason] = io_errors.get(reason, 0) + 1
                waited, status, usage = os.wait4(process.pid, os.WNOHANG)
                if waited:
                    returncode = os.waitstatus_to_exitcode(status)
                    process.returncode = returncode
                    break
                now = time.perf_counter()
                if timeout_seconds is not None and now - started >= timeout_seconds:
                    timed_out = True
                    if termination_at is None or now - termination_at >= 5:
                        try:
                            os.killpg(process.pid, signal.SIGTERM if termination_at is None else signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        termination_at = now if termination_at is None else termination_at
                time.sleep(.01)
    after = resource.getrusage(resource.RUSAGE_SELF)
    wall = time.perf_counter() - started
    child_user, child_system = (usage.ru_utime, usage.ru_stime) if usage is not None else (None, None)
    supervisor = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    receipt = dict(schema="hcsn-whole-process-cost.v1", command=list(command), cwd=os.getcwd(),
        started_at_utc=started_utc, ended_at_utc=datetime.now(timezone.utc).isoformat(),
        returncode=returncode, spawn_error=spawn_error, timed_out=timed_out, child_reaped=usage is not None,
        wall_seconds=wall, child_user_seconds=child_user, child_system_seconds=child_system,
        child_cpu_seconds=None if usage is None else child_user + child_system,
        supervisor_cpu_seconds=supervisor,
        child_peak_rss_bytes=None if usage is None else usage.ru_maxrss * 1024,
        block_input_operations=None if usage is None else usage.ru_inblock,
        block_output_operations=None if usage is None else usage.ru_oublock,
        io_samples=io_samples, io_sampled_maxima=io_max or None, io_error_counts=io_errors,
        bytes_read_observed_lower_bound=io_max.get("read_bytes"),
        bytes_written_observed_lower_bound=io_max.get("write_bytes"),
        logical_read_characters_observed_lower_bound=io_max.get("rchar"),
        logical_write_characters_observed_lower_bound=io_max.get("wchar"),
        stdout_stderr_bytes=log.stat().st_size, log_path=str(log),
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
        meter_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        nvidia_devices=glob.glob("/dev/nvidia*"),
        readable_rapl_interfaces=[p for p in glob.glob("/sys/class/powercap/**/energy_uj", recursive=True)
                                  if os.access(p, os.R_OK)],
        direct_energy_joules=None, gpu_energy_joules=None, communication_energy_joules=None,
        energy_measurement_status="unmeasured; no conversion from CPU time, event counts or local I/O",
        io_scope="Maximum observed /proc child counters before reap; may miss final I/O; not certified complete descendant traffic",
        cpu_scope="wait4 worker including startup/imports/all phases and descendants it reaped; detached or unreaped descendants are outside verified scope",
        rss_scope="Linux wait4 maximum RSS; not the sum of simultaneous descendant resident sets",
        supervisor_scope="Launch and polling through child reaping; receipt serialization is outside this clock",
        excluded=["Meter interpreter startup/imports before entry", "Environment installation",
                  "Work outside COMMAND", "External network services/infrastructure"],
        inner_training_clocks_are_subtotals=True,
        abnormal_exit_descendant_accounting_complete=False if returncode != 0 else None)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    receipt = meter_command(command, args.output, args.timeout_seconds)
    print(json.dumps({key: receipt[key] for key in
                      ("returncode", "wall_seconds", "child_cpu_seconds", "child_peak_rss_bytes")}))
    raise SystemExit(receipt["returncode"] if receipt["returncode"] >= 0 else 128 - receipt["returncode"])


if __name__ == "__main__":
    main()
