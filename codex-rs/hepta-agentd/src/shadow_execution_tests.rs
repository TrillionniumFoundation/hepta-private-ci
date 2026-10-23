//! Compare Codex Bridge translation with the independent native admission path.
use super::*;
use codex_execution_core::{Currentness, FinalUse, EXECUTION_SCHEMA_VERSION};
use codex_hepta_types::{Digest32, StableId};

fn fixture() -> (ExecutionBinding, CodexOperationIntent) {
    let payload = Digest32::of_bytes(b"checked-bridge-payload");
    (
        ExecutionBinding {
            schema_version: EXECUTION_SCHEMA_VERSION,
            run_id: "bridge-run-1".into(),
            turn_id: "bridge-turn-1".into(),
            cell_id: None,
            organ_id: Some("bridge-organ-1".into()),
            operation_id: "bridge-operation".into(),
            principal: "agentd-1".into(),
            objective_digest: Digest32::of_bytes(b"objective").to_string(),
            policy_digest: Digest32::of_bytes(b"policy").to_string(),
            candidate_digest: Digest32::of_bytes(b"candidate").to_string(),
            host: "host-1".into(),
            generation: 3,
            idempotency_key: "bridge-idempotency-1".into(),
            predecessor: None,
            currentness: Currentness::Current,
            final_use: FinalUse::NotGranted,
            rollback_reference: None,
        },
        CodexOperationIntent {
            operation_id: StableId::new("bridge-operation").unwrap(),
            thread_id: StableId::new("bridge-thread").unwrap(),
            method_id: StableId::new("bridge-method").unwrap(),
            payload_digest: payload,
            lease_payload_digest: payload,
            deadline_ms: 100,
            app_server_binding: None,
        },
    )
}

#[test]
fn codex_bridge_and_native_entry_yield_identical_non_authorizing_intents() {
    let (binding, operation) = fixture();
    let canonical = canonical_codex_intent_v1(
        binding.clone(),
        &operation,
        ExecutionClass::ReadOnlyInspection,
    )
    .unwrap();
    let native = propose_native_shadow_execution_v1(canonical).unwrap();
    let codex = propose_shadow_execution_v1(
        binding,
        &operation,
        ExecutionClass::ReadOnlyInspection,
    )
    .unwrap();
    assert_eq!(native, codex);
}

#[test]
fn codex_bridge_does_not_bypass_native_currentness_or_final_use_rejection() {
    let (mut binding, operation) = fixture();
    binding.currentness = Currentness::Unknown;
    assert!(
        propose_shadow_execution_v1(
            binding.clone(),
            &operation,
            ExecutionClass::ReadOnlyInspection,
        )
        .is_err()
    );
    binding.currentness = Currentness::Current;
    binding.final_use = FinalUse::Verified {
        grant_digest: Digest32::of_bytes(b"claim").to_string(),
        verifier_receipt_digest: Digest32::of_bytes(b"claim-verifier").to_string(),
    };
    assert!(
        propose_shadow_execution_v1(binding, &operation, ExecutionClass::ReadOnlyInspection)
            .is_err()
    );
}

#[test]
fn codex_bridge_rejects_payload_drift_before_any_native_proposal() {
    let (binding, mut operation) = fixture();
    operation.lease_payload_digest = Digest32::of_bytes(b"other-payload");
    assert!(
        propose_shadow_execution_v1(binding, &operation, ExecutionClass::ReadOnlyInspection)
            .is_err()
    );
}
