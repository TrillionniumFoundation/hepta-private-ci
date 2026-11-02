"""Predeclared per-fit control-quality and actual-CPU qualification.

Quality is evaluated on each final policy's own sampled decision distribution.
Coarse empirical strata coverage is distinct from exact numerical state overlap.
No teacher quantity is labeled actual utility or actual-label calibration.
"""
import math
import json

import numpy as np

PRIMARY_CANDIDATES = ("fpt_base_multi", "fpt_base_single", "ordinary_multi", "ordinary_single")
THRESHOLD_KEYS = ("belief_teacher_rmse_max", "selected_q_rmse_max", "pairwise_ranking_error_max",
                  "margin_absolute_error_mean_max", "teacher_regret_mean_max", "coarse_seen_fraction_min")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _key(value):
    return tuple(value)


def quality_audit(audits_by_candidate, thresholds):
    """Recompute registered criteria from raw decision audit rows.

    The six THRESHOLD_KEYS must be explicitly supplied. The requested four
    primary candidates are always included, with absent candidates marked
    incomplete. Extra supplied candidates receive the same descriptive checks.
    Undefined ranking at an all-tied teacher state is not counted as zero error;
    its count is retained and the ranking gate is null if no decision is ranked.
    """
    if any(not _number(thresholds.get(name)) or thresholds[name] < 0 for name in THRESHOLD_KEYS):
        raise ValueError("all six finite nonnegative quality thresholds must be registered")
    if thresholds["coarse_seen_fraction_min"] > 1:
        raise ValueError("coverage threshold outside [0,1]")
    candidates = list(dict.fromkeys([*PRIMARY_CANDIDATES, *audits_by_candidate]))
    output = {}
    for candidate in candidates:
        result = dict(status="incomplete", reasons=[], metrics=None, gates=None, overall=None)
        audit = audits_by_candidate.get(candidate)
        try:
            if audit is None:
                raise ValueError("missing registered candidate audit")
            rows, counts, strata = audit["decisions"], audit["counts"], audit["sparse_strata"]
            if not rows or counts["decisions"] != len(rows) or not isinstance(counts["episodes"], int) or counts["episodes"] <= 0:
                raise ValueError("missing or inconsistent final-policy decision counts")
            if sum(row["evaluation_decisions"] for row in strata) != len(rows):
                raise ValueError("stratum counts do not exhaust final decisions")
            support = {}
            for row in strata:
                key = _key(row["key"])
                if key in support:
                    raise ValueError("duplicate declared stratum")
                training = row["training_counts"]
                if not training or any(not isinstance(n, int) or n < 0 for n in training.values()):
                    raise ValueError("missing or invalid actual supervised stratum support")
                support[key] = any(n > 0 for n in training.values())
            values = []
            seen, exact_seen, rankings = 0, 0, []
            for row in rows:
                key = _key(json.loads(row["stratum"]))
                if key not in support:
                    raise ValueError("decision stratum omitted from declared counts")
                metric = row["metrics"]
                required = ("belief_teacher_mse", "selected_q_mse", "predicted_margin", "teacher_margin", "teacher_regret")
                if any(not _number(metric.get(name)) or metric[name] < 0 for name in required):
                    raise ValueError("missing, negative or nonfinite required decision metric")
                if "pairwise_ranking_error" not in metric:
                    raise ValueError("ranking metric absent")
                rank = metric["pairwise_ranking_error"]
                if rank is not None:
                    if not _number(rank) or not 0 <= rank <= 1:
                        raise ValueError("invalid pairwise ranking error")
                    rankings.append(rank)
                elif metric["teacher_margin"] != 0 or metric["teacher_regret"] != 0:
                    raise ValueError("undefined rank inconsistent with all-tied teacher state")
                if not isinstance(row["exact_unseen"], bool):
                    raise ValueError("missing exact support decision")
                seen += int(support[key])
                exact_seen += int(not row["exact_unseen"])
                values.append(metric)
            metrics = dict(decisions=len(rows), episodes=counts["episodes"],
                belief_teacher_rmse=math.sqrt(float(np.mean([v["belief_teacher_mse"] for v in values]))),
                selected_q_rmse=math.sqrt(float(np.mean([v["selected_q_mse"] for v in values]))),
                pairwise_ranking_error=float(np.mean(rankings)) if rankings else None,
                ranking_evaluable_decisions=len(rankings), ranking_undefined_decisions=len(rows) - len(rankings),
                margin_absolute_error_mean=float(np.mean([abs(v["predicted_margin"] - v["teacher_margin"]) for v in values])),
                teacher_regret_mean=float(np.mean([v["teacher_regret"] for v in values])),
                coarse_seen_fraction=seen / len(rows), exact_seen_fraction=exact_seen / len(rows),
                actual_utility_mean=audit["actual_outcomes"].get("utility_mean"))
            if not _number(metrics["actual_utility_mean"]):
                raise ValueError("actual terminal utility missing")
            mapping = dict(belief_teacher_rmse="belief_teacher_rmse_max", selected_q_rmse="selected_q_rmse_max",
                           pairwise_ranking_error="pairwise_ranking_error_max",
                           margin_absolute_error_mean="margin_absolute_error_mean_max",
                           teacher_regret_mean="teacher_regret_mean_max")
            gates = {name: None if metrics[name] is None else metrics[name] <= thresholds[limit]
                     for name, limit in mapping.items()}
            gates["coarse_seen_fraction"] = metrics["coarse_seen_fraction"] >= thresholds["coarse_seen_fraction_min"]
            result.update(status="complete", metrics=metrics, gates=gates,
                          overall=None if any(value is None for value in gates.values()) else all(gates.values()))
        except (KeyError, ValueError, TypeError) as error:
            result["reasons"].append(str(error))
        output[candidate] = result
    return dict(schema="digital-feedback-control-quality-v1", thresholds=dict(thresholds),
                required_candidates=list(PRIMARY_CANDIDATES), candidates=output,
                all_required_pass=all(output[name]["overall"] is True for name in PRIMARY_CANDIDATES),
                interpretation="Each registered fit/domain must pass every required candidate and criterion; utility benefit additionally requires the separately registered simultaneous intervals.",
                coverage_scope="Observed final-policy decisions in declared empirical strata; exact overlap reported separately; no universal support claim.")


