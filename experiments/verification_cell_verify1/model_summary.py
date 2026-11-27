"""Descriptive summaries preserve failed, missing and unexecuted denominators."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

from .model_protocol import ARMS, digest, file_sha
from .model_heads import parameter_digest
from .model_audit import inference_bindings, panel_bindings
from .model_decisions import decision_bindings


def records(directory, name):
    path = Path(directory) / name
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


def bounded_rate(rows, label):
    errors = sum(row.get(label) is True for row in rows)
    unknown = sum(type(row.get(label)) is not bool for row in rows)
    count = len(rows)
    return {
        "count": count,
        "known_errors": errors,
        "unknown_labels": unknown,
        "known_error_rate": errors / (count - unknown) if count > unknown else None,
        "missing_label_lower": errors / count if count else None,
        "missing_label_upper": (errors + unknown) / count if count else None,
    }


def control_acceptance(rows, planned_cases):
    """Acceptance must demonstrate utility as well as reject wrong outcomes."""
    expected_clean = {
        case["goal"]["task_id"]
        for case in planned_cases
        if case["fault"] in ("clean", "missing_receipt")
    }
    expected_wrong = {
        case["goal"]["task_id"]
        for case in planned_cases
        if case["fault"] not in ("clean", "missing_receipt")
    }
    result = {}
    for arm in ARMS:
        observed = [
            row for row in rows if row["arm"] == arm and row["status"] == "completed"
        ]
        accepted_clean = {
            row["case_id"]
            for row in observed
            if row["accepted"] is True and row["outcome_error"] is False
        }
        rejected_wrong = {
            row["case_id"]
            for row in observed
            if row["accepted"] is False and row["outcome_error"] is True
        }
        result[arm] = {
            "positive_controls_accepted": bool(expected_clean)
            and accepted_clean == expected_clean,
            "known_wrong_controls_rejected": bool(expected_wrong)
            and rejected_wrong == expected_wrong,
        }
    return result


def summarize(directory, failure, wall_ns, cpu_ns):
    directory = Path(directory)
    plan = json.loads((directory / "plan.json").read_text())
    rows = records(directory, "trajectory_rows.jsonl")
    operations = records(directory, "operations.jsonl")
    decisions = records(directory, "decisions.jsonl")
    planned = plan["planned_trajectories"]
    index = {(row["case_id"], row["arm"]): row for row in rows}
    if len(index) != len(rows) or any(
        key not in {(item["case_id"], item["arm"]) for item in planned} for key in index
    ):
        raise ValueError("duplicate or unplanned trajectory receipt")
    reference = {
        row["case_id"]: row["outcome_error"]
        for row in rows
        if row["arm"] == "fixed_check"
        and row["reached_step"] == 3
        and row["status"] == "completed"
    }
    arms, votes = {}, []
    for arm in sorted({item["arm"] for item in planned}):
        expected = [item for item in planned if item["arm"] == arm]
        observed = [row for row in rows if row["arm"] == arm]
        accepted = [row for row in observed if row["accepted"]]
        injected = [row for row in observed if row["injected_step"] is not None]
        detected = [row for row in injected if row["detected_step"] is not None]
        policy_decisions = [item for item in decisions if item["arm"] == arm]
        arm_report = {
            "planned": len(expected),
            "attempted": len(observed),
            "completed": sum(row["status"] == "completed" for row in observed),
            "failed": sum(row["status"] != "completed" for row in observed),
            "not_run": len(expected) - len(observed),
            "actual_policy_accepted": bounded_rate(accepted, "outcome_error"),
            "observed_actual_state_errors": bounded_rate(observed, "outcome_error"),
            "actual_injected_faults": len(injected),
            "not_yet_injected": sum(
                row["fault"] != "clean" and row["injected_step"] is None
                for row in observed
            ),
            "detections": len(detected),
            "detection_delays_steps": [
                row["detected_step"] - row["injected_step"] for row in detected
            ],
            "terminal_lead_steps": [4 - row["detected_step"] for row in detected],
            "unnecessary_interruptions_known_clean": sum(
                row["interrupted"] and row["outcome_error"] is False for row in observed
            ),
            "interruptions_unknown_outcome": sum(
                row["interrupted"] and row["outcome_error"] is None for row in observed
            ),
            "selections": dict(Counter(item["selection"] for item in policy_decisions)),
            "declared_optional_cost_spent": sum(
                item["declared_check_cost"]
                for item in policy_decisions
                if item["selection"] == "check"
            ),
        }
        if arm in ARMS:
            scored = [row for row in observed if row["risk"] is not None]
            coverage = []
            for threshold in (0.0, 0.1, 0.2, 0.5, 0.75, 1.0):
                selected = [
                    {"target": reference.get(row["case_id"])}
                    for row in scored
                    if row["risk"] <= threshold
                ]
                coverage.append(
                    {
                        "threshold": threshold,
                        "coverage_of_planned": len(selected) / len(expected),
                        **bounded_rate(selected, "target"),
                    }
                )
            arm_report.update(
                initial_risk_coverage=coverage,
                missing_initial_scores=len(expected) - len(scored),
                distinct_initial_scores=sorted({row["risk"] for row in scored}),
                coverage_label="paired full-three-step fixed-check reference, not interrupted-state labels",
            )
            for row in observed:
                target = reference.get(row["case_id"])
                assessment = row.get("initial_assessment")
                if type(target) is not bool or not assessment:
                    continue
                for voter, member in enumerate(assessment["members"]):
                    votes.append(
                        {
                            "trajectory_id": row["case_id"],
                            "voter_id": arm + "/" + str(voter),
                            "base_sha256": member["base_sha256"],
                            "adapter_sha256": member["adapter_sha256"],
                            "output_sha256": digest(member),
                            "vote_error": (member["score"] >= 0.5) != target,
                            "outcome_error": target,
                        }
                    )
        arms[arm] = arm_report
    cost_groups = {}
    for kind in sorted({operation["kind"] for operation in operations}):
        group = [operation for operation in operations if operation["kind"] == kind]
        cost_groups[kind] = {
            "operations": len(group),
            "failed": sum(operation["status"] != "completed" for operation in group),
            "wall_ns": sum(operation["wall_ns"] for operation in group),
            "cpu_ns": sum(operation["cpu_ns"] for operation in group),
        }
    by_scope = defaultdict(
        lambda: {"operations": 0, "failed": 0, "wall_ns": 0, "cpu_ns": 0}
    )
    for operation in operations:
        context = operation["context"]
        key = context.get("split", "shared") + "/" + context.get("arm", "shared")
        cost = by_scope[key]
        cost["operations"] += 1
        cost["failed"] += operation["status"] != "completed"
        cost["wall_ns"] += operation["wall_ns"]
        cost["cpu_ns"] += operation["cpu_ns"]
    counters = {
        key: max((operation["counters"][key] for operation in operations), default=0)
        for key in ("assessments", "forward_passes", "input_tokens")
    }
    members_by_case = defaultdict(list)
    for vote in votes:
        if vote["vote_error"]:
            members_by_case[vote["trajectory_id"]].append(vote["voter_id"])
    intervention_checks = []
    by_case = defaultdict(dict)
    for decision in decisions:
        if decision["intervention"]:
            by_case[decision["case_id"]][decision["intervention"]["name"]] = decision
    for case_id, panel in by_case.items():
        complete = set(panel) == {"risk_low", "risk_high", "cost_low", "cost_high"}
        same_evidence = (
            len({item["matched_evidence_parent_sha256"] for item in panel.values()})
            == 1
        )
        intervention_checks.append(
            {
                "case_id": case_id,
                "complete": complete,
                "matched_evidence": same_evidence,
                "risk_direction_correct": complete
                and panel["risk_low"]["selection"] == "defer"
                and panel["risk_high"]["selection"] == "check",
                "cost_direction_correct": complete
                and panel["cost_low"]["selection"] == "check"
                and panel["cost_high"]["selection"] == "defer",
                "raw_model_scores": {
                    name: item["raw_model_score"] for name, item in panel.items()
                },
            }
        )
    panels = records(directory, "panel_labels.jsonl")
    source_now = {
        path.name: file_sha(path) for path in sorted(Path(__file__).parent.glob("*.py"))
    }
    head_path = directory / "trained_readouts.json"
    heads = json.loads(head_path.read_text()) if head_path.exists() else []
    controls = control_acceptance(rows, plan["cases"]["confirmation"])
    cases_by_id = {
        case["goal"]["task_id"]: case for case in plan["cases"]["confirmation"]
    }
    host_provenance = True
    for row in rows:
        if row["status"] != "completed":
            continue
        matches = [
            op
            for op in operations
            if op["context"].get("case_id") == row["case_id"]
            and op["context"].get("arm") == row["arm"]
            and op["status"] == "completed"
        ]
        effects = [op for op in matches if op["kind"] == "host_effect"]
        labels = [op for op in matches if op["kind"] == "independent_outcome_label"]
        accepting = [
            op["result"]
            for op in matches
            if op["kind"] == "mandatory_host_check" and op["result"]["accepted"]
        ]
        host_provenance &= len(effects) == row["reached_step"] and {
            op["context"]["tick"] for op in effects
        } == set(range(1, row["reached_step"] + 1))
        host_provenance &= all(
            op["result"]["operation_id"]
            == f"{row['case_id']}/step/{op['context']['tick']}"
            and op["result"]["replayed"] is False
            for op in effects
        )
        host_provenance &= (
            len(labels) == 1 and labels[0]["result"] is row["outcome_error"]
        )
        host_provenance &= len(accepting) == int(row["accepted"])
        host_provenance &= all(
            report["verdict"] == "proved"
            and report["checked_step"] == 4
            and report["state_version"] == 3
            and report["subject_sha256"] == digest(cases_by_id[row["case_id"]]["goal"])
            for report in accepting
        )
    gates = {
        "all_planned_trajectories_completed": len(rows) == len(planned)
        and all(row["status"] == "completed" for row in rows),
        "all_uninterrupted_panels_completed": panel_bindings(panels, operations, plan),
        "live_inference_and_selected_check_provenance": inference_bindings(
            records(directory, "assessments.jsonl"), operations, rows, decisions
        ),
        "plan_bound_decisions_and_budgets": decision_bindings(
            plan, records(directory, "assessments.jsonl"), operations, rows, decisions
        ),
        "source_unchanged": source_now == plan["source_sha256"],
        "three_actual_distinct_readout_parameters": len(heads) == 3
        and len({parameter_digest(head) for head in heads}) == 3,
        "both_bases_executed": all(
            any(
                op["kind"] == "model_score"
                and op.get("model") == model
                and op["status"] == "completed"
                for op in operations
            )
            for model in ("qwen", "smol")
        ),
        "calibration_reports_complete": len(
            records(directory, "calibration_reports.jsonl")
        )
        == 14,
        "accepted_labels_all_known_and_correct": all(
            row["outcome_error"] is False for row in rows if row["accepted"]
        ),
        "positive_controls_accepted": all(
            item["positive_controls_accepted"] for item in controls.values()
        ),
        "known_wrong_controls_rejected": all(
            item["known_wrong_controls_rejected"] for item in controls.values()
        ),
        "host_effect_label_and_acceptance_provenance": host_provenance,
        "six_matched_actual_intervention_panels": len(intervention_checks) == 6
        and all(
            all(
                item[key]
                for key in (
                    "complete",
                    "matched_evidence",
                    "risk_direction_correct",
                    "cost_direction_correct",
                )
            )
            for item in intervention_checks
        ),
    }
    completed = failure is None and all(gates.values())
    metrics = sys.modules.get("verify1_pilot_frozen_metrics")
    vote_report = (
        metrics.compare_votes(votes) if metrics is not None and votes else None
    )
    preparation = directory / "asset_preparation_manifest.json"
    return {
        "status": "CONTROLLED_MODEL_PILOT_COMPLETED"
        if completed
        else "INCOMPLETE_OR_FAILED",
        "failure": failure,
        "engineering_gates": gates,
        "planned_trajectories": len(planned),
        "observed_trajectories": len(rows),
        "planned_uninterrupted_panels": 24,
        "observed_uninterrupted_panels": len(panels),
        "model_forwards": counters["forward_passes"],
        "inference_counters": counters,
        "arms": arms,
        "control_acceptance": controls,
        "distinct_readout_parameter_count": len(
            {parameter_digest(head) for head in heads}
        ),
        "calibration_reports": records(directory, "calibration_reports.jsonl"),
        "pairwise_vote_errors": vote_report,
        "common_error_clusters": dict(members_by_case),
        "actual_policy_interventions": intervention_checks,
        "cost": {
            "overall_wall_ns": wall_ns,
            "controller_cpu_ns": cpu_ns,
            "operations_by_kind": cost_groups,
            "operations_by_scope": dict(by_scope),
            "model_load_and_training_included": True,
            "physical_energy_joules": None,
            "network_wire_bytes": None,
            "provider_cost": None,
            "full_physical_cost_qualified": False,
            "source_bytes": plan.get("source_bytes"),
            "preparation_manifest": json.loads(preparation.read_text())
            if preparation.exists()
            else None,
        },
        "interpretation": {
            "scores_calibrated": False,
            "raw_scores": "YES/NO sequence likelihood normalized over two registered candidates",
            "adapters": "trained frozen-hidden logistic readouts; not LoRA or whole-model fine tuning",
            "budget_match": "two voter invocations per assessment; actual token/forward/wall cost measured, not forced equal",
            "training_opportunity_match": False,
            "risk_coverage_event": "uninterrupted goal-value error from paired full-three-step reference",
            "actual_accepted_error_event": "actual policy trajectory final stored-value mismatch",
            "information_limit": "tick and ACK only; initial inputs identical and most injected faults observationally indistinguishable",
            "source_groups_are_independent_natural_tasks": False,
            "missing_label_bounds_are_confidence_intervals": False,
            "natural_task_generalization": "HOLD",
            "trajectory_probability_certificate": "NONE",
            "production_authority": "NONE",
        },
    }
