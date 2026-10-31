"""Read-only checks of a completed, externally pinned P1--P5 review.

No bootstrap, training, scoring, refit, raw endpoint-array access, or new
scientific gate. Missing costs block a claim of complete cost coverage, not the
unchanged statistical results. This helper is additional operational review;
it must be source-frozen before its first real use.
"""

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import sys

OBSERVERS = ("reward", "audit")
ANALYSIS_SOURCE_SHA256 = "46ace84fa720026daa2f0b9de95b8c446f4e87ae6f1873ba43e9bceaca3f73e2"
PROTOCOL_FILE_SHA256 = "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55"
B_ARMS = ("ordinary", "field12", "full_current_state", "history6", "fixed_taper", "frozen")
C_ARMS = ("ordinary+ordinary", "ordinary+field12", "dual+ordinary", "dual+field12", "ordinary+frozen", "dual+frozen")
B_EFFECTS = {
    "ordinary-frozen task": ("task", (0, 5)),
    "field-ordinary task": ("task", (1, 0)),
    "field-history task": ("task", (1, 3)),
    "full-state-field task": ("task", (2, 1)),
    "ordinary-frozen clean": ("clean", (0, 5)),
    "field-frozen clean": ("clean", (1, 5)),
    "full-state-frozen clean": ("clean", (2, 5)),
    "history-frozen clean": ("clean", (3, 5)),
    "fixed-taper-field task (secondary)": ("task", (4, 1)),
    "fixed-taper-frozen clean (secondary)": ("clean", (4, 5)),
}
C_EFFECTS = {
    "interaction task": ("task", ((3, 2), (1, 0))),
    "dual field increment task": ("task", (3, 2)),
    "ordinary field increment task": ("task", (1, 0)),
    "dual-field minus ordinary-field task": ("task", (3, 1)),
    "ordinary-baseline minus warmstart clean": ("clean", (0, 4)),
    "ordinary-field minus warmstart clean": ("clean", (1, 4)),
    "dual-baseline minus warmstart clean": ("clean", (2, 5)),
    "dual-field minus warmstart clean": ("clean", (3, 5)),
}
PLANNED = {"A": 117504, "B": 69120, "C": 57536, "W": 2880, "R": 96768}
SPARSE_B = {"optimizer_steps", "accepted_blocks", "rejected_blocks", "discarded_gradient_microsteps"}
SPARSE_C = {"counts/evaluation." + k for k in
            ("optimizer_steps", "accepted_blocks", "rejected_blocks", "discarded_microsteps", "complete_state_restores")}


def path_cost_requirements(stage, arm):
    """Unconditional fields of the frozen Costs.since/work_delta producers."""
    if stage == "B":
        if arm == "frozen":
            return {}
        required = {"scheduled_gradient_microsteps": 288, "gradient_backward_calls": 288,
                    "gradient_generator_calls": 576, "gradient_teacher_calls": 576,
                    "guarded_transition_cpu_ns": None, "guarded_transition_wall_ns": None}
        if arm in ("field12", "history6", "full_current_state"):
            required.update({name + suffix: None for name in ("feature_measurement", "head_decision")
                             for suffix in ("_cpu_ns", "_wall_ns")})
        return required
    prefix = "counts/" + ("warmup." if arm.endswith("+frozen") else "evaluation.")
    steps = 400 if arm.endswith("+frozen") else 96
    required = {"cpu_seconds": None, "wall_seconds": None,
                prefix + "scheduled_gradient_microsteps": steps, prefix + "backward_calls": steps,
                prefix + "generator_forward_calls": None}
    if not arm.endswith("+frozen"):
        required[prefix + "teacher_forward_calls"] = None
    if arm.endswith("+field12"):
        required.update({prefix + "head_decisions": 6, prefix + "directional_backward_calls": 6,
                         prefix + "feature_probe_reverse_calls": 18})
    return required


