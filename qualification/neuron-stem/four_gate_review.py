#!/usr/bin/env python3
"""Four independent research gates; no model execution or promotion authority.

Reuses the existing prequential reviewer rather than accepting its PASS flag.
Exit 0 means all four OFFLINE diagnostics passed, 2 means incomplete/not passed,
and malformed top-level plans fail before any result file is created.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from four_gate_common import (
    COST_AXES, digest, grouped_interval, integer, number, read_pinned, require,
    result, sha, timestamp, write_once,
)
from four_gate_compute import review_compute
from four_gate_controls import V2, validate_control_plan
from four_gate_selective import review_selective, validate_selective_plan
from four_gate_outcomes import WINDOWS, review_ndu, review_reasoning

GATES = ("compute", "learning", "reasoning", "ndu")
BASELINE_BUNDLE = "hepta.four-gate.evidence-bundle.v2"


def validate_plan(plan, now):
    require(plan["schema"] in ("hepta.four-gate.plan.v1", V2), "plan schema")
    if plan["schema"] == V2:
        validate_control_plan(plan)
        validate_selective_plan(plan["learning"]["selective"])
    sha(plan["source_sha"], 40)
    sha(plan["objective_sha256"])
    require(plan["evidence_kind"] in ("observed", "synthetic_diagnostic"), "unknown evidence kind")
    minimum = 200 if plan["evidence_kind"] == "observed" else 2
    integer(plan["min_groups"], "independent source groups", minimum, 100_000)
    integer(plan["bootstrap_replicates"], "bootstrap replicates", 1000, 100_000)
    integer(plan["seed"], "seed", 0, 2**32 - 1)
    require(0 < number(plan["alpha"], "family alpha") <= .05, "alpha may not exceed .05")
    require(set(plan["windows"]) == set(WINDOWS), "two calendar windows required")
    chronology = [timestamp(plan["preregistered_at"]), timestamp(plan["selection_cutoff"])]
    require(chronology[0] <= chronology[1], "preregistration after model selection")
    for window in WINDOWS:
        require(len(plan["windows"][window]) == 2, "window endpoints required")
        start, end = map(timestamp, plan["windows"][window])
        require(chronology[-1] < start <= end, "overlapping/reversed calendar windows")
        chronology.extend((start, end))
    assessed = timestamp(plan["assessment_time"])
    require(chronology[-1] <= assessed <= now, "future calendar observations do not yet exist")
    axes = plan["required_cost_axes"]
    require(type(axes) is list and len(axes) == len(set(axes)) and
            {"cpu_ns", "wall_ns"} <= set(axes) <= set(COST_AXES), "registered measured cost axes required")
    compute = plan["compute"]
    for field in ("p99_ceiling_ns", "rss_ceiling_bytes", "throughput_floor_rps", "max_p99_ratio"):
        number(compute[field], field, 1e-30)
    for gate in ("reasoning", "ndu"):
        cfg = plan[gate]
        integer(cfg["parameter_ceiling"], "parameter ceiling", 1, 10**12)
        number(cfg["rss_ceiling_bytes"], "RSS ceiling", 1)
        for name in ("episode_ceilings", "lifecycle_ceilings"):
            require(set(cfg[name]) == set(axes), "all measured cost axes need explicit budgets")
            for value in cfg[name].values():
                number(value, "resource ceiling", 1e-30)
    reasoning = plan["reasoning"]
    require(reasoning["selected_depth"] in ((2, 4, 8, 12, 16) if plan["schema"] == V2 else (2, 4, 8, 16)), "registered reasoning depth required")
    require(0 <= number(reasoning["matching_relative_tolerance"], "cost-match tolerance") <= .05,
            "equal-compute tolerance must be <=5 percent")
    require(reasoning["match_axes"] and set(reasoning["match_axes"]) <= set(axes),
            "equal compute uses actually measured axes")
    number(reasoning["minimum_score_gain"], "minimum novelty gain")
    for field in ("cost_noninferiority_margin", "quality_noninferiority_margin"):
        number(plan["ndu"][field], field)
    number(plan["learning"]["ood_far_regression_cap"], "OOD regression ceiling")
    sha(plan["ndu"]["utility_profile_sha256"])
    require(plan["ndu"]["utility_profile_sha256"] == digest({
        "profile": "registered_linear_external_score_minus_lifecycle_cost",
        "objective_sha256": plan["objective_sha256"],
        "cost_weights": plan["ndu"]["cost_weights"]}), "utility profile digest does not bind its coefficients")


def review_learning(plan, refs, root):
    import prequential_threeway_review as legacy

    expected_refs = {"dataset", "trial", "prelabel_journal", "no_change", "ood_receipts"}
    if plan["schema"] == V2:
        expected_refs.add("selective")
    require(set(refs) == expected_refs,
            "all original learning evidence references are required")
    dataset = read_pinned(root, refs["dataset"], form="jsonl")
    trial = read_pinned(root, refs["trial"])
    journal = read_pinned(root, refs["prelabel_journal"], form="bytes")
    nochange = read_pinned(root, refs["no_change"], form="jsonl")
    ood = read_pinned(root, refs["ood_receipts"], form="jsonl")
    historical_end = timestamp(plan["selection_cutoff"])
    for row in dataset:
        event = timestamp(row["event_time"])
        require(event <= timestamp(plan["assessment_time"]), "unobserved future learning event")
        if row["split"] in ("train", "calibration", "test"):
            require(event <= historical_end, "historical learning row crosses selection cutoff")
        elif row["split"] == "future":
            require(row["future_window"] in WINDOWS, "unregistered learning window")
            start, end = map(timestamp, plan["windows"][row["future_window"]])
            require(start <= event <= end, "learning event outside preregistered window")
    indexed, _, owner, changed = legacy.verify_and_index(dataset, trial, journal, nochange)
    report = legacy.review(dataset, trial, journal, nochange, ood_receipts=ood,
                           min_future_groups=plan["min_groups"],
                           replicates=plan["bootstrap_replicates"], seed=plan["seed"])
    intervals = {}
    passes = []
    for window in WINDOWS:
        items = [v for v in indexed.values() if v["dataset"]["future_window"] == window]
        for control in ("no_change", "frozen"):
            for metric, column in (("accuracy", 0), ("brier", 1)):
                pairs = []
                for item in items:
                    row = item["dataset"]
                    a = legacy.measure(item["trained"], row["label"])[column]
                    b = legacy.measure(item[control], row["label"])[column]
                    pairs.append((digest([row["scope_id"], row["group_id"]]), a - b))
                ci = grouped_interval(pairs, alpha=plan["alpha"] / (20 if plan["schema"] == V2 else 10),
                                      replicates=plan["bootstrap_replicates"], seed=plan["seed"],
                                      min_groups=plan["min_groups"])
                intervals[f"{window}:{control}:{metric}"] = ci
                passes.append(ci["enough_groups"] and (ci["lcb"] > 0 if column == 0 else ci["ucb"] < 0))
    ood_report = legacy.offline_threeway_ood_diagnostic(dataset, trial, owner, ood)
    by_case = {(r["case_id"], r["arm"]): r["probabilities"] for r in ood}
    thresholds = {arm: v["threshold_from_historical_calibration"]
                  for arm, v in ood_report["results"].items()}
    for control in ("no_change", "frozen"):
        pairs = []
        for row in dataset:
            if row["split"] == "ood" and row["task_id"] == trial["task_id"]:
                cid = row["case_id"]
                delta = int(max(by_case[(cid, "trained")]) >= thresholds["trained"]) - int(
                    max(by_case[(cid, control)]) >= thresholds[control])
                pairs.append((digest([row["scope_id"], row["group_id"]]), delta))
        ci = grouped_interval(pairs, alpha=plan["alpha"] / (20 if plan["schema"] == V2 else 10),
                              replicates=plan["bootstrap_replicates"], seed=plan["seed"],
                              min_groups=plan["min_groups"])
        intervals[f"ood:{control}"] = ci
        if plan["schema"] != V2:
            passes.append(ci["enough_groups"] and ci["ucb"] <= plan["learning"]["ood_far_regression_cap"])
    selective = None
    if plan["schema"] == V2:
        selective = review_selective(plan, read_pinned(root, refs["selective"]),
                                     trial=trial, nochange_identity=owner)
        passes.append(selective["status"] == "diagnostic_pass")
    passed = changed and report["quality_three_way_precheck_passed"] and all(passes)
    return result(passed, {"legacy_review": report, "family_adjusted_comparisons": intervals,
                           "labelled_selective_review": selective},
                  [] if passed else ["learning/retention/OOD benefit not established against both controls"])


def review_all(plan, bundle, root, *, now=None, baseline_owner_root=None,
               baseline_trust_path=None, baseline_trust_sha256=None):
    now = now or datetime.now(timezone.utc)
    validate_plan(plan, now)
    require(bundle["schema"] in ("hepta.four-gate.evidence-bundle.v1", BASELINE_BUNDLE), "bundle schema")
    typed_baseline = bundle["schema"] == BASELINE_BUNDLE
    if typed_baseline:
        from four_gate_baseline import validate_baseline_plan
        require(plan["schema"] == V2 and set(bundle) == {
            "schema", "plan_sha256", "evidence", "production_baseline"}, "typed baseline bundle fields")
        validate_baseline_plan(plan["production_baseline"])
    else:
        require("production_baseline" not in bundle, "typed baseline needs versioned bundle")
    require(bundle["plan_sha256"] == digest(plan), "bundle is not bound to this plan")
    require(set(bundle["evidence"]) == set(GATES), "all four gate slots required")
    reports = {}
    for gate in GATES:
        reference = bundle["evidence"][gate]
        if reference is None:
            reports[gate] = {**result(False, {}, ["original evidence not supplied"]),
                             "status": "blocked_missing_evidence"}
            continue
        try:
            if gate == "learning":
                reports[gate] = review_learning(plan, reference, root)
            else:
                evidence = read_pinned(root, reference)
                reviewer = {"compute": review_compute, "reasoning": review_reasoning,
                            "ndu": review_ndu}[gate]
                reports[gate] = reviewer(plan, evidence)
        except FileNotFoundError as exc:
            reports[gate] = {**result(False, {}, [str(exc)]), "status": "blocked_missing_evidence"}
        except ImportError as exc:
            reports[gate] = {**result(False, {}, [str(exc)]), "status": "blocked_missing_runtime"}
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            reports[gate] = {**result(False, {}, [str(exc)]), "status": "invalid_evidence"}
    baseline_report = None
    if typed_baseline:
        from four_gate_baseline import review_production_baseline
        try:
            if bundle["production_baseline"] is None:
                raise FileNotFoundError("original production baseline not supplied")
            baseline_report = review_production_baseline(plan, bundle["production_baseline"], root,
                owner_root=baseline_owner_root, trust_path=baseline_trust_path,
                trust_sha256=baseline_trust_sha256)
        except (FileNotFoundError, ImportError) as exc:
            baseline_report = {"status": "blocked_missing_baseline_dependency", "reason": str(exc)}
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError) as exc:
            baseline_report = {"status": "invalid_baseline_evidence", "reason": str(exc)}
    all_passed = all(r["status"] == "diagnostic_pass" for r in reports.values())
    return {
        "schema": "hepta.four-gate.research-review.v1",
        "acceptance_plan_schema": plan["schema"],
        "strong_controls_required": plan["schema"] == V2,
        "typed_production_baseline": baseline_report,
        "typed_baseline_replaces_learning_gate": False,
        "current_acceptance_profile_passed": all_passed and plan["schema"] == V2 and not typed_baseline,
        "typed_bundle_is_supplemental_not_acceptance_profile": typed_baseline,
        "plan_sha256": digest(plan), "bundle_sha256": digest(bundle),
        "evidence_kind": plan["evidence_kind"], "experiment_source_sha": plan["source_sha"],
        "gates": reports, "all_offline_diagnostics_passed": all_passed,
        "production_promotion_permitted": False, "ndu_selection_authorized": False,
        "real_world_learning_or_reasoning_established": False,
        "independent_signatures_verified": False,
        "limitations": [
            "No model is downloaded, run, selected or installed by this reviewer.",
            "Byte hashes, claimed times, source clusters and observer IDs are not authenticated evidence.",
            "Bootstrap intervals assume independent source clusters; Cell counts do not establish independence.",
            "Observed/Synthetic provenance is caller supplied, never a production qualification.",
            "Gates 3/4 assess paired shadow/replay comparisons, not general off-policy causal identification.",
            "Only a registered linear external-utility comparison is implemented, not a general FBSDE solver.",
            "Artifact CAS/final-use, native dispatch, unclean recovery and independent selection remain separate.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", required=True, help="relative path below root")
    parser.add_argument("--plan-sha256", required=True, help="original plan file byte SHA-256")
    parser.add_argument("--bundle", required=True, help="relative path below root")
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-owner-root", type=Path, help="operator-staged pinned owner source checkout")
    parser.add_argument("--baseline-trust", type=Path, help="independently controlled public-key trust file")
    parser.add_argument("--baseline-trust-sha256", help="out-of-band trust pin, never supplied by evidence")
    args = parser.parse_args()
    plan = read_pinned(args.root, {"path": args.plan, "sha256": args.plan_sha256})
    bundle = read_pinned(args.root, {"path": args.bundle, "sha256": args.bundle_sha256})
    report = review_all(plan, bundle, args.root, baseline_owner_root=args.baseline_owner_root,
        baseline_trust_path=args.baseline_trust, baseline_trust_sha256=args.baseline_trust_sha256)
    report["plan_file_sha256"] = args.plan_sha256
    report["bundle_file_sha256"] = args.bundle_sha256
    write_once(args.output, report)
    return 0 if report["all_offline_diagnostics_passed"] and not report[
        "typed_bundle_is_supplemental_not_acceptance_profile"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
