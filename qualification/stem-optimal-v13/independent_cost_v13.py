"""Model-free, source-bound reviewer for V13 actual same-process costs.

Numerical parity within an existing resident model is not historical checkpoint
byte parity, future outcome utility or an externally attested cost receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

MODELS = ("granite47", "granite97")
SCHEMA = "hepta.stem.same-process-cost-only.v13"
SOURCE_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
SHA = "0123456789abcdef"
ORDER = [["selected", "full"], ["full", "selected"],
         ["selected", "full"], ["full", "selected"]]


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def is_sha(value, size):
    return type(value) is str and len(value) == size and all(c in SHA for c in value)


def original_selected(source, cheap):
    """Independent route reconstruction. Does not import the V8 producer."""
    require(source.get("source_plan_sha256") == SOURCE_SHA and
            cheap.get("source_plan_sha256") == SOURCE_SHA,
            "different frozen original input cohort")
    expected = {r["case_id"]: r["source_sha256"] for r in source["heldout"]}
    require(len(expected) == 32 and len(cheap["rows"]) == 32,
            "incomplete original historical 32-case source")
    ranking = []
    seen = set()
    for row in cheap["rows"]:
        cid = row["case_id"]
        require(cid not in seen and cid in expected and
                row["source_sha256"] == expected[cid], "cheap source substitution")
        seen.add(cid)
        p = row["scores"]["char_345_tfidf_centroid"]
        require(type(p) is list and len(p) == 4 and
                all(type(x) in (int,float) and math.isfinite(x) and 0 <= x <= 1 for x in p)
                and abs(sum(p)-1)<1e-5, "invalid original route confidence")
        largest = sorted(p, reverse=True)
        ranking.append((largest[0] - largest[1], cid))
    require(seen == set(expected), "incomplete independent route census")
    return [cid for _, cid in sorted(ranking)[:8]]


def inspect(report, original, source, cheap):
    require(type(report) is dict and report.get("schema") == SCHEMA,
            "not a physical cost-only V13 receipt")
    model = report.get("candidate")
    require(model in MODELS and model == original.get("candidate") and
            report.get("source_plan_sha256") == original.get("source_plan_sha256") == SOURCE_SHA and
            report.get("original_weight_sha256") == original.get("actual_weight_sha256") and
            report.get("original_model_revision") == original.get("model_revision") and
            report.get("original_head_initial_sha256") == original.get("initial_head_sha256") and
            report.get("original_head_trained_sha256") == original.get("trained_head_sha256"),
            "different original model or Head source")
    require(is_sha(report.get("observed_head_initial_sha256"), 64) and
            is_sha(report.get("observed_head_trained_sha256"), 64) and
            report["observed_head_initial_sha256"] == original["initial_head_sha256"] and
            report["observed_head_trained_sha256"] != report["observed_head_initial_sha256"] and
            report.get("historical_trained_head_byte_equal") is
              (report["observed_head_trained_sha256"] == original["trained_head_sha256"]),
            "false cross-host Head byte parity")
    require(report.get("historical_prediction_numerically_admitted") is False and
            type(report.get("max_historical_prediction_abs_drift_descriptive")) in (int,float) and
            math.isfinite(report["max_historical_prediction_abs_drift_descriptive"]) and
            report["max_historical_prediction_abs_drift_descriptive"] >= 0,
            "historic prediction cannot be re-promoted as a qualified Head")
    source_selected = original_selected(source, cheap)
    require(report.get("actual_selected_case_ids") == source_selected,
            "counterfactual route was altered after labels or before physical forward")
    loading = report.get("complete_loader_inventory")
    require(type(loading) is dict and
            set(loading) == {"missing_parameter_count", "unexpected_parameter_count",
                             "mismatched_parameter_count", "loader_error_count",
                             "complete_base_material_admitted", "loaded_parameter_scalars",
                             "model_weight_sha256"} and
            loading["complete_base_material_admitted"] is True and
            all(loading[x] == 0 for x in ("missing_parameter_count",
                                          "unexpected_parameter_count",
                                          "mismatched_parameter_count", "loader_error_count")) and
            type(loading["loaded_parameter_scalars"]) is int and
            40_000_000 <= loading["loaded_parameter_scalars"] <= 100_000_000 and
            loading["model_weight_sha256"] == original["actual_weight_sha256"],
            "checkpoint loader cannot attest complete original weights")
    require(report.get("fit_encoder_sequences") == 64 and
            report.get("fit_encoder_batches") == 4 and
            report.get("trained_head_optimizer_updates") == 100 and
            report.get("measured_order") == ORDER and
            report.get("measured_arm_sequence_counts") == {"selected": 32, "full": 128} and
            report.get("measured_arm_batch_counts") == {"selected": 4, "full": 8} and
            report.get("actual_total_encoder_sequences") == 224 and
            report.get("actual_total_encoder_batches") == 16 and
            report.get("physical_8_vs_32_matched_process_cost_observed") is True,
            "falsified physical paired census or optimizer budget")
    times = report.get("measured_arm_times")
    require(type(times) is dict and set(times) == {"selected", "full"},
            "both matched inference paths required")
    for name, rows, batches in (("selected", 8, 1), ("full", 32, 2)):
        require(type(times[name]) is list and len(times[name]) == 4,
                "missing four measured paired repeats")
        for row in times[name]:
            require(type(row) is dict and set(row) == {
                "wall_seconds", "cpu_seconds", "actual_sequences", "batches"}
                and row["actual_sequences"] == rows and row["batches"] == batches and
                all(type(row[k]) in (float,int) and math.isfinite(row[k]) and row[k] > 0
                    for k in ("wall_seconds", "cpu_seconds")),
                    "fake timed real execution")
        for src,dst in (("wall_seconds","median_arm_wall_seconds"),
                        ("cpu_seconds","median_arm_cpu_seconds")):
            median = statistics.median(r[src] for r in times[name])
            require(abs(median - report[dst][name]) < 1e-10,
                    "wrong observed paired timing statistic")
    require(type(report.get("max_within_run_selected_full_abs_drift")) in (float,int)
            and math.isfinite(report["max_within_run_selected_full_abs_drift"])
            and 0 <= report["max_within_run_selected_full_abs_drift"] <= 5e-4,
            "same-model same-resident Head numeric agreement failed")
    metric_fields = ("cheap_route_wall_seconds", "cheap_route_cpu_seconds",
        "model_load_wall_seconds", "fit_encoder_wall_seconds", "head_training_wall_seconds",
        "total_paid_workload_wall_seconds", "total_paid_workload_cpu_seconds")
    require(all(type(report.get(k)) in (float,int) and math.isfinite(report[k])
                and report[k] > 0 for k in metric_fields) and
            type(report.get("self_reported_process_maxrss_bytes")) is int and
            report["self_reported_process_maxrss_bytes"] > 0,
            "unmeasured or fake phase cost")
    components = sum(report[k] for k in ("cheap_route_wall_seconds",
        "model_load_wall_seconds", "fit_encoder_wall_seconds", "head_training_wall_seconds"))
    measured = sum(r["wall_seconds"] for arm in ("selected", "full") for r in times[arm])
    require(report["total_paid_workload_wall_seconds"] + 1e-5 >= components + measured,
            "unaccounted workload wall phases")
    require(report.get("authority") == "DENY_ALL" and report.get("disposition") == "HOLD_NO_GO"
            and report.get("production_authorized") is False
            and report.get("cell_split_authorized") is False
            and report.get("stem_winner_verified") is False
            and report.get("ndu_gain_verified") is False
            and report.get("test_gold_ever_reopened") is False
            and report.get("historical_test_labels_previously_exposed") is True
            and report.get("full_lifecycle_resource_savings_verified") is False
            and report.get("target_host_p99_energy_attested") is False
            and report.get("independent_source_families") == 1
            and report.get("future_windows") == 0,
            "physical cost receipts confer no real-world model selection authority")
    return {"schema": "hepta.stem.same-process-cost-review.v13",
        "candidate": model,
        "full_query_median_wall_seconds": report["median_arm_wall_seconds"]["full"],
        "selected_query_median_wall_seconds": report["median_arm_wall_seconds"]["selected"],
        "selected_plus_cheap_median_wall_seconds":
            report["median_arm_wall_seconds"]["selected"] + report["cheap_route_wall_seconds"],
        "descriptive_selected_to_full_query_wall_ratio":
            report["median_arm_wall_seconds"]["selected"] /
              report["median_arm_wall_seconds"]["full"],
        "initial_head_byte_equal": True,
        "trained_head_byte_equal": report["historical_trained_head_byte_equal"],
        "within_run_parity_verified_from_producer_receipt_only": True,
        "physical_forward_count_independently_hardware_attested": False,
        "full_lifecycle_savings_verified": False,
        "production_authorized": False,
        "stem_winner_verified": False,
        "authority": "DENY_ALL", "disposition": "HOLD_NO_GO"}


def main():
    p = argparse.ArgumentParser()
    for key in ("report", "manifest", "model-zip", "source-zip", "cheap-zip", "output"):
        p.add_argument("--" + key, required=True)
    a = p.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"stem-optimal-v5"))
    import paired_review_v5 as v5
    lock = json.loads(Path(a.manifest).read_text())
    require(lock["schema"] == "hepta.stem.original-hard-charge.lock.v5" and
            lock["authority"] == "DENY_ALL", "wrong original artifact lock")
    receipt = json.loads(Path(a.report).read_text())
    name = receipt.get("candidate")
    require(name in MODELS, "nonqualified model cost scope")
    source = v5.locked_json(Path(a.source_zip), lock["artifacts"], "source_v3")
    cheap = v5.locked_json(Path(a.cheap_zip), lock["artifacts"], "cheap_v4")
    original = v5.locked_json(Path(a.model_zip), lock["artifacts"], name)
    result = inspect(receipt, original, source, cheap)
    destination = Path(a.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(json.dumps(result, sort_keys=True, allow_nan=False,
              separators=(",", ":")).encode() + b"\n")
        stream.flush()
    print(json.dumps({"authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
        "candidate": name, "review_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()},
        sort_keys=True))


if __name__ == "__main__":
    main()
