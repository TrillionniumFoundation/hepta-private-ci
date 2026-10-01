use super::*;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;

fn completed() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "model-a".to_string(),
        model_provider: "provider-a".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "observed prefix and recovered suffix".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("a".repeat(64)),
    }
}

fn record(previous: Option<NativeRunOutput>) -> NativeRunRecord {
    NativeRunRecord {
        request: NativeRequest {
            request_id: "request-a".to_string(),
            principal_id: "principal-a".to_string(),
            worker_generation: 1,
            model: "model-a".to_string(),
            payload_digest: "b".repeat(64),
        },
        revision: 4,
        state: NativeReservationState::Indeterminate,
        dispatch: None,
        turn_id: Some("turn-a".to_string()),
        cancel_requested: false,
        pre_dispatch_stop: None,
        dispatch_rejection: None,
        observation: previous,
    }
}

#[test]
fn recovered_terminal_preserves_usage_owner_loss_and_local_denial() {
    for boundary in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        let lost = NativeOwnerAuthority::Lost {
            reason: "generation replaced before connection loss".to_string(),
        };
        let previous = NativeRunOutput {
            status: NativeRunStatus::Indeterminate,
            boundary_status: boundary,
            output: "observed prefix".to_string(),
            observed_output_tokens: Some(17),
            terminal_observed: false,
            owner_authority: lost.clone(),
            stop_reason: Some("local stop before disconnect".to_string()),
            codex_terminal_correlation_digest: None,
            ..completed()
        };
        let mut recovered = completed();
        preserve_recovery_evidence(&record(Some(previous)), &mut recovered).unwrap();
        assert_eq!(
            recovered,
            NativeRunOutput {
                boundary_status: NativeBoundaryStatus::Quarantined,
                observed_output_tokens: Some(17),
                owner_authority: lost,
                stop_reason: Some("local stop before disconnect".to_string()),
                ..completed()
            }
        );
        assert!(!recovered.succeeded());
    }
}

#[test]
fn recovered_terminal_preserves_partial_usage_without_inventing_absent_usage() {
    let previous = NativeRunOutput {
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: "observed prefix".to_string(),
        terminal_observed: false,
        codex_terminal_correlation_digest: None,
        ..completed()
    };
    for tokens in [None, Some(17)] {
        let mut recovered = completed();
        let previous = NativeRunOutput {
            observed_output_tokens: tokens,
            ..previous.clone()
        };
        preserve_recovery_evidence(&record(Some(previous)), &mut recovered).unwrap();
        assert_eq!(
            recovered,
            NativeRunOutput {
                observed_output_tokens: tokens,
                ..completed()
            }
        );
    }
}

#[test]
fn conflicting_recovery_cannot_erase_known_text_or_usage() {
    let previous = NativeRunOutput {
        output: "observed prefix".to_string(),
        observed_output_tokens: Some(17),
        terminal_observed: false,
        status: NativeRunStatus::Indeterminate,
        ..completed()
    };
    let previous = record(Some(previous));
    let mut changed_text = NativeRunOutput {
        output: "different text".to_string(),
        ..completed()
    };
    assert!(preserve_recovery_evidence(&previous, &mut changed_text).is_err());
    let mut changed_usage = NativeRunOutput {
        observed_output_tokens: Some(16),
        ..completed()
    };
    assert!(preserve_recovery_evidence(&previous, &mut changed_usage).is_err());
}

#[test]
fn cancellation_without_a_saved_observation_denies_recovered_success() {
    let record = NativeRunRecord {
        cancel_requested: true,
        ..record(None)
    };
    let mut recovered = completed();
    preserve_recovery_evidence(&record, &mut recovered).unwrap();
    assert_eq!(recovered.boundary_status, NativeBoundaryStatus::Cancelled);
    assert!(!recovered.succeeded());
}

#[test]
fn ready_events_cannot_bypass_cancel_or_an_expired_deadline() {
    let cancellation = CancellationToken::new();
    let future_deadline = Instant::now() + std::time::Duration::from_secs(10);
    check_observation_boundary(future_deadline, &cancellation).unwrap();
    assert_eq!(
        check_observation_boundary(Instant::now(), &cancellation),
        Err(LOCAL_DEADLINE_ELAPSED.to_string())
    );
    cancellation.cancel();
    assert_eq!(
        check_observation_boundary(future_deadline, &cancellation),
        Err(LOCAL_CANCELLED.to_string())
    );
}

#[test]
fn historical_recovery_denies_missing_frontier_before_owner_publication() {
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;

    let mut record = record(None);
    record.dispatch = Some(NativeDispatch {
        thread_id: "thread-a".to_string(),
        model_provider: "provider-a".to_string(),
        context_digest: "a".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: Some("b".repeat(64)),
        codex_request_digest: Some("c".repeat(64)),
        app_server_version: Some("test-server".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some("d".repeat(64)),
        codex_home_digest: Some("e".repeat(64)),
        codex_connection_id: Some(7),
        codex_session_id: Some("session-a".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: None,
        codex_revocation_revision: None,
        codex_revocation_head_sha256: None,
        codex_authority_witness_sha256: Some("f".repeat(64)),
    });
    let mut recovered = completed();
    preserve_recovery_evidence(&record, &mut recovered).unwrap();
    assert_eq!(recovered.status, NativeRunStatus::Completed);
    assert!(recovered.terminal_observed);
    assert_eq!(recovered.boundary_status, NativeBoundaryStatus::Quarantined);
    assert!(!recovered.succeeded());
}
