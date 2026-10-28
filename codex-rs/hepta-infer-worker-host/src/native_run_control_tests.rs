use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use pretty_assertions::assert_eq;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn fixture(label: &str) -> (AppServerModelDriver, PathBuf) {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("hepta-native-host-{label}-{nonce}.journal"));
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: path.with_extension("nonexistent-socket"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "model".to_string(),
        timeout: Duration::from_secs(5),
    })
    .unwrap();
    (driver, path)
}

fn request(driver: &AppServerModelDriver) -> NativeRequest {
    NativeRequest {
        request_id: "r1".to_string(),
        principal_id: driver.config.agent_id.to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: digest(
            &serde_json::to_vec(&(
                "hepta.native-request.v1",
                "prompt",
                Option::<String>::None,
                &driver.config.agentd_socket,
                driver.config.timeout.as_millis(),
            ))
            .unwrap(),
        ),
    }
}

fn admission() -> NativeAdmission {
    NativeAdmission {
        request_id: "r1".to_string(),
        maximum_in_flight: 1,
    }
}

#[tokio::test]
async fn reopened_dispatch_and_completed_duplicate_never_connect_to_provider() {
    let (driver, path) = fixture("reopen");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request(&driver), 1).unwrap();
    control
        .dispatch_native(
            "r1",
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
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let cancellation = CancellationToken::new();
    // The nonexistent socket makes any accidental second dispatch fail.
    let unknown = driver
        .run(
            &mut control,
            admission(),
            "prompt".to_string(),
            None,
            &cancellation,
        )
        .await
        .unwrap();
    assert_eq!(unknown.status, NativeRunStatus::Indeterminate);
    assert_eq!(unknown.observed_output_tokens, None);
    assert!(!unknown.terminal_observed);
    assert_eq!(
        control.native_record("r1").unwrap().state,
        NativeReservationState::Indeterminate
    );
    assert_eq!(
        driver
            .run(
                &mut control,
                admission(),
                "prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .unwrap(),
        unknown
    );
    assert!(
        driver
            .run(
                &mut control,
                admission(),
                "changed prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .is_err()
    );
    let terminal = NativeRunOutput {
        turn_id: "turn-1".to_string(),
        status: NativeRunStatus::Failed,
        boundary_status:
            codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Failed,
        terminal_observed: true,
        observed_output_tokens: Some(17),
        stop_reason: Some("observed terminal failure".to_string()),
        codex_terminal_correlation_digest: None,
        ..unknown
    };
    control.settle_native("r1", terminal.clone()).unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        driver
            .run(
                &mut control,
                admission(),
                "prompt".to_string(),
                None,
                &cancellation
            )
            .await
            .unwrap(),
        terminal
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pre_dispatch_cancellation_and_connection_failure_release_without_usage_claims() {
    for cancelled in [true, false] {
        let (driver, path) = fixture(if cancelled { "cancel" } else { "connection" });
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let cancellation = CancellationToken::new();
        if cancelled {
            cancellation.cancel();
        }
        assert!(
            driver
                .run(
                    &mut control,
                    admission(),
                    "prompt".to_string(),
                    None,
                    &cancellation
                )
                .await
                .is_err()
        );
        let stopped = control.native_record("r1").unwrap().clone();
        assert_eq!(stopped.state, NativeReservationState::Released);
        assert_eq!(stopped.observation, None);
        assert!(stopped.pre_dispatch_stop.is_some());
        drop(control);
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        assert!(
            driver
                .run(
                    &mut control,
                    admission(),
                    "prompt".to_string(),
                    None,
                    &CancellationToken::new()
                )
                .await
                .is_err()
        );
        assert_eq!(control.native_record("r1"), Some(&stopped));
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn reopened_explicit_dispatch_rejection_never_connects_or_becomes_unknown() {
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;

    let (driver, path) = fixture("rejected-reopen");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request(&driver), 1).unwrap();
    control
        .dispatch_native(
            "r1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "a".repeat(64),
                owner_context_digest: None,
                codex_payload_digest: Some("d".repeat(64)),
                codex_request_digest: Some("b".repeat(64)),
                app_server_version: Some("1.2.3".to_string()),
                protocol_id: Some("codex.app-server.v2".to_string()),
                codex_source_admission_digest: Some("e".repeat(64)),
                codex_home_digest: Some("f".repeat(64)),
                codex_connection_id: Some(9),
                codex_session_id: Some("session-1".to_string()),
                codex_deadline_ms: Some(10_000),
                codex_authority_epoch: None,
                codex_revocation_revision: None,
                codex_revocation_head_sha256: None,
                codex_authority_witness_sha256: Some("1".repeat(64)),
            },
        )
        .unwrap();
    control
        .reject_native_before_start(
            "r1",
            NativeDispatchRejection {
                status: NativeDispatchRejectionStatus::Overloaded,
                reason: "Server overloaded; retry later.".to_string(),
                response_digest: "c".repeat(64),
                retry_safe_before_admission: true,
            },
        )
        .unwrap();
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let error = driver
        .run(
            &mut control,
            admission(),
            "prompt".to_string(),
            None,
            &CancellationToken::new(),
        )
        .await
        .expect_err("explicit rejection must be returned without reconnecting");
    assert!(
        error
            .to_string()
            .contains("explicitly rejected before start")
    );
    let record = control.native_record("r1").unwrap();
    assert_eq!(record.state, NativeReservationState::Released);
    assert!(record.dispatch_rejection.is_some());
    assert_eq!(record.observation, None);

    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn intelligence_handoff_is_committed_to_native_admission_identity() {
    let socket = std::path::Path::new("/tmp/native-owner.sock");
    let none = native_source_payload_digest("prompt", &None, socket, 5000, None).unwrap();
    let original = NativeIntelligenceRunBinding {
        run_id: "intelligence-run".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let bound =
        native_source_payload_digest("prompt", &None, socket, 5000, Some(&original)).unwrap();
    assert_ne!(none, bound);
    for field in 0..4 {
        let mut changed = original.clone();
        match field {
            0 => changed.run_id.push_str("-other"),
            1 => changed.expected_revision += 1,
            2 => changed.context_digest = "c".repeat(64),
            _ => changed.envelope_digest = "d".repeat(64),
        }
        assert_ne!(
            bound,
            native_source_payload_digest("prompt", &None, socket, 5000, Some(&changed)).unwrap()
        );
    }
    assert_eq!(
        none,
        digest(
            &serde_json::to_vec(&(
                "hepta.native-request.v1",
                "prompt",
                Option::<String>::None,
                socket,
                5000_u128,
            ))
            .unwrap()
        )
    );
}

fn running_journal(label: &str) -> (DurableInferenceControl, PathBuf) {
    let (driver, path) = fixture(label);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let request = request(&driver);
    let payload_digest = request.payload_digest.clone();
    control.reserve_native(request, 1).unwrap();
    control
        .dispatch_native(
            "r1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "a".repeat(64),
                owner_context_digest: None,
                codex_payload_digest: Some("d".repeat(64)),
                codex_request_digest: Some("b".repeat(64)),
                app_server_version: Some("1.2.3".to_string()),
                protocol_id: Some("codex.app-server.v2".to_string()),
                codex_source_admission_digest: Some(payload_digest),
                codex_home_digest: Some("f".repeat(64)),
                codex_connection_id: Some(9),
                codex_session_id: Some("session-1".to_string()),
                codex_deadline_ms: Some(10_000),
                codex_authority_epoch: Some(1),
                codex_revocation_revision: Some(1),
                codex_revocation_head_sha256: Some("2".repeat(64)),
                codex_authority_witness_sha256: Some("1".repeat(64)),
            },
        )
        .unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    (control, path)
}

fn reconciled_completion() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "complete provider output".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("c".repeat(64)),
    }
}

#[test]
fn terminal_reconciliation_preserves_durable_denials_after_reopening() {
    for (boundary_status, reason) in [
        (
            NativeBoundaryStatus::Quarantined,
            "completed agent message changed",
        ),
        (
            NativeBoundaryStatus::Quarantined,
            "output byte limit exceeded",
        ),
        (NativeBoundaryStatus::Cancelled, "cancelled"),
        (NativeBoundaryStatus::TimedOut, "deadline elapsed"),
    ] {
        let (mut control, path) = running_journal("denied-reconciliation");
        let pending = NativeRunOutput {
            status: NativeRunStatus::Indeterminate,
            boundary_status,
            terminal_observed: false,
            stop_reason: Some(reason.to_string()),
            observed_output_tokens: Some(7),
            codex_terminal_correlation_digest: None,
            ..reconciled_completion()
        };
        control.settle_native("r1", pending).unwrap();
        control.cancel_native("r1").unwrap();
        drop(control);

        let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
        let mut completed = reconciled_completion();
        retain_reconciliation_boundary(reopened.native_record("r1").unwrap(), &mut completed);
        let expected = NativeRunOutput {
            boundary_status,
            stop_reason: Some(reason.to_string()),
            observed_output_tokens: Some(7),
            ..reconciled_completion()
        };
        assert_eq!(completed, expected);
        assert!(!completed.succeeded());
        let settled = reopened.settle_native("r1", completed).unwrap();
        assert_eq!(settled.state, NativeReservationState::Released);
        assert_eq!(settled.observation, Some(expected));
        drop(reopened);
        let replayed = DurableInferenceControl::open(&path, 8).unwrap();
        assert_eq!(replayed.native_record("r1"), Some(&settled));
        drop(replayed);
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn cancellation_intent_without_an_observation_cannot_reconcile_to_success() {
    let (mut control, path) = running_journal("cancel-intent-reconciliation");
    control.cancel_native("r1").unwrap();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let record = reopened.native_record("r1").unwrap();
    assert_eq!(record.observation, None);
    let mut completed = reconciled_completion();
    retain_reconciliation_boundary(record, &mut completed);
    let expected = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Quarantined,
        stop_reason: Some(
            "durable cancellation requested; original boundary reason unavailable".to_string(),
        ),
        ..reconciled_completion()
    };
    assert_eq!(completed, expected);
    assert!(!completed.succeeded());
    let settled = reopened.settle_native("r1", completed).unwrap();
    assert_eq!(settled.observation, Some(expected));
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn ordinary_indeterminate_reconciliation_can_settle_with_retained_usage() {
    let (mut control, path) = running_journal("unknown-reconciliation");
    let pending = NativeRunOutput {
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        terminal_observed: false,
        stop_reason: Some("terminal observation not yet available".to_string()),
        observed_output_tokens: Some(7),
        codex_terminal_correlation_digest: None,
        ..reconciled_completion()
    };
    control.settle_native("r1", pending).unwrap();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let mut completed = reconciled_completion();
    retain_reconciliation_boundary(reopened.native_record("r1").unwrap(), &mut completed);
    let expected = NativeRunOutput {
        observed_output_tokens: Some(7),
        ..reconciled_completion()
    };
    assert_eq!(completed, expected);
    assert!(completed.succeeded());
    let settled = reopened.settle_native("r1", completed).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(settled.observation, Some(expected));
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn terminal_reconciliation_cannot_restore_a_durably_lost_owner() {
    let (mut control, path) = running_journal("lost-owner-reconciliation");
    let lost = NativeOwnerAuthority::Lost {
        reason: "owner fenced".to_string(),
    };
    let pending = NativeRunOutput {
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Quarantined,
        terminal_observed: false,
        owner_authority: lost.clone(),
        stop_reason: Some("owner fenced".to_string()),
        codex_terminal_correlation_digest: None,
        ..reconciled_completion()
    };
    control.settle_native("r1", pending).unwrap();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let mut completed = reconciled_completion();
    retain_reconciliation_boundary(reopened.native_record("r1").unwrap(), &mut completed);
    let expected = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Quarantined,
        owner_authority: lost,
        stop_reason: Some("owner fenced".to_string()),
        ..reconciled_completion()
    };
    assert_eq!(completed, expected);
    assert!(!completed.succeeded());
    let settled = reopened.settle_native("r1", completed).unwrap();
    assert_eq!(settled.observation, Some(expected));
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
