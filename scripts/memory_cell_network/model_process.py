"""Bounded model subprocesses with retained diagnostics and Linux death binding."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


class ChildFailure(ValueError):
    """A model failure that the authenticated RPC already knows how to return."""

    def __init__(self, operation, receipt):
        self.receipt = receipt
        reason = (
            "timed out" if receipt["timed_out"] else f"exited {receipt['returncode']}"
        )
        super().__init__(
            f"isolated {operation} {reason}; receipt={receipt['receipt_path']}; "
            f"{receipt['stderr'][-2000:]}"
        )


def run_child(
    script,
    arguments=(),
    *,
    input_text=None,
    timeout=180,
    cwd=None,
    receipt_dir=None,
    operation="model",
):
    directory = (
        Path(receipt_dir)
        if receipt_dir is not None
        else (
            Path(cwd) / "model-processes"
            if cwd is not None
            else Path(tempfile.mkdtemp(prefix="hepta-memory-processes-"))
        )
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, stderr_name = tempfile.mkstemp(
        prefix="child-", suffix=".stderr.txt", dir=directory
    )
    stderr_path = Path(stderr_name).resolve()
    receipt_path = stderr_path.with_suffix(".result.json")
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).with_name("model_child.py").resolve()),
        "--parent-pid",
        str(os.getpid()),
        str(Path(script).resolve()),
        *[str(value) for value in arguments],
    ]
    started = time.perf_counter()
    timed_out, interrupted = False, None
    with os.fdopen(descriptor, "w", encoding="utf-8") as errors:
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        ) as process:
            try:
                stdout, _ = process.communicate(input_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, _ = process.communicate()
                timed_out = True
            except BaseException as error:
                process.kill()
                stdout, _ = process.communicate()
                interrupted = error
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    bootstrap = None
    for line in stderr.splitlines():
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get("schema") == "hepta.memory-process.started.v1"
        ):
            bootstrap = candidate
            break
    receipt = {
        "schema": "hepta.memory-process.result.v1",
        "command": command,
        "pid": process.pid,
        "returncode": process.returncode,
        "launch_thread_id": threading.get_native_id(),
        "exit_signal": -process.returncode
        if os.name == "posix" and process.returncode < 0
        else None,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "tensor_lifetime": "child_process_completed",
        "bootstrap": bootstrap,
        "cwd": str(Path(cwd).resolve()) if cwd is not None else str(Path.cwd()),
        "stderr_path": str(stderr_path),
        "receipt_path": str(receipt_path),
        "interrupted": type(interrupted).__name__ if interrupted else None,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    if interrupted is not None:
        raise interrupted
    if timed_out or process.returncode != 0:
        raise ChildFailure(operation, receipt)
    return receipt


def run_decoder(request, *, timeout=180, cwd=None, receipt_dir=None):
    receipt = run_child(
        Path(__file__).resolve().parents[1] / "memory_cell" / "parametric_worker.py",
        input_text=json.dumps(request),
        timeout=timeout,
        cwd=cwd,
        receipt_dir=receipt_dir,
        operation="decoder",
    )
    journal = json.loads(receipt["stdout"])
    journal["decoder_process"] = {
        key: value for key, value in receipt.items() if key != "stdout"
    }
    return journal
