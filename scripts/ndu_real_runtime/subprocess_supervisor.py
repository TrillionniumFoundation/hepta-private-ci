"""Bounded POSIX supervision for the Unix-only research trainer.

Keep the leader unreaped until the final process-group signal. The caller must
not install another child waiter. Detached descendants are outside this scope.
This is process/log evidence, never native stage-owner authentication.
"""

import math
import os
import selectors
import signal
import subprocess
import time

STREAM_LIMIT = 8 * 1024 * 1024
CLEANUP_SECONDS = 1.0
EXIT_DRAIN_SECONDS = 0.25
POLL_SECONDS = 0.05
CHUNK_BYTES = 64 * 1024


def supervision_policy():
    return {
        "schema": "ndu.real.subprocess-policy.v1",
        "stream_limit_bytes": STREAM_LIMIT,
        "cleanup_reserve_seconds": CLEANUP_SECONDS,
        "post_exit_drain_seconds": EXIT_DRAIN_SECONDS,
        "termination": "SIGKILL original POSIX process group before leader reap",
        "scope": "same process group only; detached descendants are not covered",
    }


def run_logged(command, *, stdout, stderr, timeout, env):
    """Stream finite prefixes to exclusive files; cleanup uses the same deadline.

    The caller owns the logs and operation directory. No launch retry is performed.
    Return the actual wait status separately from supervision errors. A missing
    wait status or incomplete cleanup remains unresolved, even if artifacts exist.
    Spawn/fsync are OS calls, not preemptible hard-real-time operations; the caller
    must also reject success when total admission/execution/verification exceeds its
    original envelope. SIGKILL/power loss of this supervisor needs an external owner.
    """
    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("waitid", "WNOWAIT", "killpg")
    ):
        raise RuntimeError("POSIX waitid/WNOWAIT process supervision is required")
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise RuntimeError(
            "A separate SIGCHLD handler could consume the original wait status"
        )
    if not math.isfinite(timeout) or timeout <= CLEANUP_SECONDS:
        raise TimeoutError("No remaining supervisor budget after cleanup reserve")
    started = time.monotonic()
    deadline = started + timeout
    streams = {
        name: {
            "observed_bytes": 0,
            "retained_bytes": 0,
            "eof": False,
            "truncated": False,
        }
        for name in ("stdout", "stderr")
    }
    result = {
        "schema": "ndu.real.subprocess-supervision.v1",
        "policy": supervision_policy(),
        "pid": None,
        "returncode": None,
        "error": None,
        "cleanup_errors": [],
        "group_signal": "not_sent",
        "child_reaped": False,
        "logs_fsynced": False,
        "timeout_seconds": timeout,
        "streams": streams,
    }
    logs = {"stdout": stdout, "stderr": stderr}
    process = None
    ownership = True
    with selectors.DefaultSelector() as selector:

        def drain(wait):
            exceeded = False
            for key, _ in selector.select(wait):
                name = key.data
                state = streams[name]
                try:
                    block = os.read(key.fd, CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not block:
                    state["eof"] = True
                    selector.unregister(key.fileobj)
                    continue
                state["observed_bytes"] += len(block)
                keep = memoryview(block)[
                    : max(0, STREAM_LIMIT - state["retained_bytes"])
                ]
                while keep:
                    count = logs[name].write(keep)
                    if not count:
                        raise OSError("Log write made no progress")
                    state["retained_bytes"] += count
                    keep = keep[count:]
                state["truncated"] = state["observed_bytes"] > state["retained_bytes"]
                exceeded |= state["truncated"]
            return exceeded

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
                bufsize=0,
            )
            result["pid"] = process.pid
            for name in logs:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            exited_at = None
            while True:
                observed = os.waitid(
                    os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
                current = time.monotonic()
                if observed is not None and exited_at is None:
                    exited_at = current
                if exited_at is not None and not selector.get_map():
                    break
                stop = deadline - CLEANUP_SECONDS
                if exited_at is not None:
                    stop = min(stop, exited_at + EXIT_DRAIN_SECONDS)
                if current >= stop:
                    result["error"] = {
                        "type": "TimeoutExpired"
                        if exited_at is None
                        else "OutputDrainExpired",
                        "message": "Execution/output deadline exhausted; original group will be terminated",
                    }
                    break
                if drain(min(POLL_SECONDS, stop - current)):
                    result["error"] = {
                        "type": "OutputLimitExceeded",
                        "message": "Observed output exceeded its fixed byte bound",
                    }
                    break
        except BaseException as error:
            result["error"] = {"type": type(error).__name__, "message": str(error)}
            ownership = not isinstance(error, ChildProcessError)
        finally:
            cleanup_started = time.monotonic()
            cleanup_deadline = min(deadline, cleanup_started + CLEANUP_SECONDS)
            if process is not None:
                try:
                    # Do not signal a potentially recycled PGID if another waiter
                    # already consumed this child's status. Never call poll().
                    if ownership:
                        os.waitid(
                            os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                        )
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                            result["group_signal"] = "sent"
                        except ProcessLookupError:
                            result["group_signal"] = "absent"
                    else:
                        raise ChildProcessError(
                            "Original child wait ownership was lost"
                        )
                except OSError as error:
                    if isinstance(error, ChildProcessError):
                        ownership = False
                    result["cleanup_errors"].append(
                        type(error).__name__ + ": " + str(error)
                    )
                try:
                    while selector.get_map() and time.monotonic() < cleanup_deadline:
                        if (
                            drain(
                                min(
                                    POLL_SECONDS,
                                    max(0, cleanup_deadline - time.monotonic()),
                                )
                            )
                            and result["error"] is None
                        ):
                            result["error"] = {
                                "type": "OutputLimitExceeded",
                                "message": "Output exceeded its bound during final drain",
                            }
                except OSError as error:
                    result["cleanup_errors"].append(
                        type(error).__name__ + ": " + str(error)
                    )
                try:
                    # A failed log write/drain must never skip reaping the child.
                    if ownership:
                        result["returncode"] = process.wait(
                            timeout=max(0, cleanup_deadline - time.monotonic())
                        )
                        result["child_reaped"] = True
                except (OSError, subprocess.TimeoutExpired) as error:
                    result["cleanup_errors"].append(
                        type(error).__name__ + ": " + str(error)
                    )
                finally:
                    for name in logs:
                        pipe = getattr(process, name)
                        if pipe is not None:
                            pipe.close()
            try:
                for stream in logs.values():
                    stream.flush()
                    os.fsync(stream.fileno())
                result["logs_fsynced"] = True
            except OSError as error:
                result["cleanup_errors"].append(
                    type(error).__name__ + ": " + str(error)
                )
            result["cleanup_wall_seconds"] = time.monotonic() - cleanup_started
    result["cleanup_complete"] = (
        result["child_reaped"]
        and all(row["eof"] for row in streams.values())
        and result["logs_fsynced"]
        and not result["cleanup_errors"]
    )
    if not result["cleanup_complete"] and result["error"] is None:
        result["error"] = {
            "type": "CleanupUnresolved",
            "message": "Original wait/output cleanup is not fully observed",
        }
    result["wall_seconds"] = time.monotonic() - started
    return result