def cost_audit(training_receipts, expected_fits=None, expected_candidates=None, between_arm_tolerance=.32,
               budget_seconds=8., per_arm_tolerance=.16):
    """Check every actual fit/arm and every within-fit maximum-minus-minimum.

    Input is {fit: {candidate: training_receipt}} or a flat receipt list. Callers
    should supply registered fit/candidate sets; absent expected sets are inferred
    and explicitly recorded, so inference cannot silently qualify missing arms.
    """
    if not _number(between_arm_tolerance) or between_arm_tolerance < 0:
        raise ValueError("finite nonnegative registered disparity tolerance required")
    if not _number(budget_seconds) or budget_seconds <= 0 or not _number(per_arm_tolerance) or per_arm_tolerance < 0:
        raise ValueError("registered per-arm CPU budget/tolerance required")
    if isinstance(training_receipts, dict):
        rows = [receipt for fit in training_receipts.values() for receipt in fit.values()]
    else:
        rows = list(training_receipts)
    fits = list(expected_fits) if expected_fits is not None else sorted({row["fit"] for row in rows})
    candidates = list(expected_candidates) if expected_candidates is not None else sorted({row["spec"]["id"] for row in rows})
    if len(fits) != len(set(fits)) or len(candidates) != len(set(candidates)):
        raise ValueError("duplicate registered fit or candidate")
    index = {}
    for row in rows:
        key = (row["fit"], row["spec"]["id"])
        if key in index or key[0] not in fits or key[1] not in candidates:
            raise ValueError("duplicate or unregistered CPU receipt")
        index[key] = row
    arms, groups = [], []
    for fit in fits:
        seconds, targets, all_numeric, arm_passes = [], [], True, []
        for candidate in candidates:
            row = index.get((fit, candidate))
            value = dict(fit=fit, candidate=candidate, seconds=None, target=None, tolerance=None,
                         absolute_deviation=None, optimizer_updates=None, training_valid=None,
                         gate=None, reason=None)
            if row is None:
                value["reason"] = "missing registered fit/arm receipt"
                all_numeric = False
            else:
                actual, target, tolerance = (row.get(key) for key in
                                            ("candidate_cpu_seconds", "training_cpu_budget", "cpu_tolerance_seconds"))
                if not all(_number(x) and x >= 0 for x in (actual, target, tolerance)) or target <= 0:
                    value["reason"] = "missing or invalid actual CPU measurement/contract"
                    all_numeric = False
                elif target != budget_seconds or tolerance != per_arm_tolerance:
                    value["reason"] = "receipt CPU contract differs from registered audit contract"
                    all_numeric = False
                else:
                    seconds.append(actual)
                    targets.append(target)
                    value.update(seconds=actual, target=target, tolerance=tolerance,
                                 absolute_deviation=abs(actual - target), gate=abs(actual - target) <= tolerance,
                                 optimizer_updates=row.get("optimizer_updates"), training_valid=row.get("training_valid"))
            arms.append(value)
            arm_passes.append(value["gate"])
        disparity = max(seconds) - min(seconds) if all_numeric and seconds else None
        target_equal = bool(targets and all_numeric and max(targets) == min(targets))
        groups.append(dict(fit=fit, arms=len(candidates), disparity_seconds=disparity,
                           common_target=targets[0] if target_equal else None,
                           common_target_gate=target_equal,
                           disparity_gate=None if disparity is None else disparity <= between_arm_tolerance,
                           all_arm_cpu_gates=all(value is True for value in arm_passes),
                           matching_gate=bool(disparity is not None and target_equal
                                             and disparity <= between_arm_tolerance
                                             and all(value is True for value in arm_passes))))
    registration_complete = expected_fits is not None and expected_candidates is not None
    return dict(schema="digital-feedback-actual-cpu-audit-v1", registered_fits=fits, registered_candidates=candidates,
                expected_sets_supplied=registration_complete, between_arm_tolerance=between_arm_tolerance,
                budget_seconds=budget_seconds, per_arm_tolerance=per_arm_tolerance,
                arms=arms, fits=groups,
                all_actual_cpu_matching=bool(registration_complete and fits and candidates and all(g["matching_gate"] for g in groups)),
                all_training_valid=bool(rows and len(rows) == len(fits) * len(candidates)
                                        and all(row.get("training_valid") is True for row in rows)),
                scope="Candidate setup, encoding, collection, optimization and finalization; persistence/shared preparation/whole worker costs are separate and not added twice.")
