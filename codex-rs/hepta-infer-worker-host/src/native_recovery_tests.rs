use super::*;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

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

fn recovery_control(path: &std::path::Path) -> DurableInferenceControl {
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    let mut control = DurableInferenceControl::open(path, /*capacity*/ 8).unwrap();
    control
        .reserve_native(record(None).request, /*maximum_in_flight*/ 1)
        .unwrap();
    control
        .dispatch_native(
            "request-a",
            NativeDispatch {
                thread_id: "thread-a".to_string(),
                model_provider: "provider-a".to_string(),
                context_digest: "a".repeat(64),
                owner_context_digest: None,
                codex_payload_digest: None,
                codex_request_digest: None,
                app_server_version: None,
                protocol_id: None,
                codex_source_admission_digest: None,
                codex_home_digest: None,
                codex_connection_id: None,
                codex_session_id: None,
                codex_deadline_ms: None,
                codex_authority_epoch: None,
                codex_revocation_revision: None,
                codex_revocation_head_sha256: None,
                codex_authority_witness_sha256: None,
            },
        )
        .unwrap();
    control
        .native_started("request-a", "turn-a".to_string())
        .unwrap();
    control
}

#[test]
fn oversized_recovered_terminal_keeps_utf8_prefix_and_releases_denied_slot() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("large-terminal.journal");
    let mut control = recovery_control(&path);
    let limit = 1024 * 1024;
    let prefix = "a".repeat(limit - 2);
    let oversized = format!("{prefix}😀lost tail");
    let mut output = NativeRunOutput {
        output: String::new(),
        ..completed()
    };
    retain_recovered_output(&mut output, [oversized.as_str(), "later text"], limit);
    assert_eq!(
        output,
        NativeRunOutput {
            output: prefix,
            boundary_status: NativeBoundaryStatus::Quarantined,
            stop_reason: Some("reconciled output byte limit exceeded".to_string()),
            ..completed()
        }
    );
    let settled = control.settle_native("request-a", output.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(settled.observation, Some(output.clone()));
    assert!(!output.succeeded());
    let mut second = record(None).request;
    second.request_id = "request-b".to_string();
    control
        .reserve_native(second, /*maximum_in_flight*/ 1)
        .unwrap();
}

#[test]
fn output_at_exact_limit_and_prior_denials_keep_their_original_semantics() {
    let mut exact = NativeRunOutput {
        output: String::new(),
        ..completed()
    };
    retain_recovered_output(&mut exact, ["ab", "说明", ""], /*maximum_bytes*/ 8);
    assert_eq!(
        exact,
        NativeRunOutput {
            output: "ab说明".to_string(),
            ..completed()
        }
    );
    for boundary_status in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
    ] {
        let previous = NativeRunOutput {
            boundary_status,
            output: "ab".to_string(),
            observed_output_tokens: Some(17),
            status: NativeRunStatus::Indeterminate,
            terminal_observed: false,
            stop_reason: Some("earlier local denial".to_string()),
            codex_terminal_correlation_digest: None,
            ..completed()
        };
        let mut recovered = NativeRunOutput {
            output: String::new(),
            ..completed()
        };
        retain_recovered_output(&mut recovered, ["ab说明longer"], /*maximum_bytes*/ 7);
        preserve_recovery_evidence(&record(Some(previous)), &mut recovered).unwrap();
        assert_eq!(
            recovered,
            NativeRunOutput {
                output: "ab说".to_string(),
                boundary_status,
                observed_output_tokens: Some(17),
                stop_reason: Some("earlier local denial".to_string()),
                ..completed()
            }
        );
    }
}

#[tokio::test]
async fn recovery_cancellation_is_durable_on_both_sides_of_await_and_on_error() {
    for initially_cancelled in [false, true] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("cancel-recovery.journal");
        let mut control = recovery_control(&path);
        let cancellation = CancellationToken::new();
        if initially_cancelled {
            cancellation.cancel();
        }
        let cancellation_ref = &cancellation;
        let result = reconcile_with_cancellation(
            &mut control,
            "request-a",
            &cancellation,
            |record| async move {
                assert_eq!(record.cancel_requested, initially_cancelled);
                tokio::task::yield_now().await;
                cancellation_ref.cancel();
                Ok(Some(completed()))
            },
        )
        .await
        .unwrap();
        let (record, output) = result;
        let output = output.unwrap();
        assert!(record.cancel_requested);
        assert_eq!(output.boundary_status, NativeBoundaryStatus::Cancelled);
        assert!(!output.succeeded());
        drop(control);
        let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        assert_eq!(reopened.native_record("request-a"), Some(&record));
    }
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cancel-error.journal");
    let mut control = recovery_control(&path);
    let cancellation = CancellationToken::new();
    let result = reconcile_with_cancellation(&mut control, "request-a", &cancellation, |_| async {
        tokio::task::yield_now().await;
        cancellation.cancel();
        Err("provider history read failed".into())
    })
    .await;
    assert_eq!(
        result.unwrap_err().to_string(),
        "provider history read failed"
    );
    let current = control.native_record("request-a").unwrap().clone();
    assert!(current.cancel_requested);
    assert_eq!(current.state, NativeReservationState::Cancelling);
    drop(control);
    let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-a"), Some(&current));
}
