"""Execute fixed maintenance function checks in a bounded disposable child.

The inputs are controlled experiment fixtures, not arbitrary untrusted programs.
Timeouts and resource limits bound this workload; they are not an OS sandbox.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def contract(task):
    """Bind exact input source, expected behavior and declared split before use."""
    checks = task.get("checks")
    entry = task.get("entry")
    provenance = task.get("provenance")
    if (
        type(task.get("source")) is not str
        or len(task["source"].encode()) > 65536
        or type(entry) is not str
        or not entry.isidentifier()
        or type(checks) is not list
        or not 1 <= len(checks) <= 32
        or any(type(row) is not dict or set(row) != {"args", "expected"}
               or type(row["args"]) is not list for row in checks)
        or type(provenance) is not dict
        or set(provenance) != {"origin", "family", "split"}
        or any(type(value) is not str or not value for value in provenance.values())
    ):
        raise ValueError("bounded function checks and explicit source/split are required")
    raw = canonical(dict(entry=entry, checks=checks, provenance=provenance)).encode()
    if len(raw) > 65536:
        raise ValueError("semantic contract exceeds bound")
    return dict(
        input_source_sha256=hashlib.sha256(task["source"].encode()).hexdigest(),
        checks_sha256=hashlib.sha256(raw).hexdigest(),
        provenance=provenance,
    )


def split_binding(panels):
    """Reject exact source/ID reuse across phases without claiming family separation."""
    identities, sources, result = set(), set(), {}
    for phase, tasks in panels.items():
        records = {}
        for task in tasks:
            bound = contract(task)
            if (task["id"] in identities or bound["input_source_sha256"] in sources
                    or bound["provenance"]["split"] != phase):
                raise ValueError("source, task identity or declared phase overlaps")
            identities.add(task["id"])
            sources.add(bound["input_source_sha256"])
            records[task["id"]] = bound
        result[phase] = records
    return result


def evaluate(task, source, *, timeout_seconds=2.0):
    """Retain actual child results; a compile pass alone can never pass checks."""
    binding = contract(task)
    if type(source) is not str or len(source.encode()) > 65536:
        raise ValueError("candidate source exceeds bound")
    if (type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 5):
        raise ValueError("semantic deadline must be finite and in (0, 5]")
    payload = canonical(dict(source=source, entry=task["entry"], checks=task["checks"]))
    started = time.perf_counter_ns()
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(payload.encode(), timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
    result = dict(
        **binding, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        status="timeout" if timed_out else "child_error", success=False,
        returncode=process.returncode, child_pid=process.pid,
        wall_ns=time.perf_counter_ns() - started,
        stdout=stdout[:65536].decode(errors="replace"),
        stderr=stderr[:4096].decode(errors="replace"),
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        stdout_bytes=len(stdout), stderr_bytes=len(stderr),
        child_source_compile_attempted=None, os_sandbox=False,
    )
    if not timed_out and process.returncode == 0 and len(stdout) <= 65536:
        try:
            observed = json.loads(stdout)
            if (type(observed) is not dict
                    or observed.get("status") not in ("passed", "failed", "error")
                    or type(observed.get("checks")) is not list):
                raise ValueError("invalid child response")
            result.update(status=observed["status"], child=observed,
                          child_source_compile_attempted=observed.get("compile_attempted"))
            result["success"] = observed["status"] == "passed" and all(
                row.get("passed") is True for row in observed["checks"]
            ) and len(observed["checks"]) == len(task["checks"])
        except (ValueError, TypeError):
            result["status"] = "invalid_child_response"
    return result


def worker():
    started = time.process_time_ns()
    limits = False
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        limits = True
    except (ImportError, OSError, ValueError):
        pass
    result = dict(status="error", checks=[], resource_limits=limits, compile_attempted=False)
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError("worker input exceeds bound")
        payload = json.loads(raw)
        scope = {"__builtins__": {}}
        result["compile_attempted"] = True
        exec(compile(payload["source"], "maintenance-candidate.py", "exec"), scope)
        function = scope[payload["entry"]]
        for case in payload["checks"]:
            observed = function(*case["args"])
            result["checks"].append(dict(
                observed=observed, passed=canonical(observed) == canonical(case["expected"]),
            ))
        result["status"] = "passed" if all(row["passed"] for row in result["checks"]) else "failed"
    except BaseException as error:
        result.update(status="error", error=type(error).__name__ + ": " + str(error)[:2048])
    result["cpu_ns"] = time.process_time_ns() - started
    try:
        encoded = canonical(result).encode()
        if len(encoded) > 65536:
            raise ValueError("worker output exceeds bound")
    except (ValueError, TypeError, RecursionError):
        encoded = b'{"status":"error","checks":[],"error":"invalid or excessive result"}'
    sys.stdout.buffer.write(encoded + b"\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("--worker is required")
    worker()
