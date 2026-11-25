"""Bounded POSIX pipe framing for the fixed, one-round SSH statistic protocol."""

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import threading
import time

from distributed import durable_write, encoded

MAX_FRAME = 65_536
MAX_STDERR = 65_536
WIRE = "pft-direct-ssh-statistics-v1"


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError("Nonfinite JSON constant: " + value)


class Stream:
    def __init__(self, reader, writer, folder, node, round_id, context_id, deadline):
        self.reader, self.writer = reader, writer
        self.folder, self.node = Path(folder), node
        self.round_id, self.context_id, self.deadline = round_id, context_id, deadline
        self.sent, self.received, self.events = 0, 0, []
        os.set_blocking(reader, False)
        os.set_blocking(writer, False)

    def ready(self, fd, event):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Absolute SSH application deadline exceeded")
        with selectors.DefaultSelector() as selector:
            selector.register(fd, event)
            if not selector.select(remaining):
                raise TimeoutError("Absolute SSH application deadline exceeded")

    def record(self, direction, raw, status, started, transferred):
        digest = hashlib.sha256(raw).hexdigest()
        frames = self.folder / "frames"
        frames.mkdir(exist_ok=True)
        path = frames / digest
        try:
            with path.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("Retained frame differs")
        self.events.append({"direction": direction, "wire_sha256": digest,
                            "frame_bytes": len(raw), "transferred_bytes": transferred,
                            "status": status, "elapsed_seconds": time.monotonic() - started})
        durable_write(self.folder / "frames.json", self.events)

    def send(self, kind, body):
        packet = {"schema": WIRE, "round_id": self.round_id, "context_id": self.context_id,
                  "sender": self.node, "recipient": 1 - self.node, "sequence": self.sent,
                  "kind": kind, "body": body}
        payload = encoded(packet).encode()
        if len(payload) > MAX_FRAME:
            raise ValueError("Oversized SSH application frame")
        raw = struct.pack("!I", len(payload)) + payload
        written, started, status = 0, time.monotonic(), "complete"
        try:
            while written < len(raw):
                self.ready(self.writer, selectors.EVENT_WRITE)
                try:
                    count = os.write(self.writer, raw[written:])
                except BlockingIOError:
                    continue
                if not count:
                    raise ConnectionError("SSH pipe closed while writing")
                written += count
            self.sent += 1
        except BaseException as error:
            status = type(error).__name__
            raise
        finally:
            self.record("send", raw, status, started, written)

    def receive(self, kind):
        raw, started, status = bytearray(), time.monotonic(), "complete"
        try:
            length = 4
            while len(raw) < length:
                self.ready(self.reader, selectors.EVENT_READ)
                try:
                    part = os.read(self.reader, length - len(raw))
                except BlockingIOError:
                    continue
                if not part:
                    raise ConnectionError("SSH pipe closed before a complete frame")
                raw.extend(part)
                if len(raw) == 4 and length == 4:
                    payload_length = struct.unpack("!I", raw)[0]
                    if not 1 <= payload_length <= MAX_FRAME:
                        raise ValueError("Oversized or empty SSH application frame")
                    length = 4 + payload_length
            packet = json.loads(raw[4:], object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not isinstance(packet, dict) or set(packet) != {
                "schema", "round_id", "context_id", "sender", "recipient", "sequence", "kind", "body"
            }:
                raise ValueError("Malformed SSH protocol envelope")
            expected = {"schema": WIRE, "round_id": self.round_id, "context_id": self.context_id,
                        "sender": 1 - self.node, "recipient": self.node, "sequence": self.received,
                        "kind": kind}
            if any(packet[key] != value for key, value in expected.items()) or any(
                type(packet[key]) is not int for key in ("sender", "recipient", "sequence")
            ) or not isinstance(packet["body"], dict):
                raise ValueError("SSH peer, sequence, round, context or phase differs")
            self.received += 1
            return packet["body"]
        except BaseException as error:
            status = type(error).__name__
            raise
        finally:
            self.record("receive", bytes(raw), status, started, len(raw))


def terminate_owned_child(process):
    """Only a Popen child started in its own session; at most four extra seconds."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
    finally:
        # A terminal leader is insufficient: its descendants may still own the
        # SSH pipe. This group was created exclusively for this invocation.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return process.returncode


def collect_stderr(process, deadline):
    """Bound SSH diagnostics; overflowing peers terminate this owned child group."""
    state = {"raw": bytearray(), "overflow": False, "eof": False, "deadline_reached": False, "error": None}
    stop = threading.Event()
    descriptor = process.stderr.fileno()
    os.set_blocking(descriptor, False)

    def drain():
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_READ)
                while not stop.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        state["deadline_reached"] = True
                        return
                    if not selector.select(min(.05, remaining)):
                        continue
                    try:
                        part = os.read(descriptor, min(4096, MAX_STDERR + 1 - len(state["raw"])))
                    except BlockingIOError:
                        continue
                    if not part:
                        state["eof"] = True
                        return
                    state["raw"].extend(part)
                    if len(state["raw"]) > MAX_STDERR:
                        state["overflow"] = True
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        return
        except BaseException as error:
            state["error"] = {"type": type(error).__name__, "message": str(error)[:200]}

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return state, thread, stop
