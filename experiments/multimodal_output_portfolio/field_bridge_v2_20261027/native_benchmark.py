"""Repeated randomized transport benchmark; no learning efficacy is inferred.

Full-record comparisons have identical receipt fields, hashing, native integer
states, and frozen downstream linear head. Compact comparisons exclude JSON/file
recording on both transports. History is a cost reference with the same 40D/5
action readout workload, not an efficacy comparison to its native counterpart.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np

from ..field_bridge_20261027.controls import choose, history_features, native_features
from ..field_bridge_20261027.native_bridge import NativeBridge
from .native_fast import NativeFastBridge, native_features_fast, prepare_request
from .native_fast_tests import requests


def summary(values):
    values = np.asarray(values, dtype=float)
    return dict(count=len(values), mean=float(values.mean()), median=float(np.median(values)),
                p05=float(np.quantile(values, .05)), p95=float(np.quantile(values, .95)),
                minimum=float(values.min()), maximum=float(values.max()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cold-worker", choices=("legacy", "ffi"))
    args = parser.parse_args()
    request = requests(count=2)[1]
    if args.cold_worker:
        started = time.perf_counter_ns()
        bridge = NativeBridge(args.legacy) if args.cold_worker == "legacy" else NativeFastBridge(args.ffi)
        loaded = time.perf_counter_ns()
        bridge.tick_pair(**request)
        finished = time.perf_counter_ns()
        bridge.close()
        print(json.dumps(dict(load_ns=loaded-started, first_pair_ns=finished-loaded, total_ns=finished-started)))
        return
    if args.out is None or args.out.exists():
        raise ValueError("Provide a new --out file")
    repeats, rows, seed = 24, 64, 271029
    rng = np.random.default_rng(seed)
    x0, x1 = rng.uniform(0, 1, (2, rows, 8))
    model = dict(schema="hepta.field-bridge.ridge-readout.v1", coefficient=rng.normal(size=(41, 5)).tolist(),
                 normalizer=dict(mean=np.zeros(40).tolist(), scale=np.ones(40).tolist()))
    inputs_sha = hashlib.sha256(np.stack((x0, x1)).astype("<f8").tobytes()).hexdigest()
    head_sha = hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()
    methods = ("legacy_full_record", "ffi_full_record", "legacy_no_record", "ffi_compact", "history")
    records, raw_abi = [], []
    fast = NativeFastBridge(args.ffi)
    with NativeBridge(args.legacy) as old, tempfile.TemporaryDirectory(prefix="hepta-native-benchmark-") as directory:
        # Warm both transports on identical events before randomized paired blocks.
        for _ in range(20):
            old.tick_pair(**request)
            fast.tick_pair(**request)
        prepared = prepare_request(**request)
        for _ in range(200):
            output, elapsed = fast.execute(prepared)
            raw_abi.append(dict(total_ns=elapsed, ffi_run_ns=output.ffi_run_ns,
                                kernel_ns=sum(t.native_ns for t in output.ticks)))
        for repeat in range(repeats):
            order = rng.permutation(methods).tolist()
            native_action_hash = None
            for rank, method in enumerate(order):
                full = method.endswith("full_record")
                path = Path(directory) / f"{repeat}-{method}.jsonl" if full else None
                started = time.perf_counter_ns()
                if method == "history":
                    features = history_features(x0, x1)
                    components = {}
                elif method.startswith("legacy"):
                    features = native_features(old, x0, x1, f"benchmark-{repeat}", receipt_path=path)
                    components = dict(old.last_feature_batch)
                else:
                    features = native_features_fast(fast, x0, x1, f"benchmark-{repeat}", receipt_path=path)
                    components = dict(fast.last_feature_batch)
                feature_end = time.perf_counter_ns()
                actions = choose(model, features)
                end = time.perf_counter_ns()
                action_hash = hashlib.sha256(actions.astype("<i8").tobytes()).hexdigest()
                if method != "history":
                    if native_action_hash is None:
                        native_action_hash = action_hash
                    assert action_hash == native_action_hash
                row = dict(repeat=repeat, position=rank, method=method, rows=rows,
                           total_ns=end-started, feature_ns=feature_end-started, readout_ns=end-feature_end,
                           per_case_total_ns=(end-started)/rows, action_sha256=action_hash,
                           feature_sha256=hashlib.sha256(features.astype("<f8").tobytes()).hexdigest(),
                           components=components)
                if path is not None:
                    row["written_receipt_bytes"] = path.stat().st_size
                    row["written_receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    path.unlink()
                    path.with_name(path.name + ".summary.json").unlink()
                records.append(row)
    cold = []
    for repeat in range(8):
        for method in rng.permutation(("legacy", "ffi")):
            command = [sys.executable, "-m", __package__ + ".native_benchmark", "--ffi", str(args.ffi.resolve()),
                       "--legacy", str(args.legacy.resolve()), "--cold-worker", str(method)]
            measured = json.loads(subprocess.check_output(command, text=True))
            cold.append(dict(repeat=repeat, method=str(method), **measured))
    aggregation = {method: summary([r["per_case_total_ns"] for r in records if r["method"] == method])
                   for method in methods}
    paired = {}
    for left, right in (("legacy_full_record", "ffi_full_record"), ("legacy_no_record", "ffi_compact"),
                        ("ffi_compact", "history"), ("ffi_full_record", "history")):
        ratios = []
        for repeat in range(repeats):
            block = {r["method"]: r for r in records if r["repeat"] == repeat}
            ratios.append(block[left]["total_ns"] / block[right]["total_ns"])
        paired[f"{left}_over_{right}"] = summary(ratios)
    report = dict(schema="hepta.field-bridge-v2.native-transport-benchmark.v1", seed=seed,
                  repeats=repeats, rows_per_repeat=rows, total_measured_native_ticks=4*repeats*rows*2,
                  randomized_order_per_block=True, matched_native_action_hashes=True,
                  public_inputs_sha256=inputs_sha, frozen_synthetic_readout_sha256=head_sha,
                  library_sha256=fast.binary_sha256, legacy_binary_sha256=old.binary_sha256,
                  per_case_wall_ns=aggregation, paired_runtime_ratios=paired,
                  raw_prepared_abi_ns={key: summary([r[key] for r in raw_abi]) for key in raw_abi[0]},
                  fresh_process={method: {key: summary([r[key] for r in cold if r["method"] == method])
                                         for key in ("load_ns", "first_pair_ns", "total_ns")}
                                 for method in ("legacy", "ffi")},
                  fresh_process_records=cold, block_records=records,
                  environment=dict(python=sys.version, numpy=np.__version__, platform=platform.platform(),
                                   cpu_count=os.cpu_count(), cpu_affinity=sorted(os.sched_getaffinity(0))),
                  limitations=["single shared host; no exclusive CPU reservation",
                               "fresh interpreter/process measurements retain operating-system caches",
                               "native full records include buffered JSON writes without fsync",
                               "compact paths omit full receipt serialization and file writes on both transports",
                               "history uses same readout workload; outputs and scientific benefit are not compared",
                               "no learned model generation, public preview extraction, or final delivery is timed",
                               "benchmark temporary receipt files removed after byte counts and hashes were recorded"],
                  scientific_effect_estimated=False, native_owner_integration=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"per_case_wall_ns": aggregation, "paired_runtime_ratios": paired,
                      "raw_prepared_abi_ns": report["raw_prepared_abi_ns"]}, sort_keys=True))


if __name__ == "__main__":
    main()
