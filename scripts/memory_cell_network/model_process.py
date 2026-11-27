"""Bounded model subprocesses with retained diagnostics and Linux death binding."""

import json
import os
from pathlib import Path
import signal
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


def model_environment():
    """Forward runtime controls, never credentials or Python import injection."""
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "CUDA_VISIBLE_DEVICES",
    }
    environment = {
        name: value for name, value in os.environ.items() if name.upper() in allowed
    }
    environment.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
    )
    return environment


def _stop_child_group(process):
    """Terminate this owned POSIX group, including children after leader exit."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass


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
    stdout_path = stderr_path.with_name(
        stderr_path.name.replace(".stderr.txt", ".stdout.txt")
    )
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
    with (
        os.fdopen(descriptor, "w", encoding="utf-8") as errors,
        os.fdopen(
            os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "w",
            encoding="utf-8",
        ) as output,
        tempfile.TemporaryFile(mode="w+b", dir=directory) as input_file,
    ):
        if input_text is not None:
            input_file.write(input_text.encode("utf-8", errors="replace"))
            input_file.seek(0)
        with subprocess.Popen(
            command,
            stdin=input_file if input_text is not None else subprocess.DEVNULL,
            # Regular files retain the raw bytes without waiting for pipe EOF
            # from a descendant that outlives the direct model process.
            stdout=output,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=model_environment(),
            start_new_session=os.name == "posix",
        ) as process:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _stop_child_group(process)
                process.wait()
                timed_out = True
            except BaseException as error:
                _stop_child_group(process)
                process.wait()
                interrupted = error
            finally:
                _stop_child_group(process)
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
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
    with os.fdopen(
        os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
        "w",
        encoding="utf-8",
    ) as stream:
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
