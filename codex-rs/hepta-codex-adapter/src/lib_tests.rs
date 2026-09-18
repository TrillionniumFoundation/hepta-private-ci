use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier must be valid")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn params() -> TurnStartParams {
    TurnStartParams {
        thread_id: "thread:1".to_string(),
        client_user_message_id: Some("client:1".to_string()),
        input: Vec::new(),
        environments: Some(Vec::new()),
        ..Default::default()
    }
}

fn intent() -> CodexOperationIntent {
    let payload_digest = turn_start_payload_digest(&params());
    CodexOperationIntent {
        operation_id: id("operation:1"),
        subject_id: id("agent:1"),
        destination_id: id("agent:1/app-server:7"),
        thread_id: id("thread:1"),
        client_message_id: "client:1".to_string(),
        method_id: id("turn/start"),
        payload_digest,
        lease_payload_digest: payload_digest,
        input_digest: turn_input_digest(&params()),
        scope_digest: digest(b"scope"),
        session_generation: 7,
        protocol_version: 2,
        deadline_ms: 2_000,
    }
}

fn dispatched() -> DispatchedCodexOperation {
    DispatchedCodexOperation {
        intent: intent(),
        turn_id: id("turn:1"),
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
fn completed_terminal_observation_maps_to_success_without_granting_authority() {
    let receipt = adapt_observation(
        1_000,
        &dispatched(),
        Some(observation(TerminalOutcome::Completed)),
    )
    .expect("completed terminal observation must succeed");
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.thread_id, id("thread:1"));
    assert_eq!(receipt.turn_id, id("turn:1"));
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_terminal_observation_is_not_success() {
    let receipt = adapt_observation(
        1_000,
        &dispatched(),
        Some(observation(TerminalOutcome::Failed)),
    )
    .expect("failed terminal observation must remain representable");
    assert_eq!(receipt.status, AdapterStatus::Failed);
}

#[test]
fn interrupted_terminal_observation_is_not_success() {
    let receipt = adapt_observation(
        1_000,
        &dispatched(),
        Some(observation(TerminalOutcome::Interrupted)),
    )
    .expect("interrupted terminal observation must remain representable");
    assert_eq!(receipt.status, AdapterStatus::Interrupted);
}

#[test]
fn missing_observation_is_indeterminate() {
    let receipt = adapt_observation(1_000, &dispatched(), None)
        .expect("unknown outcome must be represented");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.response_digest, None);
}

#[test]
fn payload_drift_is_rejected() {
    let mut value = dispatched();
    value.intent.lease_payload_digest = digest(b"other");
    assert_eq!(
        adapt_observation(1_000, &value, None),
        Err(Error::PayloadBindingMismatch)
    );
}

#[test]
fn exact_turn_start_payload_is_required() {
    let value = intent();
    let mut changed = params();
    changed.input = vec![codex_app_server_protocol::UserInput::Text {
        text: "changed".to_string(),
        text_elements: Vec::new(),
    }];
    assert_eq!(
        validate_turn_start(1_000, &value, &changed),
        Err(Error::TurnStartPayloadMismatch)
    );
}

#[test]
fn thread_and_stable_client_message_are_bound_before_dispatch() {
    let value = intent();

    let mut wrong_thread = params();
    wrong_thread.thread_id = "thread:other".to_string();
    assert_eq!(
        validate_turn_start(1_000, &value, &wrong_thread),
        Err(Error::ThreadBindingMismatch)
    );

    let mut wrong_client = params();
    wrong_client.client_user_message_id = Some("client:other".to_string());
    assert_eq!(
        validate_turn_start(1_000, &value, &wrong_client),
        Err(Error::ClientMessageBindingMismatch)
    );
}

#[test]
fn mismatched_turn_observation_is_rejected() {
    let mut value = observation(TerminalOutcome::Completed);
    value.turn_id = "turn:other".to_string();
    assert_eq!(
        adapt_observation(1_000, &dispatched(), Some(value)),
        Err(Error::ObservationCorrelationMismatch)
    );
}

#[test]
fn mismatched_protocol_observation_is_rejected() {
    let mut value = observation(TerminalOutcome::Completed);
    value.protocol_version = 3;
    assert_eq!(
        adapt_observation(1_000, &dispatched(), Some(value)),
        Err(Error::ObservationProtocolMismatch)
    );
}

#[test]
fn zero_session_generation_is_rejected() {
    let mut zero_session = dispatched();
    zero_session.intent.session_generation = 0;
    assert_eq!(
        adapt_observation(1_000, &zero_session, None),
        Err(Error::InvalidSessionGeneration)
    );
}

#[test]
fn zero_protocol_version_is_rejected() {
    let mut value = dispatched();
    value.intent.protocol_version = 0;
    assert_eq!(
        adapt_observation(1_000, &value, None),
        Err(Error::InvalidProtocolVersion)
    );
}

#[test]
fn authority_binding_is_derived_from_the_intent() {
    let value = intent();
    let binding = final_use_binding(1_000, &value).expect("binding must be valid");
    assert_eq!(binding.subject_id, value.subject_id.as_str());
    assert_eq!(binding.destination_id, value.destination_id.as_str());
    assert_eq!(binding.payload_sha256, *value.payload_digest.as_array());
    assert_eq!(binding.scope_sha256, *value.scope_digest.as_array());
    assert_eq!(binding.request_sha256, *request_digest(&value).as_array());
}

#[test]
fn stable_client_message_id_is_bounded() {
    let mut value = dispatched();
    value.intent.client_message_id = String::new();
    assert_eq!(
        adapt_observation(1_000, &value, None),
        Err(Error::InvalidClientMessageIdentity)
    );
}
