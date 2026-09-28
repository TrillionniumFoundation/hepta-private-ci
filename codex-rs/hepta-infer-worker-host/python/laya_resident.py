"""Bounded resident transport for the existing pinned semantic predictor.

This leaf owns only a child handle, not admission, journals, artifact selection or
result delivery. A resident reply settles one computation, NOT the model lease.
The native owner must keep its reservation until independent physical settlement.
Process groups are cleanup aids, not descendant containment or device attestation.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import select
import selectors
import signal
import struct
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Callable

from hepta_retrieval_wire import MAX_FRAME, decode_reply, decode_request
from laya_binary import BinaryRetrievalDriver, OwnerDeadline
from laya_process import (MAX_DIAGNOSTIC_BYTES, ProcessFailure, ProcessPrediction,
                          _cleanup_owned_child, offline_environment)
from laya_retrieval import Rejected, digest, load_pinned
from laya_wait import observation_supported

MAX_OPERATIONS = 64
MAX_LIFETIME_SECONDS = 300.0


def _limits(operations: int, seconds: float) -> None:
    if (type(operations) is not int or not 1 <= operations <= MAX_OPERATIONS
            or type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not 0 < seconds <= MAX_LIFETIME_SECONDS):
        raise Rejected("invalid resident lifetime or operation bound")


def _scope(request: dict) -> tuple:
    return request["workspace_id"], request["generation"], request["bundle_digest"]


def _read_exact(stream: BinaryIO, size: int, lifetime: OwnerDeadline) -> bytes:
    result = bytearray()
    try:
        descriptor = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        descriptor = None  # Deterministic in-memory unit fixtures only.
    while len(result) < size:
        lifetime.check(lifetime.unix_ms)
        if descriptor is None:
            chunk = stream.read(size - len(result))
        else:
            if not select.select([descriptor], [], [], 0.02)[0]:
                continue
            chunk = os.read(descriptor, size - len(result))
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


def serve(stream: BinaryIO, output: BinaryIO,
          loader: Callable[[dict], BinaryRetrievalDriver], *,
          maximum_operations: int = MAX_OPERATIONS,
          lifetime_seconds: float = MAX_LIFETIME_SECONDS) -> int:
    """Load once and process sequential, bounded, independently bound frames.

    Outer u32 lengths are transport framing only. Inner HPTARQ/HPTARS V1 bytes,
    selected bundle identity and probability semantics are unchanged. No request
    ID is rerun; a durable owner must replay its own committed result instead.
    """
    _limits(maximum_operations, lifetime_seconds)
    lifetime = OwnerDeadline.start(math.ceil(time.time() * 1000 + lifetime_seconds * 1000),
                                   maximum_seconds=lifetime_seconds)
    driver = None
    bound_scope = None
    seen = set()
    for _ in range(maximum_operations):
        header = _read_exact(stream, 4, lifetime)
        if not header:
            return len(seen)
        if len(header) != 4:
            raise Rejected("partial resident frame header")
        size = struct.unpack(">I", header)[0]
        if not 1 <= size <= MAX_FRAME:
            raise Rejected("resident frame bound")
        wire = _read_exact(stream, size, lifetime)
        request = decode_request(wire)
        deadline = OwnerDeadline.start(request["deadline_ms"])
        if ((bound_scope is not None and _scope(request) != bound_scope)
                or request["operation_id"] in seen):
            raise Rejected("resident generation substitution or duplicate operation")
        seen.add(request["operation_id"])
        if driver is None:
            bound_scope = _scope(request)
            driver = loader(request)
        lifetime.check(lifetime.unix_ms)
        deadline.check(request["deadline_ms"])
        result = driver.predict(wire, deadline)
        lifetime.check(lifetime.unix_ms)
        deadline.check(request["deadline_ms"])
        decode_reply(result.wire, wire)
        # A supervisor bounds blocking writes and can stop in-flight computation.
        frame = struct.pack(">I", len(result.wire)) + result.wire
        offset = 0
        while offset < len(frame):
            lifetime.check(lifetime.unix_ms)
            deadline.check(request["deadline_ms"])
            written = output.write(frame[offset:])
            if type(written) is not int or not 0 < written <= len(frame) - offset:
                raise Rejected("resident output made no progress")
            offset += written
        output.flush()
    return len(seen)


class ResidentLaya:
    """Exclusive, sequential model-process handle; never restarts after failure.

    Use a context manager or explicitly close this handle. Cancellation after
    dispatch fences the entire session, kills the owned group and retains an
    unreaped child on cleanup failure. Reconciliation never replays inference.
    No caller queue is allocated: concurrent use rejects before transport I/O.
    """
    def __init__(self, checkpoint: Path, pins: Path, *,
                 python_executable: str = sys.executable,
                 maximum_operations: int = MAX_OPERATIONS,
                 lifetime_seconds: float = MAX_LIFETIME_SECONDS):
        _limits(maximum_operations, lifetime_seconds)
        for path in (checkpoint, pins):
            if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
                raise Rejected("noncanonical owner path")
        if not Path(python_executable).is_absolute() or not Path(python_executable).is_file():
            raise Rejected("interpreter must be an owner-selected absolute file")
        self._command = [python_executable, "-u", str(Path(__file__).resolve()),
                         "--checkpoint", str(checkpoint), "--pins", str(pins),
                         "--maximum-operations", str(maximum_operations),
                         "--lifetime-seconds", str(lifetime_seconds)]
        self._maximum = maximum_operations
        self._seconds = lifetime_seconds
        self._lock = threading.Lock()
        self._child = None
        self._selector = None
        self._failure = None
        self._closed = False
        self._scope = None
        self._seen = set()
        self._diagnostics = bytearray()
        self._lifetime = None
        self._observation = {
            "schema": "hepta.laya.resident-observation.v1",
            "spawned": False, "process_id": None, "completed_exchanges": 0,
            "input_bytes_written": 0, "stdout_bytes": 0, "stderr_bytes": 0,
            "direct_child_reaped": False, "direct_child_exit_observed": False,
            "group_kill_sent": False, "group_exited_leader_only": False,
            "cleanup_error": None, "cleanup_stage": None, "cleanup_errno": None,
            "returncode": None, "eligible_reply": False, "retry_allowed": False,
            "descendant_exit_verified": False, "observed_memory_bytes": None,
            "device_attested": False, "production_composition": False,
            "model_reservation_released": False, "task_success": None,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def observation(self) -> dict:
        return dict(self._observation)

    def _start(self) -> None:
        if not observation_supported() or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise Rejected("resident transport requires exclusive POSIX child observation")
        self._lifetime = OwnerDeadline.start(
            math.ceil(time.time() * 1000 + self._seconds * 1000), maximum_seconds=self._seconds)
        self._selector = selectors.DefaultSelector()
        self._child = subprocess.Popen(
            self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=offline_environment(), bufsize=0,
            close_fds=True, start_new_session=True)
        self._observation.update(spawned=True, process_id=self._child.pid)
        for stream in (self._child.stdin, self._child.stdout, self._child.stderr):
            os.set_blocking(stream.fileno(), False)
        self._selector.register(self._child.stdout, selectors.EVENT_READ, "output")
        self._selector.register(self._child.stderr, selectors.EVENT_READ, "diagnostic")

    def _settle_child(self) -> None:
        # Finalizer errors cannot discard the only retained process handle.
        cleanup_error = None
        if self._selector is not None:
            try:
                self._selector.close()
            except BaseException as error:
                cleanup_error = error
            self._selector = None
        if self._child is not None:
            try:
                _cleanup_owned_child(self._child, self._observation)
            except BaseException as error:
                cleanup_error = error
                self._observation["cleanup_error"] = type(error).__name__
            for stream in (self._child.stdin, self._child.stdout, self._child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        cleanup_error = error
            if self._observation["direct_child_reaped"]:
                self._child = None
        self._observation.update(stderr_bytes=len(self._diagnostics),
                                 stderr_sha256=hashlib.sha256(self._diagnostics).hexdigest())
        if cleanup_error is not None:
            raise cleanup_error

    def predict(self, wire: bytes, deadline: OwnerDeadline,
                cancel: threading.Event | None = None) -> ProcessPrediction:
        if not self._lock.acquire(blocking=False):
            raise Rejected("resident capacity occupied")
        try:
            if self._closed or self._failure is not None:
                raise Rejected("resident handle is closed or fenced")
            request = decode_request(wire)
            deadline.check(request["deadline_ms"])
            if cancel is not None and cancel.is_set():
                raise Rejected("cancelled before resident dispatch")
            if ((self._scope is not None and _scope(request) != self._scope)
                    or request["operation_id"] in self._seen
                    or len(self._seen) >= self._maximum):
                raise Rejected("resident scope, operation identity or capacity mismatch")
            self._observation.update(eligible_reply=False, operation_id=request["operation_id"],
                                     request_sha256=hashlib.sha256(wire).hexdigest(),
                                     deadline_ms=request["deadline_ms"], reply_sha256=None)
            def check_active() -> None:
                deadline.check(request["deadline_ms"])
                if self._lifetime is not None:
                    self._lifetime.check(self._lifetime.unix_ms)
                if cancel is not None and cancel.is_set():
                    raise Rejected("cancelled resident request")
            try:
                # Preflight work must not consume the original deadline and then
                # spawn anyway. This check grants no authority to the child.
                check_active()
                if self._child is None:
                    self._start()
                    self._scope = _scope(request)
                check_active()
                # An idle channel must have no unsolicited response, nor EOF.
                try:
                    unsolicited = os.read(self._child.stdout.fileno(), MAX_FRAME + 5)
                except BlockingIOError:
                    unsolicited = None
                if unsolicited is not None:
                    raise Rejected("unsolicited resident output or closed child")
                self._seen.add(request["operation_id"])
                frame = struct.pack(">I", len(wire)) + wire
                offset = 0
                output = bytearray()
                expected = None
                self._selector.register(self._child.stdin, selectors.EVENT_WRITE, "input")
                while True:
                    check_active()
                    for key, _ in self._selector.select(0.02):
                        # Readiness is not permission: cancellation or expiry may
                        # have occurred while waiting, or during a previous event.
                        check_active()
                        try:
                            if key.data == "input":
                                wrote = os.write(key.fd, frame[offset:offset + 8192])
                                if not wrote:
                                    raise Rejected("resident write made no progress")
                                offset += wrote
                                self._observation["input_bytes_written"] += wrote
                                if offset == len(frame):
                                    self._selector.unregister(key.fileobj)
                                continue
                            target = output if key.data == "output" else self._diagnostics
                            bound = MAX_FRAME + 4 if key.data == "output" else MAX_DIAGNOSTIC_BYTES
                            chunk = os.read(key.fd, min(8192, bound + 1 - len(target)))
                            if not chunk:
                                if key.data == "output":
                                    raise Rejected("resident response ended prematurely")
                                self._selector.unregister(key.fileobj)
                                continue
                            target.extend(chunk)
                            if key.data == "output":
                                self._observation["stdout_bytes"] += len(chunk)
                            else:
                                self._observation["stderr_bytes"] = len(self._diagnostics)
                            if len(target) > bound:
                                raise Rejected("resident output bound exceeded")
                        except BlockingIOError:
                            continue
                    if len(output) >= 4:
                        expected = 4 + struct.unpack(">I", output[:4])[0]
                        if not 5 <= expected <= MAX_FRAME + 4 or len(output) > expected:
                            raise Rejected("resident frame overflow")
                    if expected is not None and len(output) == expected:
                        if offset != len(frame):
                            raise Rejected("resident replied before complete request")
                        reply = bytes(output[4:])
                        decode_reply(reply, wire)
                        # Hashing is part of observation, not a deadline reset.
                        # Retain this current reply identity even if final use
                        # expires, but never publish it as an eligible result.
                        self._observation["reply_sha256"] = hashlib.sha256(reply).hexdigest()
                        check_active()
                        self._observation["completed_exchanges"] += 1
                        self._observation.update(eligible_reply=True)
                        return ProcessPrediction(reply, self.observation)
            except BaseException as cause:
                self._closed = True
                self._observation.update(eligible_reply=False, failure_type=type(cause).__name__)
                try:
                    self._settle_child()
                except BaseException:
                    pass  # Original cause plus retained ownership remain available.
                self._failure = ProcessFailure(type(cause).__name__, self._observation, self._child)
                raise self._failure from cause
        finally:
            self._lock.release()

    def close(self) -> dict:
        if not self._lock.acquire(blocking=False):
            raise Rejected("cancel the active request before closing its resident handle")
        try:
            self._closed = True
            if self._failure is not None:
                self._observation.update(self._failure.reconcile_cleanup())
                self._child = self._failure.child
                if self._child is not None:
                    raise self._failure
                return self.observation
            try:
                self._settle_child()
            except BaseException as cause:
                self._failure = ProcessFailure(type(cause).__name__, self._observation, self._child)
                raise self._failure from cause
            if self._child is not None:
                self._failure = ProcessFailure("resident cleanup unresolved", self._observation, self._child)
                raise self._failure
            return self.observation
        finally:
            self._lock.release()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--maximum-operations", type=int, default=MAX_OPERATIONS)
    parser.add_argument("--lifetime-seconds", type=float, default=MAX_LIFETIME_SECONDS)
    args = parser.parse_args()
    def loader(request):
        with args.pins.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise Rejected("pin manifest byte bound")
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise Rejected("duplicate pin manifest key")
                result[key] = value
            return result
        pins = json.loads(raw, object_pairs_hook=unique)
        if digest(pins) != request["bundle_digest"]:
            raise Rejected("wrong pinned resident bundle before load")
        agent, identity = load_pinned(args.checkpoint, pins)
        return BinaryRetrievalDriver(agent, identity)
    output = sys.stdout.buffer
    with contextlib.redirect_stdout(sys.stderr):
        serve(sys.stdin.buffer, output, loader, maximum_operations=args.maximum_operations,
              lifetime_seconds=args.lifetime_seconds)


if __name__ == "__main__":
    main()
