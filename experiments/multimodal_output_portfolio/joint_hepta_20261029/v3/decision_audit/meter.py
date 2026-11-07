"""POSIX command receipts with bounded wall containment and signal cleanup.

Never add these receipts to nested action costs. The inherited process group is
contained; descendants that create another session/group are outside this scope.
SIGKILL, host loss and a failed receipt filesystem cannot be finalized in Python.
"""

import argparse
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time
import uuid


def _group_exists(process_group):
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_group(child, grace_seconds):
    """Signal the group even if its leader exits before an ignoring descendant."""
    signals = []
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, signum)
            signals.append(signum)
        except ProcessLookupError:
            break
        if signum == signal.SIGTERM:
            deadline = time.perf_counter() + grace_seconds
            while time.perf_counter() < deadline:
                child.poll()
                if not _group_exists(child.pid):
                    break
                time.sleep(min(.02, max(0, deadline - time.perf_counter())))
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass  # An uninterruptible child must not block the terminal receipt.
    return {"signals_sent": signals, "direct_child_reaped": child.returncode is not None,
            "group_still_present": _group_exists(child.pid)}


def _write_receipt(path, row):
    temporary = path.with_name(path.name + "." + row["attempt_id"] + ".tmp")
    with temporary.open("x") as stream:
        stream.write(json.dumps(row, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def execute(command, output, *, wall_timeout_seconds=None, termination_grace_seconds=2.0):
    """Meter a command on the main thread; timeout/cancel are nonzero outcomes.

    return_code is the wrapper outcome; child_return_code retains the actual
    reaped child's code even when it handles SIGTERM by exiting successfully.
    The optional wall deadline includes spawn/wait; bounded cleanup follows it.
    """
    for name, value in (("wall timeout", wall_timeout_seconds), ("termination grace", termination_grace_seconds)):
        if (value is None and name == "wall timeout"):
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(name + " must be finite and positive")
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("The signal-aware command meter requires the main thread")
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Each physical command attempt requires a new receipt")
    started = time.process_time(), time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    row = {"attempt_id": uuid.uuid4().hex, "command": list(command), "status": "started",
           "started_unix": time.time(), "do_not_add_to_nested_costs": True,
           "wall_timeout_seconds": wall_timeout_seconds, "termination_grace_seconds": termination_grace_seconds,
           "timed_out": False, "cancelled": False, "cancellation_signal": None, "child_pid": None}
    child, received = None, [None]
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}

    def cancelled(signum, _frame):
        # A flag cannot interrupt Popen between starting the child and returning
        # its handle, or interrupt cleanup when a second cancellation arrives.
        received[0] = received[0] or signum

    try:
        for signum in previous:
            signal.signal(signum, cancelled)
        with path.open("x") as stream:
            stream.write(json.dumps(row) + "\n")
        try:
            if received[0] is None:
                child = subprocess.Popen(command, start_new_session=True)
                row["child_pid"] = child.pid
                _write_receipt(path, row)
            while True:
                if received[0] is not None:
                    row.update(status="cancelled", return_code=128 + received[0])
                    break
                remaining = (wall_timeout_seconds - (time.perf_counter() - started[1])
                             if wall_timeout_seconds is not None else .05)
                if remaining <= 0:
                    row.update(status="timed_out", timed_out=True, return_code=124)
                    break
                try:
                    code = child.wait(timeout=min(.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
                if received[0] is not None or (wall_timeout_seconds is not None and
                        time.perf_counter() - started[1] >= wall_timeout_seconds):
                    continue
                row.update(status="completed" if code == 0 else "failed", return_code=code)
                break
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                received[0] = received[0] or signal.SIGINT
            row.update(status="cancelled" if received[0] else "failed", return_code=130 if received[0] else 1,
                       error={"type": type(exc).__name__, "message": str(exc)})
        finally:
            try:
                if child is not None and _group_exists(child.pid):
                    if row["status"] == "completed":
                        row.update(status="failed", return_code=1,
                                   error={"type": "RemainingProcessGroup", "message": "Descendants outlived the command leader"})
                    row["termination"] = _stop_group(child, termination_grace_seconds)
            except Exception as exc:
                row["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
                if row["status"] == "completed":
                    row.update(status="failed", return_code=1)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            measured_cpu = (after.ru_utime + after.ru_stime) - (usage.ru_utime + usage.ru_stime)
            reaped = child is None or child.returncode is not None
            row.update(child_return_code=child.returncode if child is not None else None,
                       parent_cpu_seconds=time.process_time() - started[0],
                       child_cpu_seconds=measured_cpu if reaped else None, observed_child_cpu_seconds=measured_cpu,
                       wall_seconds=time.perf_counter() - started[1], finished_unix=time.time(),
                       child_peak_rss_bytes=after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                       child_peak_rss_scope="meter-process lifetime RUSAGE_CHILDREN high-water mark",
                       scope="RUSAGE_CHILDREN delta and wrapper before final receipt write; only reaped child usage",
                       unknown_outer_costs=["meter_process_startup", "final_receipt_write", "external_shell_logging"])
            if "termination" in row or "cleanup_error" in row or not reaped:
                row["unknown_outer_costs"].append("descendant_usage_not_reaped_by_command_leader")
            if received[0] is not None:
                row.update(cancelled=True, cancellation_signal=received[0])
                if not row["timed_out"]:
                    row.update(status="cancelled", return_code=128 + received[0])
            _write_receipt(path, row)
            # Reconcile cancellation arriving during the final atomic write too.
            # Once committed and handlers restored, execution belongs to the caller.
            if received[0] is not None and not row["cancelled"]:
                row.update(cancelled=True, cancellation_signal=received[0])
                if not row["timed_out"]:
                    row.update(status="cancelled", return_code=128 + received[0])
                _write_receipt(path, row)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--wall-timeout-seconds", type=float)
    parser.add_argument("--termination-grace-seconds", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A physical command is required")
    result = execute(command, args.output, wall_timeout_seconds=args.wall_timeout_seconds,
                     termination_grace_seconds=args.termination_grace_seconds)
    raise SystemExit(result["return_code"] if result["return_code"] >= 0 else 128 - result["return_code"])
