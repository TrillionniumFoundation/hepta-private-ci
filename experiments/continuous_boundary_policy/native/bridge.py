"""POSIX research transport with exact wait4 child CPU and measured wire bytes.

The original NDU executes supplied scores. Neural inference remains in the caller
and must be independently replay-audited; receipt hashes bind that claimed input.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

Q = 1 << 24
MAX_BYTES = 16 * 1024 * 1024


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class ScoreBridge:
    def __init__(self, binary, root, *, expected_binary_sha256=None):
        if not hasattr(os, "wait4"):
            raise RuntimeError(
                "Exact research child CPU accounting requires POSIX wait4"
            )
        self.binary = Path(binary).resolve()
        self.root = Path(root).resolve()
        self.binary_sha256 = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        if (
            expected_binary_sha256 is not None
            and expected_binary_sha256 != self.binary_sha256
        ):
            raise ValueError("NDU score binary identity changed")
        self.root.mkdir(parents=True, exist_ok=True)
        permit = {
            "schema": "hepta.boundary-policy.local-research-permit.v1",
            "allowed_root": str(self.root),
            "external_effects": False,
            "production_authority": False,
        }
        path = self.root / "RESEARCH_PERMIT.json"
        if path.exists() and json.loads(path.read_text()) != permit:
            raise ValueError("Conflicting research permit")
        path.write_bytes(canonical(permit) + b"\n")
        self.stderr = (self.root / "score-host.stderr.log").open("ab")
        self.started_ns = time.perf_counter_ns()
        self.process = subprocess.Popen(
            [str(self.binary), str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            bufsize=65536,
        )
        self.counters = {
            "rpc_calls": 0,
            "actual_ndu_calls": 0,
            "actual_kernel_calls": 0,
            "native_physical_rpc_micros": 0,
            "python_roundtrip_ns": 0,
            "request_bytes": 0,
            "response_bytes": 0,
            "native_errors": 0,
        }
        self.closed_receipt = None
        self.shutdown_requested = False
        try:
            self.identity = self.rpc({"command": "Identity"})
            if self.identity["binary_sha256"] != self.binary_sha256:
                raise ValueError("Running NDU score binary identity mismatch")
        except BaseException:
            self.close()
            raise

    def rpc(self, request, *, allow_error=False):
        if self.closed_receipt is not None or self.shutdown_requested:
            raise RuntimeError("NDU score host is closed")
        raw = canonical(request) + b"\n"
        if len(raw) > MAX_BYTES:
            raise ValueError("NDU score request byte limit")
        started = time.perf_counter_ns()
        remaining = memoryview(raw)
        while remaining:
            count = self.process.stdin.write(remaining)
            if not count:
                raise RuntimeError("Native request pipe closed during write")
            remaining = remaining[count:]
        self.process.stdin.flush()
        response = self.process.stdout.readline(MAX_BYTES + 1)
        self.counters["python_roundtrip_ns"] += time.perf_counter_ns() - started
        self.counters["request_bytes"] += len(raw)
        self.counters["response_bytes"] += len(response)
        self.counters["rpc_calls"] += 1
        if not response or len(response) > MAX_BYTES:
            raise RuntimeError("Missing or oversized native response")
        envelope = json.loads(response)
        self.counters["native_physical_rpc_micros"] += envelope["physical_rpc_micros"]
        if not envelope["ok"]:
            self.counters["native_errors"] += 1
            if allow_error:
                return envelope
            raise RuntimeError(envelope["error"])
        result = envelope["result"]
        if (
            result.get("owner_authority") != "DENY_ALL"
            or result.get("actual_kernel_calls", 0) != 0
        ):
            raise RuntimeError("Unexpected native execution contract")
        self.counters["actual_ndu_calls"] += result.get("actual_ndu_calls", 0)
        if request["command"] == "Shutdown":
            self.shutdown_requested = True
        return result

    def decide_batch(self, rows):
        rows = list(rows)
        result = self.rpc({"command": "DecideBatch", "rows": rows})
        if len(result["rows"]) != len(rows) or result["actual_ndu_calls"] != len(rows):
            raise RuntimeError("Native batch count mismatch")
        for source, receipt in zip(rows, result["rows"], strict=True):
            if any(receipt.get(key) != value for key, value in source.items()):
                raise RuntimeError("Native input binding mismatch")
            support = digest(
                {
                    "schema": "hepta.boundary-policy.score-support.v1",
                    "native_binary_sha256": self.binary_sha256,
                    "row": source,
                }
            )
            unsigned = {
                key: value for key, value in receipt.items() if key != "receipt_sha256"
            }
            if receipt["support_sha256"] != support or receipt[
                "receipt_sha256"
            ] != digest(unsigned):
                raise RuntimeError("Native receipt digest mismatch")
        return result

    def close(self):
        if self.closed_receipt is not None:
            return self.closed_receipt
        error = None
        try:
            if not self.shutdown_requested:
                self.rpc({"command": "Shutdown"})
        except (OSError, RuntimeError, ValueError) as exc:
            error = str(exc)
        finally:
            self.process.stdin.close()
            _, status, usage = os.wait4(self.process.pid, 0)
            self.process.returncode = os.waitstatus_to_exitcode(status)
            self.process.stdout.close()
            self.stderr.close()
        self.closed_receipt = dict(
            self.counters,
            binary_sha256=self.binary_sha256,
            child_user_cpu_seconds=usage.ru_utime,
            child_system_cpu_seconds=usage.ru_stime,
            completed_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
            child_cpu_scope="exact wait4 of this score host process",
            process_wall_seconds=(time.perf_counter_ns() - self.started_ns) / 1e9,
            exit_code=self.process.returncode,
            shutdown_error=error,
        )
        return self.closed_receipt
