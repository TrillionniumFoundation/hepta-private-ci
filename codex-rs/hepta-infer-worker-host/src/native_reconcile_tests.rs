use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use std::time::Duration;

fn fixture() -> (
    AppServerModelDriver,
    tempfile::TempDir,
    DurableInferenceControl,
) {
    let directory = tempfile::tempdir().unwrap();
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: directory.path().join("must-not-connect.sock"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "model".to_string(),
        timeout: Duration::from_secs(5),
    })
    .unwrap();
    let control = DurableInferenceControl::open(
        directory.path().join("inference.journal"),
        /*capacity*/ 8,
    )
    .unwrap();
    (driver, directory, control)
}

fn reserve(driver: &AppServerModelDriver, control: &mut DurableInferenceControl) {
    control
        .reserve_native(
            NativeRequest {
                request_id: "reconcile-1".to_string(),
                principal_id: driver.config.agent_id.to_string(),
                worker_generation: driver.config.generation,
                model: driver.config.model.clone(),
                payload_digest: native_source_payload_digest(
                    "prompt",
                    &None,
                    &driver.config.agentd_socket,
                    driver.config.timeout.as_millis(),
                    /*intelligence*/ None,
                )
                .unwrap(),
            },
            /*maximum_in_flight*/ 1,
        )
        .unwrap();
}

fn dispatch(control: &mut DurableInferenceControl) {
    control
        .dispatch_native(
            "reconcile-1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
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
}

#[tokio::test]
async fn reconcile_only_never_creates_missing_request_or_dispatches_reserved_request() {
    let (driver, _directory, mut control) = fixture();
    let error = driver
        .reconcile_only(
            &mut control,
            "reconcile-1",
            "prompt",
            &None,
            /*intelligence*/ None,
        )
        .await
        .unwrap_err();
    assert!(error.to_string().contains("not found"));
    assert!(control.native_record("reconcile-1").is_none());
    reserve(&driver, &mut control);
    let before = control.native_record("reconcile-1").unwrap().clone();
    let error = driver
        .reconcile_only(
            &mut control,
            "reconcile-1",
            "prompt",
            &None,
            /*intelligence*/ None,
        )
        .await
        .unwrap_err();
    assert!(error.to_string().contains("never dispatches"));
    assert_eq!(control.native_record("reconcile-1"), Some(&before));
}

#[tokio::test]
async fn reconcile_only_rejects_changed_input_without_mutating_dispatch() {
    let (driver, _directory, mut control) = fixture();
    reserve(&driver, &mut control);
    dispatch(&mut control);
    let before = control.native_record("reconcile-1").unwrap().clone();
    for (prompt, context) in [
        ("changed prompt", None),
        ("prompt", Some("new context".to_string())),
    ] {
        let error = driver
            .reconcile_only(
                &mut control,
                "reconcile-1",
                prompt,
                &context,
                /*intelligence*/ None,
            )
            .await
            .unwrap_err();
        assert!(error.to_string().contains("binding mismatch"));
        assert_eq!(control.native_record("reconcile-1"), Some(&before));
    }
}

#[tokio::test]
async fn reconcile_only_preserves_unknown_usage_and_never_replays_legacy_dispatch() {
    let (driver, directory, mut control) = fixture();
    reserve(&driver, &mut control);
    dispatch(&mut control);
    drop(control);
    let mut control = DurableInferenceControl::open(
        directory.path().join("inference.journal"),
        /*capacity*/ 8,
    )
    .unwrap();
    let first = driver
        .reconcile_only(
            &mut control,
            "reconcile-1",
            "prompt",
            &None,
            /*intelligence*/ None,
        )
        .await
        .unwrap();
    assert_eq!(first.status, NativeRunStatus::Indeterminate);
    assert!(!first.terminal_observed);
    assert_eq!(first.observed_output_tokens, None);
    let second = driver
        .reconcile_only(
            &mut control,
            "reconcile-1",
            "prompt",
            &None,
            /*intelligence*/ None,
        )
        .await
        .unwrap();
    assert_eq!(first, second);
    assert_eq!(
        control.native_record("reconcile-1").unwrap().state,
        NativeReservationState::Indeterminate
    );
}

#[tokio::test]
async fn reconcile_only_returns_persisted_pre_dispatch_stop_without_new_execution() {
    let (driver, _directory, mut control) = fixture();
    reserve(&driver, &mut control);
    control
        .stop_native_before_dispatch("reconcile-1", "cancelled before dispatch".to_string())
        .unwrap();
    let before = control.native_record("reconcile-1").unwrap().clone();
    let error = driver
        .reconcile_only(
            &mut control,
            "reconcile-1",
            "prompt",
            &None,
            /*intelligence*/ None,
        )
        .await
        .unwrap_err();
    assert!(error.to_string().contains("stopped before dispatch"));
    assert_eq!(control.native_record("reconcile-1"), Some(&before));
}
