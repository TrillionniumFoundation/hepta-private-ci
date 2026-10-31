"""Seed-paired 2x2 attribution, complete-cost sensitivities and admission.

The five fitted-model seeds are the replication units. Sessions supply paired
within-seed means; they do not increase the Student-t degrees of freedom.
No observation, including an executed failure, is silently filtered away.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


ARMS = dict(A="ordinary_myopic", B="ordinary_value", C="analytic_myopic", D="analytic_value")
CONTRASTS = {
    "D-B": {"D": 1, "B": -1}, "C-A": {"C": 1, "A": -1},
    "B-A": {"B": 1, "A": -1}, "D-C": {"D": 1, "C": -1},
    "interaction": {"D": 1, "C": -1, "B": -1, "A": 1},
}
SCORE_FIELDS = ("utility", "reward", "charged_cost", "query_cost", "latency_cost",
                "completed_jobs", "correct_jobs")
TIME_FIELDS = ("cpu_seconds", "wall_seconds", "controller_cpu_seconds", "controller_wall_seconds", "task_elapsed")


def _number(value):
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool) and math.isfinite(value)


def _interval(values, seeds, family_size=5):
    if len(values) != len(seeds) or len(values) < 2 or any(v is None or not _number(v) for v in values):
        return dict(status="incomplete", training_replications=sum(_number(v) for v in values),
                    provided_training_seed_slots=len(values),
                    required_replications=len(seeds), per_seed=dict(zip(map(str, seeds), values)),
                    mean=None, lower=None, upper=None)
    values = np.asarray(values, dtype=float)
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    critical = float(student_t.ppf(1-.05/(2*family_size), len(values)-1))
    halfwidth = critical*sd/math.sqrt(len(values))
    return dict(status="complete", training_replications=len(values), degrees_of_freedom=len(values)-1,
        mean=mean, seed_sample_sd=sd, standard_error=sd/math.sqrt(len(values)),
        lower=mean-halfwidth, upper=mean+halfwidth, critical_value=critical,
        marginal_confidence=1-.05/family_size, family_size=family_size,
        per_seed=dict(zip(map(str, seeds), values.tolist())))


def _row_problems(row, jobs):
    problems = []
    score = row.get("score")
    if not isinstance(score, dict):
        score = {}
    for name in SCORE_FIELDS:
        if not _number(score.get(name)):
            problems.append("invalid_score_"+name)
    for name in TIME_FIELDS:
        if not _number(row.get(name)) or row.get(name, -1) < 0:
            problems.append("invalid_"+name)
    if not problems:
        if abs(score["utility"]-(score["reward"]-score["charged_cost"])) > 1e-9:
            problems.append("utility_accounting_mismatch")
        if abs(score["charged_cost"]-score["query_cost"]-score["latency_cost"]) > 1e-9:
            problems.append("task_cost_accounting_mismatch")
        completed, correct = score["completed_jobs"], score["correct_jobs"]
        if not (int(completed) == completed and int(correct) == correct and 0 <= correct <= completed <= jobs):
            problems.append("invalid_job_counts")
        if any(score[name] < 0 for name in ("charged_cost", "query_cost", "latency_cost")):
            problems.append("negative_task_cost")
        if row["controller_cpu_seconds"] > row["cpu_seconds"]+1e-6:
            problems.append("controller_cpu_exceeds_enclosing_rollout")
        if row["controller_wall_seconds"] > row["wall_seconds"]+1e-6:
            problems.append("controller_wall_exceeds_enclosing_rollout")
    if score.get("label_access_after_terminal") is False:
        problems.append("labels_accessed_before_termination")
    counts = row.get("counts", {})
    if not isinstance(counts, dict) or any(not _number(v) or v < 0 for v in counts.values()):
        problems.append("invalid_resource_counts")
    if not isinstance(row.get("events", []), list):
        problems.append("invalid_events")
    return problems


def _failure(row):
    if row.get("error") is not None or row.get("error_type") is not None or row.get("success") is False:
        return True
    if row.get("status") in ("failed", "error", "aborted", "invalid"):
        return True
    events = row.get("events", [])
    return isinstance(events, list) and any(event.get("status") in ("failed_read", "failed", "error")
               for event in events if isinstance(event, dict))


def _aggregate(rows, jobs):
    invalid = [dict(session_id=row.get("session_id"), problems=_row_problems(row, jobs)) for row in rows]
    invalid = [row for row in invalid if row["problems"]]
    failed = [row.get("session_id") for row in rows if _failure(row)]
    result = dict(sessions=len(rows), failed_sessions=failed, invalid_rows=invalid,
                  status="complete" if rows and not invalid else "incomplete")
    if not rows or invalid:
        return result
    result["means"] = {name: float(np.mean([row["score"][name] for row in rows])) for name in SCORE_FIELDS}
    result["means"].update({name: float(np.mean([row[name] for row in rows])) for name in TIME_FIELDS})
    completed = sum(row["score"]["completed_jobs"] for row in rows)
    correct = sum(row["score"]["correct_jobs"] for row in rows)
    result.update(completed_jobs=int(completed), correct_jobs=int(correct),
        completed_job_accuracy=correct/completed if completed else None,
        completion_fraction=completed/(jobs*len(rows)),
        correct_fraction_of_all_jobs=correct/(jobs*len(rows)),
        session_quality=[dict(session_id=r["session_id"], completed_jobs=r["score"]["completed_jobs"],
            correct_jobs=r["score"]["correct_jobs"], correct_fraction_of_all_jobs=r["score"]["correct_jobs"]/jobs,
            completed_job_accuracy=r["score"]["correct_jobs"]/r["score"]["completed_jobs"]
                if r["score"]["completed_jobs"] else None)
            for r in rows])
    count_names = sorted({key for row in rows for key in row.get("counts", {})})
    result["counts"] = {name: sum(row.get("counts", {}).get(name, 0) for row in rows) for name in count_names}
    result["timing_totals"] = {name: float(sum(row[name] for row in rows)) for name in TIME_FIELDS}
    return result


def _training(training_costs, seeds, policies):
    if isinstance(training_costs, list):
        training_costs = {str(item["seed"]): item for item in training_costs}
    normalized, issues, campaign = {}, [], []
    for seed in seeds:
        record = training_costs.get(seed, training_costs.get(str(seed), {}))
        by_arm = record.get("training_cpu_seconds_by_arm", {})
        normalized[str(seed)] = {}
        for arm in policies:
            value = by_arm.get(arm)
            normalized[str(seed)][arm] = float(value) if _number(value) and value >= 0 else None
            if arm in ARMS.values() and normalized[str(seed)][arm] is None:
                issues.append(dict(seed=seed, arm=arm, error="missing_standalone_training_cpu"))
        # These unique timers describe physical work. They are not added again
        # to training_cpu_seconds_by_arm, which is already the standalone total.
        unique = []
        shared = record.get("shared_setup_cpu_seconds")
        if _number(shared) and shared >= 0:
            unique.append(float(shared))
        components_valid = _number(shared) and shared >= 0
        component_details = {}
        for family in ("cellfit_costs", "critic_costs"):
            components = record.get(family)
            component_details[family] = components
            if not isinstance(components, dict):
                components_valid = False
                continue
            for item in components.values():
                value = item if _number(item) else next((item[key] for key in
                    ("cpu_seconds", "cell_cpu_seconds", "training_cpu_seconds")
                    if isinstance(item, dict) and key in item), None)
                if not _number(value) or value < 0:
                    components_valid = False
                else:
                    unique.append(float(value))
        if "learned_boundary" in policies:
            selection = record.get("learned_boundary", {})
            boundary_cpu = selection.get("cpu_seconds") if isinstance(selection, dict) else None
            component_details["auxiliary_boundary_selection_cpu_seconds"] = boundary_cpu
            if _number(boundary_cpu) and boundary_cpu >= 0:
                unique.append(float(boundary_cpu))
            else:
                components_valid = False
                issues.append(dict(seed=seed, error="missing_auxiliary_boundary_selection_cpu"))
        campaign.append(dict(seed=seed, shared_setup_cpu_seconds=shared,
            unique_component_training_cpu_seconds=sum(unique) if components_valid else None,
            component_details=component_details,
            scope="Shared setup once, cell fit once per family, critic once per fitted arm, auxiliary boundary selection once; standalone arm totals are not summed"))
    return normalized, issues, campaign


def analyze(rows, training_costs, protocol):
    """Analyze all rows without resampling, tuning or omitting failed attempts.

    training_costs is keyed by training seed. Its training_cpu_seconds_by_arm is
    the complete measured standalone preparation/training CPU for that arm,
    INCLUDING shared_setup once. Paired controllers each pay their shared cell
    fit once when evaluated as standalone deployments. For campaign accounting,
    separate unique component timers prevent double-counting that shared work.
    """
    seeds = list(protocol["seeds"])
    if len(seeds) != len(set(seeds)) or len(seeds) < 2:
        raise ValueError("Unique independent training seeds required")
    if list(protocol["primary_contrasts"]) != list(CONTRASTS):
        raise ValueError("Protocol contrast order/definitions changed")
    policies = list(protocol["arms"])+list(protocol.get("additional_references", []))+list(protocol.get("auxiliary_policies", []))
    if len(policies) != len(set(policies)) or set(protocol["arms"]) != set(ARMS.values()):
        raise ValueError("Invalid factorial policy registry")
    jobs = protocol.get("jobs_per_session", 2)
    if not _number(jobs) or int(jobs) != jobs or jobs <= 0:
        raise ValueError("Positive integer jobs_per_session required")
    grouped, row_issues, seen = defaultdict(list), [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Row {index} must be an object; original data must remain retained")
        split = str(row.get("split", "")).lower()
        split = "iid" if split in ("iid", "test") else split
        key = (row.get("seed"), split, row.get("policy"), row.get("session_id"))
        if key in seen:
            row_issues.append(dict(row_index=index, identity=list(key), error="duplicate_row_identity"))
        seen.add(key)
        if key[0] not in seeds or split not in ("iid", "ood") or key[2] not in policies or not key[3]:
            row_issues.append(dict(row_index=index, identity=list(key), error="unregistered_row_identity"))
        grouped[key[:3]].append(row)
    training, cost_issues, campaign_training = _training(training_costs, seeds, policies)
    output = dict(schema="hcsn.task.value.factorial.analysis.v1", input_rows=len(rows),
        input_rows_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=True).encode()).hexdigest(),
        row_integrity_issues=row_issues, training_cost_issues=cost_issues,
        standalone_training_cpu_by_seed_and_arm=training, campaign_training=campaign_training,
        uncertainty_contract=dict(replication_unit="independently fitted training seed",
            interval="two-sided Student t", alpha=.05, primary_family_size=5,
            family_scope="five registered utility contrasts separately within IID and OOD",
            caveat="Five-seed t inference is conditional on the registered task family; intervals are not episode-level guarantees"),
        objective_accounting="Teacher/task utility is reward minus query and modeled latency costs. Measured CPU is charged only for admission and sensitivity; it does not retrospectively alter the task teacher.",
        splits={})
    for split, expected_count in (("iid", protocol["test_sessions"]), ("ood", protocol["ood_sessions"])):
        summaries, pairing = {}, []
        for seed in seeds:
            summaries[str(seed)] = {}
            identities = {arm: {r.get("session_id") for r in grouped[seed, split, arm]} for arm in policies}
            reference = identities[ARMS["A"]]
            for arm in policies:
                rs = grouped[seed, split, arm]
                summaries[str(seed)][arm] = _aggregate(rs, jobs)
                if identities[arm] != reference or len(rs) != expected_count or len(identities[arm]) != len(rs):
                    pairing.append(dict(seed=seed, policy=arm, expected_sessions=expected_count,
                        actual_rows=len(rs), unique_sessions=len(identities[arm]),
                        missing_relative_to_A=sorted(reference-identities[arm]),
                        extra_relative_to_A=sorted(identities[arm]-reference)))
        def metric(seed, arm, name):
            record = summaries[str(seed)][arm]
            return record.get("means", {}).get(name) if name in SCORE_FIELDS+TIME_FIELDS else record.get(name)
        invalid_pairing_seeds = {issue["seed"] for issue in pairing}
        contrasts = {}
        for name, weights in CONTRASTS.items():
            values = []
            for seed in seeds:
                v = [metric(seed, ARMS[a], "utility") for a in weights]
                values.append(sum(w*x for w, x in zip(weights.values(), v))
                    if seed not in invalid_pairing_seeds and all(x is not None for x in v) else None)
            contrasts[name] = _interval(values, seeds)
        quality = _interval([metric(seed, ARMS["D"], "completed_job_accuracy")-metric(seed, ARMS["B"], "completed_job_accuracy")
            if seed not in invalid_pairing_seeds and metric(seed, ARMS["D"], "completed_job_accuracy") is not None and metric(seed, ARMS["B"], "completed_job_accuracy") is not None else None
            for seed in seeds], seeds)
        quality["noninferiority_margin"] = protocol["quality_noninferiority_margin"]
        quality["noninferiority_passed"] = quality["lower"] is not None and quality["lower"] >= -protocol["quality_noninferiority_margin"]
        sensitivities = []
        for price in protocol["cpu_prices_utility_per_second"]:
            for horizon in protocol["amortization_sessions"]:
                values, details = [], []
                for seed in seeds:
                    a, b = ARMS["D"], ARMS["B"]
                    td, tb = training[str(seed)][a], training[str(seed)][b]
                    ud, ub, cd, cb = (metric(seed, a, "utility"), metric(seed, b, "utility"),
                                       metric(seed, a, "cpu_seconds"), metric(seed, b, "cpu_seconds"))
                    if seed in invalid_pairing_seeds or any(x is None for x in (td, tb, ud, ub, cd, cb)):
                        values.append(None)
                        continue
                    charged_d, charged_b = cd+td/horizon, cb+tb/horizon
                    values.append(ud-ub-price*(charged_d-charged_b))
                    details.append(dict(seed=seed, analytic_total_cpu_per_session=charged_d,
                        ordinary_total_cpu_per_session=charged_b, analytic_training_cpu=td, ordinary_training_cpu=tb))
                sensitivities.append(dict(cpu_price=price, amortization_sessions=horizon,
                    contrast=_interval(values, seeds), accounting=details,
                    scope="Registered sensitivity; five-contrast critical value per setting, not simultaneous over all price/horizon settings"))
        per_policy = {}
        for arm in policies:
            per_policy[arm] = {name: _interval([metric(seed, arm, name) for seed in seeds], seeds, 1)
                for name in SCORE_FIELDS+TIME_FIELDS+(
                             "completed_job_accuracy", "completion_fraction", "correct_fraction_of_all_jobs")}
        quality_diagnostics = {name: _interval([
            metric(seed, ARMS["D"], name)-metric(seed, ARMS["B"], name)
            if seed not in invalid_pairing_seeds and metric(seed, ARMS["D"], name) is not None and metric(seed, ARMS["B"], name) is not None else None
            for seed in seeds], seeds, 1)
            for name in ("completed_jobs", "correct_jobs", "completion_fraction", "correct_fraction_of_all_jobs")}
        migration = None
        if "analytic_value_sampled" in policies:
            migration = dict(scope="Exploratory distribution-trained controller versus sampled finite-CTMC state execution; no retraining and no primary multiplicity claim", metrics={})
            for name in ("utility", "completed_job_accuracy", "completion_fraction", "correct_fraction_of_all_jobs", "cpu_seconds"):
                values = []
                for seed in seeds:
                    sample, distribution = metric(seed, "analytic_value_sampled", name), metric(seed, ARMS["D"], name)
                    values.append(sample-distribution
                        if seed not in invalid_pairing_seeds and sample is not None and distribution is not None else None)
                migration["metrics"][name] = _interval(values, seeds, 1)
        failures = sum(len(summaries[str(seed)][arm]["failed_sessions"]) for seed in seeds for arm in policies)
        invalid = sum(len(summaries[str(seed)][arm]["invalid_rows"]) for seed in seeds for arm in policies)
        complete = not (pairing or invalid or row_issues)
        admission_cost = next((s["contrast"] for s in sensitivities if s["cpu_price"] == .01 and s["amortization_sessions"] == 1000), None)
        output["splits"][split] = dict(per_seed=summaries, per_policy=per_policy,
            pairing_issues=pairing, cohort_complete=complete, executed_failure_rows=failures,
            invalid_rows=invalid, utility_contrasts=contrasts, completed_job_accuracy_D_minus_B=quality,
            quality_diagnostics_D_minus_B=quality_diagnostics,
            descriptive_interval_scope="Per-policy summaries, secondary quality and migration diagnostics use unadjusted 95% seed-t intervals; they are not extra primary discoveries",
            sampled_minus_distribution=migration,
            cpu_adjusted_D_minus_B=sensitivities,
            gates=dict(complete_cohort=complete, no_executed_failures=failures == 0,
                positive_D_minus_B=contrasts["D-B"]["lower"] is not None and contrasts["D-B"]["lower"] > 0,
                completed_job_accuracy_noninferior=quality["noninferiority_passed"],
                cpu_adjusted_D_minus_B_positive=admission_cost is not None and admission_cost["lower"] is not None and admission_cost["lower"] > 0))
    measured_rollout = [row["cpu_seconds"] for row in rows if _number(row.get("cpu_seconds")) and row["cpu_seconds"] >= 0]
    unique_training = [r["unique_component_training_cpu_seconds"] for r in campaign_training]
    output["campaign_cost"] = dict(measured_rollout_cpu_seconds=sum(measured_rollout),
        rollout_rows_with_valid_cpu=len(measured_rollout), rollout_rows_without_valid_cpu=len(rows)-len(measured_rollout),
        unique_component_training_cpu_seconds=sum(unique_training) if all(v is not None for v in unique_training) else None,
        scope="Measured timers only; controller CPU is nested in rollout CPU and is not added again. Development, installation, publication and unmeasured stages are excluded, not priced as zero.")
    gates = {split+"/"+name: passed for split, data in output["splits"].items() for name, passed in data["gates"].items()}
    gates["complete_training_cost"] = not cost_issues
    gates["native_integration_qualified"] = protocol.get("native_integration_qualified") is True
    output["admission"] = dict(gates=gates, main_activation=all(gates.values()),
        failed_gates=[name for name, passed in gates.items() if not passed],
        energy_measurement=protocol.get("energy_measurement"),
        energy_saving_claim_allowed=False,
        energy_scope="CPU time and event counts are not energy measurements; any energy-saving claim requires separate hardware evidence and review")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", required=True)
    parser.add_argument("--training-costs", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = analyze(json.loads(Path(args.rows).read_text()), json.loads(Path(args.training_costs).read_text()),
                     json.loads(Path(args.protocol).read_text()))
    with Path(args.output).open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["admission"], indent=2))


if __name__ == "__main__":
    main()
