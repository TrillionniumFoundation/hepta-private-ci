use super::*;
use crate::native_app_server::NativeWorkerConfig;
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
    control.compact_journal().unwrap();
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
    control.compact_journal().unwrap();
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

fn prepared_fixture(label: &str, dispatch: bool) -> (AppServerModelDriver, PathBuf) {
    prepared_fixture_with_socket(label, dispatch, None)
}

fn prepared_fixture_with_socket(
    label: &str,
    dispatch: bool,
    socket: Option<PathBuf>,
) -> (AppServerModelDriver, PathBuf) {
    let (mut driver, path) = fixture(label);
    if let Some(socket) = socket {
        driver.config.agentd_socket = socket;
    }
    let binding = NativeIntelligenceRunBinding {
        run_id: "original-intelligence-run".to_string(),
        expected_revision: 2,
        context_digest: "b".repeat(64),
        envelope_digest: "c".repeat(64),
    };
    let input = NativePreparedInputV1 {
        schema_version: 1,
        prompt: "original prompt that the caller will not resend".to_string(),
        context_query: Some("original query".to_string()),
        agentd_socket: driver.config.agentd_socket.clone(),
        timeout_ms: 5_000,
        intelligence: Some(binding),
    };
    assert_eq!(
        input.payload_digest().unwrap(),
        native_source_payload_digest(
            &input.prompt,
            &input.context_query,
            &input.agentd_socket,
            u128::from(input.timeout_ms),
            input.intelligence.as_ref()
        )
        .unwrap()
    );
    let request = NativeRequest {
        payload_digest: input.payload_digest().unwrap(),
        ..request(&driver)
    };
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native_prepared(request, 1, input).unwrap();
    if dispatch {
        let dispatch = serde_json::from_value(serde_json::json!({
            "thread_id": "thread-1", "model_provider": "provider",
            "context_digest": "a".repeat(64)
        }))
        .unwrap();
        control.dispatch_native("r1", dispatch).unwrap();
    }
    control.compact_journal().unwrap();
    (driver, path)
}

#[tokio::test]
async fn resume_retains_original_intelligence_input_and_never_redispatches() {
    let (driver, path) = prepared_fixture("resume-original", true);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let original = control.native_record("r1").unwrap().prepared_input.clone();
    // No prompt, query or newly assembled Intelligence decision enters resume.
    // Connecting to the deliberately nonexistent socket would fail this test.
    let unknown = driver
        .resume(&mut control, admission(), &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(unknown.status, NativeRunStatus::Indeterminate);
    assert!(!unknown.terminal_observed);
    assert_eq!(
        control.native_record("r1").unwrap().prepared_input,
        original
    );
    let terminal = NativeRunOutput {
        turn_id: "turn-1".to_string(),
        status: NativeRunStatus::Failed,
        boundary_status:
            codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Failed,
        terminal_observed: true,
        stop_reason: Some("independently observed failure".to_string()),
        ..unknown
    };
    control.settle_native("r1", terminal.clone()).unwrap();
    control.compact_journal().unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .unwrap(),
        terminal
    );
    assert_eq!(
        control.native_record("r1").unwrap().prepared_input,
        original
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn resume_rejects_new_model_generation_endpoint_or_budget_without_mutation() {
    let (mut driver, path) = prepared_fixture("resume-drift", true);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let original = control.native_record("r1").unwrap().clone();
    let bytes = std::fs::read(&path).unwrap();
    let socket = driver.config.agentd_socket.clone();
    for field in ["model", "generation", "endpoint", "timeout"] {
        driver.config.model = "model".to_string();
        driver.config.generation = 1;
        driver.config.agentd_socket = socket.clone();
        driver.config.timeout = Duration::from_secs(5);
        match field {
            "model" => driver.config.model = "replacement-model".to_string(),
            "generation" => driver.config.generation = 2,
            "endpoint" => driver.config.agentd_socket = PathBuf::from("/tmp/replacement.sock"),
            "timeout" => driver.config.timeout = Duration::from_secs(6),
            _ => unreachable!(),
        }
        assert!(
            driver
                .resume(&mut control, admission(), &CancellationToken::new())
                .await
                .is_err(),
            "{field}"
        );
        assert_eq!(control.native_record("r1"), Some(&original));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn resume_cannot_turn_an_unsent_reservation_into_new_execution() {
    let (driver, path) = prepared_fixture("resume-unsent", false);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let original = control.native_record("r1").unwrap().clone();
    let bytes = std::fs::read(&path).unwrap();
    assert!(
        driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .is_err()
    );
    assert_eq!(control.native_record("r1"), Some(&original));
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    control
        .stop_native_before_dispatch("r1", "cancelled before effect".to_string())
        .unwrap();
    let stopped = control.native_record("r1").unwrap().clone();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert!(
        driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .is_err()
    );
    assert_eq!(control.native_record("r1"), Some(&stopped));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[path = "native_agentd_release_tests.rs"]
mod agentd_release_tests;
