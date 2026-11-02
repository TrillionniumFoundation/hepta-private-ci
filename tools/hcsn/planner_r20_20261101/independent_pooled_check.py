"""Post hoc arithmetic disaggregation; failed per-group gates remain failed."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import time

os.sched_setaffinity(0, {1})
started = time.process_time()
here = Path(__file__).resolve().parent
folder = here / "confirmation_01"
summary = json.loads((folder / "SUMMARY.json").read_text())
review = json.loads((here / "INDEPENDENT_RESOURCES_REVIEW.json").read_text())
groups = [json.loads(gzip.decompress(p.read_bytes()))["group"] for p in sorted(folder.glob("*.json.gz"))]
pooled, by_fit = {}, {}
for key, record in summary["pooled"].items():
    model, representation = key.split("|")
    selected = [g for g in groups if g["model"] == model and g["representation"] == representation]
    assert len(selected) == 8
    costs = {mode: sum(g["cpu_with_preparation"][mode] for g in selected) for mode in ("baseline", "r18", "r19", "r20")}
    for mode, value in costs.items():
        assert abs(value - record["cpu_with_preparation"][mode]) < 1e-10
    for denominator in ("baseline", "r18"):
        assert abs(costs["r20"] / costs[denominator] - record["r20_" + denominator + "_cpu_ratio"]) < 1e-12
    pooled[key] = dict(cpu_with_preparation=costs, original_failures=sum(g["r20_baseline_cpu_ratio"] > .90 for g in selected),
                       joint_failures=sum(g["r20_r18_cpu_ratio"] > 1. or g["r20_r18_peak_ratio"] > .90 for g in selected))
for fit in sorted({g["fit"] for g in groups}):
    selected = [g for g in groups if g["fit"] == fit]
    assert len(selected) == 6
    by_fit[fit] = dict(cpu_ratios_baseline=[g["r20_baseline_cpu_ratio"] for g in selected],
                      cpu_ratios_r18=[g["r20_r18_cpu_ratio"] for g in selected],
                      peak_ratios_r18=[g["r20_r18_peak_ratio"] for g in selected],
                      original_failures=sum(g["r20_baseline_cpu_ratio"] > .90 for g in selected),
                      joint_failures=sum(g["r20_r18_cpu_ratio"] > 1. or g["r20_r18_peak_ratio"] > .90 for g in selected))
assert sum(g["original_failures"] for g in pooled.values()) == len(review["original_cpu_failures"])
assert sum(g["joint_failures"] for g in pooled.values()) == len(review["joint_failures"])
result = dict(passed=True, pooled=pooled, per_fit=by_fit,
              ratio_ranges={name: [min(g[name] for g in groups), max(g[name] for g in groups)] for name in
                            ("r20_baseline_cpu_ratio", "r20_r18_cpu_ratio", "r20_r19_cpu_ratio", "r20_r18_peak_ratio")},
              measured_body_cpu_seconds=time.process_time() - started,
              reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              input_summary_sha256=hashlib.sha256((folder / "SUMMARY.json").read_bytes()).hexdigest(),
              input_independent_review_sha256=hashlib.sha256((here / "INDEPENDENT_RESOURCES_REVIEW.json").read_bytes()).hexdigest(),
              scope="Independent arithmetic verification of all published pooled totals and post hoc per-fit disaggregation. No new statistical threshold, confidence interval, efficacy sample or pooled override of any failed registered group.")
with (here / "INDEPENDENT_PER_FIT_STATISTICS.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
