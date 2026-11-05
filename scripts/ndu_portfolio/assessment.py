"""Paired independent-task-group bootstrap; numerical evidence cannot qualify a model.

The estimand gives every registered task group equal weight and averages its seed
cases first. Intervals are empirical percentile bootstrap intervals, not exact
finite-sample coverage guarantees. No case-level Wilson interval is used here.
"""

import numpy as np

from .evaluation import panel_report
from .generation import BASELINES, checked_number, digest

ESTIMATOR = "paired-group-bootstrap-v1"
METRICS = ("joint_success", "weakest_quality", "joint_failure", "recorded_total_compute", "recorded_total_seconds")
BINDINGS = ("manifest_sha256", "objective_sha256", "dataset_sha256", "evaluator_sha256",
            "budget_compute", "budget_seconds", "group_id")


def assess_panel(rows, expected_cases, *, expected_groups, training_group_ids=(),
                 bootstrap_resamples=2000, seed=11, include_planning=False):
    """Compare NDU to fixed/greedy/ordinary, optionally planning to NDU.

    expected_groups maps EVERY registered case tuple to its independent group ID;
    absent cases therefore cannot disappear or make a partial group look complete.
    All eight registered baseline rows remain in panel denominators. Statistical
    comparisons use only complete paired test groups and disclose their coverage.
    Retention/diversity and calibrated acceptance reports are separate evidence:
    this assessor intentionally supplies no override that declares them verified.
    """
    if type(bootstrap_resamples) is not int or not 200 <= bootstrap_resamples <= 10000:
        raise ValueError("bootstrap resamples must be an integer in [200, 10000]")
    if type(seed) is not int or seed < 0 or type(include_planning) is not bool:
        raise ValueError("invalid bootstrap seed or planning flag")
    rows, expected = list(rows), [tuple(case) for case in expected_cases]
    training_group_ids = tuple(training_group_ids)
    for row in rows:
        for name in ("total_compute", "total_seconds", "budget_compute", "budget_seconds"):
            checked_number(row[name], name)
        if row["outcome"] is not None:
            if type(row["outcome"]["joint_success"]) is not bool:
                raise ValueError("joint success must be an observed boolean")
            checked_number(row["outcome"]["weakest_quality"], "weakest quality", 1.0)
    panel = panel_report(rows, expected, training_group_ids=training_group_ids,
                         minimum_independent_test_groups=100)
    if set(expected_groups) != set(expected) or any(
            not isinstance(g, str) or not g for g in expected_groups.values()):
        raise ValueError("complete registered independent-group mapping required")
    if len(expected) > 100000:
        raise ValueError("registered case limit exceeded")
    reasons = set(panel["reasons"])
    selected = {baseline: {} for baseline in BASELINES}
    for row in rows:
        case = (row["task_id"], row["sample_id"], row["seed"], row["split"])
        selected[row["baseline"]][case] = row
        reasons.update(row.get("reasons", ()))
        if row["group_id"] != expected_groups[case]:
            reasons.add("registered_group_binding_mismatch")
        if row.get("execution_provenance") != "VERIFIED" or row.get("evaluator_provenance") != "VERIFIED":
            reasons.add("execution_or_evaluator_provenance_unverified")
        if row.get("controller_metering_provenance") != "VERIFIED":
            reasons.add("controller_metering_provenance_unverified")
        if not row["receipts"] or any(r.get("usage_known") is not True for r in row["receipts"]):
            reasons.add("unknown_cost_or_missing_usage_receipts")
        if row["total_compute"] > row["budget_compute"] or row["total_seconds"] > row["budget_seconds"]:
            reasons.add("total_budget_violation")
        if row["outcome"] and row["outcome"]["missing_modalities"]:
            reasons.add("missing_required_deliveries")
    groups, split_groups = {}, {}
    for case in expected:
        group = expected_groups[case]
        split_groups.setdefault(group, set()).add(case[3])
        if case[3] == "test":
            groups.setdefault(group, []).append(case)
    if any(len(splits) > 1 for splits in split_groups.values()):
        reasons.add("evaluation_group_crosses_splits")
    if set(expected_groups.values()) & set(training_group_ids):
        reasons.add("training_evaluation_group_overlap")
    if not groups:
        reasons.add("registered_test_groups_missing")
    if len(groups) * bootstrap_resamples > 10000000:
        raise ValueError("bootstrap work limit exceeded")
    comparisons = [("ndu", baseline) for baseline in ("fixed", "greedy", "ordinary_router")]
    if include_planning:
        comparisons.append(("ndu_planning", "ndu"))
    reports = []
    for candidate, baseline in comparisons:
        grouped_differences, included, paired_cases = [], [], 0
        for group, cases in sorted(groups.items()):
            pairs = [(selected[candidate].get(case), selected[baseline].get(case)) for case in cases]
            if any(a is None or b is None or a["outcome"] is None or b["outcome"] is None
                   or a["group_id"] != group or b["group_id"] != group
                   or any(a[key] != b[key] for key in BINDINGS) for a, b in pairs):
                continue
            deltas = []
            for a, b in pairs:
                success = float(a["outcome"]["joint_success"]) - float(b["outcome"]["joint_success"])
                deltas.append([success, a["outcome"]["weakest_quality"] - b["outcome"]["weakest_quality"],
                               -success, a["total_compute"] - b["total_compute"],
                               a["total_seconds"] - b["total_seconds"]])
            grouped_differences.append(np.mean(deltas, axis=0))
            included.append(group)
            paired_cases += len(cases)
        group_count = len(included)
        report = {"candidate": candidate, "baseline": baseline,
                  "expected_test_groups": len(groups), "complete_paired_groups": group_count,
                  "expected_test_cases": sum(map(len, groups.values())), "complete_paired_cases": paired_cases,
                  "paired_case_coverage": paired_cases / sum(map(len, groups.values())) if groups else 0.0,
                  "group_ids_sha256": digest(included), "delta": None, "ci95": None,
                  "familywise_success_ci95": None, "numerical_decision": "UNAVAILABLE",
                  "bootstrap_status": "NOT_PERFORMED_INSUFFICIENT_PAIRED_GROUPS"}
        if group_count < 100:
            reasons.add("insufficient_complete_paired_test_groups:" + candidate + ":" + baseline)
        if paired_cases != sum(map(len, groups.values())):
            reasons.add("incomplete_paired_group_coverage:" + candidate + ":" + baseline)
        if group_count >= 2:
            values = np.asarray(grouped_differences)
            rng = np.random.default_rng(seed)
            samples = np.empty((bootstrap_resamples, len(METRICS)))
            for start in range(0, bootstrap_resamples, 64):
                stop = min(start + 64, bootstrap_resamples)
                indices = rng.integers(0, group_count, size=(stop-start, group_count))
                samples[start:stop] = values[indices].mean(axis=1)
            interval = np.quantile(samples, [0.025, 0.975], axis=0)
            adjusted = np.quantile(samples[:, 0], [0.025 / len(comparisons), 1 - 0.025 / len(comparisons)])
            report.update(delta=dict(zip(METRICS, values.mean(axis=0).tolist())),
                          ci95={name: interval[:, i].tolist() for i, name in enumerate(METRICS)},
                          familywise_success_ci95=adjusted.tolist(), bootstrap_status="PERFORMED",
                          numerical_decision="POSITIVE_PAIRED_DIFFERENCE" if adjusted[0] > 0 else "NO_DEMONSTRATED_GAIN")
        reports.append(report)
    performed = all(r["bootstrap_status"] == "PERFORMED" for r in reports)
    resolved = []
    if performed and "correlated_cases_require_clustered_estimator" in reasons:
        resolved.append("correlated_cases_require_clustered_estimator")
        reasons.remove(resolved[0])
    # Existing outcome rows cannot establish these separate real-model gates.
    requirements = {name: "INDEPENDENT_QUALIFICATION_NOT_SUPPLIED" for name in
                    ("retention", "calibration", "diversity", "failure_tail_definition_and_guardrails")}
    reasons.update("missing_qualification:" + name for name in requirements)
    return {"status": "HOLD", "estimator": ESTIMATOR,
            "input_rows_sha256": digest(rows),
            "registered_panel_sha256": digest([[case, expected_groups[case]] for case in sorted(expected)]),
            "estimator_status": "PERFORMED" if performed else "INCOMPLETE",
            "estimand": "equal task-group mean of within-group paired seed-case means",
            "bootstrap_resamples": bootstrap_resamples, "seed": seed,
            "success_interval_multiplicity": "Bonferroni over " + str(len(comparisons)) + " declared comparisons",
            "panel": panel, "panel_wilson_intervals_used": False,
            "cost_scope": "recorded ledger totals; unknown-usage reservations cannot establish actual efficiency",
            "resolved_panel_reasons": resolved, "reasons": sorted(reasons),
            "required_external_qualifications": requirements, "comparisons": reports,
            "ndu_necessity": "NOT_ESTABLISHED",
            "claim": "Numerical intervals do not verify provenance or establish real-model efficacy."}
