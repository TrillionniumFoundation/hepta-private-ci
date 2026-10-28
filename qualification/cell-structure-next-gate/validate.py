#!/usr/bin/env python3
"""Offline, stdlib-only evidence validator; never trains, dispatches or promotes."""

import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())


def is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class Findings:
    def __init__(self):
        self.items = []

    def require(self, condition, code, severity="failed", detail=""):
        if not condition:
            self.items.append({"severity": severity, "code": code, "detail": detail})
        return condition

    def result(self, metrics=None):
        severities = {item["severity"] for item in self.items}
        status = next((name for name in ("invalid", "held", "failed") if name in severities), "passed_registered_scope")
        return {
            "schema": "hepta.cell-structure.gate-verdict.v1",
            "status": status,
            "registered_structure_gate_passed": status == "passed_registered_scope",
            "production_authority": False,
            "general_intelligence_claim_supported": False,
            "new_training_or_inference_executed_by_validator": False,
            "findings": self.items,
            "recomputed_metrics": metrics or {},
        }


def load_artifacts(manifest, root, findings):
    """Verify exact local bytes; do not follow links or execute checkpoint code."""
    payloads, identities, seen_ids = {}, {}, set()
    root = Path(root).resolve()
    for artifact in manifest.get("artifacts", []):
        artifact_id, kind = artifact["id"], artifact["kind"]
        if not findings.require(artifact_id not in seen_ids, "duplicate_artifact_id", "invalid", artifact_id):
            continue
        seen_ids.add(artifact_id)
        relative = Path(artifact["path"])
        if not findings.require(not relative.is_absolute() and ".." not in relative.parts, "unsafe_artifact_path", "invalid", str(relative)):
            continue
        path = root / relative
        safe = path.is_file() and not any(part.is_symlink() for part in [path, *path.parents] if part != root and root in part.parents)
        if not findings.require(safe and path.resolve().is_relative_to(root), "missing_or_linked_artifact", "invalid", str(relative)):
            continue
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(block)
                digest.update(block)
        if not findings.require(count == artifact["bytes"] and digest.hexdigest() == artifact["sha256"], "artifact_identity_mismatch", "invalid", artifact_id):
            continue
        identities[artifact_id] = digest.hexdigest()
        if kind in manifest.get("required_artifact_kinds", []):
            findings.require(kind not in payloads, "duplicate_artifact_kind", "invalid", kind)
            findings.require(count <= 128 * 1024 * 1024, "metadata_artifact_too_large", "invalid", kind)
            if count <= 128 * 1024 * 1024:
                payloads[kind] = json.loads(path.read_text())
    return payloads, identities


def index_rows(rows, keys, findings, code):
    indexed = {}
    for row in rows:
        key = tuple(row[field] for field in keys)
        findings.require(key not in indexed, f"duplicate_{code}", "invalid", repr(key))
        indexed[key] = row
    return indexed


def check_splits(plan, data, findings):
    cases = index_rows(data["cases"], ["id"], findings, "case")
    training, calibration = data["training"], data["calibration"]
    for field in ("case_ids", "expression_groups", "entity_ids", "task_ids"):
        findings.require(isinstance(training[field], list) and isinstance(calibration[field], list), "invalid_split_identity", "invalid", field)
    for row in cases.values():
        case_id = row["id"]
        findings.require(case_id not in set(training["case_ids"]) | set(calibration["case_ids"]), "held_case_leaked", "invalid", case_id)
        findings.require(type(row["known"]) is bool and row["family"] in plan["families"], "invalid_case_domain", "invalid", case_id)
        if not row["known"]:
            continue
        axis = row["axis"]
        findings.require(axis in plan["axes"], "unregistered_ood_axis", "invalid", axis)
        for field, axes in (("expression_groups", ("wording_ood", "joint_ood")), ("entity_ids", ("entity_ood", "joint_ood")), ("task_ids", ("task_ood", "joint_ood"))):
            value = row[{"expression_groups": "expression_group", "entity_ids": "entity_id", "task_ids": "task_id"}[field]]
            if axis in axes:
                findings.require(value not in set(training[field]) | set(calibration[field]), "ood_identity_leaked", "invalid", f"{case_id}:{field}")
    for family in plan["families"]:
        unknown = [row for row in cases.values() if row["family"] == family and not row["known"]]
        findings.require(len(unknown) >= plan["minimum_unknown_cases_per_family"], "unknown_probe_coverage_missing", "held", family)
        for axis in plan["axes"]:
            rows = [row for row in cases.values() if row["family"] == family and row["known"] and row["axis"] == axis]
            findings.require(len(rows) >= plan["minimum_cases_per_family_axis"], "ood_case_coverage_missing", "held", f"{family}:{axis}")
            for key, minimum, applicable in (("expression_group", "minimum_distinct_wording_groups", ("wording_ood", "joint_ood")), ("entity_id", "minimum_new_entities", ("entity_ood", "joint_ood")), ("task_id", "minimum_new_tasks", ("task_ood", "joint_ood"))):
                if axis in applicable:
                    findings.require(len({row[key] for row in rows}) >= plan[minimum], "ood_diversity_missing", "held", f"{family}:{axis}:{key}")
    return {row["id"]: row for row in cases.values()}


