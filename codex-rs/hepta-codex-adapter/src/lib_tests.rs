use super::*;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnError;
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
        session_id: id("session:1"),
        thread_id: id("thread:1"),
        method_id: id(TURN_START_METHOD_ID),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        owner_generation: 7,
        protocol_version: APP_SERVER_PROTOCOL_V2,
        deadline_ms: 2_000,
    }
}

fn terminal(status: TurnStatus, error: Option<TurnError>) -> TurnCompletedNotification {
    TurnCompletedNotification {
        thread_id: "thread:1".to_string(),
        turn: Turn {
            id: "turn:1".to_string(),
            items: Vec::new(),
            items_view: TurnItemsView::Full,
            status,
            error,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        },
    }
}

#[test]
fn exact_completed_observation_maps_without_authority() {
    let intent = intent();
    let observation = AppServerObservation::from_turn_completed(
        &intent,
        &id("turn:1"),
        &terminal(TurnStatus::Completed, None),
    )
    .unwrap();
    let receipt = adapt(1_000, intent, Some(observation)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.replay, ReplayDisposition::NotRetryable);
    assert_eq!(receipt.turn_id, Some(id("turn:1")));
    assert!(receipt.response_digest.is_some());
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn failed_and_interrupted_are_never_success() {
    let failed_error = TurnError {
        message: "provider overloaded".to_string(),
        codex_error_info: Some(CodexErrorInfo::ServerOverloaded),
        additional_details: None,
    };
    let failed_intent = intent();
    let failed = AppServerObservation::from_turn_completed(
        &failed_intent,
        &id("turn:1"),
        &terminal(TurnStatus::Failed, Some(failed_error)),
    )
    .unwrap();
    let failed_receipt = adapt(1_000, failed_intent, Some(failed)).unwrap();
    assert_eq!(failed_receipt.status, AdapterStatus::Failed);
    assert_eq!(
        failed_receipt.failure_kind,
        Some(FailureKind::ServerOverloaded)
    );
    assert_eq!(failed_receipt.replay, ReplayDisposition::NotRetryable);

    let interrupted_intent = intent();
    let interrupted = AppServerObservation::from_turn_completed(
        &interrupted_intent,
        &id("turn:1"),
        &terminal(TurnStatus::Interrupted, None),
    )
    .unwrap();
    let interrupted_receipt = adapt(1_000, interrupted_intent, Some(interrupted)).unwrap();
    assert_eq!(interrupted_receipt.status, AdapterStatus::Interrupted);
    assert_eq!(interrupted_receipt.replay, ReplayDisposition::NotRetryable);
}

#[test]
fn nonterminal_completion_and_correlation_drift_are_rejected() {
    let value = intent();
    assert_eq!(
        AppServerObservation::from_turn_completed(
            &value,
            &id("turn:1"),
            &terminal(TurnStatus::InProgress, None),
        ),
        Err(Error::NonTerminalCompletion)
    );

    let mut wrong_thread = terminal(TurnStatus::Completed, None);
    wrong_thread.thread_id = "thread:other".to_string();
    assert_eq!(
        AppServerObservation::from_turn_completed(&value, &id("turn:1"), &wrong_thread),
        Err(Error::CorrelationMismatch("thread"))
    );

    assert_eq!(
        AppServerObservation::from_turn_completed(
            &value,
            &id("turn:other"),
            &terminal(TurnStatus::Completed, None),
        ),
        Err(Error::CorrelationMismatch("turn"))
    );
}

#[test]
fn overload_is_definitive_request_rejection_and_safe_to_retry() {
    let value = intent();
    let observation = AppServerObservation::from_request_error(
        &value,
        &JSONRPCErrorError {
            code: OVERLOADED_ERROR_CODE,
            message: "Server overloaded; retry later.".to_string(),
            data: None,
        },
    )
    .unwrap();
    let receipt = adapt(1_000, value, Some(observation)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Overloaded);
    assert_eq!(receipt.replay, ReplayDisposition::SafeToRetry);
    assert_eq!(receipt.failure_kind, Some(FailureKind::ServerOverloaded));
    assert_eq!(receipt.turn_id, None);
}

#[test]
fn internal_request_error_is_indeterminate_and_reconcile_only() {
    let value = intent();
    let observation = AppServerObservation::from_request_error(
        &value,
        &JSONRPCErrorError {
            code: -32603,
            message: "failed to submit turn input".to_string(),
            data: None,
        },
    )
    .unwrap();
    let receipt = adapt(1_000, value, Some(observation)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.replay, ReplayDisposition::ReconcileOnly);
    assert_eq!(
        receipt.failure_kind,
        Some(FailureKind::JsonRpcIndeterminate)
    );
    assert_eq!(receipt.turn_id, None);
}

#[test]
fn invalid_request_is_definitive_pre_admission_rejection() {
    let value = intent();
    let observation = AppServerObservation::from_request_error(
        &value,
        &JSONRPCErrorError {
            code: -32600,
            message: "thread not found".to_string(),
            data: None,
        },
    )
    .unwrap();
    let receipt = adapt(1_000, value, Some(observation)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Rejected);
    assert_eq!(receipt.replay, ReplayDisposition::SafeToRetry);
    assert_eq!(receipt.failure_kind, Some(FailureKind::JsonRpcRejected));
}

#[test]
fn timeout_and_transport_loss_require_reconciliation() {
    let timeout_intent = intent();
    let timeout_observation = AppServerObservation::timed_out(&timeout_intent).unwrap();
    let timeout_receipt = adapt(1_000, timeout_intent, Some(timeout_observation)).unwrap();
    assert_eq!(timeout_receipt.status, AdapterStatus::TimedOut);
    assert_eq!(timeout_receipt.replay, ReplayDisposition::ReconcileOnly);

    let transport_intent = intent();
    let transport_observation = AppServerObservation::transport_lost(&transport_intent).unwrap();
    let transport_receipt = adapt(1_000, transport_intent, Some(transport_observation)).unwrap();
    assert_eq!(transport_receipt.status, AdapterStatus::Unavailable);
    assert_eq!(transport_receipt.replay, ReplayDisposition::ReconcileOnly);
}

#[test]
fn missing_observation_is_indeterminate_before_deadline() {
    let receipt = adapt(1_000, intent(), None).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.response_digest, None);
    assert_eq!(receipt.replay, ReplayDisposition::ReconcileOnly);
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
fn an_observation_cannot_be_reused_for_another_exact_request() {
    let first = intent();
    let mut observation = AppServerObservation::timed_out(&first).unwrap();
    observation.request_digest = digest(b"forged-binding");
    assert_eq!(
        adapt(1_000, first, Some(observation)),
        Err(Error::ObservationBindingMismatch)
    );
}

#[test]
fn a_late_real_terminal_event_is_not_discarded_by_deadline_expiry() {
    let value = intent();
    let observation = AppServerObservation::from_turn_completed(
        &value,
        &id("turn:1"),
        &terminal(TurnStatus::Completed, None),
    )
    .unwrap();
    let receipt = adapt(3_000, value, Some(observation)).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
}
