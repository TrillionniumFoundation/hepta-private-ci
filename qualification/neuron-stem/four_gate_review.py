#!/usr/bin/env python3
"""Four distinct research reviews, never production installation/selection authority.

The existing Cell reviewer remains canonical. This module does not change the
cross-Stem resource gate or reinterpret its maximum stage p99 as request p99.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import math
from pathlib import Path
import sys

from four_gate_core import (COMPUTE_ARMS, NDU_ARMS, TASKS, causal_depth, default_plan,
                            digest, identity, integer, latency, number, paired_interval,
                            read_bytes, read_json, read_jsonl, require, sha, validate_plan,
                            work_totals, write_once)


def review_compute(rows, plan):
    fingerprint = validate_plan(plan)
    require(type(rows) is list and rows, "missing compute census")
    cohorts, executions = defaultdict(dict), set()
    for row in rows:
        require(row.get("schema") == "hepta.four-gate-compute.v1" and row.get("plan_digest") == fingerprint,
                "wrong compute schema/plan")
        require(row.get("production_promotion_permitted") is False, "research cannot promote")
        execution = identity(row.get("execution_id"))
        require(execution not in executions, "duplicate execution")
        executions.add(execution)
        arm = row.get("arm")
        require(arm in COMPUTE_ARMS, "unknown compute arm")
        n = integer(row.get("logical_cells"), "logical Cells", 1, 4096)
        fraction = number(row.get("active_fraction"), "active fraction", .001, 1)
        repeat = number(row.get("input_repeat_fraction"), "input repeat fraction", 0, .99)
        repetition = integer(row.get("repetition"), "repetition", 0, 2)
        similarity = row.get("task_similarity")
        key = (n, fraction, repeat, similarity, repetition)
        require(n in plan["scales"] and fraction in plan["active_fractions"] and
                repeat in plan["input_repeat_fractions"] and similarity in plan["task_similarity"], "unregistered cohort")
        require(arm not in cohorts[key], "duplicate arm/cohort")
        active = max(1, math.ceil(n * fraction))
        count = integer(row.get("requests"), "request count", active)
        ticked = row.get("ticked_cell_ids")
        require(type(ticked) is list and len(ticked) == len(set(ticked)) == active, "actual active Cell coverage missing")
        for cell in ticked:
            identity(cell)
        for key_name in ("workload_digest", "host_session_digest", "encoder_pipeline_digest", "weights_digest"):
            sha(row.get(key_name))
        unique = integer(row.get("unique_admitted_inputs"), "unique inputs", 1, count)
        encoded = integer(row.get("encoded_samples"), "encoded samples", 1, count)
        integer(row.get("encoder_batch_calls"), "physical calls", 1, encoded)
        integer(row.get("encoded_tokens"), "encoded tokens", encoded)
        hits = integer(row.get("cache_hits"), "cache hits", 0, count)
        inflight = integer(row.get("inflight_coalesced"), "inflight coalescence", 0, count)
        require(encoded + hits + inflight == count and encoded >= unique, "physical work/reuse accounting mismatch")
        if arm != "shared_features_heads":
            require(encoded == count and hits == inflight == 0, "baseline borrowed shared cache")
        samples = row.get("request_latencies_ms")
        require(type(samples) is list and len(samples) == count, "request-level end-to-end latency coverage missing")
        observed_latency = latency(samples)
        number(row.get("peak_rss_bytes"), "peak RSS", 1)
        number(row.get("cpu_seconds"), "CPU time", 0)
        wall = number(row.get("wall_seconds"), "wall time", 1e-12)
        require(row.get("isolated_process_measurement") is True, "cumulative RSS cannot compare arms")
        require(row.get("arrival_profile") == "cohort_burst", "different offered-load semantics")
        for metric in ("gpu_seconds", "energy_joules"):
            if row.get(metric) is not None:
                number(row[metric], metric, 0)
        cohorts[key][arm] = dict(row, latency=observed_latency, throughput_rps=count / wall)
    expected = set(itertools.product(plan["scales"], plan["active_fractions"], plan["input_repeat_fractions"],
                                    plan["task_similarity"], range(plan["compute_repetitions"])))
    results = []
    for key, arms in sorted(cohorts.items()):
        require(set(arms) == set(COMPUTE_ARMS), "missing compute control")
        base, shared = arms["joint_encoder_batch"], arms["shared_features_heads"]
        for other in arms.values():
            for field in ("workload_digest", "host_session_digest", "encoder_pipeline_digest", "weights_digest",
                          "requests", "ticked_cell_ids", "unique_admitted_inputs", "arrival_profile"):
                require(other[field] == base[field], "unpaired compute " + field)
        budget = plan["runtime_resource_budget"]
        budget_ok = None
        if budget is not None:
            require(base["cpu_seconds"] > 0, "zero baseline CPU cannot support a ratio")
            budget_ok = (shared["peak_rss_bytes"] <= budget["max_peak_rss_bytes"] and
                         shared["latency"]["p99_ms"] <= budget["max_request_p99_ms"] and
                         shared["throughput_rps"] >= budget["min_throughput_rps"] and
                         shared["cpu_seconds"] / base["cpu_seconds"] <= budget["max_cpu_ratio"])
        results.append({"cohort": list(key), "encoded_sample_ratio": shared["encoded_samples"] / base["encoded_samples"],
                        "physical_batch_call_ratio": shared["encoder_batch_calls"] / base["encoder_batch_calls"],
                        "cpu_ratio": shared["cpu_seconds"] / base["cpu_seconds"] if base["cpu_seconds"] > 0 else None,
                        "budget_passed": budget_ok,
                        "arms": {arm: {k: value[k] for k in ("latency", "throughput_rps", "peak_rss_bytes",
                                                             "encoder_batch_calls", "encoded_samples", "encoded_tokens")}
                                 for arm, value in arms.items()}})
    complete = set(cohorts) == expected
    return {"schema": "hepta.four-gate-compute-review.v1", "plan_digest": fingerprint,
            "observed_cohorts": len(cohorts), "required_cohorts": len(expected), "matrix_complete": complete,
            "accounting_precheck": True, "budget_precheck": complete and all(r["budget_passed"] is True for r in results),
            "native_model_execution_authenticated": False, "same_physical_host_authenticated": False,
            "learning_or_prediction_equivalence_inferred": False, "production_promotion_permitted": False,
            "cohorts": results}


def bound_path(root, entry):
    require(type(entry) is dict and set(entry) == {"path", "sha256"}, "invalid artifact descriptor")
    name = entry["path"]
    require(isinstance(name, str) and name and not Path(name).is_absolute() and ".." not in Path(name).parts,
            "artifact scope escape")
    path = Path(root) / name
    require(hashlib.sha256(read_bytes(path)).hexdigest() == sha(entry["sha256"]), "artifact bytes changed")
    return path


def review_cell(manifest, root, plan):
    validate_plan(plan)
    names = ("dataset", "trial", "prelabel_journal", "no_change", "resources", "ood_receipts")
    require(type(manifest) is dict and set(manifest) == set(names), "complete six-artifact Cell evidence required")
    paths = {key: bound_path(root, manifest[key]) for key in names}
    try:
        import prequential_threeway_review as existing
    except ImportError as exc:
        raise ValueError("existing Cell reviewer/dependencies missing; no fabricated substitute") from exc
    result = existing.review(read_jsonl(paths["dataset"]), read_json(paths["trial"]), read_bytes(paths["prelabel_journal"]),
                             read_jsonl(paths["no_change"]), resources=read_json(paths["resources"]),
                             ood_receipts=read_jsonl(paths["ood_receipts"]), min_future_groups=plan["min_source_groups"],
                             replicates=plan["bootstrap_draws"], seed=plan["seed"])
    require(result.get("production_promotion_permitted") is False, "existing reviewer authority drift")
    return {"schema": "hepta.four-gate-cell-review.v1", "existing_result": result,
            "artifact_byte_bindings_verified": True, "independent_observer_authenticated": False,
            "production_promotion_permitted": False}


def behavior_census(predictions, outcomes, plan, arms, kind):
    validate_plan(plan)
    require(predictions and outcomes, "missing behavior/outcome census")
    results, cases, status_counts = {}, defaultdict(dict), defaultdict(int)
    all_jobs = {}
    for row in outcomes:
        key = identity(row.get("case_id")), identity(row.get("arm"))
        require(key not in results, "duplicate result")
        require(row.get("terminal") is True and row.get("censored") is False, "missing/censored result is not zero reward")
        require(row.get("observer_role") == "external_result_owner" and type(row.get("correct")) is bool,
                "independent result shape required")
        results[key] = row
    for row in predictions:
        require(row.get("plan_digest") == digest(plan) and row.get("kind") == kind, "wrong behavior plan/kind")
        require(row.get("production_promotion_permitted") is False, "behavior cannot authorize")
        require(not set(row).intersection({"label", "correct", "utility", "reward", "external_score"}), "policy self-labeling denied")
        case, arm = identity(row.get("case_id")), identity(row.get("arm"))
        require(arm in arms and arm not in cases[case], "unknown/duplicate behavior arm")
        require((case, arm) in results, "missing attempted-episode result")
        observed = results.pop((case, arm))
        for field in ("request_digest", "objective_digest"):
            sha(row.get(field))
            require(observed.get(field) == row[field], "result/input/objective binding mismatch")
        require(identity(observed.get("observer_id")) != identity(row.get("producer_id")), "producer cannot self-certify")
        status = row.get("status")
        require(status in ("Succeeded", "Failed", "TimedOut", "Cancelled", "Indeterminate"), "unknown terminal status")
        require(status == "Succeeded" or observed["correct"] is False, "failed attempt labeled correct")
        status_counts[status] += 1
        require(row.get("split") == "held_out" and row.get("window") in plan["future_windows"] and
                row.get("task_family") in TASKS, "missing held-out family/window")
        sources, train_sources = row.get("root_source_ids"), row.get("training_root_source_ids")
        require(type(sources) is list and sources and type(train_sources) is list and
                not set(sources).intersection(train_sources), "missing source lineage or training/test leakage")
        for field in ("information_digest", "training_dataset_digest", "common_budget_digest"):
            sha(row.get(field))
        budget = row.get("common_budget")
        expected_budget_keys = {"max_" + phase + "_wall_seconds" for phase in ("training", "search", "inference", "evaluation", "migration")}
        require(type(budget) is dict and set(budget) == expected_budget_keys and digest(budget) == row["common_budget_digest"],
                "unbound complete lifecycle budget")
        for key, value in budget.items():
            number(value, key, 0)
        require(budget["max_inference_wall_seconds"] > 0, "zero inference budget")
        trace = causal_depth(row.get("activation_trace"))
        entries = row.get("work_ledger")
        require(type(entries) is list and entries, "missing physical lifecycle ledger")
        totals = work_totals(entries)
        require(totals["phases"]["inference"]["jobs"] > 0, "no actual inference job")
        for entry in entries:
            key = entry["physical_work_id"]
            require(key not in all_jobs or all_jobs[key] == entry, "cross-episode work identity/cost drift")
            all_jobs[key] = entry
        budget_ok = all(totals["phases"][p]["wall_seconds"] <= budget["max_" + p + "_wall_seconds"]
                        for p in totals["phases"])
        cases[case][arm] = {"row": row, "result": observed, "depth": trace, "cost": totals, "budget_ok": budget_ok}
    require(not results, "extra unmatched result")
    window_owner, training_union, test_union = {}, set(), set()
    for case, versions in cases.items():
        require(set(versions) == set(arms), "missing attempted arm")
        reference = versions[arms[0]]["row"]
        for version in versions.values():
            for field in ("information_digest", "training_dataset_digest", "common_budget_digest", "objective_digest",
                          "root_source_ids", "training_root_source_ids", "task_family", "window"):
                require(version["row"][field] == reference[field], "unequal-information/budget pairing: " + field)
        for source in reference["root_source_ids"]:
            require(source not in window_owner or window_owner[source] == reference["window"], "source reused across future windows")
            window_owner[source] = reference["window"]
        training_union.update(reference["training_root_source_ids"])
        test_union.update(reference["root_source_ids"])
    require(not training_union.intersection(test_union), "cross-row training/test leakage")
    return cases, {"attempt_statuses": dict(status_counts), "deduplicated_global_work": work_totals(list(all_jobs.values()))}


def review_behavior(predictions, outcomes, plan, kind):
    arms = ("single_step", "fixed_depth", "matched_budget_feedforward") if kind == "reasoning" else NDU_ARMS
    cases, meta = behavior_census(predictions, outcomes, plan, arms, kind)
    contrasts, budget_ok = {}, all(v["budget_ok"] for c in cases.values() for v in c.values())
    for window in plan["future_windows"]:
        for family in TASKS:
            paired = []
            for key, versions in cases.items():
                reference = versions[arms[0]]["row"]
                if reference["window"] != window or reference["task_family"] != family:
                    continue
                if kind == "reasoning":
                    require(versions["single_step"]["depth"]["sequential_cell_depth"] == 1 and
                            versions["matched_budget_feedforward"]["depth"]["sequential_cell_depth"] == 1,
                            "hidden control recurrence")
                    require(versions["fixed_depth"]["depth"]["sequential_cell_depth"] in (2, 4, 8, 16), "missing real reasoning depth")
                scores = {}
                for arm, v in versions.items():
                    correct = float(v["result"]["correct"])
                    if kind == "ndu":
                        price = number(v["row"].get("external_cost_price"), "fixed cost price", 0, 1)
                        require(price == reference.get("external_cost_price"), "external objective price changed")
                        relative_cost = v["cost"]["phases"]["inference"]["wall_seconds"] / reference["common_budget"]["max_inference_wall_seconds"]
                        require(relative_cost <= 1, "NDU exceeded common budget")
                        correct -= price * relative_cost
                    scores[arm] = correct
                paired.append({"case_id": key, "root_source_ids": reference["root_source_ids"], "external_scores": scores})
            require(paired, "missing task family/window census")
            pairs = (("fixed_depth", "single_step"), ("fixed_depth", "matched_budget_feedforward")) if kind == "reasoning" else (
                ("deterministic_ndu", "fixed_budget"), ("deterministic_ndu", "confidence"),
                ("recursive_risk_ndu", "deterministic_ndu"), ("recursive_risk_ndu", "generic_nested_risk"))
            for candidate, control in pairs:
                label = window + "/" + family + "/" + candidate + "-" + control
                contrasts[label] = paired_interval(paired, candidate, control, comparisons=plan["planned_comparisons"],
                                                  draws=plan["bootstrap_draws"], seed=plan["seed"], min_groups=plan["min_source_groups"])
    return {"schema": "hepta.four-gate-" + kind + "-review.v1", **meta, "contrasts": contrasts,
            "same_frozen_budget_precheck": budget_ok, "same_actual_compute_claimed": False,
            "independent_outcome_authenticated": False, "future_calendar_chronology_authenticated": False,
            "general_fbsde_conformance_claimed": False, "ndu_exclusive_advantage_claimed": False,
            "production_promotion_permitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("plan")
    freeze.add_argument("--output", required=True)
    evaluate = sub.add_parser("review")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        write_once(args.output, default_plan())
        return 0
    plan, manifest = read_json(args.plan), read_json(args.manifest)
    fingerprint = validate_plan(plan)
    require(manifest.get("plan_digest") == fingerprint and set(manifest) <= {"plan_digest", "compute", "cell", "reasoning", "ndu"},
            "unbound manifest or unknown gate")
    root = Path(args.manifest).parent
    reports, missing = {}, []
    for name in ("compute", "cell", "reasoning", "ndu"):
        if name not in manifest:
            missing.append(name)
        elif name == "compute":
            reports[name] = review_compute(read_jsonl(bound_path(root, manifest[name])), plan)
        elif name == "cell":
            reports[name] = review_cell(manifest[name], root, plan)
        else:
            entry = manifest[name]
            require(set(entry) == {"predictions", "outcomes"}, "invalid behavior artifacts")
            reports[name] = review_behavior(read_jsonl(bound_path(root, entry["predictions"])),
                                            read_jsonl(bound_path(root, entry["outcomes"])), plan, name)
    write_once(args.output, {"schema": "hepta.four-gate-review.v1", "plan_digest": fingerprint,
                            "gate_reports": reports, "missing_gates": missing,
                            "research_census_complete": not missing, "hepta_learning_or_reasoning_qualified": False,
                            "production_promotion_permitted": False})
    return 2 if missing else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("four-gate rejected: " + str(exc), file=sys.stderr)
        sys.exit(2)
