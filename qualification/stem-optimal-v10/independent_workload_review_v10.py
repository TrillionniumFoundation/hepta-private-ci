"""Model-free audit of same-process paired V10 timing/census and old owner.

Checks real original archive identity, report arithmetic, denial fields. Does NOT
claim independent hardware telemetry or source/time-disjoint usefulness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

SCHEMA = "hepta.stem.original-physical-paired.v10"
ORDER = (("selected", "full"), ("full", "selected"),
         ("selected", "full"), ("full", "selected"))
MODELS = ("granite47", "granite97", "mmbert140")


def check(ok, why):
    if not ok:
        raise ValueError(why)


def inspect(result, old):
    check(type(result) is dict and result.get("schema") == SCHEMA,
          "not original paired receipt")
    name = result.get("candidate")
    check(name in MODELS and name == old.get("candidate") and
          result.get("source_plan_sha256") == old.get("source_plan_sha256") and
          result.get("actual_weight_sha256") == old.get("actual_weight_sha256") and
          result.get("original_v3_model_revision") == old.get("model_revision") and
          result.get("original_trained_head_sha256") == old.get("trained_head_sha256"),
          "paired model checkpoint/source substituted")
    check(result.get("authority") == "DENY_ALL" and result.get("disposition") == "HOLD_NO_GO"
          and result.get("production_authorized") is False
          and result.get("stem_winner_verified") is False
          and result.get("cell_split_authorized") is False
          and result.get("amortized_full_lifecycle_savings_verified") is False
          and result.get("production_p99_gpu_energy_wal_attested") is False
          and result.get("negative_transfer_verified") is False
          and result.get("ndu_net_gain_verified") is False
          and result.get("source_independent_families") == 1
          and result.get("future_windows") == 0,
          "improper production or future-world claim")
    check(result.get("fit_training_actual_updates") == 100
          and result.get("fit_physical_encoder_sequences") == 64
          and result.get("fit_physical_encoder_batches") == 4
          and result.get("measured_full_and_selected_both_executed") is True
          and result.get("counterbalanced_order") == [list(x) for x in ORDER],
          "full physical work/counterbalancing not observed")
    counts = result.get("measured_arm_sequence_counts")
    batches = result.get("measured_arm_batch_counts")
    check(counts == {"selected": 32, "full": 128} and
          batches == {"selected": 4, "full": 8}
          and result.get("actual_total_workload_encoder_sequences") == 224
          and result.get("actual_total_workload_encoder_batches") == 16,
          "missing paid full+selected measurement arm")
    times = result.get("measured_arm_timings")
    check(type(times) is dict and set(times) == {"selected", "full"}, "missing timing arm")
    sums = {}
    for arm, width, batch_count in (("selected", 8, 1), ("full", 32, 2)):
        seq = times[arm]
        check(type(seq) is list and len(seq) == 4, "missing paired original repeats")
        for trial in seq:
            check(type(trial) is dict and set(trial) == {
                "wall_seconds", "cpu_seconds", "actual_sequences", "batches"
            } and trial["actual_sequences"] == width and trial["batches"] == batch_count
                  and all(type(trial[k]) in (int, float) and math.isfinite(trial[k])
                          and trial[k] > 0 for k in ("wall_seconds", "cpu_seconds")),
                  "forged physical wall/CPU/forward counts")
        for metric, summary in (("wall_seconds", "per_arm_median_query_wall_seconds"),
                                ("cpu_seconds", "per_arm_median_query_cpu_seconds")):
            m = statistics.median(row[metric] for row in seq)
            check(type(result[summary][arm]) in (int, float) and
                  math.isclose(m, result[summary][arm], rel_tol=1e-10, abs_tol=1e-10),
                  "forged per-arm summary")
        sums[arm] = sum(x["wall_seconds"] for x in seq)
    for name in ("cheap_actual_wall_seconds", "cheap_actual_cpu_seconds",
                 "model_load_wall_seconds", "fit_encode_wall_seconds",
                 "fit_training_wall_seconds", "paid_workload_total_wall_seconds",
                 "paid_workload_total_cpu_seconds",
                 "self_reported_same_process_peak_rss_bytes"):
        value = result.get(name)
        check(type(value) in (int, float) and math.isfinite(value) and value > 0,
              "physically unmetered stage " + name)
    check(result["paid_workload_total_wall_seconds"] + 1e-6 >=
          sums["selected"] + sums["full"] + result["cheap_actual_wall_seconds"] +
          result["model_load_wall_seconds"] + result["fit_encode_wall_seconds"] +
          result["fit_training_wall_seconds"], "inconsistent complete stage costs")
    for key in ("max_original_v3_probability_abs_drift",
                "max_full_vs_selected_probability_abs_drift"):
        value = result.get(key)
        check(type(value) in (int, float) and math.isfinite(value) and
              0 <= value <= 5e-4, "original/full/selected score parity not proven")
    return {"schema": "hepta.stem.original-physical-paired.independent-read.v10",
            "candidate": name, "same_process_counterbalanced_meter_recounted": True,
            "fit_64_physically_reported": True,
            "both_arms_physically_reported": True,
            "selected_vs_full_measured_median_wall_ratio": (
                result["per_arm_median_query_wall_seconds"]["selected"] /
                result["per_arm_median_query_wall_seconds"]["full"]),
            "all_measured_encoder_sequences": 224,
            "encoder_forward_count_independently_attested": False,
            "paired_new_source_or_future_windows": 0,
            "full_lifecycle_savings_verified": False,
            "production_authorized": False, "disposition": "HOLD_NO_GO",
            "authority": "DENY_ALL"}


def main():
    p = argparse.ArgumentParser()
    for k in ("report", "manifest", "original-zip", "output"):
        p.add_argument("--"+k, required=True)
    args = p.parse_args()
    here=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(here/"stem-optimal-v5"))
    import paired_review_v5 as custody
    lock=json.loads(Path(args.manifest).read_text())
    candidate=json.loads(Path(args.report).read_text())["candidate"]
    original=custody.locked_json(args.original_zip,lock["artifacts"],candidate)
    result=inspect(json.loads(Path(args.report).read_text()),original)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as out:
        out.write(json.dumps(result,sort_keys=True,allow_nan=False,separators=(",", ":")).encode()+b"\n")
    print(json.dumps({"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                      "candidate":candidate,"authority":"DENY_ALL"},sort_keys=True))

if __name__=="__main__":
    main()
