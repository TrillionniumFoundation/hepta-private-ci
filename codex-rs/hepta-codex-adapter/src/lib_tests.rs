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
fn prompt_delivery_v1_requires_exact_terminal_provider_request() {
    let intent = intent();
    let observation = PromptProviderTerminalObservationV1 {
        terminal_observed: true,
        observed_provider_request_digest: intent.payload_digest,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: Some(vec![0, 3, 7]),
        truncation_observed: false,
    };
    let value = observe_prompt_delivery_v1(1_000, &intent, id("compilation:1"), observation)
        .expect("exact terminal delivery");
    assert!(value.delivered);
    assert_eq!(value.provider_request_digest, intent.payload_digest);
    assert_eq!(value.observed_token_positions, Some(vec![0, 3, 7]));
}

#[test]
fn prompt_delivery_v1_rejects_digest_drift_and_nonterminal_claims() {
    let intent = intent();
    let drifted = PromptProviderTerminalObservationV1 {
        terminal_observed: true,
        observed_provider_request_digest: digest(b"other-request"),
        delivered: true,
        rejected_reason: None,
        observed_token_positions: None,
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_v1(1_000, &intent, id("compilation:2"), drifted),
        Err(Error::PayloadBindingMismatch)
    );

    let nonterminal = PromptProviderTerminalObservationV1 {
        terminal_observed: false,
        observed_provider_request_digest: intent.payload_digest,
        delivered: false,
        rejected_reason: None,
        observed_token_positions: None,
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_v1(1_000, &intent, id("compilation:3"), nonterminal),
        Err(Error::MissingTerminalResponse)
    );
}

#[test]
fn prompt_delivery_v1_rejection_requires_bounded_reason_and_canonical_positions() {
    let intent = intent();
    let Ok(reason) = PromptDeliveryRejectReasonV1::new(id("provider_rejected")) else {
        panic!("bounded reason");
    };
    let rejected = PromptProviderTerminalObservationV1 {
        terminal_observed: true,
        observed_provider_request_digest: intent.payload_digest,
        delivered: false,
        rejected_reason: Some(reason),
        observed_token_positions: Some(vec![1, 4]),
        truncation_observed: true,
    };
    let value = observe_prompt_delivery_v1(1_000, &intent, id("compilation:4"), rejected)
        .expect("terminal rejection");
    assert!(!value.delivered);
    assert!(value.rejected_reason.is_some());

    let duplicate_positions = PromptProviderTerminalObservationV1 {
        terminal_observed: true,
        observed_provider_request_digest: intent.payload_digest,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: Some(vec![2, 2]),
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_v1(1_000, &intent, id("compilation:5"), duplicate_positions,),
        Err(Error::InvalidPromptDeliveryObservation)
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
        observed_token_positions: Some(vec![4, 5, 6]),
        truncation_observed: false,
    };
    let observation = observe_prompt_delivery_bytes_v1(input, payload)
        .expect("exact submitted payload is observed");
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
        observed_token_positions: None,
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_bytes_v1(base.clone(), b"different"),
        Err(Error::PayloadBindingMismatch)
    );

    let mut nonterminal = base;
    nonterminal.terminal_observed = false;
    assert_eq!(
        observe_prompt_delivery_bytes_v1(nonterminal, payload),
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
        observed_token_positions: None,
        truncation_observed: false,
    };
    assert_eq!(
        observe_prompt_delivery_bytes_v1(invalid_rejection, payload),
        Err(Error::InvalidPromptDeliveryDisposition)
    );

    let noncanonical_positions = PromptDeliveryBoundaryInputV1 {
        compilation_id: id("compilation:1"),
        expected_payload_digest: digest(payload),
        terminal_observed: true,
        delivered: false,
        rejected_reason: Some(
            PromptDeliveryRejectReasonV1::new(id("provider_rejected")).expect("reason"),
        ),
        observed_token_positions: Some(vec![8, 8]),
        truncation_observed: true,
    };
    assert_eq!(
        observe_prompt_delivery_bytes_v1(noncanonical_positions, payload),
        Err(Error::NonCanonicalTokenPositions)
    );
}
