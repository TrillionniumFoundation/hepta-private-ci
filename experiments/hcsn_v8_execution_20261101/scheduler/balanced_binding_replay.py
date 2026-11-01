"""Supplementary full historical binding replay, preserving the subset record.

The earlier first-object-per-actor/label subset did not preserve video
marginals. This additive development run uses all 24 original historical pairs
and the exact already-fitted calibration/value tables. No model is retrained.
"""

import argparse
from collections import Counter
from dataclasses import fields
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import CacheBudget
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import BinnedCorrectness, LegacyV3Head
from experiments.hcsn_v8_execution_20261101.frontend.replay import episode_arrays, legacy_data, populated_cache
from experiments.hcsn_causal_execution_v3.av_probe import labels_of
from .execution import LogicalClock, run_episode
from .historical_probe import EmpiricalForecast, FixedServiceModel, METHODS, fixed_plans, source_hashes, write_json
from .historical_service import PreparedPrefixService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    adapter_path = args.prior / "av_binding_ADAPTERS.json"
    adapter_bytes = adapter_path.read_bytes()
    fitted = json.loads(adapter_bytes)
    head = LegacyV3Head("av_binding")
    head.calibrator = BinnedCorrectness(**{f.name: fitted["calibrator"][f.name]
                                         for f in fields(BinnedCorrectness)})
    if fitted["head_id"] != head.head_id:
        raise ValueError("Prior adapters do not identify this restored head")
    forecast = EmpiricalForecast(head, fitted["table"], fitted["fallback"])
    data = legacy_data("av_binding", "test")
    labels = labels_of(data)
    marginal_counts = {str(label): {name: dict(Counter(str(data[name][i])
                         for i in range(len(labels)) if labels[i] == label))
                         for name in ("audio_source_ids", "video_source_ids")}
                       for label in (0, 1)}
    same_marginals = marginal_counts["0"] == marginal_counts["1"]
    if not same_marginals:
        raise ValueError("Full historical source marginals unexpectedly differ")
    before = source_hashes()
    protocol = {"schema": "hcsn-v8-balanced-historical-binding.v1", "sources": before,
                "scope": "Additive historical development replay; no new confirmation",
                "reason": "Earlier actor/label subset did not retain balanced video marginals; preserve that result and use the complete historical set here",
                "selection": "All original historical binding test objects in original order",
                "objects": len(labels), "ids": data["ids"].astype(str).tolist(),
                "actors": sorted(set(data["group_ids"].astype(str))),
                "prior_adapter_sha256": hashlib.sha256(adapter_bytes).hexdigest(),
                "input_array_sha256": data["metadata"]["array_sha256"],
                "calibration_role": fitted["calibrator"]["data_role"],
                "models_retrained": False, "new_fit_count": 0,
                "methods": list(METHODS), "marginal_source_counts": marginal_counts,
                "same_source_marginals_across_labels": same_marginals,
                "logical_service_seconds": 0.001,
                "fresh_confirmation": False, "strong_audio_reference_available": False}
    write_json(args.out / "PROTOCOL.json", protocol)
    rows = []
    for index in range(len(labels)):
        arrays = episode_arrays(data, index)
        for method in METHODS:
            object_id = f"balanced-old-binding-{index}-{method}"
            captured = []
            result = run_episode(
                object_id, CacheBudget(65536), head, forecast, FixedServiceModel(),
                PreparedPrefixService(*arrays, object_id), captured.append, clock=LogicalClock(),
                horizon=6 if method != "cache_value" else 2,
                wait_seconds=() if method != "cache_value" else (0.05,), fixed_plans=fixed_plans(method))
            levels = {"audio": 0, "video": 0}
            for event in result["events"]:
                if event["kind"] == "read" and event["status"] == "accepted":
                    _, modality, prefix = event["action"].split(":")
                    levels[modality] = int(prefix)
            expected = head.classify(populated_cache(data, index, levels["audio"], levels["video"]))
            if not np.array_equal(expected, result["output"]["probabilities"]):
                raise AssertionError("Scheduler differs from the independently populated final prefix")
            correct = result["output"]["predicted_class"] == int(labels[index])
            row = {"index": index, "method": method, "actor": str(data["group_ids"][index]),
                   "label": int(labels[index]), "prediction": result["output"]["predicted_class"],
                   "correct": bool(correct), "requests": result["requested_observations"],
                   "utility": float(correct - result["observation_fee"] - result["latency_fee"] - result["deadline_penalty"]),
                   "terminal_prefix_levels": levels, "head_parity": True}
            rows.append(row)
            write_json(args.out / f"episode-{index}-{method}.json", result)
    groups = []
    for method in METHODS:
        chosen = [r for r in rows if r["method"] == method]
        groups.append({"method": method, "objects": len(chosen),
                       "correct": sum(r["correct"] for r in chosen),
                       "accuracy": float(np.mean([r["correct"] for r in chosen])),
                       "mean_requested_reads": float(np.mean([r["requests"] for r in chosen])),
                       "mean_logical_utility": float(np.mean([r["utility"] for r in chosen]))})
    recordings = {str(data[name][i]) for name in ("audio_source_ids", "video_source_ids")
                  for i in range(len(labels))}
    summary = {"schema": protocol["schema"], "groups": groups, "rows": rows,
               "same_source_marginals_across_labels": same_marginals,
               "unique_source_recordings": len(recordings), "actors": protocol["actors"],
               "source_unchanged": source_hashes() == before,
               "prior_adapter_unchanged": adapter_path.read_bytes() == adapter_bytes,
               "all_scheduler_head_parity": True, "models_retrained": False,
               "fresh_confirmation": False, "balanced_new_AV_gate_passed": False,
               "real_clock_episodes": 0,
               "quality_scope": "Complete already-exposed V3 historical binding set; exactly same fitted old-validation adapters; no semantic statement-binding or architecture claim"}
    write_json(args.out / "SUMMARY.json", summary)
    print(json.dumps({"groups": groups, "source_unchanged": summary["source_unchanged"],
                      "unique_source_recordings": len(recordings)}), flush=True)
    if not summary["source_unchanged"] or not summary["prior_adapter_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
