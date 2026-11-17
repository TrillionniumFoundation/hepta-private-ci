"""Source-growth accounting with explicit missing evidence and paired retention.

The functions summarize supplied immutable receipts. They never authenticate
users, manufacture independent samples, or grant native adoption qualification.
"""

import copy
import math

from .circuit_readiness_v3 import provenance_groups, verified_business_row
from .circuit_study_v2 import source_growth_plan
from .composition_core import digest as circuit_digest, require, sha
from .data import digest
from .source_metrics_retention_v3 import retention_metrics as retention_metrics


SCOPES = (
    "model_inference",
    "training",
    "encoder",
    "router_kernel",
    "verification",
    "recovery",
    "network",
    "orchestration",
)
METRICS = (
    "model_calls",
    "input_tokens",
    "output_tokens",
    "optimizer_updates",
    "cpu_seconds",
    "wall_seconds",
    "energy_joules",
    "kernel_mac_equivalent",
)
COUNTS = {
    "model_calls",
    "input_tokens",
    "output_tokens",
    "optimizer_updates",
    "kernel_mac_equivalent",
}


def source_growth_metrics(
    rows, *, unit_field="project_id", updates_per_source=224, readiness=None
):
    """Allow source/budget diagnostics while withholding unsupported growth claims."""
    result = source_growth_plan(
        rows, unit_field=unit_field, updates_per_source=updates_per_source
    )
    result.update(
        schema="hepta.source-growth-plan.v3",
        records_digest=digest(rows),
        authenticated_user_evidence_count=0,
        user_population_size=None,
        independent_scientific_qualification="BLOCKED",
        time_split_authentication=None,
    )
    observations = None
    if readiness is not None:
        require(
            readiness.get("schema") == "hepta.circuit-readiness.v3"
            and readiness.get("feature_rows_digest") == circuit_digest(rows),
            "source observations use a different panel",
        )
        require(
            readiness.get("receipt_digest")
            == digest(
                {
                    key: value
                    for key, value in readiness.items()
                    if key != "receipt_digest"
                }
            ),
            "readiness receipt differs",
        )
        observations = {row["task_id"]: row for row in readiness["observations"]}
        require(
            len(observations) == len(rows)
            and set(observations) == {row["task_id"] for row in rows},
            "source observation task set differs",
        )
        result["execution_observation_binding"] = readiness["receipt_digest"]
    for setting in result["settings"]:
        setting.update(
            capability_claim_eligible=False,
            actual_executed_experience_clusters=None,
            verified_successful_experience_clusters=None,
            statistical_effective_sample_size=None,
            adoption_rate=None,
            task_success_rate=None,
            forgetting=None,
            full_system_cost=None,
        )
        setting.update(
            recorded_verifier_execution_clusters=None,
            recorded_completed_subject_call_clusters=None,
            recorded_business_success_clusters=None,
        )
        if observations is not None and "row_indices" in setting:
            chosen = [rows[index] for index in setting["row_indices"]]
            groups = provenance_groups(chosen)
            events = [
                [observations[chosen[index]["task_id"]] for index in group]
                for group in groups
            ]
            setting["recorded_verifier_execution_clusters"] = sum(
                any(row["verifier_executed_slots"] for row in group) for group in events
            )
            calls = [
                True
                if any(
                    value is not None and value > 0
                    for row in group
                    for value in row["completed_original_calls_by_slot"]
                )
                else None
                if any(
                    value is None
                    for row in group
                    for value in row["completed_original_calls_by_slot"]
                )
                else False
                for group in events
            ]
            successes = [
                True
                if any(row["successful_slots"] for row in group)
                else None
                if any(
                    row.get(
                        "successes_missing_business_evidence",
                        row.get("successes_missing_call_evidence"),
                    )
                    for row in group
                )
                else False
                for group in events
            ]
            for name, values in (
                ("recorded_completed_subject_call_clusters", calls),
                ("recorded_business_success_clusters", successes),
            ):
                setting[name] = (
                    sum(values) if all(value is not None for value in values) else None
                )
                setting[name + "_observed_positive_subtotal"] = (
                    sum(value is True for value in values)
                    if any(value is not None for value in values)
                    else None
                )
                setting[name + "_unknown_clusters"] = sum(
                    value is None for value in values
                )
            setting["execution_observation_scope"] = (
                "frozen expert first attempts; verifier execution and completed subject calls are separate from student attempted calls and statistical effective experience"
            )
    result["metric_requirements"] = {
        "effective_experience": "retain raw records and task/lineage/input clusters separately; student execution and semantic-result receipts are required; statistical effective sample size remains unknown",
        "adoption_rate": "same setting's actual candidate opportunities, frozen decisions, selected-model C use and recovery receipts; external native adoption is separate",
        "forgetting": "paired before/after on the same predeclared retention panel, with the original successful-task denominator",
        "full_system_cost": "all actual model, training, encoder, router, verifier, recovery, network and orchestration work; overlapping process accounting must be reconciled",
        "users_and_time": "declared source groups do not authenticate users or establish prospective temporal generalization",
    }
    result["receipt_digest"] = digest(result)
    return result