def measure_scores(plan, cases, data, findings):
    rows = index_rows(data["observations"], ["seed", "arm", "case_id"], findings, "observation")
    expected = {(seed, arm, case_id) for seed in plan["seeds"] for arm in plan["arms"] for case_id in cases}
    findings.require(set(rows) == expected, "observation_matrix_incomplete_or_extra", "held")
    scores = {}
    for seed in plan["seeds"]:
        for arm in plan["arms"]:
            for family in plan["families"]:
                false_accepts = 0
                for case_id, case in cases.items():
                    row = rows.get((seed, arm, case_id))
                    if row is None:
                        continue
                    findings.require(type(row["accepted"]) is bool, "invalid_acceptance_value", "invalid")
                    if case["family"] == family and not case["known"] and row["accepted"]:
                        false_accepts += 1
                if arm in (plan["primary_candidate"], plan["network_candidate"]):
                    findings.require(false_accepts <= plan["metrics"]["unknown_acceptances_max"], "unknown_false_acceptance", detail=f"{seed}:{arm}:{family}:{false_accepts}")
                for axis in plan["axes"]:
                    subset = [case for case in cases.values() if case["known"] and case["family"] == family and case["axis"] == axis]
                    accepted = correct = 0
                    for case in subset:
                        row = rows.get((seed, arm, case["id"]))
                        if row is not None and row["accepted"]:
                            accepted += 1
                            correct += row["output"] == case["expected"]
                    total = len(subset)
                    metric = {"correct": correct, "accepted": accepted, "total": total, "accuracy": correct / max(total, 1), "coverage": accepted / max(total, 1), "accepted_error_rate": (accepted - correct) / max(accepted, 1)}
                    scores[(seed, arm, family, axis)] = metric
                    if arm in (plan["primary_candidate"], plan["network_candidate"]):
                        findings.require(total > 0 and metric["coverage"] >= plan["metrics"]["known_coverage_min"], "known_coverage_failed", detail=f"{seed}:{arm}:{family}:{axis}")
                        findings.require(metric["accepted_error_rate"] <= plan["metrics"]["accepted_error_rate_max"], "accepted_error_rate_failed", detail=f"{seed}:{arm}:{family}:{axis}")
    return scores


