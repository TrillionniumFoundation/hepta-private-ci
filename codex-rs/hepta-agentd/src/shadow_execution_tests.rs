//! Native route and legacy Codex route must share one non-authorizing gate.
use super::*;
use codex_execution_core::{Currentness, FinalUse, EXECUTION_SCHEMA_VERSION};

fn digest(value: u8) -> String {
    format!("{value:064x}")
}

fn native_intent() -> ExecutionIntent {
    ExecutionIntent {
        binding: ExecutionBinding {
            schema_version: EXECUTION_SCHEMA_VERSION,
            run_id: "run-native-1".into(),
            turn_id: "turn-native-1".into(),
            cell_id: Some("cell-native-1".into()),
            organ_id: None,
            operation_id: "native-op-1".into(),
            principal: "agentd-1".into(),
            objective_digest: digest(1),
            policy_digest: digest(2),
            candidate_digest: digest(3),
            host: "host-1".into(),
            generation: 1,
            idempotency_key: "native-idempotency-1".into(),
            predecessor: None,
            currentness: Currentness::Current,
            final_use: FinalUse::NotGranted,
            rollback_reference: Some("rollback-native-1".into()),
        },
        class: ExecutionClass::DurableProcess,
        payload_digest: digest(4),
    }
}

#[test]
fn native_intent_requires_no_codex_session_or_model_and_grants_no_authority() {
    let intent = native_intent();
    let candidate = propose_native_shadow_execution_v1(intent.clone()).unwrap();
    assert_eq!(candidate.intent, intent);
    assert_eq!(
        candidate.record_digest,
        ExecutionRecord::ExecutionIntent(intent).digest().unwrap()
    );
}

#[test]
fn shadow_native_route_rejects_unbounded_or_unauthorized_input() {
    let mut intent = native_intent();
    intent.binding.currentness = Currentness::Stale;
    assert!(propose_native_shadow_execution_v1(intent.clone()).is_err());
    intent.binding.currentness = Currentness::Current;
    intent.binding.final_use = FinalUse::Verified {
        grant_digest: digest(5),
        verifier_receipt_digest: digest(6),
    };
    assert!(propose_native_shadow_execution_v1(intent.clone()).is_err());
    intent.binding.final_use = FinalUse::NotGranted;
    intent.binding.predecessor = Some(digest(7));
    assert!(propose_native_shadow_execution_v1(intent.clone()).is_err());
    intent.binding.predecessor = None;
    intent.binding.rollback_reference = None;
    assert!(propose_native_shadow_execution_v1(intent).is_err());
}
