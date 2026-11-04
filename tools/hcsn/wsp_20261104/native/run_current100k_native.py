#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Run the native gate on an independently pinned PRIVATE historical fixture.

The fixture, generated weights, runtime state and full receipts stay in --work-dir.
Only aggregate numbers and content commitments are written to --output. This is
a replay of previously viewed historical rows, never a prospective efficacy test.
Requires NumPy; invokes the built Rust MCP executable, not a Python gate mock.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading
import time

import numpy as np

FIXTURE_SHA = "205bb2d9d1329c5a4ee134ce12146c29e842da80a8662a8e3533e0b85a4bd90a"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_fixture(path):
    raw = path.read_bytes()
    if sha(raw) != FIXTURE_SHA:
        raise ValueError("private fixture differs from the independently audited commitment")
    n = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8+n])
    result = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        lo, hi = meta["data_offsets"]
        dtype = {"F64": "<f8", "F32": "<f4"}[meta["dtype"]]
        result[name] = np.frombuffer(raw[8+n+lo:8+n+hi], dtype=dtype).reshape(meta["shape"])
    return result


def encode_weight(weight):
    data = np.asarray(weight, dtype="<f4").tobytes()
    header = json.dumps({"weight": {"dtype": "F32", "shape": list(weight.shape),
                                   "data_offsets": [0, len(data)]}}, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 8)
    return struct.pack("<Q", len(header)) + header + data


def pin_binary(binary, work):
    """Execute an isolated immutable-by-this-driver copy, not a changing build path."""
    pinned = work / "hepta-runtime-executed"
    with binary.open("rb") as src, pinned.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    os.chmod(pinned, 0o500)
    return pinned, sha(pinned.read_bytes()), pinned.stat()


def verify_binary(pinned, identity, before):
    after = pinned.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    assert tuple(getattr(before, f) for f in fields) == tuple(getattr(after, f) for f in fields)
    assert sha(pinned.read_bytes()) == identity, "executed binary changed during qualification"


