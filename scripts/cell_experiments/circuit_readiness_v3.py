"""A-only readiness and paired business effects for the cached-output selector.

This gate does not prohibit single/fixed baseline measurements. A missing
success/complementarity witness makes learned-selector capability NOT_READY;
it is not a theorem about all possible composed or interactive Circuits.
"""

import copy

from .chat_protocol import inference_messages
from .circuit_receipts_v3 import business_evidence, semantic_identity
from .circuit_receipts_v3 import completed_original_calls as completed_original_calls
from .circuit_receipts_v3 import verified_business_row as verified_business_row
from .circuit_task_bindings_v2 import _bound_features, _bound_panel
from .composition_core import digest as circuit_digest, require, sha
from .data import digest


def provenance_groups(rows):
    """Transitive task/lineage/input aliases; no statistical independence claim."""
    require(type(rows) is list and bool(rows), "nonempty provenance rows required")
    parents, seen = list(range(len(rows))), {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, row in enumerate(rows):
        for field in ("task_id", "lineage_id", "observation_digest"):
            value = row.get(field)
            require(isinstance(value, str) and bool(value), "missing " + field)
            previous = seen.setdefault((field, value), index)
            a, b = root(previous), root(index)
            if a != b:
                parents[max(a, b)] = min(a, b)
    groups = {}
    for index in range(len(rows)):
        groups.setdefault(root(index), []).append(index)
    return sorted(
        groups.values(), key=lambda group: min(rows[i]["task_id"] for i in group)
    )


def bound_panel(records, evaluations, model_digests, panel_digest):
    """Validate v3 through an explicit schema-only v2 projection, retaining raw IDs."""
    projected, projections = [], []
    for evaluation in evaluations:
        require(
            evaluation.get("schema")
            in ("hepta.repository-evaluation.v2", "hepta.repository-evaluation.v3"),
            "unsupported evaluation schema",
        )
        value = copy.deepcopy(evaluation)
        value["schema"] = "hepta.repository-evaluation.v2"
        projected.append(value)
        projections.append(
            {
                "original_digest": digest(evaluation),
                "validation_projection_digest": digest(value),
                "changed_fields": [] if value == evaluation else ["schema"],
            }
        )
    bound, upstream = _bound_panel(records, projected, model_digests, panel_digest)
    tasks = {record["task_id"]: record for record in records}
    for index, evaluation in enumerate(evaluations):
        identity = projections[index]["original_digest"]
        upstream[index]["evaluation_digest"] = identity
        upstream[index]["validation_projection"] = projections[index]
        for row in evaluation["rows"]:
            step = row["steps"][0]
            if evaluation["schema"] == "hepta.repository-evaluation.v3":
                record = tasks[row["task_id"]]
                request = {
                    "record_id": record["record_id"],
                    "task": {
                        "input": record["task"]["input"],
                        "messages": inference_messages(
                            record["task"]["input"], record["task"].get("messages")
                        ),
                    },
                }
                require(
                    type(step.get("number")) is int
                    and step.get("request_sha256") == digest(request),
                    "first-attempt request differs from frozen chat context",
                )
            count = completed_original_calls(step["verification"])
            summary = step.get("execution_summary")
            if summary is not None:
                require(
                    summary.get("verification_receipt_sha256")
                    == step["verification"]["receipt_sha256"],
                    "execution summary verification binding differs",
                )
                require(
                    summary.get("subject_call_count") == count
                    and (count is None or type(summary["subject_call_count"]) is int),
                    "completed original call count differs",
                )
                require(
                    summary.get("subject_call_count_scope")
                    == "completed_original_calls"
                    and summary.get("subject_call_attempt_count") is None,
                    "completed calls cannot be relabeled as attempted calls",
                )
            target = bound[index][row["task_id"]]
            target["evaluation_digest"] = identity
            target["completed_original_calls"] = count
            target["semantic_identity"] = semantic_identity(step["verification"])
            evidence = business_evidence(target)
            target["business_success"] = evidence["business_success"]
            if summary is not None:
                for key, metric in (
                    ("execution_performed", "verifier_executed"),
                    ("original_passed", "original_passed"),
                    (
                        "control_comparison_informative",
                        "control_comparison_informative",
                    ),
                    ("controls_rejected", "controls_rejected"),
                    ("control_count", "control_count"),
                ):
                    require(
                        key not in summary
                        or digest(summary[key]) == digest(evidence[metric]),
                        "execution summary differs from business observations",
                    )
    return bound, upstream, projections


def routing_readiness(
    a_records, evaluations, model_digests, feature_rows, *, expected_panel_digest
):
    """Return primary A labels only for real successes; failures have target null."""
    require(
        all(
            row.get("split") == "train"
            and row.get("authorization", {}).get("training_allowed") is True
            for row in a_records
        ),
        "authorized A training records required",
    )
    bound, upstream, projections = bound_panel(
        a_records, evaluations, model_digests, expected_panel_digest
    )
    features = _bound_features(a_records, feature_rows)
    groups = provenance_groups(feature_rows)
    primary_ids = {min(feature_rows[i]["task_id"] for i in group) for group in groups}
    observations, training_rows, verifier_ids = [], [], set()
    for record in a_records:
        task = record["task_id"]
        successful, missing_calls, missing_business = [], [], []
        for slot, model in enumerate(bound):
            row = model[task]
            verifier_ids.add(row["semantic_receipt"]["verifier_source_sha256"])
            count = row["completed_original_calls"]
            if row["success"] and (count is None or count == 0):
                missing_calls.append(slot)
            if row["business_success"] is None:
                missing_business.append(slot)
            if row["business_success"] is True:
                successful.append(slot)
        target = successful[0] if successful else None
        observation = {
            "task_id": task,
            "primary_cluster_row": task in primary_ids,
            "successful_slots": successful,
            "verifier_executed_slots": [
                slot for slot, model in enumerate(bound) if model[task]["executed"]
            ],
            "completed_original_calls_by_slot": [
                model[task]["completed_original_calls"] for model in bound
            ],
            "target": target,
            "successes_missing_call_evidence": missing_calls,
            "successes_missing_business_evidence": missing_business,
            "semantic_receipts": [
                model[task]["semantic_receipt_sha256"] for model in bound
            ],
        }
        observations.append(observation)
        if target is not None and task in primary_ids:
            training_rows.append({**copy.deepcopy(features[task]), "target": target})
    require(len(verifier_ids) == 1, "mixed semantic verifier versions")
    primary = [row for row in observations if row["primary_cluster_row"]]
    per_model = [
        sum(slot in row["successful_slots"] for row in primary) for slot in range(3)
    ]
    union = sum(bool(row["successful_slots"]) for row in primary)
    best = max(per_model)
    reasons = []
    if union == 0:
        reasons.append("no_verified_success_on_primary_A_clusters")
    if union <= best:
        reasons.append("no_observed_complementarity_for_single_choice_routing")
    if any(row["successes_missing_call_evidence"] for row in primary):
        reasons.append("some_success_claims_lack_completed_original_call_evidence")
    if any(row["successes_missing_business_evidence"] for row in primary):
        reasons.append("some_success_claims_lack_complete_business_observations")
    status = "READY_FOR_ROUTING_DIAGNOSTIC" if not reasons else "NOT_READY"
    receipt = {
        "schema": "hepta.circuit-readiness.v3",
        "status": status,
        "reasons": reasons,
        "panel_digest": expected_panel_digest,
        "feature_rows_digest": circuit_digest(feature_rows),
        "model_digests": list(model_digests),
        "verifier_source_sha256": next(iter(verifier_ids)),
        "observations": observations,
        "primary_task_ids": sorted(primary_ids),
        "primary_row_rule": "lexicographically first task_id per transitive task/lineage/input cluster, independent of outcomes",
        "unique_task_count": len(a_records),
        "provenance_cluster_count": len(groups),
        "statistical_effective_sample_size": None,
        "per_model_successful_primary_clusters": per_model,
        "observed_oracle_successful_primary_clusters": union,
        "best_single_successful_primary_clusters": best,
        "observed_oracle_gain_clusters": union - best,
        "supervised_rows_digest": circuit_digest(training_rows),
        "supervised_row_count": len(training_rows),
        "all_failed_label": None,
        "single_and_fixed_measurements_allowed": True,
        "learned_capability_question_ready": not reasons,
        "upstream_evaluations": upstream,
        "validation_projections": projections,
        "independent_scientific_qualification": "BLOCKED",
        "native_circuit": False,
        "scope": "A-only readiness for the existing cached first-attempt single-choice selector; not a general prerequisite for composed-agent capability",
    }
    receipt["receipt_digest"] = digest(receipt)
    return {"training_rows": training_rows, "receipt": receipt}


def ablation_metrics(readout, *, expected_readout_digest, expected_members):
    """Require paired business receipts and the predeclared Cell/edge inventory."""
    require(
        sha(expected_readout_digest) and digest(readout) == expected_readout_digest,
        "readout identity differs",
    )
    arms, missing = {}, []
    require(
        isinstance(expected_members, dict) and bool(expected_members),
        "frozen ablation inventory required",
    )
    for arm, inventory in expected_members.items():
        require(
            set(inventory) == {"cells", "edges"}
            and all(
                isinstance(names, list) and names and len(names) == len(set(names))
                for names in inventory.values()
            ),
            "nonempty unique Cell and edge inventory required",
        )
        actual = readout.get("arms", {}).get(arm)
        if actual is None:
            missing.append(arm)
            continue
        main = {row["task_id"]: row for row in actual["main"]["rows"]}
        require(len(main) == len(actual["main"]["rows"]), "duplicate main task")
        base_scores = {task: verified_business_row(row) for task, row in main.items()}
        arm_results = {}
        for kind, names in inventory.items():
            variants = actual.get("ablations", {}).get(kind, {})
            require(set(variants) <= set(names), "undeclared ablation")
            arm_results[kind] = {}
            for name in names:
                if name not in variants:
                    missing.append(f"{arm}/{kind}/{name}")
                    continue
                rows = {row["task_id"]: row for row in variants[name]["rows"]}
                require(
                    set(rows) == set(main) and len(rows) == len(variants[name]["rows"]),
                    "ablation task panel differs",
                )
                for task in rows:
                    require(
                        all(
                            rows[task].get(field) == main[task].get(field)
                            for field in ("task_digest", "source_id", "lineage_id")
                        ),
                        "ablation task provenance differs",
                    )
                    require(
                        semantic_identity(rows[task]["semantic_receipt"])
                        == semantic_identity(main[task]["semantic_receipt"]),
                        "ablation semantic task identity differs",
                    )
                scores = {
                    task: verified_business_row(row) for task, row in rows.items()
                }
                known = all(
                    value is not None
                    for value in [*base_scores.values(), *scores.values()]
                )
                lost = [
                    task
                    for task in rows
                    if base_scores[task] is True and scores[task] is False
                ]
                gained = [
                    task
                    for task in rows
                    if base_scores[task] is False and scores[task] is True
                ]
                arm_results[kind][name] = {
                    "unique_task_count": len(rows),
                    "business_outcomes_complete": known,
                    "tasks_lost": lost,
                    "tasks_gained": gained,
                    "success_count_change": len(gained) - len(lost) if known else None,
                    "routing_changes": sum(
                        rows[task]["model_digest"] != main[task]["model_digest"]
                        for task in rows
                    ),
                    "independent_sample_increment": 0,
                }
        arms[arm] = arm_results
    return {
        "schema": "hepta.ablation-metrics.v3",
        "readout_digest": expected_readout_digest,
        "expected_members_digest": digest(expected_members),
        "arms": arms,
        "missing_ablations": missing,
        "declared_ablations_complete": not missing,
        "online_composed_execution_performed": readout.get(
            "online_routed_execution_performed"
        )
        is True,
        "capability_qualification": "BLOCKED",
        "scope": "paired retained business outcomes; logits and routing changes alone are not task capability",
    }
