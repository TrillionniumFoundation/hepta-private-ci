use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
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

fn admitted_receipt(phase: AgentRunPhase) -> AgentRunReceipt {
    let dispatched = phase == AgentRunPhase::Dispatched;
    AgentRunReceipt {
        run_id: "intelligence-run".to_string(),
        revision: if dispatched { 3 } else { 2 },
        phase,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 9,
        generation: 7,
        fence_digest: "c".repeat(64),
        deadline_ms: 50_000,
        dispatch_binding_digest: dispatched.then(|| "d".repeat(64)),
        pre_effect_abort_commitment_digest: dispatched.then(|| "e".repeat(64)),
        pre_effect_abort_proof_digest: None,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: false,
    }
}

#[test]
fn agentd_admitted_binding_is_derived_from_durable_owner_state() {
    let attached = NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        admitted_receipt(AgentRunPhase::ContextAttached),
    )
    .unwrap();
    assert_eq!(attached.expected_revision, 2);
    assert_eq!(attached.context_digest, "a".repeat(64));
    assert_eq!(attached.envelope_digest, "b".repeat(64));

    let dispatched = NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        admitted_receipt(AgentRunPhase::Dispatched),
    )
    .unwrap();
    assert_eq!(dispatched, attached);
}

#[test]
fn agentd_admitted_binding_rejects_caller_minted_or_terminal_state() {
    let mut wrong_generation = admitted_receipt(AgentRunPhase::ContextAttached);
    assert!(
        NativeIntelligenceRunBinding::from_agentd_receipt(
            "intelligence-run",
            8,
            wrong_generation.clone(),
        )
        .is_err()
    );
    wrong_generation.run_id = "other-run".to_string();
    assert!(
        NativeIntelligenceRunBinding::from_agentd_receipt("intelligence-run", 7, wrong_generation,)
            .is_err()
    );

    let mut terminal = admitted_receipt(AgentRunPhase::Succeeded);
    terminal.terminal_observed = true;
    assert!(
        NativeIntelligenceRunBinding::from_agentd_receipt("intelligence-run", 7, terminal,)
            .is_err()
    );

    let mut malformed = admitted_receipt(AgentRunPhase::ContextAttached);
    malformed.context_digest = Some("A".repeat(64));
    assert!(
        NativeIntelligenceRunBinding::from_agentd_receipt("intelligence-run", 7, malformed,)
            .is_err()
    );

    let mut incomplete_dispatch = admitted_receipt(AgentRunPhase::Dispatched);
    incomplete_dispatch.pre_effect_abort_commitment_digest = None;
    assert!(
        NativeIntelligenceRunBinding::from_agentd_receipt(
            "intelligence-run",
            7,
            incomplete_dispatch,
        )
        .is_err()
    );
}