def check_training(plan, data, registration, identities, findings):
    runs = index_rows(data["runs"], ["seed", "arm"], findings, "training_run")
    expected = {(seed, arm) for seed in plan["seeds"] for arm in plan["arms"]}
    findings.require(set(runs) == expected, "training_matrix_missing", "held")
    attempts = {}
    for key, run in runs.items():
        findings.require(run["registration_sha256"] == registration["artifact_sha256"], "training_registration_changed", "invalid", repr(key))
        findings.require(run["source_manifest_sha256"] == registration["source_manifest_sha256"], "training_source_changed", "invalid", repr(key))
        findings.require(run["contract"] == registration["contracts"][f"{key[0]}|{key[1]}"], "pretraining_budget_registration_changed", "invalid", repr(key))
        for field in plan["matching_fields"]:
            value = run["contract"][field]
            if field.endswith("_sha256"):
                findings.require(is_digest(value) and value in identities.values(), "registered_contract_artifact_missing", "held", field)
            else:
                findings.require(finite_number(value), "invalid_registered_budget", "invalid", field)
        compute = run["training_compute_units"]
        if findings.require(finite_number(compute), "invalid_training_compute", "invalid", repr(key)):
            findings.require(compute <= run["contract"]["training_compute_cap"], "training_budget_exceeded", detail=repr(key))
        trial_ids = set()
        for attempt in run["attempts"]:
            trial_ids.add(attempt["id"])
            findings.require(attempt["started_unix_ns"] > registration["registered_at_unix_ns"] and attempt["finished_unix_ns"] >= attempt["started_unix_ns"], "training_before_registration", "invalid")
            findings.require(attempt["finished_unix_ns"] < registration["held_opened_unix_ns"], "held_opened_before_training_exit", "invalid")
            findings.require(attempt["status"] in ("completed", "failed", "interrupted"), "attempt_status_unknown", "held")
        findings.require(len(trial_ids) == len(run["attempts"]) and len(trial_ids) <= run["contract"]["search_trial_cap"], "candidate_trial_budget_invalid", "invalid")
        attempts[key] = trial_ids
        if key[1] in (plan["primary_candidate"], plan["network_candidate"]):
            findings.require(any(attempt["status"] == "completed" and attempt["optimization_steps"] > 0 for attempt in run["attempts"]), "completed_parameter_fit_missing", "held", repr(key))
            findings.require(run["gradient_trace_sha256"] in identities.values() and run["initial_parameters_sha256"] in identities.values() and run["final_parameters_sha256"] in identities.values(), "real_training_artifacts_missing", "held", repr(key))
            findings.require(run["initial_parameters_sha256"] != run["final_parameters_sha256"], "no_parameter_learning_observed", detail=repr(key))
    comparisons = [(plan["primary_candidate"], plan["primary_baselines"]), (plan["network_candidate"], plan["network_baselines"])]
    for seed in plan["seeds"]:
        for candidate, baselines in comparisons:
            for baseline in baselines:
                if (seed, candidate) not in runs or (seed, baseline) not in runs:
                    continue
                for field in plan["matching_fields"]:
                    findings.require(runs[(seed, candidate)]["contract"][field] == runs[(seed, baseline)]["contract"][field], "unmatched_information_or_budget", "invalid", f"{seed}:{candidate}:{baseline}:{field}")
    return attempts


def measure_costs(plan, data, attempts, findings, identities=None):
    identities = identities or {}
    runs = index_rows(data["runs"], ["seed", "arm"], findings, "cost_run")
    findings.require(set(runs) == {(s, a) for s in plan["seeds"] for a in plan["arms"]}, "cost_matrix_missing", "held")
    costs = {}
    for key, run in runs.items():
        findings.require(run["orchestrator_finished_ns"] > run["orchestrator_started_ns"], "global_wall_interval_invalid", "invalid")
        findings.require(set(run["phases"]) == set(plan["cost_phases"]), "lifecycle_phase_cost_missing", "held", repr(key))
        lower = upper = 0.0
        bounded = True
        charged_attempts = set()
        for phase in run["phases"].values():
            charged_attempts.update(phase["attempt_ids"])
            measured = phase.get("measurement_source_sha256") in identities.values()
            findings.require(measured, "phase_measurement_source_missing", "held", repr(key))
            bounded &= measured
            for metric, weight in plan["cost_weights"].items():
                interval = phase["metrics"].get(metric, {})
                lo, hi = interval.get("lower"), interval.get("upper")
                known = finite_number(lo) and finite_number(hi) and hi >= lo
                findings.require(known, "unbounded_or_unknown_lifecycle_cost", "held", f"{key}:{metric}")
                bounded &= known
                if known:
                    lower += lo * weight
                    upper += hi * weight
                coverage_known = type(interval.get("unobserved_ns")) is int and interval["unobserved_ns"] >= 0
                findings.require(coverage_known, "cost_coverage_unknown", "held", repr(key))
                bounded &= coverage_known
                if interval.get("unobserved_ns"):
                    gap_bounded = bool(interval.get("bound_method")) and interval.get("bound_evidence_sha256") in identities.values()
                    findings.require(gap_bounded, "unexplained_cost_gap", "held", repr(key))
                    bounded &= gap_bounded
        findings.require(attempts.get(key, set()) <= charged_attempts, "failed_or_selected_candidate_cost_omitted", "held", repr(key))
        findings.require(upper > 0, "zero_whole_lifecycle_cost", "invalid", repr(key))
        costs[key] = {"lower": lower, "upper": upper, "bounded": bounded, "global_wall_ns": run["orchestrator_finished_ns"] - run["orchestrator_started_ns"]}
    return costs


