"""Inclusive physical command receipts; never add these to nested action costs."""

import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import uuid


def execute(command, output):
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Each physical command attempt requires a new receipt")
    started = time.process_time(), time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    row = {"attempt_id": uuid.uuid4().hex, "command": list(command), "status": "started",
           "started_unix": time.time(), "do_not_add_to_nested_costs": True}
    path.write_text(json.dumps(row) + "\n")
    child = None
    try:
        child = subprocess.Popen(command, start_new_session=True)
        code = child.wait()
        row.update(status="completed" if code == 0 else "failed", return_code=code)
    except (Exception, KeyboardInterrupt) as exc:
        row.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                   error={"type": type(exc).__name__, "message": str(exc)})
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        row["return_code"] = 130 if isinstance(exc, KeyboardInterrupt) else 1
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    row.update(parent_cpu_seconds=time.process_time() - started[0],
               child_cpu_seconds=(after.ru_utime + after.ru_stime) - (usage.ru_utime + usage.ru_stime),
               wall_seconds=time.perf_counter() - started[1],
               child_peak_rss_bytes=after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
               scope="inclusive_completed_child_command_and_wrapper_before_final_receipt_write",
               unknown_outer_costs=["meter_process_startup", "final_receipt_write", "external_shell_logging"])
    path.write_text(json.dumps(row, indent=2, allow_nan=False) + "\n")
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A physical command is required")
    result = execute(command, args.output)
    raise SystemExit(result["return_code"] if result["return_code"] >= 0 else 128 - result["return_code"])
