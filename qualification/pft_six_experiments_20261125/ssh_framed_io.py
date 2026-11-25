"""Bounded POSIX pipe framing for the fixed, one-round SSH statistic protocol."""

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import threading
import time

from distributed import durable_write, encoded

MAX_FRAME = 65_536
MAX_STDERR = 65_536
WIRE = "pft-direct-ssh-statistics-v2"


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
    def __init__(self, reader, writer, folder, node, round_id, context_id, deadline, cancel=None):
        self.reader, self.writer = reader, writer
        self.folder, self.node = Path(folder), node
        self.round_id, self.context_id, self.deadline = round_id, context_id, deadline
        self.cancel = cancel
        self.sent, self.received, self.events = 0, 0, []
        os.set_blocking(reader, False)
        os.set_blocking(writer, False)

    def ready(self, fd, event):
        with selectors.DefaultSelector() as selector:
            selector.register(fd, event)
            while True:
                if self.cancel is not None and self.cancel.is_set():
                    raise ValueError("Bounded SSH diagnostic capture cancelled the exchange")
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Absolute SSH application deadline exceeded")
                if selector.select(min(.05, remaining) if self.cancel is not None else remaining):
                    return

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


def wait_owned_child(process, deadline, cancel=None):
    """Observe a direct child's exit without releasing its PID/process group."""
    while True:
        if process.returncode is not None:
            raise RuntimeError("The sole reaper must not reap before group cleanup")
        if cancel is not None and cancel.is_set():
            raise ValueError("Bounded SSH diagnostic capture cancelled the exchange")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Absolute owned-child deadline exceeded")
        try:
            status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except InterruptedError:
            continue
        if status is not None:
            if status.si_code == os.CLD_EXITED:
                return status.si_status
            if status.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
                return -status.si_status
            raise RuntimeError("Unexpected owned-child exit status")
        time.sleep(min(.005, remaining))


def terminate_owned_child(process):
    """Signal the still-reserved group, then be its leader's unique final reaper."""
    if process.returncode is not None:
        if not getattr(process, "_hepta_group_signals_complete", False):
            raise RuntimeError("Already-reaped leader cannot authorize a process-group signal")
        return process.returncode
    # WNOWAIT also confirms that this PID is still our direct, unreaped child.
    os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            wait_owned_child(process, time.monotonic() + 2)
        except TimeoutError:
            pass
    finally:
        # No poll/wait or diagnostic-thread signal may precede this final group
        # signal. A zombie leader reserves the PGID even on successful exit.
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process._hepta_group_signals_complete = True
        process.wait(timeout=2)
    return process.returncode


def collect_stderr(process, deadline):
    """Only observe; all process signals and reaping belong to the main owner."""
    state = {"raw": bytearray(), "overflow": False, "eof": False, "deadline_reached": False, "error": None,
             "observed_bytes": 0}
    stop = threading.Event()
    cancel = threading.Event()
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
                        cancel.set()
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
                    available = MAX_STDERR - len(state["raw"])
                    state["observed_bytes"] += len(part)
                    state["raw"].extend(part[:available])
                    if len(part) > available:
                        state["overflow"] = True
                        cancel.set()
                        return
        except BaseException as error:
            state["error"] = {"type": type(error).__name__, "message": str(error)[:200]}
            cancel.set()

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return state, thread, stop, cancel