def check_benefits(plan, scores, costs, findings):
    comparisons = [(plan["primary_candidate"], plan["primary_baselines"]), (plan["network_candidate"], plan["network_baselines"])]
    m = plan["metrics"]
    for seed in plan["seeds"]:
        for candidate, baselines in comparisons:
            for baseline in baselines:
                a, b = costs.get((seed, candidate)), costs.get((seed, baseline))
                if a is None or b is None or not a["bounded"] or not b["bounded"]:
                    continue
                for family in plan["families"]:
                    for axis in plan["axes"]:
                        delta = scores[(seed, candidate, family, axis)]["accuracy"] - scores[(seed, baseline, family, axis)]["accuracy"]
                        gain = delta >= m["quality_gain_min"] and a["upper"] <= m["quality_gain_cost_ratio_max"] * b["lower"]
                        efficiency = delta >= -m["quality_noninferiority_tolerance"] and a["upper"] <= m["cost_gain_ratio_max"] * b["lower"]
                        findings.require(gain or efficiency, "same_budget_net_benefit_not_established", detail=f"{seed}:{candidate}:{baseline}:{family}:{axis}")
        for family in plan["families"]:
            for axis in plan["axes"]:
                reference = scores[(seed, plan["reference_arm"], family, axis)]["accuracy"]
                findings.require(scores[(seed, plan["primary_candidate"], family, axis)]["accuracy"] >= reference - m["quality_noninferiority_tolerance"], "same_information_reference_regressed", detail=f"{seed}:{family}:{axis}")


def check_retention_and_deletion(plan, registration, retention, deletion, findings):
    capabilities = registration["retained_capability_ids"]
    findings.require(len(set(capabilities)) == len(capabilities) and len(capabilities) >= plan["minimum_retained_capabilities"], "retained_capability_population_missing", "held")
    rows = index_rows(retention["observations"], ["seed", "arm", "cycle", "capability_id"], findings, "retention")
    expected = {(s, a, c, k) for s in plan["seeds"] for a in plan["arms"] for c in plan["retention_cycles"] for k in capabilities}
    findings.require(set(rows) == expected, "continual_retention_matrix_missing", "held")
    for row in rows.values():
        findings.require(type(row["accepted"]) is bool, "invalid_retention_acceptance_value", "invalid")
        findings.require(canonical_digest(row["expected"]) == registration["retained_expected_sha256"].get(row["capability_id"]), "retained_target_changed_after_registration", "invalid")
    score = {}
    for seed in plan["seeds"]:
        for arm in plan["arms"]:
            for cycle in plan["retention_cycles"]:
                score[(seed, arm, cycle)] = sum(rows.get((seed, arm, cycle, k), {}).get("accepted") is True and rows[(seed, arm, cycle, k)]["output"] == rows[(seed, arm, cycle, k)]["expected"] for k in capabilities) / max(len(capabilities), 1)
    for seed in plan["seeds"]:
        for candidate, baselines in [(plan["primary_candidate"], plan["primary_baselines"]), (plan["network_candidate"], plan["network_baselines"])]:
            findings.require(score[(seed, candidate, 0)] >= plan["metrics"]["known_coverage_min"], "initial_retained_capability_missing")
            for cycle in plan["retention_cycles"]:
                reference = max([score[(seed, candidate, 0)], *[score[(seed, base, cycle)] for base in baselines]])
                findings.require(score[(seed, candidate, cycle)] >= reference - plan["metrics"]["retention_drop_max"], "continual_capability_retention_failed", detail=f"{seed}:{candidate}:{cycle}")
    deleted = index_rows(deletion["runs"], ["seed", "arm"], findings, "deletion")
    findings.require(set(deleted) == {(s, a) for s in plan["seeds"] for a in plan["arms"]}, "deletion_matrix_missing", "held")
    for key, run in deleted.items():
        findings.require(run["revoked_output_exposed"] is False and run["deleted_source_id"] not in run["active_training_source_ids"], "revocation_or_deleted_lineage_failed", detail=repr(key))
        actual, rebuilt = run["retained_outputs"], run["independent_clean_rebuild_outputs"]
        findings.require(set(actual) == set(rebuilt) == set(capabilities), "deletion_retained_capability_coverage_missing", "held", repr(key))
        agreement = sum(actual.get(k) == rebuilt.get(k) for k in capabilities if k in actual and k in rebuilt) / max(len(capabilities), 1)
        findings.require(agreement >= plan["metrics"]["deletion_counterfactual_agreement_min"], "finite_clean_rebuild_agreement_failed", detail=repr(key))
        retained_accuracy = sum(canonical_digest(actual[k]) == registration["retained_expected_sha256"].get(k) for k in capabilities if k in actual) / max(len(capabilities), 1)
        # These registered capabilities exclude the deleted knowledge. Matching
        # a clean rebuild alone could otherwise hide the same loss in both.
        before_deletion = max(score[(*key, 0)], score[(*key, max(plan["retention_cycles"]))])
        findings.require(retained_accuracy >= before_deletion - plan["metrics"]["retention_drop_max"], "post_deletion_retained_capability_failed", detail=repr(key))


