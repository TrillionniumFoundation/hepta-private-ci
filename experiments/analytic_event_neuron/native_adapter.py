"""Persistent JSON-lines adapter with an exact fresh-build receipt binding."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time


class Native:
    def __init__(self, binary, receipt):
        self.binary = Path(binary)
        self.receipt = json.loads(Path(receipt).read_text()) if not isinstance(receipt, dict) else dict(receipt)
        actual = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        if (actual != self.receipt.get("binary_sha256") or not self.receipt.get("fresh_build")
                or not self.receipt.get("original_source_git_blob_verified")
                or not self.receipt.get("dependency_lock_subset_verified")):
            raise ValueError("Unverified or changed native executable")
        self._lock = threading.Lock()
        self._process = subprocess.Popen([str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1)
        self.calls = 0
        self.original_sparse_ticks = 0
        self.wall_ns = 0

    def _request(self, request):
        started = time.perf_counter_ns()
        with self._lock:
            if self._process.poll() is not None:
                raise RuntimeError("Native process terminated")
            self._process.stdin.write(json.dumps(request, allow_nan=False, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError("Native process closed output")
            result = json.loads(line)
        if "error" in result:
            raise ValueError("Native rejection: " + result["error"])
        self.calls += 1
        self.original_sparse_ticks += result.get("original_sparse_tick_calls", int(result.get("original_neuron_runtime", False)))
        elapsed = time.perf_counter_ns() - started
        self.wall_ns += elapsed
        result["subprocess_roundtrip_ns"] = elapsed
        result["native_binary_sha256"] = self.receipt["binary_sha256"]
        return result

    def sparse_features(self, observations, times, mask, case="history", *, obs_var=None):
        return self._request({"op": "sparse_features", "case": str(case),
            "observations": [float(x) for x in observations], "times": [float(x) for x in times],
            "mask": [bool(x) for x in mask],
            "obs_var": None if obs_var is None else [float(x) for x in obs_var]})

    def tick_pair(self, case, readback_digest, feedback_q24, reset_before_readout=False):
        return self._request({"op": "pair", "case": str(case), "readback_digest": str(readback_digest),
            "feedback_q24": int(feedback_q24), "reset_before_readout": bool(reset_before_readout)})

    def typed(self, case, directory, mean, variance, lower, upper, *, expected_checkpoint=None):
        return self._request({"op": "typed", "case": str(case), "directory": str(directory),
            "mean": float(mean), "variance": float(variance), "lower": float(lower), "upper": float(upper),
            "expected_checkpoint": expected_checkpoint})

    def close(self):
        if self._process.poll() is None:
            self._process.stdin.close()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)
        self._process.stdout.close()
        self._process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
