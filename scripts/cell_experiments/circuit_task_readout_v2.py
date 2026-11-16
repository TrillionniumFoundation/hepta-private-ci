"""Join frozen routes to already executed repository outcomes, without new calls.

Slot order and the A-only label rule are fixed before reading outcomes. This is
an offline readout of cached first attempts, not an online Circuit deployment.
All three candidate evaluations were actually paid for; choosing a cached row
does not retroactively turn that cost into one candidate call.

Repository receipts use UTF-8 data.digest; frozen Circuit artifacts retain
composition_core.digest and its escaped-ASCII canonical serialization.
"""

import copy

from .composition_core import ARMS, digest as circuit_digest, require, sha
from .data import digest as receipt_digest
from .circuit_task_bindings_v2 import MODEL_ORDER, _bound_features, _bound_panel


LABEL_RULE = {
    "successful_slot_priority": [0, 1, 2],
    "all_failed_fallback_slot": 2,
    "uses": "A first-attempt semantic execution only",
}


def routing_targets(
    a_records,
    evaluations_by_model_order,
    expected_model_digests,
    feature_rows,
    *,
    expected_panel_digest,
):
    """Label only A by observed first-attempt success; all failed means slot 2."""
    require(
        all(
            record.get("split") == "train"
            and record.get("authorization", {}).get("training_allowed") is True
            for record in a_records
        ),
        "routing targets require authorized A training tasks only",
    )
    bound, upstream = _bound_panel(
        a_records,
        evaluations_by_model_order,
        expected_model_digests,
        expected_panel_digest,
    )
    features = _bound_features(a_records, feature_rows)
    rows, observations = [], []
    for record in a_records:
        task = record["task_id"]
        successes = [
            slot
            for slot in LABEL_RULE["successful_slot_priority"]
            if bound[slot][task]["success"]
        ]
        target = successes[0] if successes else LABEL_RULE["all_failed_fallback_slot"]
        rows.append({**copy.deepcopy(features[task]), "target": target})
        observations.append(
            {
                "task_id": task,
                "successful_slots": successes,
                "target": target,
                "all_failed_fallback": not successes,
                "semantic_receipts": [
                    model[task]["semantic_receipt_sha256"] for model in bound
                ],
            }
        )
    receipt = {
        "schema": "hepta.routing-targets.v2",
        "panel_digest": expected_panel_digest,
        "feature_rows_digest": circuit_digest(feature_rows),
        "rows_digest": circuit_digest(rows),
        "model_order": list(MODEL_ORDER),
        "model_digests": list(expected_model_digests),
        "label_rule": LABEL_RULE,
        "label_rule_digest": receipt_digest(LABEL_RULE),
        "observations": observations,
        "observed_first_attempt_oracle_ceiling": sum(
            bool(row["successful_slots"]) for row in observations
        )
        / len(observations),
        "oracle_scope": "best of the three already observed first attempts; not a deployable policy or model capability bound",
        "upstream_evaluations": upstream,
        "external_teacher_count": 0,
        "independent_sample_increment": 0,
    }
    return {"rows": rows, "receipt": receipt}


def _route(predictions, bound, feature_rows):
    require(
        predictions.get("input_digest") == circuit_digest(feature_rows),
        "route input panel differs",
    )
    rows = predictions.get("rows")
    expected = {row["task_id"] for row in feature_rows}
    require(
        type(rows) is list
        and len(rows) == len(expected)
        and {row["task_id"] for row in rows} == expected,
        "route task set differs",
    )
    selected = []
    for row in rows:
        slot = row.get("prediction")
        require(
            type(slot) is int and 0 <= slot < 3, "route must choose a frozen model slot"
        )
        selected.append(copy.deepcopy(bound[slot][row["task_id"]]))
    return {
        "prediction_receipt_digest": circuit_digest(predictions),
        "rows": selected,
        "business_successes": sum(row["success"] for row in selected),
        "business_success_rate": sum(row["success"] for row in selected)
        / len(selected),
        "selected_cached_input_tokens": sum(row["input_tokens"] for row in selected),
        "selected_cached_output_tokens": sum(row["output_tokens"] for row in selected),
        "additional_model_calls": 0,
        "additional_verifier_calls": 0,
        "online_routed_execution_performed": False,
        "scope": "offline reuse of actual first-attempt function-contract executions; no full repository integration",
    }


