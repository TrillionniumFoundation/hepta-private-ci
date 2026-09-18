use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn intent() -> CodexOperationIntent {
    CodexOperationIntent {
        operation_id: id("operation:1"),
        thread_id: id("thread:1"),
        method_id: id("method:1"),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        deadline_ms: 2_000,
    }
}

#[test]
fn exact_terminal_observation_maps_without_authority() {
    let observation = AppServerObservation {
        terminal_observed: true,
        response_digest: digest(b"response"),
    };
    let Ok(receipt) = adapt(1_000, intent(), Some(observation)) else {
        panic!("terminal observation must succeed");
    };
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn missing_observation_is_indeterminate() {
    let Ok(receipt) = adapt(1_000, intent(), None) else {
        panic!("unknown outcome must be represented");
    };
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.response_digest, None);
}

#[test]
fn payload_drift_is_rejected() {
    let mut value = intent();
    value.lease_payload_digest = digest(b"other");
    assert_eq!(
        adapt(1_000, value, None),
        Err(Error::PayloadBindingMismatch)
    );
}

#[test]
fn exact_prompt_delivery_observation_binds_submitted_bytes() {
    let payload = b"compiled-provider-request";
    let input = PromptDeliveryBoundaryInputV1 {
        compilation_id: id("compilation:1"),
        expected_payload_digest: digest(payload),
        terminal_observed: true,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: vec![4, 5, 6],
        truncation_observed: false,
    };
    let observation =
        observe_prompt_delivery_v1(input, payload).expect("exact submitted payload is observed");
    assert_eq!(observation.provider_request_digest, digest(payload));
    assert!(observation.delivered);
    observation.validate().expect("valid observation");
    assert!(
        !observation
            .semantic_digest()
            .expect("valid semantic digest")
            .is_zero()
    );
}

#[test]
fn prompt_delivery_rejects_payload_drift_and_nonterminal_claims() {
    let payload = b"compiled-provider-request";
    let base = PromptDeliveryBoundaryInputV1 {
        compilation_id: id("compilation:1"),
        expected_payload_digest: digest(payload),
        terminal_observed: true,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: Vec::new(),
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_v1(base.clone(), b"different"),
        Err(Error::PayloadBindingMismatch)
    );

    let mut nonterminal = base;
    nonterminal.terminal_observed = false;
    assert_eq!(
        observe_prompt_delivery_v1(nonterminal, payload),
        Err(Error::PromptDeliveryNotTerminal)
    );
}

#[test]
fn prompt_delivery_rejection_and_positions_fail_closed() {
    let payload = b"compiled-provider-request";
    let invalid_rejection = PromptDeliveryBoundaryInputV1 {
        compilation_id: id("compilation:1"),
        expected_payload_digest: digest(payload),
        terminal_observed: true,
        delivered: false,
        rejected_reason: None,
        observed_token_positions: Vec::new(),
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_v1(invalid_rejection, payload),
        Err(Error::InvalidPromptDeliveryDisposition)
    );

    let noncanonical_positions = PromptDeliveryBoundaryInputV1 {
        compilation_id: id("compilation:1"),
        expected_payload_digest: digest(payload),
        terminal_observed: true,
        delivered: false,
        rejected_reason: Some(PromptDeliveryRejectionV1::ProviderRejected),
        observed_token_positions: vec![8, 8],
        truncation_observed: true,
    };
    assert_eq!(
        observe_prompt_delivery_v1(noncanonical_positions, payload),
        Err(Error::NonCanonicalTokenPositions)
    );
}