class Mcp:
    def __init__(self, binary, config, log):
        self.log = log.open("w")
        try:
            self.p = subprocess.Popen([str(binary), "mcp", "--runtime-config", str(config)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.log, text=True, bufsize=1)
        except BaseException:
            self.log.close()
            raise
        self.sequence = 0
        self.lines = queue.Queue()

        def read():
            for line in self.p.stdout:
                self.lines.put(line)
            self.lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            self.request("initialize", {"protocolVersion": "2026-07-28", "capabilities": {},
                                        "clientInfo": {"name": "wsp-private-replay", "version": "1"}})
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def send(self, value):
        self.p.stdin.write(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")
        self.p.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        seq = self.sequence
        self.send({"jsonrpc": "2.0", "id": seq, "method": method, "params": params})
        deadline = time.monotonic() + 120
        for _ in range(64):
            line = self.lines.get(timeout=max(0.001, deadline-time.monotonic()))
            if line is None:
                raise RuntimeError("native MCP process ended before replying")
            reply = json.loads(line)
            if reply.get("id") == seq:
                if "error" in reply:
                    raise RuntimeError(str(reply["error"]))
                return reply["result"]
        raise RuntimeError("too many unrelated MCP notifications")

    def call(self, tool, arguments):
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(str(result))
        return json.loads(result["content"][0]["text"])

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait(timeout=10)
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    work = args.work_dir.resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    f = load_fixture(args.fixture)
    x64 = np.c_[f["inputs"], np.ones(len(f["inputs"]))]
    x32 = x64.astype(np.float32)
    targets = f["targets_usd"].reshape(-1, 1)
    parent64 = np.c_[f["parent.weight"], f["parent.bias"]]
    parent32 = parent64.astype(np.float32)
    source = work / "parent-f32-affine.safetensors"
    original = encode_weight(parent32)
    source.write_bytes(original)
    source_sha = sha(original)
    config = work / "runtime.json"
    config.write_text(json.dumps({"state_dir": str(work / "state"),
        "controller_workspace_roots": [str(work)], "weight_workers": {},
        "hosts": {"unused": {"ssh_target": "unused.invalid",
            "remote_state_dir": str(work / "unused"), "allow_execute": False}}}))
    results, private = [], []
    pinned, binary_sha, binary_stat = pin_binary(args.binary.resolve(), work)
    mcp = Mcp(pinned, config, work / "mcp.stderr.log")
    try:
        names = {t["name"] for t in mcp.request("tools/list", {})["tools"]}
        assert "weight_guarded_linear_patch" in names
        for fit, lo, hi in [(18, 18, 36), (36, 36, 54), (54, 0, 54)]:
            candidate64 = np.c_[f[f"exact{fit}.weight"], f[f"exact{fit}.bias"]]
            candidate32 = candidate64.astype(np.float32)
            # This study's norm premise is not a built-in native guard feature.
            # USD lowering multiplies the nominal 0.1/tolerance 0.100001 by 100.
            norm_cap = Fraction("10.0001")
            exact_norm_squared = sum(Fraction(float(v))**2 for v in candidate32.flat)
            assert exact_norm_squared <= norm_cap**2, "lowered candidate violates the study norm envelope"
            edits = []
            for index, (before, after) in enumerate(zip(parent32.flat, candidate32.flat)):
                a, b = struct.pack("<f", before), struct.pack("<f", after)
                if a != b:
                    edits.append({"index": index, "expected_hex": a.hex(), "replacement_hex": b.hex()})
            arguments = {"patch": {"path": str(source), "expected_sha256": source_sha,
                         "tensor_name": "weight", "edits": edits},
                "inputs": x32[lo:hi].tolist(), "bias": None,
                "objective": {"kind": "squared_error", "targets": targets[lo:hi].astype(np.float32).tolist()},
                "minimum_gain": 0.0, "constraints": []}
            receipt = mcp.call("weight_guarded_linear_patch", arguments)
            expected = "accepted_on_supplied_rows" if fit == 54 else "rejected_and_restored"
            assert receipt["outcome"] == expected, (fit, receipt)
            assert not receipt["production_eligible"] and not receipt["independent_holdout_verified"]
            assert source.read_bytes() == original
            if fit != 54:
                assert Path(receipt["restoration"]["artifact_path"]).read_bytes() == original
            y = targets[lo:hi]
            parent_pred = x64[lo:hi] @ parent64.T
            candidate_pred = x64[lo:hi] @ candidate64.T
            result = {"fit_rows": fit, "evaluation_row_range_zero_based": [lo, hi],
                "status": receipt["outcome"], "accepted": receipt["accepted"],
                "interpretation": "resubstitution probe only" if fit == 54 else "previously viewed chronological history, not a fresh holdout",
                "f64_parent_rmse_usd": float(np.sqrt(np.mean((parent_pred-y)**2))),
                "f64_candidate_rmse_usd": float(np.sqrt(np.mean((candidate_pred-y)**2))),
                "native_f32_parent_rmse_usd": math.sqrt(-receipt["primary_before"]),
                "native_f32_candidate_rmse_usd": math.sqrt(-receipt["primary_after"]),
                "primary_gain_negative_mse": receipt["gain"], "changed_elements": len(edits),
                "lowered_parent_sha256": source_sha, "lowered_candidate_sha256": receipt["candidate"]["sha256"],
                "evaluation_id": receipt["evaluation_id"],
                "source_bytes_unchanged": True, "restored_bytes_equal_parent": fit != 54,
                "native_operation_wall_seconds": receipt["native_operation_wall_seconds"],
                "f32_rounding_weight_max_absolute": float(np.max(np.abs(candidate32.astype(float)-candidate64))),
                "independent_holdout_verified": False, "production_eligible": False}
            result["exact_f32_parameter_norm_envelope_checked_by_driver"] = True
            result["norm_envelope_usd_head"] = str(norm_cap)
            results.append(result)
            private.append(receipt)
    finally:
        mcp.close()
    verify_binary(pinned, binary_sha, binary_stat)
    (work / "private-receipts.json").write_text(json.dumps(private, indent=2, allow_nan=False) + "\n")
    summary = {"schema": "hepta.current100k.native-gate-replay.v1", "fixture_sha256": FIXTURE_SHA,
        "binary_sha256": binary_sha, "executed_binary_unchanged": True,
        "driver_sha256": sha(Path(__file__).read_bytes()),
        "scope": "fixed historical 54 rows, audited F64 fixture explicitly lowered to F32 affine head with appended constant; no live checkpoint changes",
        "numeric_change": "F64 weights/inputs/targets are rounded to F32 for the bounded native operator; this is not bitwise parity with the F64 model",
        "results": results, "driver_wall_seconds": time.perf_counter()-started,
        "cost_excludes": ["feature extraction", "candidate solving", "original training", "LLM tokens", "Rust compilation", "data transfer", "energy"],
        "production_eligible": False, "prospective_efficacy": "unverified"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, allow_nan=False))


if __name__ == "__main__":
    main()