def _capacity(evidence, expected_models):
    if evidence is None:
        return {
            "provided": False,
            "matched_trainable_adapter_parameters": None,
            "matched_rank4": None,
        }
    require(
        type(evidence) in (list, tuple) and len(evidence) == 3,
        "three model training/plan bindings required",
    )
    parameters, parents, ranks, bindings = [], [], [], []
    for item, expected in zip(evidence, expected_models):
        training, plan = item["training"], item["plan"]
        require(
            training.get("status") == "COMPLETE"
            and training.get("candidate_model_digest") == expected
            and training.get("plan_digest") == receipt_digest(plan),
            "capacity training binding differs",
        )
        require(
            type(training.get("trainable_parameters")) is int
            and training["trainable_parameters"] > 0
            and sha(training.get("parent_model_digest")),
            "actual adapter parameter evidence required",
        )
        parameters.append(training["trainable_parameters"])
        parents.append(training["parent_model_digest"])
        ranks.append(plan["training"]["rank"])
        bindings.append(
            {
                "training_digest": receipt_digest(training),
                "plan_digest": receipt_digest(plan),
            }
        )
    require(
        len(set(parameters)) == len(set(parents)) == 1 and ranks == [4, 4, 4],
        "chosen model capacities are not matched rank4 on one parent",
    )
    return {
        "provided": True,
        "matched_trainable_adapter_parameters": True,
        "matched_rank4": True,
        "trainable_adapter_parameters_per_model": parameters[0],
        "parent_model_digest": parents[0],
        "bindings": bindings,
        "scope": "frozen plans and actual training receipts; no independent hardware audit",
    }


def readout(
    report,
    evaluations_by_model_order,
    expected_model_digests,
    records,
    feature_rows,
    *,
    expected_panel_digest,
    capacity_evidence=None,
):
    """Resolve every frozen main/ablation route to its original execution receipt."""
    bound, upstream = _bound_panel(
        records,
        evaluations_by_model_order,
        expected_model_digests,
        expected_panel_digest,
    )
    _bound_features(records, feature_rows)
    require(
        type(report.get("arms")) is dict
        and bool(report["arms"])
        and set(report["arms"]) <= set(ARMS),
        "actual arm predictions required",
    )
    if "c_input_digest" in report:
        require(
            report["c_input_digest"] == circuit_digest(feature_rows),
            "confirmation feature panel differs",
        )
    arms, reuse = {}, 0
    for arm, value in report["arms"].items():
        main = value.get("main", value)
        routed = {"main": _route(main, bound, feature_rows), "ablations": {}}
        reuse += len(feature_rows)
        for kind, variants in value.get("ablations", {}).items():
            require(kind in ("cells", "edges"), "unknown ablation type")
            routed["ablations"][kind] = {
                name: _route(predictions, bound, feature_rows)
                for name, predictions in variants.items()
            }
            reuse += len(variants) * len(feature_rows)
        arms[arm] = routed
    selected = report.get("selected_arm")
    require(selected is None or selected in arms, "selected arm missing")
    ceiling = sum(
        any(model[record["task_id"]]["success"] for model in bound)
        for record in records
    ) / len(records)
    return {
        "schema": "hepta.circuit-task-readout.v2",
        "routing_report_digest": circuit_digest(report),
        "panel_digest": expected_panel_digest,
        "feature_rows_digest": circuit_digest(feature_rows),
        "model_order": list(MODEL_ORDER),
        "model_digests": list(expected_model_digests),
        "arms": arms,
        "selected_arm": selected,
        "selection_changed": False,
        "observed_first_attempt_oracle_ceiling": ceiling,
        "unique_tasks": len(records),
        "cached_row_uses": reuse,
        "independent_sample_increment": 0,
        "upstream_evaluations": upstream,
        "upstream_cost": {
            "model_calls": sum(item["cost"]["model_calls"] for item in upstream),
            "input_tokens": sum(item["cost"]["input_tokens"] for item in upstream),
            "output_tokens": sum(item["cost"]["output_tokens"] for item in upstream),
            "sum_evaluation_wall_seconds_not_elapsed": sum(
                item["cost"]["wall_seconds"] for item in upstream
            ),
            "sum_evaluation_parent_cpu_seconds": sum(
                item["cost"]["cpu_seconds"] for item in upstream
            ),
            "complete": False,
            "excludes": "encoder, training, router computation, verifier subprocess CPU, networking and energy",
        },
        "model_capacity": _capacity(capacity_evidence, expected_model_digests),
        "matched_full_system_cost": False,
        "online_routed_execution_performed": False,
        "full_repository_integration": False,
        "independent_scientific_qualification": "BLOCKED",
        "interpretation": "routed business success uses the exact selected cached semantic result, not classifier correctness; all upstream candidate executions retain their actual cost",
    }
