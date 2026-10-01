use super::*;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

fn request(request_id: &str) -> NativeRequest {
    NativeRequest {
        request_id: request_id.to_string(),
        principal_id: "principal-a".to_string(),
        worker_generation: 1,
        model: "model-a".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn started_control(path: &std::path::Path) -> DurableInferenceControl {
    let mut control = DurableInferenceControl::open(path, /*capacity*/ 8).unwrap();
    control
        .reserve_native(request("request-a"), /*maximum_in_flight*/ 1)
        .unwrap();
    control
        .dispatch_native(
            "request-a",
            NativeDispatch {
                thread_id: "thread-a".to_string(),
                model_provider: "provider-a".to_string(),
                context_digest: "b".repeat(64),
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

fn denied(boundary_status: NativeBoundaryStatus) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "model-a".to_string(),
        model_provider: "provider-a".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status,
        output: "observed prefix".to_string(),
        observed_output_tokens: Some(17),
        terminal_observed: false,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: Some("local denial before any cancellation await".to_string()),
        codex_terminal_correlation_digest: None,
    }
}

#[test]
fn denied_boundary_and_observed_facts_survive_reopen_with_capacity_held() {
    for boundary_status in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("denied.journal");
        let mut control = started_control(&path);
        let output = denied(boundary_status);
        persist_denied_observation(&mut control, "request-a", &output).unwrap();
        let expected = control.native_record("request-a").unwrap().clone();
        assert_eq!(expected.observation, Some(output.clone()));
        assert_eq!(expected.state, NativeReservationState::Cancelling);
        assert!(expected.cancel_requested);
        drop(control);
        let mut reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        assert_eq!(reopened.native_record("request-a"), Some(&expected));
        assert_eq!(
            reopened.reserve_native(request("request-b"), /*maximum_in_flight*/ 1),
            Err(Error::CapacityExceeded)
        );
        let late_terminal = NativeRunOutput {
            status: NativeRunStatus::Completed,
            terminal_observed: true,
            output: "observed prefix and late terminal suffix".to_string(),
            ..output
        };
        let settled = reopened
            .settle_native("request-a", late_terminal.clone())
            .unwrap();
        assert_eq!(settled.state, NativeReservationState::Released);
        assert_eq!(settled.observation, Some(late_terminal.clone()));
        assert!(!late_terminal.succeeded());
    }
}

#[test]
fn observation_failure_still_attempts_to_persist_cancellation() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("invalid-observation.journal");
    let mut control = started_control(&path);
    let invalid = NativeRunOutput {
        model: "another-model".to_string(),
        ..denied(NativeBoundaryStatus::TimedOut)
    };
    assert_eq!(
        persist_denied_observation(&mut control, "request-a", &invalid),
        Err(Error::AssignmentMismatch)
    );
    let expected = control.native_record("request-a").unwrap().clone();
    assert!(expected.cancel_requested);
    assert_eq!(expected.observation, None);
    assert_eq!(expected.state, NativeReservationState::Cancelling);
    drop(control);
    let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-a"), Some(&expected));
}
