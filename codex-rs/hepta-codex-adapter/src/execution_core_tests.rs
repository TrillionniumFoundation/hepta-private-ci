use codex_execution_core::Currentness;
use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::FinalUse;
use codex_execution_core::EXECUTION_SCHEMA_VERSION;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CodexOperationIntent;

use super::canonical_codex_intent_v1;

fn digest(value: &[u8]) -> String {
    Digest32::of_bytes(value).to_string()
}

fn fixture() -> (ExecutionBinding, CodexOperationIntent) {
    let payload = Digest32::of_bytes(b"payload");
    (
        ExecutionBinding {
            schema_version: EXECUTION_SCHEMA_VERSION,
            run_id: "run-1".into(),
            turn_id: "turn-1".into(),
            cell_id: None,
            organ_id: Some("organ-1".into()),
            operation_id: "operation:test".into(),
            principal: "agentd-1".into(),
            objective_digest: digest(b"objective"),
            policy_digest: digest(b"policy"),
            candidate_digest: digest(b"candidate"),
            host: "host-1".into(),
            generation: 3,
            idempotency_key: "idem-1".into(),
            predecessor: None,
            currentness: Currentness::Current,
            final_use: FinalUse::NotGranted,
            rollback_reference: None,
        },
        CodexOperationIntent {
            operation_id: StableId::new("operation:test").unwrap(),
            thread_id: StableId::new("thread:test").unwrap(),
            method_id: StableId::new("method:test").unwrap(),
            payload_digest: payload,
            lease_payload_digest: payload,
            deadline_ms: 100,
            app_server_binding: None,
        },
    )
}

#[test]
fn admitted_codex_operation_is_only_an_intent() {
    let (binding, operation) = fixture();
    let record = canonical_codex_intent_v1(
        binding.clone(),
        &operation,
        ExecutionClass::ReadOnlyInspection,
    )
    .unwrap();
    assert_eq!(record.binding, binding);
    assert_eq!(record.payload_digest, operation.payload_digest.to_string());
}

#[test]
fn adapter_denies_operation_rebinding_and_payload_drift() {
    let (mut binding, mut operation) = fixture();
    binding.operation_id = "another-operation".into();
    assert!(matches!(
        canonical_codex_intent_v1(binding, &operation, ExecutionClass::FileRead),
        Err(ExecutionError::Binding(_))
    ));
    let (binding, _) = fixture();
    operation.lease_payload_digest = Digest32::of_bytes(b"different");
    assert!(matches!(
        canonical_codex_intent_v1(binding, &operation, ExecutionClass::FileRead),
        Err(ExecutionError::Binding(_))
    ));
}
