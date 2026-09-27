"""Bounded POSIX transport for the existing one-shot Laya binary leaf.

This is not another inference owner: callers retain admission, the durable
operation fence and result persistence. A process error never permits retry.
Process groups are cleanup aids, not a sandbox; escaped descendants, device
memory, current source authority and independent task success are not attested.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

from hepta_retrieval_wire import MAX_FRAME, decode_reply, decode_request
from laya_binary import OwnerDeadline
from laya_retrieval import Rejected
from laya_wait import observation_supported, observe_owned_exit
from laya_process_group import EXITED_LEADER_ONLY, SIGNALLED, signal_owned_group

MAX_DIAGNOSTIC_BYTES = 8192
CLEANUP_SECONDS = 2.0


@dataclass(frozen=True)
class ProcessPrediction:
    wire: bytes
    observation: dict


class ProcessFailure(RuntimeError):
    """No eligible result; retain the original durable fence and observations.

    An uncollected child handle remains attached rather than being discarded.
    Direct-child exit does not prove that all descendants or resources stopped.
    """
    def __init__(self, reason: str, observation: dict, child=None):
        # Only bounded codes are retained. Exception text may contain source data.
        phase = observation.get("cleanup_stage")
        cleanup = observation.get("cleanup_error")
        error_number = observation.get("cleanup_errno")
        super().__init__(f"{reason}; cleanup={cleanup}; stage={phase}; errno={error_number}")
        self._observation = dict(observation)
        self.child = child
        self._cleanup_lock = threading.Lock()

    @property
    def observation(self) -> dict:
        """A scalar-only projection; callers cannot mutate lifecycle decisions."""
        return dict(self._observation)

    def reconcile_cleanup(self) -> dict:
        """Retry cleanup of the retained child, never inference or result delivery.

        This process remains the exclusive child reaper. Do not call poll/wait
        on ``child`` yourself: losing ownership disables subsequent signalling.
        A successful direct-child cleanup still does not attest descendants,
        device resources, operation success or permission to retry the request.
        """
        if not self._cleanup_lock.acquire(blocking=False):
            raise Rejected("cleanup reconciliation already in progress")
        try:
            if self.child is not None:
                _cleanup_owned_child(self.child, self._observation)
                if self._observation["direct_child_reaped"]:
                    self.child = None
            return dict(self._observation)
        finally:
            self._cleanup_lock.release()


def _cleanup_owned_child(child: subprocess.Popen, observation: dict) -> None:
    """Keep the unreaped leader as the process-group identity until signalling.

    If signalling fails without a verified exited-singleton observation, DO NOT
    wait/poll/reap: another process could otherwise
    reuse that group number before a later cleanup attempt. This is a trusted
    exclusive-reaper protocol, not protection against a concurrent foreign reaper.
    """
    if (observation["direct_child_reaped"]
            or observation.get("cleanup_error") == "ChildOwnershipLost"):
        # ECHILD/external reaping irrevocably loses this handle's PID identity.
        # A future successful waitid could name a different, recycled child.
        return
    observation["cleanup_stage"] = "observe_child"
    observation["cleanup_errno"] = None
    try:
        if child.returncode is not None:
            raise ChildProcessError("child was reaped outside its owner")
        exited = observe_owned_exit(child.pid)
    except ChildProcessError:
        observation["cleanup_error"] = "ChildOwnershipLost"
        return
    except OSError as error:
        observation["cleanup_error"] = type(error).__name__
        observation["cleanup_errno"] = error.errno
        return
    observation["cleanup_stage"] = "signal_group"
    try:
        disposition = signal_owned_group(child, exited)
        if disposition == SIGNALLED:
            observation["group_kill_sent"] = True
        if disposition == EXITED_LEADER_ONLY:
            observation["group_exited_leader_only"] = True
    except ChildProcessError:
        observation["cleanup_error"] = "ChildOwnershipLost"
        return
    except OSError as error:
        observation["cleanup_error"] = type(error).__name__
        observation["cleanup_errno"] = error.errno
        return
    observation["cleanup_stage"] = "reap_child"
    try:
        observation["returncode"] = child.wait(timeout=CLEANUP_SECONDS)
        observation["direct_child_exit_observed"] = True
        observation["direct_child_reaped"] = True
        observation["cleanup_error"] = None
        observation["cleanup_stage"] = None
        observation["cleanup_errno"] = None
    except ChildProcessError:
        observation["cleanup_error"] = "ChildOwnershipLost"
    except (subprocess.TimeoutExpired, OSError) as error:
        observation["cleanup_error"] = type(error).__name__
        observation["cleanup_errno"] = error.errno if isinstance(error, OSError) else None


def offline_environment() -> dict[str, str]:
    """Do not forward credential, Python import or dynamic-loader overrides."""
    environment = {key: os.environ[key] for key in
                   ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP",
                    "SYSTEMROOT", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false",
                       PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    return environment


def run_pinned(checkpoint: Path, pins: Path, request_wire: bytes,
               deadline: OwnerDeadline, cancel: threading.Event | None = None,
               *, python_executable: str = sys.executable) -> ProcessPrediction:
    """Launch only the reviewed leaf, never a command supplied by model input.

    The caller must supply immutable artifact paths and the already captured
    deadline. Pins are rechecked by the leaf before loading. This transport has
    bounded parent buffers/time but does not enforce an OS resident-memory quota.
    """
    for path in (checkpoint, pins):
        if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
            raise Rejected("noncanonical owner path")
    if not Path(python_executable).is_absolute() or not Path(python_executable).is_file():
        raise Rejected("interpreter must be an owner-selected absolute file")
    command = [python_executable, "-u", str(Path(__file__).with_name("laya_binary.py").resolve()),
               "--checkpoint", str(checkpoint), "--pins", str(pins)]
    return _exchange(command, request_wire, deadline, cancel)


def _exchange(command: list[str], request_wire: bytes, deadline: OwnerDeadline,
              cancel: threading.Event | None = None) -> ProcessPrediction:
    # WNOWAIT keeps the child PID reserved until group cleanup. Never signal a
    # numerical process group after poll/wait has reaped its leader.
    if not observation_supported():
        raise Rejected("transport requires POSIX non-reaping child observation")
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise Rejected("child lifecycle must not have an external reaper")
    request = decode_request(request_wire)
    deadline.check(request["deadline_ms"])
    if cancel is not None and cancel.is_set():
        raise Rejected("cancelled before process creation")
    observation = {
        "schema": "hepta.laya.process-observation.v1",
        "request_sha256": hashlib.sha256(request_wire).hexdigest(),
        "operation_id": request["operation_id"], "deadline_ms": request["deadline_ms"],
        "spawned": False, "direct_child_exit_observed": False, "returncode": None,
        "direct_child_reaped": False,
        "group_kill_sent": False, "group_exited_leader_only": False,
        "cleanup_error": None, "cleanup_stage": None,
        "cleanup_errno": None, "input_bytes_written": 0,
        "stdout_bytes": 0, "stderr_bytes": 0, "stderr_sha256": None,
        "reply_sha256": None, "eligible_reply": False, "retry_allowed": False,
        "descendant_exit_verified": False, "observed_memory_bytes": None,
        "device_attested": False, "production_composition": False, "task_success": None,
    }
    started = time.monotonic()
    child = None
    selector = selectors.DefaultSelector()
    output = bytearray()
    diagnostics = bytearray()
    reason = None
    cause = None
    identity_lost = False
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=offline_environment(), bufsize=0,
                                 close_fds=True, start_new_session=True)
        observation["spawned"] = True
        for stream, mode, kind in ((child.stdin, selectors.EVENT_WRITE, "input"),
                                   (child.stdout, selectors.EVENT_READ, "output"),
                                   (child.stderr, selectors.EVENT_READ, "diagnostic")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, mode, kind)
        while True:
            deadline.check(request["deadline_ms"])
            if cancel is not None and cancel.is_set():
                raise Rejected("cancelled after process creation")
            exited = observe_owned_exit(child.pid)
            if exited is not None and not selector.get_map():
                break
            remaining = min(0.02, deadline.monotonic_end - deadline.monotonic_clock())
            for key, _ in selector.select(max(0, remaining)):
                stream = key.fileobj
                try:
                    if key.data == "input":
                        offset = observation["input_bytes_written"]
                        wrote = os.write(stream.fileno(), request_wire[offset:offset + 8192])
                        observation["input_bytes_written"] += wrote
                        if observation["input_bytes_written"] == len(request_wire):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        target = output if key.data == "output" else diagnostics
                        limit = MAX_FRAME if key.data == "output" else MAX_DIAGNOSTIC_BYTES
                        chunk = os.read(stream.fileno(), min(8192, limit + 1 - len(target)))
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                        else:
                            target.extend(chunk)
                            if len(target) > limit:
                                raise Rejected("bounded pipe output exceeded")
                except BlockingIOError:
                    continue
    except BaseException as error:
        reason, cause = type(error).__name__, error
        identity_lost = isinstance(error, ChildProcessError)
    finally:
        # A selector/pipe finalizer must not bypass owned-child cleanup. Keep
        # interruptions as the cause of the typed failure until identity is safe.
        try:
            selector.close()
        except BaseException as error:
            reason, cause = type(error).__name__, error
        if child is not None and identity_lost:
            observation["cleanup_error"] = "ChildOwnershipLost"
        if child is not None and not identity_lost:
            try:
                _cleanup_owned_child(child, observation)
            except BaseException as error:
                # Even process interruption cannot discard an unresolved child.
                reason, cause = type(error).__name__, error
                observation["cleanup_error"] = type(error).__name__
        if child is not None:
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        reason, cause = type(error).__name__, error
        observation.update(stdout_bytes=len(output), stderr_bytes=len(diagnostics),
                           stderr_sha256=hashlib.sha256(diagnostics).hexdigest(),
                           transport_seconds=time.monotonic() - started)
    if reason is None:
        try:
            if (observation["returncode"] != 0 or observation["cleanup_error"] is not None
                    or observation["input_bytes_written"] != len(request_wire)):
                raise Rejected("process did not complete the admitted exchange")
            deadline.check(request["deadline_ms"])
            decode_reply(bytes(output), request_wire)
            # The last loop check predates group observation and bounded reap.
            # Cancellation during that interval cannot publish an eligible reply.
            if cancel is not None and cancel.is_set():
                raise Rejected("cancelled before result delivery")
        except Exception as error:
            reason, cause = type(error).__name__, error
    if reason is not None:
        observation["failure_type"] = reason
        # Never publish partial output or diagnostics containing source text.
        pending = child if not observation["direct_child_reaped"] else None
        if pending is None and cause is not None and not isinstance(cause, Exception):
            raise cause
        raise ProcessFailure(reason, observation, pending) from cause
    observation["reply_sha256"] = hashlib.sha256(output).hexdigest()
    observation["eligible_reply"] = True
    return ProcessPrediction(bytes(output), observation)