def upstream_cost_events(readouts):
    """Retain all paid candidate evaluations, not just selected cached rows."""
    events = []
    for readout in readouts:
        for item in readout.get("upstream_evaluations", []):
            events.append(
                {
                    "receipt_digest": item["evaluation_digest"],
                    "scope": "model_inference",
                    "cost": copy.deepcopy(item["cost"]),
                }
            )
    return events


def resource_ledger(events):
    """Deduplicate actual receipt IDs; component sums are not complete-system cost.

    Nested/overlapping process CPU must not be inferred additive across scopes.
    Wall values are explicitly sums of recorded intervals, never elapsed time.
    """
    require(type(events) is list, "cost observations must be a list")
    unique = {}
    for event in events:
        identity, scope, cost = (
            event.get("receipt_digest"),
            event.get("scope"),
            event.get("cost"),
        )
        require(
            sha(identity) and scope in SCOPES and isinstance(cost, dict),
            "bound component cost required",
        )
        projected = {"scope": scope, "cost": cost}
        require(
            identity not in unique or unique[identity] == projected,
            "conflicting cost for one execution receipt",
        )
        for key in METRICS:
            value = cost.get(key)
            if value is not None:
                require(
                    type(value) in (int, float) and math.isfinite(value) and value >= 0,
                    "invalid cost metric " + key,
                )
                require(
                    key not in COUNTS or type(value) is int,
                    "integer counter required: " + key,
                )
        unique[identity] = copy.deepcopy(projected)
    components = {}
    for scope in SCOPES:
        items = [
            (identity, item["cost"])
            for identity, item in unique.items()
            if item["scope"] == scope
        ]
        metrics = {}
        for key in METRICS:
            measured = [cost[key] for _, cost in items if cost.get(key) is not None]
            known = bool(items) and len(measured) == len(items)
            metrics[key] = {
                "recorded_sum": sum(measured) if known else None,
                "measured_subtotal": sum(measured) if measured else None,
                "measured_receipts": len(measured),
                "missing_receipts": [
                    identity for identity, cost in items if cost.get(key) is None
                ],
                "complete_for_supplied_component_receipts": known,
            }
        components[scope] = {"receipt_count": len(items), "metrics": metrics}
    return {
        "schema": "hepta.resource-ledger.v3",
        "input_digest": digest(events),
        "unique_execution_receipts": len(unique),
        "duplicate_references": len(events) - len(unique),
        "components": components,
        "receipt_bindings": unique,
        "missing_components": [
            scope for scope, value in components.items() if value["receipt_count"] == 0
        ],
        "sum_of_wall_intervals_is_elapsed_time": False,
        "cross_scope_cpu_overlap_reconciled": False,
        "full_system_cost_known": False,
        "full_system_cost": None,
        "currency_cost": None,
        "scope": "deduplicated observed component receipts; missing meters and cross-scope overlap are not zero cost",
    }


