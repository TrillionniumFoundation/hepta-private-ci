use super::*;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;

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
        turn_id: Some(id("turn:1")),
        method_id: id("turn:start"),
        protocol_version: id(APP_SERVER_V2_PROTOCOL_ID),
        session_generation: 7,
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        deadline_ms: 2_000,
    }
}

fn terminal(status: TurnStatus) -> TurnCompletedNotification {
    TurnCompletedNotification {
        thread_id: "thread:1".to_string(),
        turn: Turn {
            id: "turn:1".to_string(),
            items: Vec::new(),
            items_view: TurnItemsView::Full,
            status,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        },
    }
}

fn observation(status: TurnStatus) -> AppServerObservation {
    AppServerObservation::from_turn_completed(
        id(APP_SERVER_V2_PROTOCOL_ID),
        7,
        11,
        &terminal(status),
    )
    .expect("terminal observation must be valid")
}

#[test]
fn exact_completed_observation_maps_without_authority() {
    let Ok(receipt) = adapt(
        1_000,
        intent(),
        Some(observation(TurnStatus::Completed)),
    ) else {
        panic!("terminal observation must succeed");
    };
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.terminal_outcome, Some(TerminalOutcome::Completed));
    assert_eq!(receipt.retry, RetryDisposition::Never);
    assert_eq!(receipt.event_sequence, Some(11));
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_and_interrupted_never_collapse_into_success() {
    let failed = adapt(
        1_000,
        intent(),
        Some(observation(TurnStatus::Failed)),
    )
    .expect("failed terminal is still a valid observation");
    assert_eq!(failed.status, AdapterStatus::Failed);
    assert_eq!(failed.terminal_outcome, Some(TerminalOutcome::Failed));

    let interrupted = adapt(
        1_000,
        intent(),
        Some(observation(TurnStatus::Interrupted)),
    )
    .expect("interrupted terminal is still a valid observation");
    assert_eq!(interrupted.status, AdapterStatus::Interrupted);
    assert_eq!(
        interrupted.terminal_outcome,
        Some(TerminalOutcome::Interrupted)
    );
}

#[test]
fn missing_observation_is_indeterminate() {
    let Ok(receipt) = adapt(1_000, intent(), None) else {
        panic!("unknown outcome must be represented");
    };
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
    assert_eq!(receipt.response_digest, None);
    assert_eq!(receipt.event_sequence, None);
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
fn terminal_correlation_mismatch_is_rejected() {
    let mut value = terminal(TurnStatus::Completed);
    value.turn.id = "turn:other".to_string();
    let observed = AppServerObservation::from_turn_completed(
        id(APP_SERVER_V2_PROTOCOL_ID),
        7,
        11,
        &value,
    )
    .expect("observation can be formed before correlation check");
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::CorrelationMismatch("turn"))
    );
}

#[test]
fn in_progress_completion_notification_is_not_terminal() {
    assert_eq!(
        AppServerObservation::from_turn_completed(
            id(APP_SERVER_V2_PROTOCOL_ID),
            7,
            11,
            &terminal(TurnStatus::InProgress),
        ),
        Err(Error::NonTerminalCompletion)
    );
}

#[test]
fn overload_is_the_only_backoff_safe_transport_rejection() {
    let overloaded = JSONRPCErrorError {
        code: APP_SERVER_OVERLOADED_ERROR_CODE,
        message: "Server overloaded; retry later.".to_string(),
        data: None,
    };
    let observed = AppServerObservation::from_rpc_error(
        id("thread:1"),
        None,
        id(APP_SERVER_V2_PROTOCOL_ID),
        7,
        3,
        &overloaded,
    )
    .expect("overload observation must be valid");
    let mut pre_turn = intent();
    pre_turn.turn_id = None;
    let receipt = adapt(1_000, pre_turn, Some(observed)).expect("overload is observed");
    assert_eq!(receipt.status, AdapterStatus::Overloaded);
    assert_eq!(receipt.retry, RetryDisposition::BackoffSafe);

    let rejected = JSONRPCErrorError {
        code: -32602,
        message: "invalid params".to_string(),
        data: None,
    };
    let observed = AppServerObservation::from_rpc_error(
        id("thread:1"),
        None,
        id(APP_SERVER_V2_PROTOCOL_ID),
        7,
        4,
        &rejected,
    )
    .expect("rejection observation must be valid");
    let mut pre_turn = intent();
    pre_turn.turn_id = None;
    let receipt = adapt(1_000, pre_turn, Some(observed)).expect("rejection is observed");
    assert_eq!(receipt.status, AdapterStatus::Rejected);
    assert_eq!(receipt.retry, RetryDisposition::Never);
}

#[test]
fn protocol_and_generation_mismatch_fail_closed() {
    let observed = AppServerObservation::from_turn_completed(
        id(APP_SERVER_V2_PROTOCOL_ID),
        8,
        12,
        &terminal(TurnStatus::Completed),
    )
    .expect("well-formed observation");
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::CorrelationMismatch("generation"))
    );

    let observed = AppServerObservation::from_turn_completed(
        id("codex.app-server.v3"),
        7,
        13,
        &terminal(TurnStatus::Completed),
    )
    .expect("well-formed observation");
    assert_eq!(
        adapt(1_000, intent(), Some(observed)),
        Err(Error::CorrelationMismatch("protocol"))
    );
}

#[test]
fn timeout_unavailable_and_quarantine_never_become_success() {
    let cases = [
        (
            AppServerObservation::timed_out(
                id("thread:1"),
                Some(id("turn:1")),
                id(APP_SERVER_V2_PROTOCOL_ID),
                7,
                20,
            )
            .unwrap(),
            AdapterStatus::TimedOut,
        ),
        (
            AppServerObservation::unavailable(
                id("thread:1"),
                Some(id("turn:1")),
                id(APP_SERVER_V2_PROTOCOL_ID),
                7,
                21,
            )
            .unwrap(),
            AdapterStatus::Unavailable,
        ),
        (
            AppServerObservation::quarantined(
                id("thread:1"),
                Some(id("turn:1")),
                id(APP_SERVER_V2_PROTOCOL_ID),
                7,
                22,
            )
            .unwrap(),
            AdapterStatus::Quarantined,
        ),
    ];

    for (observation, expected) in cases {
        let receipt = adapt(1_000, intent(), Some(observation)).unwrap();
        assert_eq!(receipt.status, expected);
        assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
        assert_eq!(receipt.terminal_outcome, None);
        assert!(!receipt.authority.grants_any());
    }
}

#[test]
fn internal_server_error_remains_indeterminate_not_rejected() {
    let ambiguous = JSONRPCErrorError {
        code: -32603,
        message: "internal error after unknown processing point".to_string(),
        data: None,
    };
    let observed = AppServerObservation::from_rpc_error(
        id("thread:1"),
        None,
        id(APP_SERVER_V2_PROTOCOL_ID),
        7,
        30,
        &ambiguous,
    )
    .unwrap();
    let mut pre_turn = intent();
    pre_turn.turn_id = None;
    let receipt = adapt(1_000, pre_turn, Some(observed)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
}