def check_structure_and_migration(plan, trace, inventory, migration, cases, identities, findings):
    changed = set()
    for event in trace["events"]:
        findings.require(type(event["accepted"]) is bool, "invalid_structure_acceptance_value", "invalid")
        findings.require(event["decision_partition"] in ("train", "calibration"), "held_driven_structure_selection", "invalid")
        before, after = event["before_graph"]["nodes"], event["after_graph"]["nodes"]
        parameters = {node["parameter_artifact_sha256"] for node in after}
        materialized = bool(parameters) and parameters <= set(identities.values()) and parameters <= set(event["fresh_reader_artifact_sha256s"])
        size_changed = (event["kind"] == "split" and len(after) > len(before)) or (event["kind"] == "merge" and len(after) < len(before))
        if event["accepted"] is True:
            findings.require(materialized, "structure_parameter_materialization_missing", "held")
        if event["accepted"] is True and materialized and size_changed:
            changed.add((event["seed"], event["arm"]))
    findings.require({(s, a) for s in plan["seeds"] for a in (plan["primary_candidate"], plan["network_candidate"])} <= changed, "executed_structure_change_missing", "held")
    hosts = {host["id"]: host for host in inventory["hosts"]}
    findings.require(len(hosts) >= 2 and len({h["machine_fingerprint_sha256"] for h in hosts.values()}) == len(hosts), "distinct_physical_hosts_missing", "held")
    for host in hosts.values():
        address = ipaddress.ip_address(host["observed_transport_address"])
        findings.require(host["kind"] == "physical_machine" and not address.is_loopback and not address.is_unspecified and is_digest(host["machine_fingerprint_sha256"]) and host["inventory_evidence_sha256"] in identities.values(), "physical_host_evidence_missing", "held", host["id"])
    completed = set()
    for record in migration["observations"]:
        physical = record["source_host"] in hosts and record["destination_host"] in hosts and record["source_host"] != record["destination_host"]
        findings.require(physical, "migration_same_or_unknown_physical_host", "held")
        exact = record["sent_artifact_sha256"] == record["received_artifact_sha256"] and record["sent_artifact_sha256"] in identities.values()
        registered = record["case_id"] in cases and record["expected_output"] == cases[record["case_id"]]["expected"]
        findings.require(exact and registered and record["fresh_receiver_process"] is True and record["receiver_started_ns"] > record["transfer_completed_ns"] and record["observed_output"] == record["expected_output"], "fresh_receiver_artifact_or_output_failed")
        if physical and exact:
            completed.add((record["seed"], record["arm"]))
    findings.require({(s, a) for s in plan["seeds"] for a in (plan["network_candidate"], "distributed_static_graph")} <= completed, "cross_physical_migration_matrix_missing", "held")


