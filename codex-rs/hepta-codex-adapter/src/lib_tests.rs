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
        method_id: id("method:turn-start"),
        protocol_version: 2,
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        deadline_ms: 2_000,
    }
}

fn observation(outcome: AppServerOutcome) -> AppServerObservation {
    AppServerObservation {
        thread_id: id("thread:1"),
        turn_id: id("turn:1"),
        protocol_version: 2,
        outcome,
        response_digest: Some(digest(b"response")),
    }
}

#[test]
fn exact_completed_observation_maps_without_authority() {
    let Ok(receipt) = adapt(
        1_000,
        intent(),
        Some(observation(AppServerOutcome::Completed)),
    ) else {
        panic!("completed observation must map");
    };
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.thread_id, id("thread:1"));
    assert_eq!(receipt.turn_id, id("turn:1"));
    assert_eq!(receipt.protocol_version, 2);
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_and_interrupted_terminal_events_never_become_success() {
    for (outcome, expected) in [
        (AppServerOutcome::Failed, AdapterStatus::Failed),
        (AppServerOutcome::Interrupted, AdapterStatus::Interrupted),
    ] {
        let receipt = adapt(1_000, intent(), Some(observation(outcome)))
            .expect("correlated terminal outcome must map");
        assert_eq!(receipt.status, expected);
        assert_ne!(receipt.status, AdapterStatus::Succeeded);
    }
}

#[test]
fn transport_and_policy_outcomes_preserve_information() {
    for (outcome, expected) in [
        (AppServerOutcome::Rejected, AdapterStatus::Rejected),
        (AppServerOutcome::Unavailable, AdapterStatus::Unavailable),
        (AppServerOutcome::TimedOut, AdapterStatus::TimedOut),
        (AppServerOutcome::Overloaded, AdapterStatus::Overloaded),
        (AppServerOutcome::Quarantined, AdapterStatus::Quarantined),
    ] {
        let mut observed = observation(outcome);
        observed.response_digest = None;
        let receipt = adapt(1_000, intent(), Some(observed))
            .expect("non-turn-terminal outcome must map without invented response");
        assert_eq!(receipt.status, expected);
        assert_eq!(receipt.response_digest, None);
    }
}

#[test]
fn missing_or_in_progress_observation_is_indeterminate() {
    let receipt = adapt(1_000, intent(), None).expect("unknown outcome must be represented");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);

    let mut observed = observation(AppServerOutcome::InProgress);
    observed.response_digest = None;
    let receipt = adapt(1_000, intent(), Some(observed))
        .expect("nonterminal observation must remain representable");
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
fn cross_thread_cross_turn_and_protocol_observations_are_rejected() {
    let mut observed = observation(AppServerOutcome::Completed);
    observed.thread_id = id("thread:other");
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::ObservationThreadMismatch)
    );

    let mut observed = observation(AppServerOutcome::Completed);
    observed.turn_id = id("turn:other");
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::ObservationTurnMismatch)
    );

    let mut observed = observation(AppServerOutcome::Completed);
    observed.protocol_version = 3;
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::ObservationProtocolMismatch)
    );
}

#[test]
fn completed_failed_and_interrupted_require_a_nonzero_terminal_response_digest() {
    for outcome in [
        AppServerOutcome::Completed,
        AppServerOutcome::Failed,
        AppServerOutcome::Interrupted,
    ] {
        let mut observed = observation(outcome);
        observed.response_digest = None;
        assert_eq!(
            adapt(1_000, intent(), Some(observed)),
            Err(Error::MissingTerminalResponse)
        );
    }
}
