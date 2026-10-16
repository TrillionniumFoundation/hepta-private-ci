use codex_hepta_types::ExecutionPortIntentErrorV1;
use codex_hepta_types::ExecutionPortIntentV1;

use super::*;

fn port(intent: &CodexOperationIntent) -> ExecutionPortIntentV1<'_> {
    let binding = intent.app_server_binding.as_ref().unwrap();
    ExecutionPortIntentV1 {
        operation_id: &intent.operation_id,
        source_admission_digest: binding.source_admission_digest,
        generation: binding.agent_generation,
        payload_digest: intent.payload_digest,
        lease_payload_digest: intent.lease_payload_digest,
        deadline_ms: intent.deadline_ms,
    }
}

#[test]
fn port_preparation_preserves_existing_codex_receipt_and_has_no_authority() {
    let codex = tests::product_intent();
    let port = port(&codex);
    let observed = adapt_execution_port_request_v1(1, &port, codex.clone()).unwrap();
    assert_eq!(observed, adapt_request(1, codex).unwrap());
    assert_eq!(observed.status, AdapterStatus::Indeterminate);
    assert_eq!(observed.retry_posture, RetryPosture::ReconcileSameOperation);
    assert_eq!(observed.authority, AuthorityPosture::DENY_ALL);
    assert!(!observed.model_authority);
    assert!(!observed.provider_authority);
    assert!(observed.response_digest.is_none());
}

#[test]
fn all_execution_port_identity_drift_is_rejected() {
    let codex = tests::product_intent();
    let port = port(&codex);

    let mut drift = codex.clone();
    drift.operation_id = StableId::new("operation:other").unwrap();
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch("operation"))
    );

    let mut drift = codex.clone();
    drift
        .app_server_binding
        .as_mut()
        .unwrap()
        .source_admission_digest = Digest32::of_bytes(b"other-owner");
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch(
            "source admission"
        ))
    );

    let mut drift = codex.clone();
    drift.app_server_binding.as_mut().unwrap().agent_generation =
        Generation::new(8).unwrap();
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch("generation"))
    );

    let mut drift = codex.clone();
    drift.payload_digest = Digest32::of_bytes(b"other-payload");
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch("payload"))
    );

    let mut drift = codex.clone();
    drift.lease_payload_digest = Digest32::of_bytes(b"other-lease-payload");
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch("lease payload"))
    );

    let mut drift = codex.clone();
    drift.deadline_ms += 1;
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, drift),
        Err(ExecutionPortAdapterErrorV1::BindingMismatch("deadline"))
    );
}

#[test]
fn port_rejects_unbound_or_non_turn_codex_before_admission() {
    let codex = tests::product_intent();
    let port = port(&codex);

    let mut no_binding = codex.clone();
    no_binding.app_server_binding = None;
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, no_binding),
        Err(ExecutionPortAdapterErrorV1::ProductBindingRequired)
    );

    let mut wrong_operation = codex.clone();
    wrong_operation.method_id = StableId::new("method:tool").unwrap();
    assert_eq!(
        adapt_execution_port_request_v1(1, &port, wrong_operation),
        Err(ExecutionPortAdapterErrorV1::UnsupportedOperation)
    );
}

#[test]
fn expired_or_invalid_port_cannot_be_prepared_even_if_codex_is_valid() {
    let codex = tests::product_intent();
    let port = port(&codex);
    assert_eq!(
        adapt_execution_port_request_v1(port.deadline_ms, &port, codex.clone()),
        Err(ExecutionPortAdapterErrorV1::InvalidIntent(
            ExecutionPortIntentErrorV1::DeadlineExpired
        ))
    );

    let mut missing_source = port;
    missing_source.source_admission_digest = Digest32::ZERO;
    assert_eq!(
        adapt_execution_port_request_v1(1, &missing_source, codex.clone()),
        Err(ExecutionPortAdapterErrorV1::InvalidIntent(
            ExecutionPortIntentErrorV1::EmptyDigest("source admission")
        ))
    );

    let mut mismatched_lease = port;
    mismatched_lease.lease_payload_digest = Digest32::of_bytes(b"invalid-lease");
    assert_eq!(
        adapt_execution_port_request_v1(1, &mismatched_lease, codex),
        Err(ExecutionPortAdapterErrorV1::InvalidIntent(
            ExecutionPortIntentErrorV1::PayloadBindingMismatch
        ))
    );
}
