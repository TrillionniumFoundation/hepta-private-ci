#!/usr/bin/env python3
"""Read-only, synthetic execution transport cost probe; never executes user commands.

This is a research-only comparison of Python dispatch/IPC mechanisms. It is NOT
Codex Exec Server and cannot mint Hepta authority or attest real tool effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Any

SCHEMA_VERSION = 1
MAX_FRAME_BYTES = 65_536
MAX_PAYLOAD_BYTES = 8_192
MAX_ACTIVE_CELLS = 4_096
MAX_LOGICAL_CELLS = 4_096
MAX_OPERATIONS = 8_192
MAX_COLD_OPERATIONS = 32
REQUIRED_INTENT = frozenset({
    "version", "operation_id", "scope", "generation", "fence",
    "payload", "payload_sha256",
})
REQUIRED_RECEIPT = frozenset({
    "version", "operation_id", "scope", "generation", "fence",
    "payload_sha256", "disposition", "authority", "external_effect_observed",
})


class ProtocolRejected(ValueError):
    """Malformed research message; this is not an authority verdict."""


class TransportIndeterminate(RuntimeError):
    """Request may have reached a peer; never silently retry as a new operation."""


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolRejected("duplicate JSON key")
        result[key] = value
    return result


def decode_object(raw: bytes, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise ProtocolRejected("bounded bytes required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise ProtocolRejected("invalid JSON") from exc
    if not isinstance(value, dict) or value.keys() != fields:
        raise ProtocolRejected("unknown/missing critical field")
    return value


def valid_identity(value: Any) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 96
            and value.isascii() and all(c.isalnum() or c in "-_." for c in value))


def validate_identity(value: dict[str, Any]) -> None:
    if type(value["version"]) is not int or value["version"] != SCHEMA_VERSION:
        raise ProtocolRejected("unsupported version")
    if not valid_identity(value["operation_id"]) or not valid_identity(value["scope"]):
        raise ProtocolRejected("invalid identity")
    if not all(type(value[k]) is int and 0 < value[k] < 2**63
               for k in ("generation", "fence")):
        raise ProtocolRejected("invalid generation/fence")
    digest = value["payload_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProtocolRejected("invalid digest")


def evaluate(raw: bytes) -> bytes:
    """Pure read-only fake work; consumes identical encoded bytes in every mode."""
    value = decode_object(raw, REQUIRED_INTENT)
    validate_identity(value)
    payload = value["payload"]
    if not isinstance(payload, str) or not payload.isascii() or len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolRejected("invalid bounded research payload")
    digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
    if digest != value["payload_sha256"]:
        raise ProtocolRejected("payload digest mismatch")
    # No shell, filesystem mutation, HTTP, model, Codex, or executable tool path.
    return canonical_json({
        "version": SCHEMA_VERSION,
        "operation_id": value["operation_id"],
        "scope": value["scope"],
        "generation": value["generation"],
        "fence": value["fence"],
        "payload_sha256": digest,
        "disposition": "SYNTHETIC_ONLY",
        "authority": "DENY_ALL",
        "external_effect_observed": False,
    })


def validate_receipt(raw: bytes, intent: bytes) -> None:
    receipt = decode_object(raw, REQUIRED_RECEIPT)
    origin = decode_object(intent, REQUIRED_INTENT)
    validate_identity(receipt)
    if any(receipt[k] != origin[k] for k in (
        "operation_id", "scope", "generation", "fence", "payload_sha256"
    )):
        raise ProtocolRejected("receipt correlation mismatch")
    if (receipt["disposition"] != "SYNTHETIC_ONLY"
            or receipt["authority"] != "DENY_ALL"
            or receipt["external_effect_observed"] is not False):
        raise ProtocolRejected("research receipt attempted to assert authority/effect")
    if raw != evaluate(intent):
        raise ProtocolRejected("noncanonical/altered receipt")


def make_intents(logical_cells: int, active_cells: int, payload_bytes: int) -> list[bytes]:
    if not (1 <= logical_cells <= MAX_LOGICAL_CELLS
            and 1 <= active_cells <= min(logical_cells, MAX_ACTIVE_CELLS)
            and 0 <= payload_bytes <= MAX_PAYLOAD_BYTES):
        raise ValueError("invalid bounded Cell/payload matrix")
    payload = "x" * payload_bytes
    digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
    intents = []
    for i in range(active_cells):
        intents.append(canonical_json({
            "version": SCHEMA_VERSION,
            "operation_id": f"cell-{i:05d}",
            "scope": "research-only", "generation": 1, "fence": 1,
            "payload": payload, "payload_sha256": digest,
        }))
    if any(len(raw) > MAX_FRAME_BYTES for raw in intents):
        raise ValueError("frame limit exceeded")
    return intents


def recv_exact(sock: socket.socket, count: int, *, allow_clean_eof: bool = False) -> bytes | None:
    out = bytearray()
    while len(out) < count:
        try:
            part = sock.recv(count - len(out))
        except (TimeoutError, OSError) as exc:
            raise TransportIndeterminate("receiver lost") from exc
        if not part:
            if allow_clean_eof and not out:
                return None
            raise TransportIndeterminate("truncated frame")
        out.extend(part)
    return bytes(out)


def recv_frame(sock: socket.socket) -> bytes | None:
    header = recv_exact(sock, 4, allow_clean_eof=True)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    if not 0 < length <= MAX_FRAME_BYTES:
        raise ProtocolRejected("frame length out of bounds")
    return recv_exact(sock, length)


def send_frame(sock: socket.socket, raw: bytes) -> None:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise ProtocolRejected("invalid outgoing frame")
    try:
        sock.sendall(struct.pack(">I", len(raw)) + raw)
    except (TimeoutError, OSError) as exc:
        raise TransportIndeterminate("send outcome unknown") from exc


def serve_socket(fd: int) -> int:
    """Synthetic worker; no authority, no external effects and no retries."""
    with socket.socket(fileno=fd) as sock:
        sock.settimeout(5)
        while True:
            try:
                raw = recv_frame(sock)
                if raw is None:
                    return 0
                try:
                    result = evaluate(raw)
                except ProtocolRejected:
                    # Invalid input cannot be reclassified as successful work.
                    result = canonical_json({"rejected": "INVALID_RESEARCH_INTENT", "authority": "DENY_ALL"})
                send_frame(sock, result)
            except (ProtocolRejected, TransportIndeterminate):
                return 2


class DirectClient:
    startup_ms = 0.0
    processes_spawned = 0

    def __enter__(self) -> DirectClient:
        return self

    def request(self, raw: bytes) -> bytes:
        return evaluate(raw)

    def __exit__(self, *_: object) -> None:
        pass


class QueueClient:
    """A bounded typed in-process queue, one logical owner, one worker thread."""
    processes_spawned = 0

    def __init__(self) -> None:
        self.inputs: queue.Queue[Any] = queue.Queue(maxsize=1)
        self.closed = False
        self.thread = threading.Thread(target=self._worker, daemon=True)
        start = time.perf_counter_ns()
        self.thread.start()
        self.startup_ms = (time.perf_counter_ns() - start) / 1e6

    def _worker(self) -> None:
        while True:
            item = self.inputs.get()
            if item is None:
                return
            raw, reply, reply_queue = item
            try:
                reply_queue.put((evaluate(raw), None))
            except Exception as exc:
                reply_queue.put((None, exc))
            finally:
                reply.set()

    def __enter__(self) -> QueueClient:
        return self

    def request(self, raw: bytes) -> bytes:
        if self.closed or not self.thread.is_alive():
            raise TransportIndeterminate("queue owner unavailable")
        ready = threading.Event()
        output: queue.Queue[Any] = queue.Queue(maxsize=1)
        try:
            self.inputs.put((raw, ready, output), timeout=5)
        except queue.Full as exc:
            raise TransportIndeterminate("queue admission failed") from exc
        if not ready.wait(timeout=5):
            raise TransportIndeterminate("queue response unknown")
        result, error = output.get_nowait()
        if error:
            raise error
        return result

    def __exit__(self, *_: object) -> None:
        self.closed = True
        try:
            self.inputs.put(None, timeout=5)
        except queue.Full:
            pass
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise TransportIndeterminate("queue shutdown incomplete")


class ProcessClient:
    """One persistent child per client, not one child per logical Cell."""
    processes_spawned = 1

    def __init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("POSIX socketpair/pass_fds required for this profile")
        start = time.perf_counter_ns()
        parent, child = socket.socketpair()
        try:
            child_fd = child.fileno()
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-S", str(Path(__file__).resolve()),
                 "--worker-fd", str(child_fd)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, pass_fds=(child_fd,), close_fds=True,
                # Never forward model/API credentials to a research child.
                env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
            )
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self.sock = parent
        self.sock.settimeout(5)
        self.startup_ms = (time.perf_counter_ns() - start) / 1e6

    def __enter__(self) -> ProcessClient:
        return self

    def request(self, raw: bytes) -> bytes:
        if self.process.poll() is not None:
            raise TransportIndeterminate("worker no longer running")
        send_frame(self.sock, raw)
        response = recv_frame(self.sock)
        if response is None:
            raise TransportIndeterminate("worker closed before response")
        return response

    def __exit__(self, *_: object) -> None:
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.sock.close()
        try:
            code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            self.process.kill()
            self.process.wait()
            raise TransportIndeterminate("worker shutdown timed out") from exc
        if code:
            raise TransportIndeterminate(f"worker abnormal exit: {code}")


def nearest_rank(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[max(0, math.ceil(len(sorted_values) * fraction) - 1)]


def summarize_ms(timings: list[float]) -> dict[str, float | None]:
    if not timings:
        raise ValueError("no actual observations")
    ordered = sorted(timings)
    n = len(ordered)
    return {
        "samples": n,
        "p50_ms": nearest_rank(ordered, 0.50),
        "p95_ms": nearest_rank(ordered, 0.95) if n >= 20 else None,
        "p99_ms": nearest_rank(ordered, 0.99) if n >= 100 else None,
        "max_ms": ordered[-1],
    }


def run_mode(mode: str, intents: list[bytes], rounds: int) -> dict[str, Any]:
    if not (1 <= rounds <= 32) or len(intents) * rounds > MAX_OPERATIONS:
        raise ValueError("mode work budget exceeded")
    if mode not in {"direct", "queue", "persistent", "cold"}:
        raise ValueError("unknown mode")
    count = len(intents) * rounds
    if mode == "cold" and count > MAX_COLD_OPERATIONS:
        raise ValueError("cold-start budget exceeded; never silently sample less work")
    cls = {"direct": DirectClient, "queue": QueueClient, "persistent": ProcessClient}
    latencies_ms = []
    receipts = hashlib.sha256()
    startup_ms = 0.0
    started = time.perf_counter_ns()
    if mode == "cold":
        for _ in range(rounds):
            for intent in intents:
                begin = time.perf_counter_ns()
                with ProcessClient() as client:
                    output = client.request(intent)
                    startup_ms += client.startup_ms
                latencies_ms.append((time.perf_counter_ns() - begin) / 1e6)
                validate_receipt(output, intent)
                receipts.update(output)
        spawned = count
    else:
        with cls[mode]() as client:
            startup_ms = client.startup_ms
            for _ in range(rounds):
                for intent in intents:
                    begin = time.perf_counter_ns()
                    output = client.request(intent)
                    latencies_ms.append((time.perf_counter_ns() - begin) / 1e6)
                    validate_receipt(output, intent)
                    receipts.update(output)
            spawned = client.processes_spawned
    total_ms = (time.perf_counter_ns() - started) / 1e6
    return {
        "mode": mode, "operations": count,
        "logical_execution_workers": 1 if mode != "cold" else count,
        "processes_spawned": spawned,
        "worker_startup_ms_total": startup_ms,
        "total_wall_ms": total_ms,
        "throughput_ops_per_second": count / (total_ms / 1000),
        "dispatch_latency": summarize_ms(latencies_ms),
        "observed_receipts_sha256": receipts.hexdigest(),
        "effects": "NONE_SYNTHETIC", "authority": "DENY_ALL",
    }


def benchmark(logical_cells: int, active_cells: int, payload_bytes: int,
              rounds: int, modes: list[str]) -> dict[str, Any]:
    if not 1 <= rounds <= 32 or active_cells * rounds > MAX_OPERATIONS:
        raise ValueError("work budget exceeded")
    if not modes or len(set(modes)) != len(modes):
        raise ValueError("modes must be a unique nonempty list")
    intents = make_intents(logical_cells, active_cells, payload_bytes)
    expected = hashlib.sha256()
    for _ in range(rounds):
        for raw in intents:
            expected.update(evaluate(raw))
    reference = expected.hexdigest()
    runs = [run_mode(mode, intents, rounds) for mode in modes]
    if any(run["observed_receipts_sha256"] != reference for run in runs):
        raise ProtocolRejected("cross-mode result parity failure")
    return {
        "status": "RESEARCH_DENY_ALL", "real_codex_exec_server": False,
        "real_hepta_runtime": False, "real_model_or_tool_effects": False,
        "independent_evaluation": False, "production_qualification": False,
        "comparability": "same_encoded_intents_and_pure_work; Python_only_not_Rust_Codex",
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "pid": os.getpid()},
        "workload": {"logical_cells": logical_cells, "active_calls_per_round": active_cells,
                     "payload_bytes": payload_bytes, "rounds": rounds,
                     "identical_intent_bytes_across_modes": True},
        "expected_receipts_sha256": reference, "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-fd", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--logical-cells", type=int, default=64)
    parser.add_argument("--active-cells", type=int, default=8)
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--modes", default="direct,queue,persistent,cold")
    args = parser.parse_args(argv)
    if args.worker_fd is not None:
        if not 0 <= args.worker_fd < 1_000_000:
            return 2
        return serve_socket(args.worker_fd)
    result = benchmark(args.logical_cells, args.active_cells, args.payload_bytes,
                       args.rounds, args.modes.split(","))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, ProtocolRejected, TransportIndeterminate) as exc:
        print(f"research probe rejected: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