def validate(plan, plan_digest, prior_digest, manifest, root):
    findings = Findings()
    metrics = {}
    try:
        findings.require(manifest["schema"] == "hepta.cell-structure.result-pack.v1", "result_schema_mismatch", "invalid")
        findings.require(manifest["plan_sha256"] == plan_digest and manifest["prior_evidence_sha256"] == prior_digest, "frozen_protocol_or_prior_changed", "invalid")
        kind = manifest["evidence_kind"]
        findings.require(kind in ("cell_structure_measured", "no_new_measurements", "synthetic_fixture"), "unrelated_evidence_substitution", "invalid", kind)
        findings.require(kind == "cell_structure_measured", "new_structure_measurements_not_available", "held", kind)
        # The required inventory comes from the frozen plan, never the submitter.
        bound_manifest = dict(manifest, required_artifact_kinds=plan["required_artifact_kinds"])
        data, identities = load_artifacts(bound_manifest, root, findings)
        for required in plan["required_artifact_kinds"]:
            findings.require(required in data, "required_evidence_missing", "held", required)
        if not all(required in data for required in plan["required_artifact_kinds"]):
            return findings.result()
        descriptors = {a["kind"]: a for a in manifest["artifacts"]}
        registration = dict(data["registration"], artifact_sha256=descriptors["registration"]["sha256"], held_opened_unix_ns=data["evaluation_observations"]["held_first_opened_unix_ns"])
        findings.require(registration["plan_sha256"] == plan_digest and registration["prior_evidence_sha256"] == prior_digest, "execution_registration_changed", "invalid")
        for kind in ("source_manifest", "split_manifest"):
            findings.require(registration[f"{kind}_sha256"] == descriptors[kind]["sha256"], "registered_source_or_split_changed", "invalid", kind)
        source = data["source_manifest"]
        findings.require(bool(source["files"]), "candidate_sources_missing", "held")
        for item in source["files"]:
            findings.require(identities.get(item["artifact_id"]) == item["sha256"], "candidate_source_artifact_missing", "held", item["artifact_id"])
        for field in ("authority_control_source_sha256", "held_evaluator_source_sha256"):
            findings.require(source[field] in identities.values(), "source_control_or_evaluator_missing", "held", field)
        audit = data["independent_audit"]
        audit_id = descriptors["independent_audit"]["id"]
        findings.require(audit["verified_artifacts"] == {k: v for k, v in identities.items() if k != audit_id}, "independent_audit_inventory_incomplete", "held")
        for violation in ("held_access_violations", "unaccounted_attempt_ids", "authority_control_violations", "unexplained_monitor_gaps"):
            findings.require(audit[violation] == [], "independent_audit_violation", detail=violation)
        cases = check_splits(plan, data["split_manifest"], findings)
        attempts = check_training(plan, data["training_receipts"], registration, identities, findings)
        scores = measure_scores(plan, cases, data["evaluation_observations"], findings)
        costs = measure_costs(plan, data["cost_ledger"], attempts, findings, identities)
        check_benefits(plan, scores, costs, findings)
        check_retention_and_deletion(plan, registration, data["retention_observations"], data["deletion_observations"], findings)
        check_structure_and_migration(plan, data["structure_trace"], data["physical_host_inventory"], data["migration_observations"], cases, identities, findings)
        metrics = {"quality": {"|".join(map(str, k)): v for k, v in scores.items()}, "lifecycle_cost": {"|".join(map(str, k)): v for k, v in costs.items()}}
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as error:
        findings.require(False, "malformed_or_unreadable_evidence", "invalid", str(error))
    return findings.result(metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    freeze = json.loads((directory / "FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        if sha256((directory / name).read_bytes()) != expected:
            raise SystemExit(f"frozen gate file changed: {name}")
    plan = json.loads((directory / "PLAN.json").read_text())
    result = validate(plan, freeze["files"]["PLAN.json"], freeze["files"]["PRIOR_EVIDENCE.json"], json.loads(args.manifest.read_text()), args.manifest.parent)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return {"passed_registered_scope": 0, "held": 3, "failed": 1, "invalid": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
