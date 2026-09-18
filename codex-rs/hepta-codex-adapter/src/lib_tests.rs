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
        turn_id: id("turn:1"),
        method_id: id("method:1"),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        session_generation: 7,
        protocol_version: 2,
        deadline_ms: 2_000,
    }
}

fn observation(outcome: TerminalOutcome) -> TerminalObservation {
    TerminalObservation {
        thread_id: "thread:1".to_string(),
        turn_id: "turn:1".to_string(),
        outcome,
        protocol_version: 2,
        response_digest: digest(b"response"),
    }
}

#[test]
fn completed_terminal_observation_maps_to_success_without_authority() {
    let Ok(receipt) = adapt_observation(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Completed)),
    ) else {
        panic!("completed terminal observation must succeed");
    };
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_terminal_observation_is_not_success() {
    let receipt = adapt_observation(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Failed)),
    )
    .expect("failed terminal observation must remain representable");
    assert_eq!(receipt.status, AdapterStatus::Failed);
}

#[test]
fn interrupted_terminal_observation_is_not_success() {
    let receipt = adapt_observation(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Interrupted)),
    )
    .expect("interrupted terminal observation must remain representable");
    assert_eq!(receipt.status, AdapterStatus::Interrupted);
}

#[test]
fn missing_observation_is_indeterminate() {
    let Ok(receipt) = adapt_observation(1_000, intent(), None) else {
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
        adapt_observation(1_000, value, None),
        Err(Error::PayloadBindingMismatch)
    );
}

#[test]
fn mismatched_turn_observation_is_rejected() {
    let mut value = observation(TerminalOutcome::Completed);
    value.turn_id = "turn:other".to_string();
    assert_eq!(
        adapt_observation(1_000, intent(), Some(value)),
        Err(Error::ObservationCorrelationMismatch)
    );
}

#[test]
fn zero_session_generation_is_rejected() {
    let mut value = intent();
    value.session_generation = 0;
    assert_eq!(
        adapt_observation(1_000, value, None),
        Err(Error::InvalidSessionGeneration)
    );
}

#[test]
fn zero_protocol_version_is_rejected() {
    let mut value = intent();
    value.protocol_version = 0;
    assert_eq!(
        adapt(1_000, value, None),
        Err(Error::InvalidProtocolVersion)
    );
}

#[test]
fn mismatched_protocol_observation_is_rejected() {
    let mut value = observation(TerminalOutcome::Completed);
    value.protocol_version = 3;
    assert_eq!(
        adapt_observation(1_000, intent(), Some(value)),
        Err(Error::ObservationProtocolMismatch)
    );
}
