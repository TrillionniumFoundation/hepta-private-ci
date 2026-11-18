"""Two already admitted HIA owners reconcile one original result concurrently.

Cold admission is serialized. Readback callbacks wait after each owner has
durably recorded its attempt. POSIX workers own separate process groups, so
failure cleanup includes their ordinary Git children. Detached descendants are
not covered; this is not a generic process-tree or authority mechanism.
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


WORKER = Path(__file__).resolve().parents[1] / "hepta_cell_joint_worker.py"
PHASES = {"ADMITTED": "START", "READBACK": "RESUME"}


def _terminate(child):
    record = {
        "pid": child.pid,
        "scope": "owned_process_group" if os.name == "posix" else "direct_worker",
    }
    try:
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
        record["outcome"] = "termination_requested"
    except ProcessLookupError:
        record["outcome"] = "already_absent"
    except OSError as error:
        record.update(outcome="cleanup_error", error=f"{type(error).__name__}: {error}")
    return record


def _publish(path, value):
    if path.exists():
        raise FileExistsError(path)
    pending = path.with_suffix(".pending")
    with pending.open("x") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.rename(path)


def wait_joint_phase(root, phase, *, timeout=15.0):
    """Publish this worker's phase; require its PID in the matching release."""
    if phase not in PHASES:
        raise ValueError("unknown joint readback phase")
    pid = os.getpid()
    _publish(
        root / f"{phase}-{pid}.json",
        {
            "pid": pid,
            "phase": phase,
            "ready_ns": time.monotonic_ns(),
        },
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = root / (PHASES[phase] + ".json")
        if path.exists():
            release = json.loads(path.read_text())
            pids = release["pids"]
            if (
                type(pids) is not list
                or len(pids) != 2
                or len(set(pids)) != 2
                or any(type(value) is not int or value <= 0 for value in pids)
                or pid not in pids
                or release["phase"] != phase
            ):
                raise ValueError("joint release does not name the admitted worker")
            return
        time.sleep(0.005)
    raise TimeoutError("joint controller did not release " + phase)


def _wait_ready(gate, phase, child, children, deadline):
    path = gate / f"{phase}-{child.pid}.json"
    while time.monotonic() < deadline:
        if any(item.poll() is not None for item, _ in children):
            raise RuntimeError("joint worker exited before " + phase)
        if path.exists():
            row = json.loads(path.read_text())
            if (
                type(row) is not dict
                or set(row) != {"pid", "phase", "ready_ns"}
                or type(row["pid"]) is not int
                or row["pid"] != child.pid
                or row["phase"] != phase
                or type(row["ready_ns"]) is not int
                or not 0 <= row["ready_ns"] <= time.monotonic_ns()
            ):
                raise ValueError("joint readiness differs from launched worker")
            return row
        time.sleep(0.005)
    raise TimeoutError("joint worker did not reach " + phase)


def run_joint_readbacks(candidate, database, request, output, *, timeout=30.0):
    """Keep two-worker denominators and raw exits, including incomplete startup."""
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 30
    ):
        raise ValueError("joint process deadline must be within 30 seconds")
    if type(request) is not dict or request.get("operation") != "readback":
        raise ValueError("joint campaign requires an original readback request")
    raw = (
        json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    if len(raw) > 65536:
        raise ValueError("joint request exceeds the worker bound")
    request = json.loads(raw)
    gate = output / "joint-readback-admission"
    gate.mkdir(parents=True, exist_ok=False)
    request_path = gate / "REQUEST.json"
    with request_path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    started, deadline = time.monotonic_ns(), time.monotonic() + timeout
    children, records, cleanup = [], [], []
    admission = dict(
        expected_workers=2,
        launched_workers=0,
        admitted=[],
        readback_ready=[],
        start_released=False,
        resume_released=False,
        error=None,
    )
    try:
        for index in range(2):
            if time.monotonic() >= deadline:
                raise TimeoutError("joint deadline expired before worker launch")
            command = [
                sys.executable,
                "-B",
                str(WORKER),
                "--candidate",
                str(candidate),
                "--database",
                str(database),
                "--admission-directory",
                str(gate),
            ]
            began = time.monotonic_ns()
            with (
                request_path.open("rb") as incoming,
                (gate / f"process-{index}.stdout").open("xb") as stdout,
                (gate / f"process-{index}.stderr").open("xb") as stderr,
            ):
                child = subprocess.Popen(
                    command,
                    stdin=incoming,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=os.name == "posix",
                    env={
                        **os.environ,
                        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
            children.append((child, began))
            admission["launched_workers"] = len(children)
            admission["admitted"].append(
                _wait_ready(gate, "ADMITTED", child, children, deadline)
            )
        pids = [child.pid for child, _ in children]
        _publish(
            gate / "START.json",
            dict(pids=pids, phase="ADMITTED", released_ns=time.monotonic_ns()),
        )
        admission["start_released"] = True
        for child, _ in children:
            admission["readback_ready"].append(
                _wait_ready(gate, "READBACK", child, children, deadline)
            )
        _publish(
            gate / "RESUME.json",
            dict(pids=pids, phase="READBACK", released_ns=time.monotonic_ns()),
        )
        admission["resume_released"] = True
    except Exception as error:
        admission["error"] = f"{type(error).__name__}: {error}"
    finally:
        if admission["error"] is not None:
            for child, _ in children:
                cleanup.append(_terminate(child))
        for index, (child, began) in enumerate(children):
            timed_out = False
            try:
                child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup.append(_terminate(child))
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    admission["error"] = "cleanup did not reap direct worker"
            stdout = (gate / f"process-{index}.stdout").read_bytes()
            stderr = (gate / f"process-{index}.stderr").read_bytes()
            record = dict(
                request=request,
                pid=child.pid,
                exit_code=child.returncode,
                wall_ns=time.monotonic_ns() - began,
                timed_out=timed_out,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            )
            records.append(record)
            _publish(output / f"fault-cold-original-result-{index}.json", record)
    result = dict(
        schema="hepta.joint-readback-admission.v1",
        admission=admission,
        processes=records,
        controller_wall_ns=time.monotonic_ns() - started,
        protocol="serial_cold_admission_two_durable_readbacks.v1",
        cleanup=cleanup,
        detached_descendants_covered=False,
        concurrent_cold_open_qualified=False,
    )
    _publish(gate / "RESULT.json", result)
    return result
