"""Rebuild native timing summaries from recorded randomized measurement blocks."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def statistics(values):
    array = np.asarray(values, dtype=float)
    return {"count": len(array), "mean": float(array.mean()), "median": float(np.median(array)),
            "p05": float(np.quantile(array, .05)), "p95": float(np.quantile(array, .95)),
            "minimum": float(array.min()), "maximum": float(array.max())}


def verify(path):
    data = json.loads(path.read_text())
    methods = ("legacy_full_record", "ffi_full_record", "legacy_no_record", "ffi_compact", "history")
    rows = data["block_records"]
    expected = {(repeat, method) for repeat in range(24) for method in methods}
    actual = {(row["repeat"], row["method"]) for row in rows}
    if len(rows) != 120 or actual != expected:
        raise ValueError("Randomized measurement grid is incomplete or duplicated")
    for repeat in range(24):
        block = [row for row in rows if row["repeat"] == repeat]
        if {row["position"] for row in block} != set(range(5)):
            raise ValueError("Block order is not a complete permutation")
        native = [row for row in block if row["method"] != "history"]
        if len({row["feature_sha256"] for row in native}) != 1:
            raise ValueError("Native features differ across transport paths")
        if len({row["action_sha256"] for row in native}) != 1:
            raise ValueError("Native actions differ across transport paths")
    for row in rows:
        if (row["rows"] != 64 or row["total_ns"] <= 0
                or row["feature_ns"] + row["readout_ns"] != row["total_ns"]
                or row["total_ns"] / 64 != row["per_case_total_ns"]):
            raise ValueError("Timing boundary or amortization mismatch")
        if row["method"] != "history":
            comp = row["components"]
            if (comp["original_sparse_tick_calls"] != 128
                    or comp["authority"] != "DENY_ALL" or comp["native_owner_integration"]
                    or comp["target_accesses"] != 0):
                raise ValueError("Recorded native workload or authority mismatch")
    recomputed = {method: statistics([row["per_case_total_ns"] for row in rows if row["method"] == method])
                  for method in methods}
    paired = {}
    for left, right in (("legacy_full_record", "ffi_full_record"), ("legacy_no_record", "ffi_compact"),
                        ("ffi_compact", "history"), ("ffi_full_record", "history")):
        values = []
        for repeat in range(24):
            block = {row["method"]: row for row in rows if row["repeat"] == repeat}
            values.append(block[left]["total_ns"] / block[right]["total_ns"])
        paired[left + "_over_" + right] = statistics(values)
    error = max(abs(float(value) - float(data["per_case_wall_ns"][method][key]))
                for method, stats in recomputed.items() for key, value in stats.items())
    ratio_error = max(abs(float(value) - float(data["paired_runtime_ratios"][method][key]))
                      for method, stats in paired.items() for key, value in stats.items())
    if error > 1e-9 or ratio_error > 1e-12:
        raise ValueError("Reported timing summaries differ from raw blocks")
    cold = data["fresh_process_records"]
    if len(cold) != 16 or {(r["repeat"], r["method"]) for r in cold} != {
            (repeat, method) for repeat in range(8) for method in ("legacy", "ffi")}:
        raise ValueError("Fresh-process record grid mismatch")
    for row in cold:
        if row["load_ns"] + row["first_pair_ns"] != row["total_ns"]:
            raise ValueError("Fresh-process timing mismatch")
    fresh = {method: {key: statistics([row[key] for row in cold if row["method"] == method])
                      for key in ("load_ns", "first_pair_ns", "total_ns")}
             for method in ("legacy", "ffi")}
    cold_error = max(abs(float(value) - float(data["fresh_process"][method][key][name]))
                     for method, metrics in fresh.items() for key, stats in metrics.items()
                     for name, value in stats.items())
    if cold_error > 1e-9:
        raise ValueError("Fresh-process summary differs from records")
    return {"schema": "hepta.field-bridge.v2.native-independent-arithmetic.v1",
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "complete_blocks": 120, "paired_repeat_units": 24,
            "all_native_feature_and_action_hashes_match": True,
            "main_block_original_tick_calls": 12288,
            "max_summary_error": error, "max_ratio_error": ratio_error,
            "max_fresh_process_error": cold_error,
            "per_case_wall_ns": recomputed, "paired_runtime_ratios": paired,
            "fresh_process": fresh,
            "engineering_overhead_improvement_supported": (
                paired["legacy_full_record_over_ffi_full_record"]["p05"] > 1),
            "scientific_benefit_inferred": False,
            "scope": "Read-only arithmetic and recorded identity checks, not independent rerunning of the native benchmark. Shared-host timing and absence of model generation remain limitations."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.benchmark)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as file:
        json.dump(result, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    print(json.dumps({key: result[key] for key in ("complete_blocks", "max_summary_error",
          "max_ratio_error", "engineering_overhead_improvement_supported")}))


if __name__ == "__main__":
    main()
