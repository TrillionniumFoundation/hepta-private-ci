use super::*;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

fn request() -> NativeRequest {
    NativeRequest {
        request_id: "private-operation".to_string(),
        principal_id: "private-principal".to_string(),
        worker_generation: 3,
        model: "private-model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "private-thread".to_string(),
        model_provider: "private-provider".to_string(),
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
    }
}

#[test]
fn inspection_preserves_owner_records_bytes_and_unknown_usage() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("owner.journal");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let reserved = control
        .reserve_native(request(), /*maximum_in_flight*/ 1)
        .unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let first = inspect_native_run(&control, "private-operation").unwrap();
    assert_eq!(
        first.recovery_action,
        NativeRecoveryAction::ReservedNotDispatched
    );
    assert_eq!(first.observed_output_tokens, None);
    assert!(first.holds_local_slot);
    assert!(!first.terminal_observed);
    assert_eq!(
        inspect_native_run(&control, "private-operation").unwrap(),
        first
    );
    assert_eq!(control.native_record("private-operation"), Some(&reserved));
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(
        inspect_native_run(&control, "absent"),
        Err(Error::RequestNotFound)
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    drop(control);
    let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(
        inspect_native_run(&reopened, "private-operation").unwrap(),
        first
    );
}

#[test]
fn stopped_before_dispatch_does_not_invent_zero_usage_or_terminality() {
    let root = tempfile::tempdir().unwrap();
    let mut control =
        DurableInferenceControl::open(root.path().join("owner.journal"), /*capacity*/ 8).unwrap();
    control
        .reserve_native(request(), /*maximum_in_flight*/ 1)
        .unwrap();
    control
        .stop_native_before_dispatch("private-operation", "private-reason".to_string())
        .unwrap();
    let snapshot = inspect_native_run(&control, "private-operation").unwrap();
    assert_eq!(
        snapshot.recovery_action,
        NativeRecoveryAction::StoppedBeforeEffect
    );
    assert!(!snapshot.holds_local_slot);
    assert!(!snapshot.terminal_observed);
    assert_eq!(snapshot.observed_output_tokens, None);
    let json = serde_json::to_string(&snapshot).unwrap();
    assert!(!json.contains("private-"));
    assert!(!json.contains("age_ms"));
}

#[test]
fn reopened_legacy_dispatch_is_unresolved_and_retains_capacity() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("owner.journal");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    control
        .reserve_native(request(), /*maximum_in_flight*/ 1)
        .unwrap();
    control
        .dispatch_native("private-operation", dispatch())
        .unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let before = std::fs::read(&path).unwrap();
    let snapshot = inspect_native_run(&control, "private-operation").unwrap();
    assert_eq!(
        snapshot.recovery_action,
        NativeRecoveryAction::LegacyUnresolved
    );
    assert!(snapshot.holds_local_slot);
    assert_eq!(snapshot.observed_output_tokens, None);
    assert_eq!(snapshot.recorded_dispatch_deadline_unix_ms, None);
    let mut other = request();
    other.request_id = "other".to_string();
    assert!(
        control
            .reserve_native(other, /*maximum_in_flight*/ 1)
            .is_err()
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);
}

#[test]
fn terminal_zero_and_missing_usage_remain_distinct_and_output_is_redacted() {
    let root = tempfile::tempdir().unwrap();
    for usage in [None, Some(0), Some(19)] {
        let path = root.path().join(format!("owner-{usage:?}.journal"));
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        control
            .reserve_native(request(), /*maximum_in_flight*/ 1)
            .unwrap();
        control
            .dispatch_native("private-operation", dispatch())
            .unwrap();
        control
            .settle_native(
                "private-operation",
                NativeRunOutput {
                    thread_id: "private-thread".to_string(),
                    turn_id: "private-turn".to_string(),
                    model: "private-model".to_string(),
                    model_provider: "private-provider".to_string(),
                    status: NativeRunStatus::Failed,
                    boundary_status: NativeBoundaryStatus::Failed,
                    output: "private-output".to_string(),
                    observed_output_tokens: usage,
                    terminal_observed: true,
                    stop_reason: Some("private-reason".to_string()),
                    owner_authority: NativeOwnerAuthority::Lost {
                        reason: "private-owner-reason".to_string(),
                    },
                    codex_terminal_correlation_digest: None,
                },
            )
            .unwrap();
        let before = std::fs::read(&path).unwrap();
        let snapshot = inspect_native_run(&control, "private-operation").unwrap();
        assert_eq!(
            snapshot.recovery_action,
            NativeRecoveryAction::TerminalObserved
        );
        assert_eq!(snapshot.observed_output_tokens, usage);
        assert_eq!(snapshot.owner_authority, NativeAuthorityObservation::Lost);
        assert!(!snapshot.holds_local_slot);
        assert!(
            !serde_json::to_string(&snapshot)
                .unwrap()
                .contains("private-")
        );
        assert_eq!(std::fs::read(&path).unwrap(), before);
    }
}