def need(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (float, int) and math.isfinite(value)


def close(left, right):
    # Floating arithmetic identity check only; not an effect acceptance margin.
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def checked_bytes(item, max_bytes=64 * 1024**2):
    need(type(item.get("bytes")) is int and 0 <= item["bytes"] <= max_bytes,
         "Missing or excessive input byte count")
    need(re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256"))), "Missing external digest")
    path = Path(item["path"])
    need(path.is_absolute() and path.is_file() and not path.is_symlink(), "Input must be an absolute regular file")
    raw = path.read_bytes()
    need(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "Input bytes changed: " + str(path))
    return raw


def checked_json(item, max_bytes=64 * 1024**2):
    raw = checked_bytes(item, max_bytes)
    def reject(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.loads(raw, parse_constant=reject, object_pairs_hook=strict_object)


def effect_value(means, arms, expression, observer):
    if type(expression) is int:
        return means[arms[expression]][observer]
    return (effect_value(means, arms, expression[0], observer)
            - effect_value(means, arms, expression[1], observer))


def expected_thresholds(analysis, stage):
    effects = analysis["effects"]
    lower = lambda name, observer: effects[name]["ci"][observer][0]
    if stage == "C":
        positive = all(lower("interaction task", o) > 0 for o in OBSERVERS)
        retained = all(lower(name, o) > -.01 for name, row in effects.items()
                       if row["role"] == "clean" for o in OBSERVERS)
        return {"interaction_positive_both_observers": positive,
                "all_four_arms_retained_both_observers": retained,
                "interaction_and_retention_thresholds_pass": positive and retained}
    per_model = all(effects[name]["per_seed"][str(seed)][o] >= 0
                    for name in ("field-ordinary task", "field-history task")
                    for seed in (17, 29, 43) for o in OBSERVERS)
    field = all(lower("field-ordinary task", o) > .001 and lower("field-history task", o) > 0
                and lower("field-frozen clean", o) > -.01 for o in OBSERVERS)
    ordinary = all(lower("ordinary-frozen task", o) > 0 and lower("ordinary-frozen clean", o) > -.01
                   for o in OBSERVERS)
    return {"ordinary_gain_thresholds_pass": ordinary,
            "field_task_deltas_nonnegative_each_fixed_model": per_model,
            "field_advantage_thresholds_pass": field and per_model,
            "ordinary_pooled_development_target_0.005_met":
                all(effects["ordinary-frozen task"]["point"][o] >= .005 for o in OBSERVERS)}


def phase_checks(analysis, stage):
    family, arms = (B_EFFECTS, B_ARMS) if stage == "B" else (C_EFFECTS, C_ARMS)
    seeds = (17, 29, 43) if stage == "B" else tuple(range(801, 809))
    counts = {"task": 512, "clean": 812} if stage == "B" else {"task": 988, "clean": 988}
    need(analysis["stage"] == stage and analysis["seeds"] == list(seeds)
         and analysis["observers"] == list(OBSERVERS) and analysis["source_pairs"] == counts,
         "Wrong analysis population: " + stage)
    need(analysis["formal_family"] == list(family) and set(analysis["effects"]) == set(family),
         "Incomplete or reordered formal family: " + stage)
    need(set(analysis["source_pair_identities_sha256"]) == set(counts)
         and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in analysis["source_pair_identities_sha256"].values()),
         "Missing paired-source digests")
    stats = analysis["statistics"]
    tail = .05 / (2 * len(family))
    need(stats["draws"] == 8000 and stats["seed"] == (291029 if stage == "B" else 291030)
         and stats["family_size_per_observer"] == len(family) and stats["family_alpha"] == .05
         and stats["quantiles"] == [tail, 1-tail], "Original inference settings differ")
    for role in counts:
        means = analysis["arm_means"][role]
        need(set(means) == set(arms) and all(set(row) == set(OBSERVERS)
             and all(number(v) for v in row.values()) for row in means.values()), "Incomplete arm means")
    for name, (role, expression) in family.items():
        row = analysis["effects"][name]
        need(row["role"] == role and set(row["point"]) == set(row["ci"]) == set(OBSERVERS)
             and set(row["per_seed"]) == {str(s) for s in seeds}, "Effect identity differs: " + name)
        for observer in OBSERVERS:
            ci, point = row["ci"][observer], row["point"][observer]
            per_seed = [row["per_seed"][str(s)][observer] for s in seeds]
            need(len(ci) == 2 and all(number(v) for v in [point, *ci, *per_seed]) and ci[0] <= ci[1],
                 "Malformed or nonfinite effect: " + name)
            need(close(point, sum(per_seed)/len(per_seed)), "Point is not the mean of fixed/paired seed effects: " + name)
            need(close(point, effect_value(analysis["arm_means"][role], arms, expression, observer)),
                 "Effect direction/arithmetic disagrees with arm means: " + name)
    need(analysis["statistical_thresholds"] == expected_thresholds(analysis, stage),
         "Stored statistical boolean disagrees with original frozen rule")
    return {"effect_count_per_observer": len(family), "both_observers": True,
            "point_seed_arm_arithmetic": "consistent", "original_boolean_rules": "consistent",
            "source_pair_digests_recorded_not_independently_rederived_from_pixels": True}


def cost_coverage(analysis, stage):
    arms = B_ARMS if stage == "B" else C_ARMS
    paths = 48 if stage == "B" else 8
    result, missing = {}, []
    costs = analysis.get("costs", {})
    records = costs.get("arms", {})
    for arm in arms:
        frozen = arm == "frozen" or arm.endswith("+frozen")
        no_new_training = stage == "B" and frozen
        expected = 3 if stage == "B" and frozen else paths
        row = records.get(arm)
        if not isinstance(row, dict) or row.get("expected_paths") != expected:
            missing.append(stage + ":" + arm + ": expected path cost population absent")
            continue
        measured = row.get("paths_with_costs")
        need(type(measured) is int and 0 <= measured <= expected, "Invalid path cost coverage")
        metrics = row.get("metrics", {})
        need(isinstance(metrics, dict), "Malformed cost metrics")
        if not no_new_training and (measured != expected or not metrics):
            missing.append(stage + ":" + arm + ": incomplete deployed-path ledger")
        required = path_cost_requirements(stage, arm)
        missing.extend(stage + ":" + arm + ": required cost metric absent: " + key
                       for key in sorted(set(required) - set(metrics)))
        sparse_zeros = {}
        for key, metric in metrics.items():
            n = metric.get("paths")
            need(type(n) is int and 0 < n <= measured, "Cost metric coverage exceeds measured paths")
            if n != expected:
                if measured == expected and key in (SPARSE_B if stage == "B" else SPARSE_C):
                    sparse_zeros[key] = expected - n
                else:
                    missing.append(f"{stage}:{arm}: incomplete metric coverage {key}: {n}/{expected}; no absent-path zero imputed")
            for k, value in metric.items():
                need(number(value) and value >= 0, "Nonfinite/negative cost summary: " + key + "/" + k)
            need((metric["minimum"] <= metric["mean"] or close(metric["minimum"], metric["mean"]))
                 and (metric["mean"] <= metric["maximum"] or close(metric["mean"], metric["maximum"])),
                 "Cost min/mean/max inconsistent")
            need(not (("peak" in key.lower() or "max_rss" in key.lower()) and "sum_over_recorded_paths" in metric),
                 "Peak resource was incorrectly summed")
            if "sum_over_recorded_paths" in metric:
                need(close(metric["sum_over_recorded_paths"], metric["mean"] * n), "Cost mean/sum disagrees")
            if required.get(key) is not None:
                need(metric["minimum"] == metric["maximum"] == required[key], "Per-path physical work differs: " + key)
        result[arm] = {"expected_paths": expected, "paths_with_costs": measured,
                       "existing_B_frozen_reference_has_no_new_training_charge": no_new_training,
                       "C_frozen_reference_carries_own_warmup_cost_once": stage == "C" and frozen,
                       "schema_proven_zero_suppressed_path_counts": sparse_zeros,
                       "metric_paths": {k: v["paths"] for k, v in metrics.items()}}
    limitations = []
    if stage == "B":
        limitations.append("B path timers cover named operations; the producer does not record whole-path CPU/wall time.")
        paired = costs.get("field_minus_taper_descriptive", {})
        missing.extend("B: paired field-minus-taper cost metric absent: " + key
                       for key in sorted(set(path_cost_requirements("B", "fixed_taper")) - set(paired)))
        for key, metric in paired.items():
            n = metric.get("paired_paths")
            need(type(n) is int and 0 < n <= 48 and number(metric.get("mean_difference")), "Invalid paired cost summary")
            if n != 48:
                target = limitations if key in SPARSE_B and all(result.get(a, {}).get("paths_with_costs") == 48
                                                              for a in ("field12", "fixed_taper")) else missing
                target.append(f"B: paired field-minus-taper metric {key} uses {n}/48 jointly recorded paths; original conditional mean unchanged")
            if "sum_difference" in metric:
                need(number(metric["sum_difference"]) and close(metric["sum_difference"], n * metric["mean_difference"]),
                     "Paired cost mean/sum differs")
    return {"arms": result, "coverage_deficiencies": missing,
            "scope_limitations": limitations,
            "per_path_ledger_is_not_full_campaign_cost": True,
            "B_path_timers_are_selected_operations_not_total_elapsed_time": stage == "B",
            "sparse_zero_rule": "Only unconditional complete path populations plus named optional counters from Costs.since/work_delta; original means remain conditional on recorded nonzero paths.",
            "absent_metric_not_silently_zero": True}


def campaign_row_checks(rows):
    """Check fields already emitted by cost_rows; never manufacture missing time."""
    missing, limitations = [], []
    for index, row in enumerate(rows):
        label = f"Campaign: row {index} {row.get('phase', 'preflight')} {row.get('kind')}"
        ledger = row.get("ledger", {})
        counts = ledger.get("counts", ledger)
        need(isinstance(counts, dict) and all(type(v) is int and v >= 0 for v in counts.values()),
             "Stage physical ledger is not nonnegative integer counters")
        if not counts:
            missing.append(label + ": physical ledger absent")
        for key in ("cpu_seconds", "wall_seconds"):
            if not number(row.get(key)) or row[key] < 0:
                target = limitations if row.get("kind") == "engineering_preflight" and key == "cpu_seconds" else missing
                target.append(label + ": overall " + key + " absent; selected operation timers cannot substitute")
        physical = row.get("gradient_microsteps")
        need(type(physical) is int and physical >= 0, "Invalid actual gradient work")
        scheduled = {k: v for k, v in counts.items() if k.split(".")[-1] == "scheduled_gradient_microsteps"}
        if row.get("kind") == "endpoint_scoring":
            need(physical == 0 and not any(scheduled.values()), "Endpoint scoring must not add gradient training")
            phase = row["phase"]
            required = (["endpoint.generator_forward_calls", "endpoint.reward_observer_calls", "endpoint.audit_observer_calls"]
                        if phase == "C" else [f"endpoint_{role}_{name}" for role in ("task", "clean")
                                              for name in ("generator_calls", "reward_observer_calls", "audit_observer_calls")])
        else:
            if not scheduled:
                missing.append(label + ": scheduled-gradient physical counter absent")
            need(not scheduled or sum(scheduled.values()) == physical, "Row gradient work disagrees with actual ledger")
            required = ([p + "." + k for p in ("warmup", "bank", "evaluation", "replay_audit")
                         for k in ("scheduled_gradient_microsteps", "backward_calls", "generator_forward_calls")]
                        if row.get("phase") == "C" else ["gradient_backward_calls", "gradient_generator_calls", "gradient_teacher_calls"])
            backwards = [v for k, v in counts.items() if k.split(".")[-1] == "backward_calls"]
            backward = (sum(backwards) if backwards else None) if row.get("phase") == "C" else counts.get("gradient_backward_calls")
            need(backward is None or backward == physical, "Scheduled gradients and backward calls disagree")
        missing.extend(label + ": required physical counter absent/nonpositive: " + key
                       for key in required if not counts.get(key, 0))
    return missing, limitations


def aggregate_checks(aggregate):
    need(aggregate.get("status") == "COMPLETE" and aggregate.get("efficacy_artifacts_opened") is True,
         "Primary aggregate is incomplete")
    rows = aggregate.get("five_priority_findings", [])
    need(len(rows) == 5 and {r["priority"] for r in rows} == set(range(1, 6)), "Five priorities missing")
    analyses = aggregate["formal_analyses"]
    need(set(analyses) == {"B", "C"}, "Wrong formal analysis phases")
    numerical = {phase: phase_checks(analyses[phase], phase) for phase in ("B", "C")}
    costs = {phase: cost_coverage(analyses[phase], phase) for phase in ("B", "C")}
    deficits = [x for result in costs.values() for x in result["coverage_deficiencies"]]
    actual = aggregate.get("actual_costs", {})
    actual_rows = actual.get("rows", [])
    row_deficits, row_limitations = campaign_row_checks(actual_rows)
    deficits.extend(row_deficits)
    if not actual_rows:
        deficits.append("Campaign: actual_costs.rows missing; local path ledgers cannot substitute")
    for phase, count in (("A", 3), ("B", 3), ("C", 1), ("W", 1), ("R", 3)):
        members = [r for r in actual_rows if r.get("phase") == phase and r.get("kind") != "endpoint_scoring"]
        if len(members) != count or any(not number(r.get("gradient_microsteps")) for r in members):
            deficits.append("Campaign: incomplete " + phase + " stage work rows")
        elif sum(r["gradient_microsteps"] for r in members) != PLANNED[phase]:
            deficits.append("Campaign: " + phase + " scheduled work disagrees with frozen inventory")
        expected_seeds = {17, 29, 43} if count == 3 else {None}
        if len(members) == count and {r.get("seed") for r in members} != expected_seeds:
            deficits.append("Campaign: duplicated or omitted " + phase + " seed cost row")
    for phase in ("A", "B", "C"):
        if sum(r.get("kind") == "endpoint_scoring" and r.get("phase") == phase for r in actual_rows) != 1:
            deficits.append("Campaign: missing/duplicate " + phase + " endpoint-scoring cost")
    if sum(r.get("kind") == "engineering_preflight" for r in actual_rows) != 2:
        deficits.append("Campaign: both executed engineering preflights are not present")
    if actual.get("completed_receipt_gradient_microsteps") != sum(r["gradient_microsteps"] for r in actual_rows):
        deficits.append("Campaign: completed receipt work total absent or inconsistent")
    return {"numerical_consistency": numerical, "per_path_cost_coverage": costs,
            "cost_coverage_deficiencies": deficits, "declared_cost_rows_complete": not deficits,
            "cost_scope_limitations": row_limitations + [x for c in costs.values() for x in c["scope_limitations"]],
            "coverage_scope": "Named current path/stage/scoring rows and original preflights only; no complete historical campaign cost claim.",
            "net_benefit_admission_assigned": False, "original_statistics_unchanged": True,
            "unknown_historical_work_remains_unknown": True,
            "all_positive_or_global_optimality_claim_assigned": False,
            "bootstrap_training_scoring_refitting_performed": False}


def read_after_review_complete(path, expected_sha):
    path = Path(path).absolute()
    complete_item = {"path": str(path), "bytes": path.stat().st_size, "sha256": expected_sha}
    complete = checked_json(complete_item, 4 * 1024**2)
    need(re.fullmatch(r"hepta\.execution\d+\.postseal-review-completion\.1", str(complete.get("schema")))
         and complete.get("complete") is True
         and complete.get("status") in ("REVIEW_COMPLETE", "REVIEW_COMPLETE_WITH_INTEGRITY_ISSUES")
         and not path.with_name("FAILED.json").exists(), "Original postseal review did not complete")
    # The completion is metadata. Re-enter the original full source/seal gate
    # before decoding either REVIEW.json or the aggregate scientific values.
    provenance = complete["provenance"]
    implementation = provenance["implementation"]
    checked_bytes(implementation, 4 * 1024**2)
    implementation_path = Path(implementation["path"])
    suffix = implementation_path.parts[-4:]
    need(len(suffix) == 4 and suffix[0] == "operational"
         and re.fullmatch(r"parameter_field_recovery\d+", suffix[1])
         and suffix[2:] == ("postseal", "review.py"), "Unknown original review entrypoint")
    source_root = implementation_path.parents[3]
    previous_path = list(sys.path)
    sys.path.insert(0, str(source_root))
    try:
        module = importlib.import_module(".".join((*suffix[:3], "review")))
        need(Path(module.__file__).resolve() == implementation_path.resolve(), "Imported original gate path differs")
        context = module.open_gate(provenance["arguments"], provenance["supplement_wait4"])
    finally:
        sys.path[:] = previous_path
    gate = context["gate"]
    need(gate["status"] == "FULL_PRIMARY_PIPELINE_AND_LITERAL_RESTORE_VERIFIED"
         and gate["controller_jobs"] == 14 and gate["completion_seals"] == 30
         and gate["original_source_files_verified"] > 0,
         "Original whole-study source/seal gate did not admit")
    outputs = complete["outputs"]
    selected = [r for r in outputs if Path(r["path"]).name == "REVIEW.json"]
    need(len(selected) == 1 and Path(selected[0]["path"]).parent == path.parent, "Review output is not uniquely bound")
    review = checked_json(selected[0])
    need(review.get("complete") is True and review["status"] == complete["status"]
         and review["provenance"] == complete["provenance"]
         and review["scientific_positive_conclusion_automatically_assigned"] is False,
         "Review payload/provenance differs from its completion")
    aggregate_item = review["provenance"]["aggregate_results"]
    need(aggregate_item == context["pins"]["artifacts"]["aggregate_results"],
         "Review selects an aggregate outside the actual original gate")
    aggregate = checked_json(aggregate_item)
    return aggregate, review, {"review_complete": complete_item, "review": selected[0], "aggregate": aggregate_item}, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-complete")
    parser.add_argument("--expected-review-complete-sha256")
    args = parser.parse_args()
    if not args.review_complete or not args.expected_review_complete_sha256:
        print(json.dumps({"schema": "hepta.postseal-analysis-coverage-audit.1", "status": "NOT_EVALUATED",
            "reasons": ["An actual complete original postseal review and its externally held SHA256 are required.",
                        "Engineering fixtures are not scientific outcomes; no original source/seal gate has been entered."],
            "scientific_payloads_decoded": False, "scientific_inputs_modified": False}))
        return 2
    admitted = False
    try:
        aggregate, review, inputs, context = read_after_review_complete(args.review_complete, args.expected_review_complete_sha256)
        admitted = True
        result = aggregate_checks(aggregate)
        context["inputs"].unchanged()
        result.update({"schema": "hepta.postseal-analysis-coverage-audit.1", "inputs": inputs,
                       "status": ("ORIGINAL_INTEGRITY_ISSUES" if review["integrity_issues"]["issue_count"] else
                                  "COST_COVERAGE_INCOMPLETE" if result["cost_coverage_deficiencies"] else "DECLARED_COVERAGE_CHECKED"),
                       "original_full_source_seal_gate_reentered": True,
                       "analysis_source_sha256": ANALYSIS_SOURCE_SHA256,
                       "frozen_protocol_file_sha256": PROTOCOL_FILE_SHA256,
                       "original_review_integrity_issues": review["integrity_issues"],
                       "scientific_inputs_modified": False})
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 3 if result["cost_coverage_deficiencies"] or review["integrity_issues"]["issue_count"] else 0
    except (ValueError, KeyError, TypeError, OSError, ImportError) as error:
        print(json.dumps({"schema": "hepta.postseal-analysis-coverage-audit.1",
                          "status": "INTEGRITY_FAILURE" if admitted else "NOT_EVALUATED",
                          "reason": str(error), "scientific_inputs_modified": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
