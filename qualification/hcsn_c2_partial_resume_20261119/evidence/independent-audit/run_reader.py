"""Run the archive reader once with fresh-process limits and exact wait4 costs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import resource
import signal
import subprocess
import sys
import threading
import time


HERE = Path(__file__).resolve().parent


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())


def main(archive, receipt, output):
    output.mkdir(parents=True, exist_ok=False)
    reader = HERE.parents[1] / "audit.py"
    before = identity(reader)
    cpu = min(os.sched_getaffinity(0))
    limits = {"address_space_bytes": 4 * 1024**3, "cpu_soft_seconds": 300, "cpu_hard_seconds": 310,
              "wall_seconds": 360, "threads": 1, "affinity": [cpu]}
    environment = {**os.environ, **{key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
                   "CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    command = [sys.executable, "-u", str(reader), "--archive", str(archive.resolve()), "--receipt", str(receipt.resolve())]
    write(output / "REQUEST.json", {"command": command, "reader_identity": before, "limits": limits,
          "archive": str(archive.resolve()), "receipt": str(receipt.resolve()), "wrapper_identity": identity(Path(__file__)),
          "scope": "Separate postprocessing only. No model, optimizer, inference or training replay is requested."})

    def constrain():
        os.setsid()
        os.sched_setaffinity(0, {cpu})
        resource.setrlimit(resource.RLIMIT_AS, (limits["address_space_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_soft_seconds"], limits["cpu_hard_seconds"]))

    started = time.monotonic()
    with (output / "reader.stdout").open("xb") as stdout, (output / "reader.stderr").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=reader.parent, env=environment, preexec_fn=constrain,
                                   stdout=stdout, stderr=stderr)
    messages = queue.Queue()

    def waiter():
        pid, status, usage = os.wait4(process.pid, 0)
        messages.put((pid, status, usage, time.monotonic()))

    threading.Thread(target=waiter, daemon=True).start()
    timed_out = False
    while True:
        try:
            pid, status, usage, finished = messages.get(timeout=.25)
            break
        except queue.Empty:
            if not timed_out and time.monotonic() - started >= limits["wall_seconds"]:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    process.returncode = os.waitstatus_to_exitcode(status)
    review, parse_error = None, None
    try:
        review = json.loads((output / "reader.stdout").read_text())
        if review["status"] != "VERIFIED_ARCHIVED_CONTINUATIONS" or review["reader_source_sha256"] != before["sha256"]:
            raise ValueError("reader completion or source identity differs")
    except Exception as error:
        parse_error = repr(error)
    after = identity(reader)
    passed = process.returncode == 0 and not timed_out and finished - started <= limits["wall_seconds"] and before == after and parse_error is None
    cost = {"schema": "hcsn-c2-archive-reader-fresh-process-cost-v1", "status": "PASSED" if passed else "FAILED",
            "pid": pid, "returncode": process.returncode, "raw_wait_status": status, "timed_out": timed_out,
            "full_fresh_process_wall_seconds": finished - started, "cpu_user_seconds": usage.ru_utime,
            "cpu_system_seconds": usage.ru_stime, "cpu_total_seconds": usage.ru_utime + usage.ru_stime,
            "peak_rss_kib": usage.ru_maxrss, "limits": limits, "reader_identity_before": before,
            "reader_identity_after": after, "stdout_identity": identity(output / "reader.stdout"),
            "stderr_identity": identity(output / "reader.stderr"), "parse_error": parse_error,
            "cost_scope": "Whole reader child including Python, NumPy and Torch startup/imports, archive decoding and checks; separate from scientific training budget.",
            "requested_model_forward_calls": 0, "requested_optimizer_calls": 0}
    write(output / "COST.json", cost)
    if passed:
        with (output / "REVIEW.json").open("xb") as stream:
            stream.write((output / "reader.stdout").read_bytes()); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(cost, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "attempt001")
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.archive, arguments.receipt, arguments.output))
