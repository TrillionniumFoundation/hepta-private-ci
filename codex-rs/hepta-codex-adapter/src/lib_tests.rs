use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnItemsView;

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

fn prepared() -> PreparedCodexRequest {
    prepare(1_000, intent()).expect("prepared request")
}

fn terminal(outcome: TerminalOutcome) -> AppServerObservation {
    AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        outcome,
        digest(b"response"),
    )
    .expect("terminal observation")
}

fn completed_notification(thread: &str, turn: &str, status: TurnStatus) -> ServerNotification {
    ServerNotification::TurnCompleted(TurnCompletedNotification {
        thread_id: thread.to_string(),
        turn: Turn {
            id: turn.to_string(),
            items: Vec::new(),
            items_view: TurnItemsView::Full,
            status,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        },
    })
}

fn server_error(code: i64, message: &str) -> TypedRequestError {
    TypedRequestError::Server {
        method: TURN_START_METHOD.to_string(),
        source: JSONRPCErrorError {
            code,
            message: message.to_string(),
            data: None,
        },
    }
}

#[test]
fn completed_terminal_observation_maps_without_authority() {
    let receipt = adapt(1_000, intent(), Some(terminal(TerminalOutcome::Completed)))
        .expect("terminal observation must adapt");
    assert_eq!(receipt.thread_id, id("thread:1"));
    assert_eq!(receipt.turn_id, Some(id("turn:1")));
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.retry, RetryDisposition::DoNotRetry);
    assert_eq!(receipt.response_digest, Some(digest(b"response")));
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.model_authority);
    assert!(!receipt.provider_authority);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn terminal_failure_is_never_collapsed_into_success() {
    let failed = adapt(1_000, intent(), Some(terminal(TerminalOutcome::Failed)))
        .expect("failed terminal observation must adapt");
    let interrupted = adapt(
        1_000,
        intent(),
        Some(terminal(TerminalOutcome::Interrupted)),
    )
    .expect("interrupted terminal observation must adapt");

    assert_eq!(failed.status, AdapterStatus::Failed);
    assert_eq!(failed.retry, RetryDisposition::DoNotRetry);
    assert_eq!(interrupted.status, AdapterStatus::Interrupted);
    assert_eq!(interrupted.retry, RetryDisposition::DoNotRetry);
    assert_ne!(failed.receipt_digest, interrupted.receipt_digest);
}

#[test]
fn v2_turn_completed_notification_is_the_terminal_source_of_truth() {
    for (turn_status, expected) in [
        (TurnStatus::Completed, AdapterStatus::Succeeded),
        (TurnStatus::Failed, AdapterStatus::Failed),
        (TurnStatus::Interrupted, AdapterStatus::Interrupted),
    ] {
        let notification = completed_notification("thread:1", "turn:protocol", turn_status);
        let receipt = observe_server_notification(&prepared(), &notification)
            .expect("protocol event should map")
            .expect("matching terminal event must produce a receipt");
        assert_eq!(receipt.status, expected);
        assert_eq!(receipt.retry, RetryDisposition::DoNotRetry);
        assert_eq!(receipt.thread_id, id("thread:1"));
        assert_eq!(receipt.turn_id, Some(id("turn:protocol")));
        assert!(receipt.response_digest.is_some());
        assert!(!receipt.model_authority);
        assert!(!receipt.provider_authority);
        assert!(!receipt.authority.grants_any());
    }
}

#[test]
fn unrelated_and_nonterminal_protocol_notifications_fail_closed() {
    let unrelated = completed_notification("thread:other", "turn:1", TurnStatus::Completed);
    assert_eq!(
        observe_server_notification(&prepared(), &unrelated).expect("unrelated event"),
        None
    );

    let in_progress = completed_notification("thread:1", "turn:1", TurnStatus::InProgress);
    assert_eq!(
        observe_server_notification(&prepared(), &in_progress),
        Err(Error::NonTerminalCompletion)
    );
}

