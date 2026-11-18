"""Admit disposable fault workers before releasing concurrent owner mutations."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _publish(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.rename(path)


def await_fault_release(root, *, timeout=15.0):
    """Called only after both authoritative stores have opened successfully."""
    pid = os.getpid()
    _publish(root / f"READY-{pid}.json", {"pid": pid, "ready_ns": time.monotonic_ns()})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        start = root / "START.json"
        if start.exists():
            record = json.loads(start.read_text())
            if pid not in record["pids"]:
                raise RuntimeError("worker not admitted to this start barrier")
            return
        time.sleep(0.005)
    raise TimeoutError("controller did not release admitted fault workers")


def run_fault_workers(root, script, fault, *, expected_workers, timeout=30.0):
    """Retain every launched process, including partial startup and cleanup failures.

    This helper owns fixed append workers that do not launch descendants. It is
    not a generic process-tree timeout or resource-accounting implementation.
    Only concurrent_writers uses the admission barrier. Opening a store while a
    writer mutates it may correctly fail retained-byte validation; that is a
    different experiment from simultaneous dispatch by already admitted owners.
    """
    barrier = fault == "concurrent_writers"
    children, processes, ready = [], [], []
    started = time.monotonic_ns()
    deadline = time.monotonic() + timeout
    failure, released = None, False
    try:
        for _ in range(expected_workers):
            command = [
                sys.executable,
                "-B",
                str(script),
                "--worker",
                str(root),
                "--fault",
                fault,
            ]
            if barrier:
                command.append("--start-barrier")
            child = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "PYTHONPATH": str(script.parent),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            children.append(child)
            if barrier:
                # Cold open may create WAL sidecars. Serialize admission, while
                # preserving concurrent dispatch by all four admitted owners.
                path = root / f"READY-{child.pid}.json"
                while time.monotonic() < deadline:
                    if any(item.poll() is not None for item in children):
                        raise RuntimeError(
                            "fault worker exited before common admission"
                        )
                    if path.exists():
                        row = json.loads(path.read_text())
                        if row["pid"] != child.pid:
                            raise ValueError(
                                "ready record differs from launched worker"
                            )
                        ready.append(row)
                        break
                    time.sleep(0.005)
                else:
                    raise TimeoutError("fault worker did not reach admission")
        if barrier:
            _publish(
                root / "START.json",
                {
                    "pids": [child.pid for child in children],
                    "released_ns": time.monotonic_ns(),
                },
            )
            released = True
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        if failure is not None:
            for child in children:
                if child.poll() is None:
                    child.kill()
        for index, child in enumerate(children):
            timed_out = False
            try:
                stdout, stderr = child.communicate(
                    timeout=max(0.01, deadline - time.monotonic())
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                child.kill()
                stdout, stderr = child.communicate()
            (root / f"process-{index}.stdout").write_bytes(stdout)
            (root / f"process-{index}.stderr").write_bytes(stderr)
            processes.append(
                {
                    "pid": child.pid,
                    "exit": child.returncode,
                    "timed_out": timed_out,
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                }
            )
    return {
        "processes": processes,
        "controller_wall_ns": time.monotonic_ns() - started,
        "admission": {
            "expected_workers": expected_workers,
            "launched_workers": len(children),
            "barrier_required": barrier,
            "released": released,
            "ready": ready,
            "startup_error": failure,
        },
    }
