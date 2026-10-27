"""Persistent JSON-lines client for the exact native Hepta sparse-kernel bridge.

Only bounded public numerical observations enter this interface. Training labels,
private scoring targets, and an outcome evaluator are intentionally absent.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import time

Q24 = 1 << 24
MAX_FEATURES = 8


class NativeBridge:
    def __init__(self, binary, expected_sha256=None):
        self.binary = Path(binary).resolve()
        with self.binary.open("rb") as binary_file:
            self.binary_sha256 = hashlib.file_digest(binary_file, "sha256").hexdigest()
        if expected_sha256 is not None and self.binary_sha256 != expected_sha256:
            raise ValueError("Native binary hash differs from its build receipt")
        self.process = subprocess.Popen(
            [str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )
        self.request_count = 0

    def tick_pair(self, *, case, readback_digest, features_q24,
                  next_features_q24=None, reset_before_readout=False):
        features = list(features_q24)
        if not isinstance(case, str) or not 1 <= len(case.encode()) <= 256:
            raise ValueError("Case must contain 1..256 UTF-8 bytes")
        if not 1 <= len(features) <= MAX_FEATURES:
            raise ValueError("Native bridge accepts 1..8 public features")
        if any(type(value) is not int or not -Q24 <= value <= Q24 for value in features):
            raise ValueError("Features must be integer Q24 values in [-1,1]")
        if not isinstance(readback_digest, str) or len(readback_digest) != 64:
            raise ValueError("Public input digest must be a SHA-256 hexadecimal value")
        bytes.fromhex(readback_digest)
        if type(reset_before_readout) is not bool:
            raise ValueError("Reset must be explicitly boolean")
        request = dict(case=case, readback_digest=readback_digest,
                       features_q24=features, reset_before_readout=reset_before_readout)
        if next_features_q24 is not None:
            next_features = list(next_features_q24)
            if len(next_features) != len(features) or any(
                type(value) is not int or not -Q24 <= value <= Q24 for value in next_features
            ):
                raise ValueError("Next public observation must match the first feature shape")
            request["next_features_q24"] = next_features
        started = time.perf_counter_ns()
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        elapsed = time.perf_counter_ns() - started
        if not line:
            error = self.process.stderr.read()
            raise RuntimeError(f"Native bridge terminated: {error}")
        receipt = json.loads(line)
        if receipt["original_sparse_tick_calls"] != 2 or receipt["native_owner_integration"]:
            raise RuntimeError("Native receipt has an incompatible execution boundary")
        if any(tick["authority"] != "DENY_ALL" or not tick["requires_calibration"]
               for tick in receipt["ticks"]):
            raise RuntimeError("Native receipt changed the original authority posture")
        receipt["bridge_roundtrip_ns"] = elapsed
        receipt["binary_sha256"] = self.binary_sha256
        self.request_count += 1
        return receipt

    def tick_pairs(self, requests):
        """Execute independent two-event cases through one persistent native process."""
        return [self.tick_pair(**request) for request in requests]

    def close(self):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        code = self.process.wait(timeout=10)
        error = self.process.stderr.read() if code else ""
        self.process.stdout.close()
        self.process.stderr.close()
        if code:
            raise RuntimeError(f"Native bridge exited {code}: {error}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def q24_features(values):
    """Encode caller-normalized finite public values without fitting a normalizer."""
    result = []
    for value in values:
        value = float(value)
        if not -1.0 <= value <= 1.0:
            raise ValueError("Normalize public features to [-1,1] before conversion")
        result.append(round(value * Q24))
    return result
