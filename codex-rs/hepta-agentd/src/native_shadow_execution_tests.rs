//! The native entrypoint must not require a Codex session or carry authority.
use super::*;
use codex_execution_core::{
    Currentness, ExecutionBinding, ExecutionClass, FinalUse, EXECUTION_SCHEMA_VERSION,
};

fn digest(value: u8) -> String {
    format!("{value:064x}")
}

fn native_intent() -> ExecutionIntent {
    ExecutionIntent {
        binding: ExecutionBinding {
            schema_version: EXECUTION_SCHEMA_VERSION,
            run_id: "native-run-1".into(),
            turn_id: "native-turn-1".into(),
            cell_id: Some("native-cell-1".into()),
            organ_id: None,
            operation_id: "native-op-1".into(),
            principal: "native-agentd-1".into(),
            objective_digest: digest(1),
            policy_digest: digest(2),
            candidate_digest: digest(3),
            host: "host-1".into(),
            generation: 1,
            idempotency_key: "native-idempotency-1".into(),
            predecessor: None,
            currentness: Currentness::Current,
            final_use: FinalUse::NotGranted,
            rollback_reference: Some("native-rollback-1".into()),
        },
        class: ExecutionClass::DurableProcess,
        payload_digest: digest(4),
    }
}

#[test]
fn native_proposal_has_canonical_record_identity_without_codex_types() {
    let intent = native_intent();
    let candidate = propose_native_shadow_execution_v1(intent.clone()).unwrap();
    assert_eq!(candidate.intent, intent);
    assert_eq!(
        candidate.record_digest,
        ExecutionRecord::ExecutionIntent(intent).digest().unwrap()
    );
}

#[test]
fn rejects_stale_generation_and_verified_or_injected_grants() {
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
    assert!(propose_native_shadow_execution_v1(intent).is_err());
}

#[test]
fn rejects_missing_rollback_and_invalid_canonical_identities() {
    let mut intent = native_intent();
    intent.binding.rollback_reference = None;
    assert!(propose_native_shadow_execution_v1(intent.clone()).is_err());

    intent.binding.rollback_reference = Some("native-rollback-1".into());
    intent.binding.operation_id.clear();
    assert!(propose_native_shadow_execution_v1(intent.clone()).is_err());

    intent.binding.operation_id = "native-op-1".into();
    intent.payload_digest = "incomplete".into();
    assert!(propose_native_shadow_execution_v1(intent).is_err());
}