#[test]
fn lost_or_disconnected_event_stream_requires_reconciliation() {
    for event in [
        AppServerEvent::Lagged { skipped: 3 },
        AppServerEvent::Disconnected {
            message: "connection lost".to_string(),
        },
    ] {
        let receipt = observe_app_server_event(&prepared(), &event)
            .expect("uncertain stream event should classify")
            .expect("uncertain stream event must produce receipt");
        assert_eq!(receipt.status, AdapterStatus::Indeterminate);
        assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
        assert_eq!(receipt.turn_id, None);
        assert_eq!(receipt.response_digest, None);
    }
}

#[test]
fn turn_start_overload_and_closed_validation_errors_are_retry_safe() {
    let overloaded = observe_turn_start_error(
        &prepared(),
        &server_error(JSON_RPC_OVERLOADED, "Server overloaded; retry later."),
    )
    .expect("overload response");
    assert_eq!(overloaded.status, AdapterStatus::Overloaded);
    assert_eq!(overloaded.retry, RetryDisposition::RetrySafe);
    assert!(overloaded.response_digest.is_some());

    for code in [JSON_RPC_INVALID_REQUEST, JSON_RPC_INVALID_PARAMS] {
        let rejected = observe_turn_start_error(
            &prepared(),
            &server_error(code, "turn/start rejected before admission"),
        )
        .expect("closed validation response");
        assert_eq!(rejected.status, AdapterStatus::Rejected);
        assert_eq!(rejected.retry, RetryDisposition::RetrySafe);
        assert!(rejected.response_digest.is_some());
    }
}

#[test]
fn unclassified_server_error_is_not_blindly_retryable() {
    let receipt = observe_turn_start_error(
        &prepared(),
        &server_error(-32_000, "server failed after request handling began"),
    )
    .expect("generic server failure");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
    assert!(receipt.response_digest.is_some());

    let wrong_method = TypedRequestError::Server {
        method: "thread/start".to_string(),
        source: JSONRPCErrorError {
            code: JSON_RPC_INVALID_REQUEST,
            message: "wrong method".to_string(),
            data: None,
        },
    };
    assert_eq!(
        observe_turn_start_error(&prepared(), &wrong_method),
        Err(Error::UnexpectedMethod)
    );
}

#[test]
fn missing_observation_is_indeterminate_and_not_blindly_retryable() {
    let receipt = adapt(1_000, intent(), None).expect("unknown outcome must be represented");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
    assert_eq!(receipt.turn_id, None);
    assert_eq!(receipt.response_digest, None);
}

#[test]
fn explicit_admission_failures_have_closed_status_and_retry_semantics() {
    for (failure, expected) in [
        (AdmissionFailure::Rejected, AdapterStatus::Rejected),
        (AdmissionFailure::Overloaded, AdapterStatus::Overloaded),
        (AdmissionFailure::Unavailable, AdapterStatus::Unavailable),
    ] {
        let observation = AppServerObservation::admission_failure(
            id("thread:1"),
            failure,
            digest(b"admission-response"),
        )
        .expect("server rejection must carry a response digest");
        let receipt = adapt(1_000, intent(), Some(observation)).expect("admission failure");
        assert_eq!(receipt.status, expected);
        assert_eq!(receipt.retry, RetryDisposition::RetrySafe);
        assert_eq!(receipt.turn_id, None);
        assert_eq!(
            receipt.response_digest,
            Some(digest(b"admission-response"))
        );
    }
}

#[test]
fn uncertain_timeout_requires_reconciliation_and_cancel_is_not_terminal_success() {
    let timeout = adapt(
        1_000,
        intent(),
        Some(AppServerObservation::timed_out(
            id("thread:1"),
            Some(id("turn:1")),
        )),
    )
    .expect("timeout observation");
    assert_eq!(timeout.status, AdapterStatus::TimedOut);
    assert_eq!(timeout.retry, RetryDisposition::ReconcileBeforeRetry);

    let cancelled = adapt(
        1_000,
        intent(),
        Some(AppServerObservation::cancelled(
            id("thread:1"),
            Some(id("turn:1")),
        )),
    )
    .expect("cancel observation");
    assert_eq!(cancelled.status, AdapterStatus::Cancelled);
    assert_eq!(cancelled.retry, RetryDisposition::DoNotRetry);
    assert_eq!(cancelled.response_digest, None);
}