def adoption_metrics(reports):
    """Count actual experiment decisions without relabeling them native adoption."""
    require(type(reports) is list, "E6 reports must be a list")
    unique = {}
    for report in reports:
        require(
            report.get("schema") == "hepta.e6.result.v1"
            and sha(report.get("evidence_binding")),
            "bound E6 operation required",
        )
        identity = report["evidence_binding"]
        require(
            identity not in unique or unique[identity] == report,
            "conflicting E6 reports for one opportunity",
        )
        unique[identity] = copy.deepcopy(report)
    complete, adopted, used, recovered, native_claims = 0, 0, 0, 0, 0
    bindings = []
    for identity, report in unique.items():
        decision = report.get("model_decision")
        terminal = report.get("status") in ("ADOPTED", "NO_UPDATE")
        if terminal:
            require(
                report["status"] == decision
                and sha(report.get("selected_model_digest")),
                "terminal decision binding differs",
            )
            complete += 1
        selected = report.get("selected_model_digest")
        c_rows = report.get("C") or []
        require(isinstance(c_rows, list), "C use receipts must be a list")
        require(
            len({row["task_id"] for row in c_rows}) == len(c_rows),
            "duplicate C task does not create another use",
        )
        for row in c_rows:
            prediction, outcome = row["prediction"], row["outcome"]
            require(
                prediction.get("loaded_model_digest") == selected,
                "C used a different selected model",
            )
            require(
                sha(prediction.get("input_sha256"))
                and prediction["input_sha256"] == outcome.get("input_sha256"),
                "C input differs from semantic receipt",
            )
            require(
                all(
                    type(prediction.get(key)) is int and prediction[key] >= 0
                    for key in ("input_tokens", "output_tokens")
                ),
                "actual C token counts required",
            )
            verified_business_row(
                {
                    "raw_answer": prediction["answer"],
                    "success": outcome["success"],
                    "semantic_receipt": outcome,
                    "semantic_receipt_sha256": outcome["receipt_sha256"],
                }
            )
        cold = report.get("cold")
        if cold is not None:
            require(
                cold.get("selected_model_digest") == selected
                and cold.get("prediction", {}).get("loaded_model_digest") == selected,
                "cold recovery model differs",
            )
            require(
                c_rows
                and all(
                    cold["prediction"].get(key) == c_rows[-1]["prediction"].get(key)
                    for key in (
                        "input_sha256",
                        "answer",
                        "input_tokens",
                        "output_tokens",
                        "loaded_model_digest",
                    )
                ),
                "cold prediction differs from retained C use",
            )
            require(
                type(cold.get("pid")) is int
                and type(cold.get("ppid")) is int
                and cold["pid"] > 0
                and cold["ppid"] > 0
                and cold["pid"] != cold["ppid"],
                "cold process identity required",
            )
        is_adopted = terminal and decision == "ADOPTED"
        adopted += is_adopted
        used += bool(is_adopted and c_rows)
        recovered += bool(is_adopted and c_rows and cold is not None)
        native_claims += report.get("production_activation") is True
        bindings.append(
            {
                "operation_binding": identity,
                "report_digest": digest(report),
                "status": report.get("status"),
                "selected_model_digest": selected,
                "C_task_ids": [row["task_id"] for row in c_rows],
            }
        )
    count = len(unique)
    complete_panel = bool(count) and complete == count
    return {
        "schema": "hepta.adoption-metrics.v3",
        "input_digest": digest(reports),
        "opportunity_count": count,
        "completed_decisions": complete,
        "duplicate_report_references": len(reports) - count,
        "adopted_experiment_decisions": adopted,
        "experiment_adopt_decision_rate": adopted / count if complete_panel else None,
        "same_candidate_use_count": used,
        "same_candidate_use_rate": used / count if complete_panel else None,
        "same_candidate_use_and_recovery_count": recovered,
        "native_activation_claims_not_authenticated_here": native_claims,
        "native_adoption_rate": None,
        "useful_native_adoption_rate": None,
        "bindings": bindings,
        "independent_scientific_qualification": "BLOCKED",
        "scope": "experiment journal report accounting; raw owner/FinalUse/settlement authentication and cross-task capability qualification remain separate",
    }
