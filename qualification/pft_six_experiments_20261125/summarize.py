#!/usr/bin/env python3
"""Derive compact reported aggregates from the frozen per-case receipts."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def grouped(rows, keys, value):
    result = []
    for group in sorted({tuple(r[k] for k in keys) for r in rows}):
        items = [r for r in rows if tuple(r[k] for k in keys) == group]
        result.append({**dict(zip(keys, group)), "cases": len(items),
                       "mean": float(np.mean([value(r) for r in items]))})
    return result


def summarize(root):
    names = ["pft1", "pft2", "pft2_transport", "pft3", "pft4", "pft34_verification",
             "pft5", "pft6", "receipt_audit"]
    data = {n: json.loads((root / (n + ".json")).read_text()) for n in names}
    p5 = []
    for condition in sorted({r["condition"] for r in data["pft5"]["results"]}):
        rows = [r for r in data["pft5"]["results"] if r["condition"] == condition]
        p5.append({"condition": condition, "cases": len(rows),
                   "numeric_passes": sum(r["numeric_gate"] == "PASS" for r in rows),
                   "median_B_relative_improvement": float(np.median([r["B"]["relative_improvement"] for r in rows])),
                   "median_keep_mse_increase": float(np.median([
                       r["keep"]["candidate_mse"] - r["keep"]["parent_mse"] for r in rows]))})
    rows6 = [r for r in data["pft6"]["results"] if r["mode"] == "time_to_quality"]
    lookup = {(r["width"], r["seed"], r["method"]): r for r in rows6}
    speed = []
    for method in ("ridge", "rls"):
        ratios = [lookup[(r["width"], r["seed"], "readout_bp")]["local_end_to_end_s"] /
                  r["local_end_to_end_s"] for r in rows6 if r["method"] == method]
        speed.append({"ratio": "readout_bp_time / " + method + "_time", "cases": len(ratios),
                      "median": float(np.median(ratios)), "minimum": min(ratios), "maximum": max(ratios),
                      "warning": "Single-host millisecond measurements; no statistical speed guarantee."})
    return {"schema": "pft_six.summary.v1", "scope": "Exploratory controlled mechanisms, not global HCSN or LLM qualification",
            "pft1": data["pft1"]["summary"], "pft2": data["pft2"]["summary"],
            "pft2_loopback": data["pft2_transport"]["summary"],
            "pft3": grouped(data["pft3"]["rows"], ("mode", "boundary", "features"), lambda r: r["test"]["accuracy"]),
            "pft3_pre_reveal_accuracy_mean": float(np.mean([r["test"]["pre_reveal_accuracy"] for r in data["pft3"]["rows"]])),
            "pft4": grouped(data["pft4"]["rows"], ("width", "graph"), lambda r: r["test"]["accuracy"]),
            "pft4_sender_permutation": {key: float(np.mean([r[key] for r in data["pft34_verification"]["rows"]]))
                                        for key in ("intact_accuracy", "sender_permuted_accuracy", "accuracy_drop")},
            "pft4_lq_costs": grouped(data["pft4"]["pft_horizon_probe"]["rows"], ("policy",), lambda r: r["mean_cost"]),
            "pft5": p5, "pft5_real_gate": data["pft5"]["real_cross_user_gate"],
            "pft6": data["pft6"]["summary"], "pft6_paired_time_ratios": speed,
            "pft6_runtime_gate": data["pft6"]["real_distributed_cost_gate"],
            "receipt_audit": data["receipt_audit"]["status"],
            "input_sha256": {n + ".json": hashlib.sha256((root / (n + ".json")).read_bytes()).hexdigest() for n in names},
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        json.dump(summarize(args.results), stream, indent=2, allow_nan=False)
        stream.write("\n")