#[test]
fn quarantine_is_terminal_for_the_operation_identity() {
    let receipt = adapt(
        1_000,
        intent(),
        Some(AppServerObservation::quarantined(
            id("thread:1"),
            Some(id("turn:1")),
        )),
    )
    .expect("quarantine observation");
    assert_eq!(receipt.status, AdapterStatus::Quarantined);
    assert_eq!(receipt.retry, RetryDisposition::DoNotRetry);
}

#[test]
fn indeterminate_observation_preserves_known_turn_correlation() {
    let receipt = adapt(
        1_000,
        intent(),
        Some(AppServerObservation::indeterminate(
            id("thread:1"),
            Some(id("turn:known")),
        )),
    )
    .expect("indeterminate observation");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
    assert_eq!(receipt.retry, RetryDisposition::ReconcileBeforeRetry);
    assert_eq!(receipt.turn_id, Some(id("turn:known")));
}

#[test]
fn cross_thread_observation_is_rejected() {
    let observation = AppServerObservation::terminal(
        id("thread:other"),
        id("turn:1"),
        TerminalOutcome::Completed,
        digest(b"response"),
    )
    .expect("terminal observation");
    assert_eq!(
        adapt(1_000, intent(), Some(observation)),
        Err(Error::ThreadBindingMismatch)
    );
}

#[test]
fn terminal_and_admission_observations_require_content_binding() {
    assert_eq!(
        AppServerObservation::terminal(
            id("thread:1"),
            id("turn:1"),
            TerminalOutcome::Completed,
            Digest32::ZERO,
        ),
        Err(Error::MissingTerminalResponse)
    );
    assert_eq!(
        AppServerObservation::admission_failure(
            id("thread:1"),
            AdmissionFailure::Rejected,
            Digest32::ZERO,
        ),
        Err(Error::MissingAdmissionResponse)
    );
}

#[test]
fn payload_drift_and_empty_bindings_are_rejected() {
    let mut drift = intent();
    drift.lease_payload_digest = digest(b"other");
    assert_eq!(
        adapt(1_000, drift, None),
        Err(Error::PayloadBindingMismatch)
    );

    let mut empty_payload = intent();
    empty_payload.payload_digest = Digest32::ZERO;
    assert_eq!(
        adapt(1_000, empty_payload, None),
        Err(Error::EmptyDigest("payload"))
    );

    let mut empty_lease = intent();
    empty_lease.lease_payload_digest = Digest32::ZERO;
    assert_eq!(
        adapt(1_000, empty_lease, None),
        Err(Error::EmptyDigest("lease_payload"))
    );
}

#[test]
fn receipt_digest_binds_turn_status_and_response() {
    let completed = adapt(1_000, intent(), Some(terminal(TerminalOutcome::Completed)))
        .expect("completed receipt");
    let failed = adapt(1_000, intent(), Some(terminal(TerminalOutcome::Failed)))
        .expect("failed receipt");
    let other_turn = adapt(
        1_000,
        intent(),
        Some(
            AppServerObservation::terminal(
                id("thread:1"),
                id("turn:2"),
                TerminalOutcome::Completed,
                digest(b"response"),
            )
            .expect("terminal observation"),
        ),
    )
    .expect("other turn receipt");
    let other_response = adapt(
        1_000,
        intent(),
        Some(
            AppServerObservation::terminal(
                id("thread:1"),
                id("turn:1"),
                TerminalOutcome::Completed,
                digest(b"different-response"),
            )
            .expect("terminal observation"),
        ),
    )
    .expect("other response receipt");

    assert_ne!(completed.receipt_digest, failed.receipt_digest);
    assert_ne!(completed.receipt_digest, other_turn.receipt_digest);
    assert_ne!(completed.receipt_digest, other_response.receipt_digest);
}

#[test]
fn settlement_does_not_reapply_the_pre_dispatch_deadline() {
    let mut value = intent();
    value.deadline_ms = 1_001;
    let prepared = prepare(1_000, value).expect("request admitted before its deadline");

    // No current-time input exists at settlement: a terminal event received
    // later remains an exact fact instead of becoming DeadlineExpired.
    let receipt = prepared
        .observe(Some(terminal(TerminalOutcome::Completed)))
        .expect("late terminal settlement");
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
}
