"""POSIX bounded private process transport for an existing inference owner.

No effect, durable store, automatic retry or selection authority. The owner must
supply a reviewed executable/environment and artifact identity, reserve resources,
persist dispatch before calling, and durably retain a validated response. A new
process cannot prove that its predecessor never ran an unknown operation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence

MAX_FRAME = 96 * 1024
MAX_SECONDS = 120
COMMAND_SCHEMA = "hepta.frozen-encoder-command.v1"
REPLY_SCHEMA = "hepta.frozen-encoder-reply.v1"


class WorkerTransportError(RuntimeError):
    """Channel closed or corrupt. Already submitted inference is indeterminate."""


class WorkerCancelled(WorkerTransportError):
    pass


class WorkerDeadline(WorkerTransportError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _json(raw: bytes) -> dict:
    def pairs(items):
        value = dict(items)
        if len(value) != len(items):
            raise ValueError("duplicate reply field")
        return value
    def nonfinite(_):
        raise ValueError("non-finite reply")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("reply must be an object")
    return value


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None and value != "0" * 64


def build_request(request_id: str, text: str, candidates: Sequence[str], *, deadline_ns: int) -> dict:
    if not isinstance(request_id, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id) is None:
        raise ValueError("invalid request identity")
    if not isinstance(text, str) or not 0 < len(text.encode()) <= 16384:
        raise ValueError("invalid observation text")
    if not isinstance(candidates, (list, tuple)) or len(candidates) != 4 or any(
            not isinstance(item, str) or not 0 < len(item.encode()) <= 4096 for item in candidates):
        raise ValueError("invalid candidate texts")
    if type(deadline_ns) is not int or not time.monotonic_ns() < deadline_ns <= time.monotonic_ns() + MAX_SECONDS * 10**9:
        raise ValueError("invalid process-local deadline")
    projection = {"projection_schema": "hepta.decision-cell-text-projection.v1",
                  "texts": [text], "candidates": [list(candidates)]}
    return {"schema": "hepta.frozen-encoder-request.v1", "request_id": request_id,
            "projection_sha256": hashlib.sha256(canonical(projection)).hexdigest(),
            "deadline_monotonic_ns": deadline_ns, "text": text, "candidates": list(candidates)}


class FrozenEncoderProcess:
    """One serialized, artifact-bound resident process; fail closed on uncertainty.

    Nonblocking writes and reads both honor cancellation/deadline. Termination
    kills only the child's newly created process group and reaps the direct child.
    POSIX only: Windows is deliberately not claimed by this transport.
    """
    def __init__(self, command: Sequence[str], expected_ready: Mapping[str, Any], *,
                 environment: Mapping[str, str], startup_seconds: float = 120):
        if os.name != "posix":
            raise ValueError("POSIX process profile required")
        if not 0 < startup_seconds <= MAX_SECONDS or not command or any(type(v) is not str for v in command):
            raise ValueError("invalid bounded launch configuration")
        if not Path(command[0]).is_absolute():
            raise ValueError("executable must be an absolute host-selected path")
        required = {"schema", "session_id", "head_manifest_sha256", "base_snapshot_digest",
                    "runtime_profile_sha256", "device", "advisory_only", "external_effect"}
        expected = dict(expected_ready)
        if set(expected) != required or expected["schema"] != "hepta.frozen-encoder-ready.v1" or expected["device"] != "cpu":
            raise ValueError("invalid ready profile")
        if expected["advisory_only"] is not True or expected["external_effect"] is not False:
            raise ValueError("invalid authority profile")
        if not isinstance(expected["session_id"], str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", expected["session_id"]) is None:
            raise ValueError("invalid session")
        if any(not _digest(expected[k]) for k in ("head_manifest_sha256", "base_snapshot_digest", "runtime_profile_sha256")):
            raise ValueError("invalid artifact identity")
        self.expected = expected
        self._lock = threading.Lock()
        self._closed = False
        self._buffer = bytearray()
        self._process = subprocess.Popen(list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=dict(environment), close_fds=True, start_new_session=True, bufsize=0)
        self.pid = self._process.pid
        os.set_blocking(self._process.stdin.fileno(), False)
        os.set_blocking(self._process.stdout.fileno(), False)
        try:
            deadline = time.monotonic_ns() + int(startup_seconds * 10**9)
            ready = _json(self._read(deadline, None))
            if ready != self.expected:
                raise WorkerTransportError("worker ready artifact/session mismatch")
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _check(self, deadline: int, cancel: threading.Event | None) -> float:
        if self._closed:
            raise WorkerTransportError("worker channel is permanently closed")
        if cancel is not None and cancel.is_set():
            raise WorkerCancelled("worker request cancelled")
        remaining = (deadline - time.monotonic_ns()) / 10**9
        if remaining <= 0:
            raise WorkerDeadline("worker deadline expired")
        return min(remaining, 0.025)

    def _wait(self, stream, mode: int, deadline: int, cancel: threading.Event | None) -> None:
        with selectors.DefaultSelector() as selector:
            selector.register(stream, mode)
            while True:
                if selector.select(self._check(deadline, cancel)):
                    self._check(deadline, cancel)
                    return

    def _write(self, raw: bytes, deadline: int, cancel: threading.Event | None) -> None:
        offset = 0
        while offset < len(raw):
            self._wait(self._process.stdin, selectors.EVENT_WRITE, deadline, cancel)
            try:
                count = os.write(self._process.stdin.fileno(), raw[offset:])
            except BlockingIOError:
                continue
            if count <= 0:
                raise WorkerTransportError("worker input closed")
            offset += count

    def _read(self, deadline: int, cancel: threading.Event | None) -> bytes:
        while True:
            self._check(deadline, cancel)
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                if newline + 1 > MAX_FRAME:
                    raise WorkerTransportError("worker reply exceeds frame bound")
                raw = bytes(self._buffer[:newline + 1])
                del self._buffer[:newline + 1]
                if self._buffer:
                    raise WorkerTransportError("unsolicited buffered worker reply")
                return raw
            if len(self._buffer) >= MAX_FRAME:
                raise WorkerTransportError("unterminated oversized worker reply")
            self._wait(self._process.stdout, selectors.EVENT_READ, deadline, cancel)
            try:
                data = os.read(self._process.stdout.fileno(), min(8192, MAX_FRAME + 1 - len(self._buffer)))
            except BlockingIOError:
                continue
            if not data:
                raise WorkerTransportError("worker exited without complete reply")
            self._buffer.extend(data)

    def exchange(self, value: Mapping[str, Any], invocation_sha256: str, *,
                 kind: str = "infer", timeout_seconds: float = 30,
                 cancel: threading.Event | None = None) -> dict:
        if kind not in ("infer", "lookup") or not _digest(invocation_sha256):
            raise ValueError("invalid command binding")
        if not 0 < timeout_seconds <= MAX_SECONDS:
            raise ValueError("invalid transport deadline")
        # Snapshot caller-owned containers before hashing and dispatch.
        request = _json(canonical(dict(value)))
        raw = canonical({"schema": COMMAND_SCHEMA, "session_id": self.expected["session_id"],
            "kind": kind, "invocation_sha256": invocation_sha256, "request": request})
        if len(raw) > MAX_FRAME:
            raise ValueError("request exceeds frame bound")
        deadline = time.monotonic_ns() + int(timeout_seconds * 10**9)
        if kind == "infer":
            request_deadline = request.get("deadline_monotonic_ns")
            if type(request_deadline) is not int:
                raise ValueError("invalid request deadline")
            deadline = min(deadline, request_deadline)
        # Contention never creates an unbounded wait or kills somebody else's call.
        while not self._lock.acquire(timeout=self._check(deadline, cancel)):
            pass
        try:
            self._check(deadline, cancel)
            self._write(raw, deadline, cancel)
            reply = _json(self._read(deadline, cancel))
            expected_binding = {"schema": REPLY_SCHEMA, "session_id": self.expected["session_id"],
                "request_id": request["request_id"], "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
                "invocation_sha256": invocation_sha256, "projection_sha256": request["projection_sha256"],
                "advisory_only": True, "external_effect": False}
            if set(reply) != {*expected_binding, "status", "observation"} or any(
                    reply[key] != val or type(reply[key]) is not type(val) for key, val in expected_binding.items()):
                raise WorkerTransportError("reply request/session/authority binding mismatch")
            if reply["status"] not in ("observed", "unknown", "indeterminate"):
                raise WorkerTransportError("invalid reply disposition")
            if reply["status"] == "observed":
                self._validate_observation(reply["observation"], request["projection_sha256"])
            elif reply["observation"] is not None or (kind == "infer" and reply["status"] == "unknown"):
                raise WorkerTransportError("invalid unknown outcome")
            self._check(deadline, cancel)
            return reply
        except BaseException:
            self.close()
            raise
        finally:
            self._lock.release()

    def _validate_observation(self, value: Any, projection: str) -> None:
        bindings = {"schema": "hepta.frozen-encoder-observation.v2", "input_sha256": projection,
            "base_snapshot_digest": self.expected["base_snapshot_digest"],
            "head_manifest_sha256": self.expected["head_manifest_sha256"],
            "advisory_only": True, "external_effect": False}
        if not isinstance(value, dict) or set(value) != {*bindings, "scores", "probabilities", "base_forward_passes", "latency_ns"}:
            raise WorkerTransportError("invalid observation shape")
        if any(value[k] != v or type(value[k]) is not type(v) for k, v in bindings.items()):
            raise WorkerTransportError("observation artifact/input binding mismatch")
        if any(type(value[k]) is not int or not 0 < value[k] <= limit for k, limit in (
                ("base_forward_passes", 2), ("latency_ns", MAX_SECONDS * 10**9))):
            raise WorkerTransportError("invalid observed runtime bounds")
        shapes = {"action": 6, "target": 4, "disposition": 6, "postcondition": 6, "ood": 2, "value_cost": 2}
        for group in ("scores", "probabilities"):
            expected_keys = set(shapes) if group == "scores" else set(shapes) - {"value_cost"} | {"supported"}
            if not isinstance(value[group], dict) or set(value[group]) != expected_keys:
                raise WorkerTransportError("invalid output heads")
            for key, array in value[group].items():
                if key == "supported":
                    if type(array) is not list or len(array) != 1 or type(array[0]) is not bool:
                        raise WorkerTransportError("invalid supported flag")
                    continue
                if type(array) is not list or len(array) != 1 or type(array[0]) is not list or len(array[0]) != shapes[key]:
                    raise WorkerTransportError("invalid tensor shape")
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in array[0]):
                    raise WorkerTransportError("nonfinite tensor")
                if group == "probabilities" and (any(v < 0 or v > 1 for v in array[0]) or abs(sum(array[0]) - 1) > 1e-5):
                    raise WorkerTransportError("invalid probability simplex")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            self._process.wait(timeout=5)
            self._process.stdin.close()
            self._process.stdout.close()
            self._buffer.clear()
