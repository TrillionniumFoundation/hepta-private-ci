//! Static acceptance guards for the exact-candidate closure workflow and route.
//!
//! These tests do not claim that GitHub Actions has executed. They prevent the
//! checked-in product route, exact settlement and workflow from silently
//! weakening while the external execution receipts remain pending.

const WORKFLOW: &str = include_str!(
    "../../../../.github/workflows/hepta-intelligence-control-closure.yml"
);
const PORTABILITY_WORKFLOW: &str = include_str!(
    "../../../../.github/workflows/hepta-intelligence-control-portability.yml"
);
const REQUIREMENT_MAP: &str = include_str!(
    "../../../../docs/modules/intelligence.control/REQUIREMENT_TEST_MAP.json"
);
const STATUS_ENTRYPOINT: &str =
    include_str!("../../../../scripts/hepta-intelligence-control-status.py");
const PRODUCT_ROUTE: &str = include_str!("../state_intelligence_product_loop.rs");
const OBJECTIVE_ROUTE: &str = include_str!("../objective_runtime.rs");
const PRODUCT_CONTINUATION: &str = include_str!(
    "../../../hepta-infer-worker-host/src/canonical_intelligence_product_loop_base.rs"
);
const LEARNING_PRODUCT_API: &str = include_str!("../intelligence_learning_product_api.rs");
const RUNTIME_PROFILE_GATE: &str = include_str!("../runtime.rs");
const PRODUCT_PROFILE: &str = include_str!("../intelligence_product_profile.rs");
const OWNER_PORTS: &str = include_str!("../intelligence_product_ports.rs");
const STAGE_BOUND_PORTS: &str = include_str!("../intelligence_stage_bound_ports.rs");
const PROMPT_BINDING: &str = include_str!("../intelligence_prompt_binding.rs");
const PRODUCT_BASE: &str = include_str!("../intelligence_product_base.rs");
const RUNNER_WRAPPER: &str = include_str!("../intelligence_product_runner.rs");
const RUNNER_BASE: &str = include_str!("../intelligence_product_runner_base.rs");

#[test]
fn current_candidate_workflow_requires_source_and_merge_native_execution() {
    for required in [
        "[\"source-head\",\"base-merge\"]",
        "cargo test --locked -p codex-hepta-agentd",
        "cargo test --locked -p codex-hepta-infer-worker-host",
        "cargo test --locked -p codex-hepta-operations",
        "cargo test --locked -p codex-hepta-ndu",
        "-p codex-hepta-ndu --all-targets",
        "cargo check --locked",
        "cargo clippy --locked",
        "/usr/bin/time -v",
        "TESTED_SHA",
        "executionStatus\": \"passed",
    ] {
        assert!(
            WORKFLOW.contains(required),
            "closure workflow omitted required gate: {required}"
        );
    }
}

#[test]
fn portability_workflow_executes_private_state_and_dependency_boundaries() {
    for required in [
        "runs-on: macos-15",
        "signed_evaluation_completes_existing_owner_preparation_and_run_admission",
        "signed_input_cannot_install_host_trust_or_change_actual_context",
        "guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen",
        "authority_read_rejects_parent_leaf_links_and_oversize",
        "cargo clippy --locked -p codex-hepta-ndu --all-targets -- -D warnings",
        "SOURCE_SHA",
    ] {
        assert!(
            PORTABILITY_WORKFLOW.contains(required),
            "portability workflow omitted required gate: {required}"
        );
    }
}

#[test]
fn tracked_claim_boundary_remains_fail_closed() {
    for required in [
        "\"sourcePresenceIsExecutionEvidence\": false",
        "\"queuedOrSkippedCountsAsPassed\": false",
        "\"realProcessE2EProved\": false",
        "\"targetHostQualified\": false",
        "\"activation\": false",
        "\"release\": false",
        "\"phase\": \"B\"",
        "\"phase\": \"D\"",
        "INT-B-POST-TERMINAL-RECONCILIATION",
    ] {
        assert!(
            REQUIREMENT_MAP.contains(required),
            "tracked closure claims were widened or a phase disappeared: {required}"
        );
    }
}

#[test]
fn canonical_product_route_requires_continuation_before_admission() {
    let continuation = PRODUCT_ROUTE
        .find("product_continuation()")
        .expect("product continuation lookup");
    let admission = PRODUCT_ROUTE
        .find("start_canonical_intelligence(record)")
        .expect("canonical admission call");
    assert!(
        continuation < admission,
        "source-only provider must be rejected before canonical preparation/admission"
    );
    assert!(
        PRODUCT_ROUTE[..admission].contains("None => return Ok(None)"),
        "missing continuation must fall back to compatibility before admission"
    );
    for required in [
        "validate_intelligence_product_profile(&config)?",
        "provider.product_continuation().is_some()",
        "source-only runner/provider composition is not a product capability",
        "canonical intelligence product profile is partially configured",
    ] {
        assert!(
            RUNTIME_PROFILE_GATE.contains(required),
            "runtime product-profile gate omitted: {required}"
        );
    }
}

