//! Static acceptance guards for the exact-candidate closure workflow and route.
//!
//! These tests do not claim that GitHub Actions has executed. They prevent the
//! checked-in product route, exact settlement and workflow from silently
//! weakening while the external execution receipts remain pending.

const WORKFLOW: &str = include_str!(
    "../../../../.github/workflows/hepta-intelligence-control-closure.yml"
);
const REQUIREMENT_MAP: &str = include_str!(
    "../../../../docs/modules/intelligence.control/REQUIREMENT_TEST_MAP.json"
);
const PRODUCT_ROUTE: &str = include_str!("../state_intelligence_product_loop.rs");
const LEARNING_PRODUCT_API: &str = include_str!("../intelligence_learning_product_api.rs");

#[test]
fn current_candidate_workflow_requires_source_and_merge_native_execution() {
    for required in [
        "[\"source-head\",\"base-merge\"]",
        "cargo test --locked -p codex-hepta-agentd",
        "cargo test --locked -p codex-hepta-infer-worker-host",
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
