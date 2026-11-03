"""The executed harness topology is not a common production owner boundary.

These are implementation facts of this driver, not caller-provided attestations.
Model identity, matching tasks, or an equal runtime revision cannot turn this
qualification topology into a product total-cost experiment.
"""

COST_SCOPES = ("execution-observation", "product-total")
LANES = ("app-server", "facade", "native")

MISSING_SHARED_PRODUCT_COMPONENTS = (
    "Agentd signed Objective admission and current run/generation fence",
    "Canonical product context compilation and source-cut validation",
    "Original production writer lease, operation journal and outbox settlement",
    "Existing external FinalUse issuer, one-shot claim and physical-entry revalidation",
    "Product ext/queue admission, original-input confirmation and recovery CAS",
    "End-to-end production restart/reconciliation and final durable owner receipt",
)


def lane_owner_boundary(lane):
    if lane not in LANES:
        raise ValueError("unknown executed owner lane")
    codex = lane != "native"
    return {
        "schema": "hepta.qualification-owner-boundary.v1",
        "lane": lane,
        "classification": "qualification_harness_stack",
        "qualification_owner": {
            "implementation": "hepta_native_qualification::owner::SessionOwner",
            "role": "tool sessions" if codex else "whole native turn",
            "session_scope": "hepta.qualification.turn-owner.v2",
            "owner_instances": "one durable session per turn",
            "handle_lifetime": "reopened for each tool request" if codex else "held across the native loop",
            "checkpoint": "private hashed file chain with fsync",
            "production_admission_authority": False,
        },
        "codex_core_owner": {
            "present": codex,
            "entry": "thread/start then turn/start" if codex else None,
            "persistent_thread_requested": codex,
            "additional_to_qualification_owner": codex,
        },
        "ui_delivery": {
            "native_event_sink": None if codex else "QualificationUiSink",
            "codex_notifications_consumed": codex,
            "required_collector_contract": "hepta.qualification.streamed-ui.v1",
            "required_actual_deltas_and_same_item_completion": True,
            "capability_result_source": "per-attempt ui_observation and task outcome",
            "codex_core_event_path": codex,
            "production_core_ui_parity_established": False,
        },
        "hepta_production_writer": False,
        "hepta_final_use_authority": False,
        "hepta_product_queue_and_run_owner": False,
        "common_host_owner_evidence": None,
        "missing_product_cost_components": list(MISSING_SHARED_PRODUCT_COMPONENTS)
            + ([] if codex else [
                "Core turn reservation, canonical ThreadStore/history and final item publication",
                "Core-bound streamed UI delivery and task-currentness checks",
            ]),
        "product_total_cost": None,
        "execution_layer_causal_attribution": False,
    }


def matrix_owner_boundary(lanes):
    lanes = list(lanes)
    if not lanes or len(set(lanes)) != len(lanes):
        raise ValueError("unique executed owner lanes are required")
    return {
        "schema": "hepta.qualification-owner-matrix.v1",
        "lanes": {lane: lane_owner_boundary(lane) for lane in lanes},
        "common_host_owner_boundary_established": False,
        "common_host_owner_evidence": None,
        "required_product_owner_components": list(MISSING_SHARED_PRODUCT_COMPONENTS),
        "product_total_cost_gate": {
            "status": "held",
            "reason": "This executable matrix has no adapter through one common actual product owner boundary.",
            "model_identity_or_task_success_can_satisfy_owner_gate": False,
            "thin_session_owner_alignment_can_satisfy_owner_gate": False,
        },
        "product_total_cost": None,
        "execution_layer_causal_attribution": False,
    }


def require_cost_scope(scope, lanes):
    if scope not in COST_SCOPES:
        raise ValueError("explicit known cost scope required")
    boundary = matrix_owner_boundary(lanes)
    if scope == "product-total":
        # No flag, model evidence JSON, or fixture-owner receipt may promote
        # this driver. A future product harness needs actual common-owner
        # admission/settlement evidence and complete cost coverage first.
        raise ValueError(
            "product-total requires a genuinely common product owner boundary; "
            "this SessionOwner/Codex-owner qualification matrix cannot provide it")
    return boundary


def cost_claim_fields(lane=None):
    return {
        "owner_boundary": lane_owner_boundary(lane) if lane else None,
        "cost_scope": "execution-observation",
        "product_total_cost": None,
        "execution_layer_causal_attribution": False,
    }