#[test]
fn post_terminal_failures_are_reconciliation_required_not_redispatchable_errors() {
    for required in [
        "matching_terminal_receipt",
        "reconciliation_required_receipt",
        "AgentdIntelligenceProductLoopDispositionV1::ReconciliationRequired",
        "physical_terminal_digest: Some(physical_terminal_digest)",
    ] {
        assert!(
            PRODUCT_CONTINUATION.contains(required),
            "post-terminal continuation omitted reconciliation guard: {required}"
        );
    }
    assert!(
        OBJECTIVE_ROUTE.contains("canonical_reconciliation_required"),
        "ObjectiveStart must expose post-terminal reconciliation as a distinct state"
    );
}

#[test]
fn canonical_stage_semantics_bind_real_owner_results() {
    for required in [
        "objective legal candidate binding",
        "validate_utility_universe",
        "intuition bypassed utility infeasibility",
        "prompt_conditioned_state_digest_v1",
        "owner-backed prompt delivery",
        "owner-backed context delivery",
    ] {
        assert!(
            OWNER_PORTS.contains(required),
            "owner-bound product path omitted semantic guard: {required}"
        );
    }
    for required in [
        "context_stage_digest_v1",
        "context intuition predecessor substitution",
        "candidate_set_digest",
        "selected_candidate",
    ] {
        assert!(
            STAGE_BOUND_PORTS.contains(required),
            "final stage binding omitted: {required}"
        );
    }
    assert!(
        RUNNER_WRAPPER.contains(
            "StageBoundAgentdOwnerPortsV1 as AgentdOwnerPortsV1"
        ),
        "the semantic wrapper must be the active runner port type"
    );
}

#[test]
fn prompt_payload_and_context_attachment_are_frozen_in_prepared_run() {
    for required in [
        "PreparedPromptDeliveryV1",
        "AgentdIntelligencePhysicalPromptV1",
        "pub fn physical_prompt",
        "owner-backed prompt delivery",
    ] {
        assert!(
            PRODUCT_BASE.contains(required),
            "prepared intelligence run omitted Prompt delivery binding: {required}"
        );
    }
    for required in [
        "serialized_payload.is_empty()",
        "payload_digest",
        "context_attachment_digest",
        "prompt_stage_digest",
        "prompt realization membership",
    ] {
        assert!(
            PROMPT_BINDING.contains(required),
            "Prompt delivery validation omitted: {required}"
        );
    }
}

#[test]
fn canonical_profile_requires_external_rollback_witness_and_independent_watchdog() {
    assert!(
        PRODUCT_PROFILE.contains("runner.canonical_profile_ready()"),
        "canonical profile must reject a runner without an independent rollback witness"
    );
    for required in [
        "with_authority_rollback_guard",
        "canonical_profile_ready",
        "WorkerCompletionV1::supervise",
        "spawn_owner_work_with_budget",
    ] {
        assert!(
            RUNNER_BASE.contains(required),
            "runner omitted required currentness/supervision guard: {required}"
        );
    }
}

#[test]
fn exact_operation_settlement_never_dispatches_an_arbitrary_queue_head() {
    assert!(
        LEARNING_PRODUCT_API.contains(".claim_operation("),
        "interactive settlement must use kernel.operations exact claim"
    );
    let start = LEARNING_PRODUCT_API
        .find("pub async fn settle_operation_current")
        .expect("settlement function");
    let end = LEARNING_PRODUCT_API[start..]
        .find("\nfn apply_payload_current")
        .map(|offset| start + offset)
        .expect("settlement function end");
    let settlement = &LEARNING_PRODUCT_API[start..end];
    assert!(
        !settlement.contains("dispatch_next_current()"),
        "settlement must not spend work on the arbitrary queue head"
    );
    assert!(
        !settlement.contains("reconcile_unsettled_current("),
        "settlement must not reconcile unrelated operations"
    );
    assert!(
        settlement.contains("dispatch_operation_current(scope_id, operation_id)")
            && settlement.contains("reconcile_operation_current(scope_id, operation_id)"),
        "settlement must stay bound to the requested operation"
    );
}

#[test]
fn generated_truth_reads_active_split_implementation_files() {
    for required in [
        "ACTIVE_SOURCE_FILES",
        "intelligence_product_runner_base.rs",
        "intelligence_product_base.rs",
        "intelligence_learning_base.rs",
        "intelligence_invocation_supervisor.rs",
    ] {
        assert!(
            STATUS_ENTRYPOINT.contains(required),
            "generated truth entrypoint omitted active split source: {required}"
        );
    }
}
