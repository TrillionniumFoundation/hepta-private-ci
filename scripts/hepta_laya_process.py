#!/usr/bin/env python3
"""Bounded Linux subprocess transport for the experimental Laya leaf.

This is a transport, not an inference owner, sandbox, model selector or durable
reconciler. The native owner must fence dispatch before calling it and persist a
validated result before delivery. All post-spawn errors remain unknown to that
owner. A host-selected, immutable offline environment is a precondition. Process
group signalling does not prove containment of hostile/setsid descendants.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence

try:
    from .hepta_laya_worker import DeadlineGuard
    from .hepta_retrieval_wire import MAX_FRAME, decode_request, decode_reply
except ImportError:
    from hepta_laya_worker import DeadlineGuard
    from hepta_retrieval_wire import MAX_FRAME, decode_request, decode_reply

MAX_DIAGNOSTIC_BYTES = 16 * 1024
MAX_QUANTUM_BYTES = 4096
CLEANUP_SECONDS = 2.0


@dataclass(frozen=True)
class ProcessObservation:
    request_sha256: str
    reply_wire: bytes
    elapsed_us: int
    peak_rss_bytes: int
    user_cpu_us: int
    system_cpu_us: int
    stderr_bytes: int
    stderr_sha256: str
    leader_pid: int
    leader_reaped: bool
    process_group_signalled: bool


class ProcessUnavailable(RuntimeError):
    """The caller must consult its durable dispatch record, never retry blindly.

    A retained child means cleanup has not been observed. Keep this exception (or
    transfer the handle to the existing supervisor) until reconcile_cleanup has
    observed leader exit. Error messages never include child diagnostics, model
    inputs, environment values or credentials.
    """

    def __init__(self, reason: str, *, spawned: bool, child=None, cleanup_error=False):
        super().__init__(reason)
        self.spawned = spawned
        self.child = child
        self.cleanup_error = cleanup_error

    def reconcile_cleanup(self) -> bool:
        if self.child is None:
            return not self.cleanup_error
        if _exited(self.child):
            _reap(self.child)
            self.child = None
            # Reaping a leader does not retroactively prove a failed group signal.
            return not self.cleanup_error
        return False


def _exited(child: subprocess.Popen) -> bool:
    # Do not use Popen.poll/try_wait: reaping before killpg permits PID/PGID reuse.
    result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    return result is not None and result.si_pid == child.pid


def _reap(child: subprocess.Popen):
    pid, status, usage = os.wait4(child.pid, 0)
    if pid != child.pid:
        raise ProcessUnavailable("wrong child observed", spawned=True, child=child)
    child.returncode = os.waitstatus_to_exitcode(status)
    return usage


def _signal_group(child: subprocess.Popen) -> None:
    # The unreaped child pins the process-group number through this call. There
    # must be no SIGCHLD handler or other thread that independently reaps it.
    os.killpg(child.pid, signal.SIGKILL)


def _validate_command(command: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
    if (not isinstance(command, (tuple, list)) or not 1 <= len(command) <= 24
            or any(not isinstance(arg, str) or not arg or "\0" in arg
                   or len(arg.encode("utf-8")) > 4096 for arg in command)
            or not Path(command[0]).is_absolute()):
        raise ProcessUnavailable("invalid host-selected command", spawned=False)
    executable = Path(command[0])
    try:
        available = stat.S_ISREG(executable.stat().st_mode) and os.access(executable, os.X_OK)
    except OSError as error:
        raise ProcessUnavailable("unavailable host-selected executable", spawned=False) from error
    if not available:
        raise ProcessUnavailable("unavailable host-selected executable", spawned=False)
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ProcessUnavailable("invalid immutable working directory", spawned=False)
    allowed = {"PATH", "LANG", "LC_ALL", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
               "PYTHONDONTWRITEBYTECODE", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
               "TOKENIZERS_PARALLELISM", "HOME", "TMPDIR"}
    if (set(env) - allowed or any(not isinstance(v, str) or "\0" in v or len(v) > 4096
                                  for v in env.values())
            or env.get("HF_HUB_OFFLINE") != "1"
            or env.get("TRANSFORMERS_OFFLINE") != "1"):
        raise ProcessUnavailable("invalid offline process environment", spawned=False)


def run_process(frame: bytes, *, command: Sequence[str], cwd: Path,
                env: Mapping[str, str], cancelled: Callable[[], bool],
                now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
                monotonic_ns: Callable[[], int] = time.monotonic_ns) -> ProcessObservation:
    """Run one trusted leaf exactly once with bounded nonblocking pipe I/O.

    No durable state or currentness oracle is owned here. Command and environment
    are host configuration, never model output or fields accepted from the wire.
    Memory is a measured Linux wait4 leader high-water mark, not a hard cgroup
    limit, aggregate descendant usage or a device attestation. The existing host
    must supply memory isolation and final-use artifact/source revalidation.
    """
    if sys.platform != "linux" or not all(hasattr(os, x) for x in ("waitid", "WNOWAIT", "wait4")):
        raise ProcessUnavailable("Linux waitid/wait4 profile required", spawned=False)
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ProcessUnavailable("exclusive child-reaping ownership required", spawned=False)
    request = decode_request(frame)
    guard = DeadlineGuard(request["deadline_ms"], now_ms=now_ms, monotonic_ns=monotonic_ns)
    _validate_command(command, cwd, env)
    if cancelled() is not False:
        raise ProcessUnavailable("cancelled before spawn", spawned=False)
    guard.check()
    started = time.monotonic_ns()
    try:
        child = subprocess.Popen(list(command), cwd=cwd, env=dict(env), shell=False,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, close_fds=True,
                                 start_new_session=True, bufsize=0)
    except OSError as error:
        raise ProcessUnavailable("leaf spawn failed", spawned=False) from error
    selector = selectors.DefaultSelector()
    output = bytearray()
    diagnostics = hashlib.sha256()
    diagnostic_bytes = 0
    offset = 0
    group_signalled = False
    child_exited = False
    usage = None
    try:
        for stream, events, name in ((child.stdin, selectors.EVENT_WRITE, "stdin"),
                                     (child.stdout, selectors.EVENT_READ, "stdout"),
                                     (child.stderr, selectors.EVENT_READ, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events, name)
        while True:
            guard.check()
            if cancelled() is not False:
                raise ProcessUnavailable("cancelled after spawn", spawned=True)
            if not child_exited and _exited(child):
                child_exited = True
                # Even normal leader exit does not imply inherited pipes closed.
                _signal_group(child)
                group_signalled = True
            if child_exited and not selector.get_map():
                break
            for key, _ in selector.select(0.01):
                stream, name = key.fileobj, key.data
                if name == "stdin":
                    try:
                        count = os.write(stream.fileno(), frame[offset:offset + MAX_QUANTUM_BYTES])
                    except BlockingIOError:
                        continue
                    offset += count
                    if offset == len(frame):
                        selector.unregister(stream)
                        stream.close()
                else:
                    try:
                        block = os.read(stream.fileno(), MAX_QUANTUM_BYTES)
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(stream)
                        stream.close()
                    elif name == "stdout":
                        if len(output) + len(block) > MAX_FRAME:
                            raise ProcessUnavailable("stdout byte budget exceeded", spawned=True)
                        output.extend(block)
                    else:
                        diagnostic_bytes += len(block)
                        if diagnostic_bytes > MAX_DIAGNOSTIC_BYTES:
                            raise ProcessUnavailable("stderr byte budget exceeded", spawned=True)
                        diagnostics.update(block)
        usage = _reap(child)
        if child.returncode != 0:
            raise ProcessUnavailable("leaf exited without successful completion", spawned=True)
        # This validates reply shape, exact request/bundle identity and all mass.
        decode_reply(bytes(output), frame)
        guard.check()
        if cancelled() is not False:
            raise ProcessUnavailable("cancelled before result publication", spawned=True)
        peak = int(usage.ru_maxrss) * 1024  # Linux units, never a cross-OS guess.
        if peak <= 0:
            raise ProcessUnavailable("missing memory observation", spawned=True)
        return ProcessObservation(hashlib.sha256(frame).hexdigest(), bytes(output),
                                  (time.monotonic_ns() - started) // 1000, peak,
                                  int(usage.ru_utime * 1_000_000),
                                  int(usage.ru_stime * 1_000_000), diagnostic_bytes,
                                  diagnostics.hexdigest(), child.pid, True, group_signalled)
    except BaseException as error:
        cleanup_error = False
        if child.returncode is None:
            try:
                if not group_signalled:
                    _signal_group(child)
                    group_signalled = True
            except OSError:
                cleanup_error = True
            limit = time.monotonic() + CLEANUP_SECONDS
            try:
                while not _exited(child) and time.monotonic() < limit:
                    time.sleep(0.01)
                if _exited(child):
                    _reap(child)
            except OSError:
                cleanup_error = True
        retained = child if child.returncode is None else None
        reason = str(error) if isinstance(error, ProcessUnavailable) else "leaf transport unavailable"
        raise ProcessUnavailable(reason, spawned=True, child=retained,
                                 cleanup_error=cleanup_error) from error
    finally:
        selector.close()
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None and not stream.closed:
                stream.close()
