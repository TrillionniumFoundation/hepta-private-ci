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

fn terminal(outcome: TerminalOutcome) -> AppServerObservation {
    AppServerObservation::terminal(
        id("thread:1"),
        id("turn:1"),
        outcome,
        digest(b"response"),
    )
    .expect("terminal observation")
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
