//! Static acceptance guards for the exact-candidate closure workflow.
//!
//! These tests do not claim that GitHub Actions has executed. They prevent the
//! checked-in workflow and tracked claim boundary from silently dropping the
//! source-head/base-merge native gates that must produce that evidence.

const WORKFLOW: &str = include_str!(
    "../../../../.github/workflows/hepta-intelligence-control-closure.yml"
);
const REQUIREMENT_MAP: &str = include_str!(
    "../../../../docs/modules/intelligence.control/REQUIREMENT_TEST_MAP.json"
);

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
