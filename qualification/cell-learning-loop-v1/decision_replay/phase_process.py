"""Bound one owned replay child while retaining failure and unknown costs."""

import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def run_phase(command, log, environment, *, wall_seconds, cleanup_seconds):
    for value in (wall_seconds, cleanup_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Phase deadlines must be finite positive numbers")
    started = time.monotonic()
    completion_deadline = started + wall_seconds
    deadline = completion_deadline
    timed_out = False
    signal_sent = False
    usage = None
    wait_error = None
    termination_error = None
    log_error = None
    with Path(log).open("xb") as stream:
        process = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
        while True:
            try:
                pid, status, observed = os.wait4(process.pid, os.WNOHANG)
            except OSError as error:
                # Ownership of the wait result is lost. Never signal a possibly
                # reused PID or fabricate zero CPU from a missing wait record.
                wait_error = str(error)
                break
            if pid == process.pid:
                usage = observed
                process.returncode = os.waitstatus_to_exitcode(status)
                timed_out = timed_out or time.monotonic() >= completion_deadline
                break
            now = time.monotonic()
            if now >= deadline:
                if timed_out:
                    break
                timed_out = True
                # The unreaped direct child owns this fresh process group.
                # This signal is a request, not proof that all descendants exit.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    signal_sent = True
                except ProcessLookupError:
                    pass
                except OSError as error:
                    termination_error = str(error)
                deadline = now + cleanup_seconds
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
        try:
            stream.flush()
            os.fsync(stream.fileno())
        except OSError as error:
            log_error = str(error)
    return {
        "pid": process.pid,
        "exit_code": process.returncode,
        "wall_seconds": time.monotonic() - started,
        "wall_limit_seconds": wall_seconds,
        "cleanup_limit_seconds": cleanup_seconds,
        "timed_out": timed_out,
        "termination_requested": signal_sent,
        "direct_child_reaped": usage is not None,
        "wait_error": wait_error,
        "termination_error": termination_error,
        "log_error": log_error,
        "cpu_user_seconds": None if usage is None else usage.ru_utime,
        "cpu_system_seconds": None if usage is None else usage.ru_stime,
        "peak_rss_bytes": None if usage is None else usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "cost_scope": "direct wait4 child including waited descendants; missing wait record remains unknown",
    }


def complete_cpu_total(records, key):
    values = [row["process_metrics"][key] for row in records]
    return None if any(value is None for value in values) else sum(values)
