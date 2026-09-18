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
        expected_turn_id: Some(id("turn:1")),
        method_id: id("method:1"),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        connection_digest: digest(b"connection"),
        session_generation: 7,
        protocol_version: 2,
        deadline_ms: 2_000,
    }
}

fn observation(outcome: TerminalOutcome) -> AppServerObservation {
    AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        7,
        2,
        digest(b"connection"),
        outcome,
        digest(b"response"),
    )
    .expect("valid terminal observation")
}

#[test]
fn completed_terminal_observation_maps_without_authority() {
    let Ok(receipt) = adapt(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Completed)),
    ) else {
        panic!("completed terminal observation must succeed");
    };
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.turn_id.as_ref(), Some(&id("turn:1")));
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_and_interrupted_are_not_success() {
    let failed = adapt(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Failed)),
    )
    .expect("failed terminal observation is still terminal evidence");
    let interrupted = adapt(
        1_000,
        intent(),
        Some(observation(TerminalOutcome::Interrupted)),
    )
    .expect("interrupted terminal observation is still terminal evidence");

    assert_eq!(failed.status, AdapterStatus::Failed);
    assert_eq!(interrupted.status, AdapterStatus::Interrupted);
    assert_ne!(failed.status, AdapterStatus::Succeeded);
    assert_ne!(interrupted.status, AdapterStatus::Succeeded);
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
fn terminal_correlation_drift_is_rejected() {
    let wrong_thread = AppServerObservation::terminal(
        id("thread:other"),
        id("turn:1"),
        7,
        2,
        digest(b"connection"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("syntactically valid terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(wrong_thread)),
        Err(Error::ThreadMismatch)
    );

    let wrong_turn = AppServerObservation::terminal(
        id("thread:1"),
        id("turn:other"),
        7,
        2,
        digest(b"connection"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("syntactically valid terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(wrong_turn)),
        Err(Error::TurnMismatch)
    );

    let wrong_generation = AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        8,
        2,
        digest(b"connection"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("syntactically valid terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(wrong_generation)),
        Err(Error::SessionGenerationMismatch)
    );

    let wrong_protocol = AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        7,
        3,
        digest(b"connection"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("syntactically valid terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(wrong_protocol)),
        Err(Error::ProtocolVersionMismatch)
    );

    let wrong_connection = AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        7,
        2,
        digest(b"other-connection"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("syntactically valid terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(wrong_connection)),
        Err(Error::ConnectionMismatch)
    );
}

#[test]
fn turn_start_may_bind_the_allocated_turn_only_at_terminal_observation() {
    let mut value = intent();
    value.expected_turn_id = None;
    let receipt = adapt(
        1_000,
        value,
        Some(observation(TerminalOutcome::Completed)),
    )
    .expect("App Server allocated turn id must be accepted when request did not know it");
    assert_eq!(receipt.turn_id.as_ref(), Some(&id("turn:1")));
}
