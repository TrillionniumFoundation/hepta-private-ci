use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::Error as ControlError;
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
        snapshot: codex_hepta_agentd::AgentRunSnapshot {
            run_id: "intelligence-run".to_string(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 9,
            generation: 1,
            fence_digest: "5".repeat(64),
            deadline_ms: 10_000,
        },
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let bound =
        native_source_payload_digest("prompt", &None, socket, 5000, Some(&original)).unwrap();
    assert_ne!(none, bound);
    for field in 0..12 {
        let mut changed = original.clone();
        match field {
            0 => changed.snapshot.run_id.push_str("-other"),
            1 => changed.snapshot.request_digest = "6".repeat(64),
            2 => changed.snapshot.objective_digest = "6".repeat(64),
            3 => changed.snapshot.body_digest = "6".repeat(64),
            4 => changed.snapshot.artifact_set_digest = "6".repeat(64),
            5 => changed.snapshot.authority_epoch += 1,
            6 => changed.snapshot.generation += 1,
            7 => changed.snapshot.fence_digest = "6".repeat(64),
            8 => changed.snapshot.deadline_ms += 1,
            9 => changed.expected_revision += 1,
            10 => changed.context_digest = "c".repeat(64),
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

#[tokio::test]
async fn context_delivery_is_bound_before_connection_and_preserves_legacy_admission() {
    let (driver, path) = fixture("delivery-identity");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    let query = Some("private query".to_string());
    let expected = native_source_payload_digest(
        "prompt",
        &query,
        &driver.config.agentd_socket,
        driver.config.timeout.as_millis(),
        /*intelligence*/ None,
    )
    .unwrap();
    for (request_id, delivery) in [
        ("attached", NativeContextDelivery::Attach),
        ("withheld", NativeContextDelivery::Withhold),
    ] {
        let error = driver
            .run_with_context_delivery(
                &mut control,
                NativeAdmission {
                    request_id: request_id.to_string(),
                    maximum_in_flight: 1,
                },
                "prompt".to_string(),
                "private query".to_string(),
                delivery,
                &cancelled,
            )
            .await
            .unwrap_err();
        assert!(error.to_string().contains("cancelled before admission"));
        assert!(
            control
                .native_record(request_id)
                .unwrap()
                .dispatch
                .is_none()
        );
    }
    assert_eq!(
        control
            .native_record("attached")
            .unwrap()
            .request
            .payload_digest,
        expected
    );
    let withheld = control.native_record("withheld").unwrap().clone();
    assert_ne!(withheld.request.payload_digest, expected);
    let error = driver
        .run(
            &mut control,
            NativeAdmission {
                request_id: "withheld".to_string(),
                maximum_in_flight: 1,
            },
            "prompt".to_string(),
            query,
            &CancellationToken::new(),
        )
        .await
        .unwrap_err();
    assert_eq!(
        error.downcast_ref::<ControlError>(),
        Some(&ControlError::Conflict)
    );
    assert_eq!(control.native_record("withheld"), Some(&withheld));
    assert!(
        driver
            .run_with_context_delivery(
                &mut control,
                NativeAdmission {
                    request_id: "empty".to_string(),
                    maximum_in_flight: 1
                },
                "prompt".to_string(),
                String::new(),
                NativeContextDelivery::Withhold,
                &cancelled,
            )
            .await
            .is_err()
    );
    assert!(control.native_record("empty").is_none());
}

fn retained_input(driver: &AppServerModelDriver) -> NativePreparedInputV2 {
    NativePreparedInputV2 {
        schema_version: 2,
        prompt: "prompt".to_string(),
        context_query: None,
        agentd_socket: driver.config.agentd_socket.clone(),
        timeout_ms: driver.config.timeout.as_millis().try_into().unwrap(),
        intelligence: None,
    }
}

fn historical_dispatch() -> NativeDispatch {
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
    }
}

#[test]
fn retained_snapshot_roundtrips_all_fields_with_the_existing_v3_digest() {
    let (driver, _) = fixture("retained-digest");
    let binding = NativeIntelligenceRunBinding {
        snapshot: codex_hepta_agentd::AgentRunSnapshot {
            run_id: "original-run".to_string(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 9,
            generation: 7,
            fence_digest: "5".repeat(64),
            deadline_ms: 10_000,
        },
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let mut input = retained_input(&driver);
    input.intelligence = Some(binding.prepared_input());
    assert_eq!(
        input.payload_digest().unwrap(),
        native_source_payload_digest(
            &input.prompt,
            &input.context_query,
            &input.agentd_socket,
            u128::from(input.timeout_ms),
            Some(&binding),
        )
        .unwrap(),
    );
    let retained = input.intelligence.as_ref().unwrap();
    assert_eq!(
        serde_json::to_vec(&retained.snapshot).unwrap(),
        serde_json::to_vec(&binding.snapshot).unwrap(),
    );
    assert_eq!(
        NativeIntelligenceRunBinding::from_prepared_input(retained),
        binding,
    );
    // Match the existing request serializer without connecting to this path.
    // Platform transport limits remain the owner's existing connection rules.
    let mut long_path = input.clone();
    long_path.agentd_socket = input.agentd_socket.with_file_name("x".repeat(4097));
    assert!(long_path.agentd_socket.as_os_str().len() > 4096);
    assert_eq!(
        long_path.payload_digest().unwrap(),
        native_source_payload_digest(
            &long_path.prompt,
            &long_path.context_query,
            &long_path.agentd_socket,
            u128::from(long_path.timeout_ms),
            Some(&binding),
        )
        .unwrap(),
    );
    long_path.intelligence = None;
    assert_eq!(
        long_path.payload_digest().unwrap(),
        native_source_payload_digest(
            &long_path.prompt,
            &long_path.context_query,
            &long_path.agentd_socket,
            u128::from(long_path.timeout_ms),
            /*intelligence*/ None,
        )
        .unwrap(),
    );
    input.intelligence = None;
    assert_eq!(
        input.payload_digest().unwrap(),
        request(&driver).payload_digest
    );
}

#[tokio::test]
async fn resume_rejects_unknown_reserved_stopped_and_digest_only_without_io() {
    for kind in ["unknown", "reserved", "stopped", "digest-only"] {
        let (driver, path) = fixture(kind);
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        match kind {
            "unknown" => {}
            "digest-only" => {
                control
                    .reserve_native(request(&driver), /*maximum_in_flight*/ 1)
                    .unwrap();
                control
                    .dispatch_native("r1", historical_dispatch())
                    .unwrap();
            }
            _ => {
                control
                    .reserve_native_prepared_v2(
                        request(&driver),
                        /*maximum_in_flight*/ 1,
                        retained_input(&driver),
                    )
                    .unwrap();
                if kind == "stopped" {
                    control
                        .stop_native_before_dispatch("r1", "stopped".to_string())
                        .unwrap();
                }
            }
        }
        let bytes = control.qualification_file_bytes(1024 * 1024).unwrap();
        let record = control.native_record("r1").cloned();
        let error = driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .expect_err("a resume must not infer input or dispatch a reserved request");
        let expected = match kind {
            "unknown" => "existing durable",
            "digest-only" => "original retained V3 input",
            _ => "possibly dispatched",
        };
        assert!(error.to_string().contains(expected), "{kind}: {error}");
        assert_eq!(control.native_record("r1"), record.as_ref());
        assert_eq!(
            control.qualification_file_bytes(1024 * 1024).unwrap(),
            bytes
        );
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn resume_rejects_configuration_or_capacity_changes_before_reconciliation() {
    for field in [
        "agent",
        "generation",
        "model",
        "socket",
        "timeout",
        "capacity",
    ] {
        let (mut driver, path) = fixture(field);
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        control
            .reserve_native_prepared_v2(
                request(&driver),
                /*maximum_in_flight*/ 1,
                retained_input(&driver),
            )
            .unwrap();
        control
            .dispatch_native("r1", historical_dispatch())
            .unwrap();
        let record = control.native_record("r1").unwrap().clone();
        let bytes = control.qualification_file_bytes(1024 * 1024).unwrap();
        let mut selection = admission();
        match field {
            "agent" => {
                driver.config.agent_id =
                    AgentId::parse("00000000-0000-4000-8000-000000000002").unwrap()
            }
            "generation" => driver.config.generation += 1,
            "model" => driver.config.model.push_str("-other"),
            "socket" => driver.config.agentd_socket = path.with_extension("different-socket"),
            "timeout" => driver.config.timeout += Duration::from_millis(1),
            "capacity" => selection.maximum_in_flight += 1,
            _ => unreachable!(),
        }
        assert!(
            driver
                .resume(&mut control, selection, &CancellationToken::new())
                .await
                .is_err(),
            "{field}",
        );
        assert_eq!(control.native_record("r1"), Some(&record));
        assert_eq!(
            control.qualification_file_bytes(1024 * 1024).unwrap(),
            bytes
        );
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn resume_retains_uncertainty_and_never_dispatches_missing_terminal_evidence() {
    let (driver, path) = fixture("resume-unknown");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    control
        .reserve_native_prepared_v2(
            request(&driver),
            /*maximum_in_flight*/ 1,
            retained_input(&driver),
        )
        .unwrap();
    control
        .dispatch_native("r1", historical_dispatch())
        .unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let output = driver
        .resume(&mut control, admission(), &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
    assert!(!output.succeeded());
    assert_eq!(output.observed_output_tokens, None);
    assert_eq!(
        control.native_record("r1").unwrap().state,
        NativeReservationState::Indeterminate
    );
    let bytes = control.qualification_file_bytes(1024 * 1024).unwrap();
    assert_eq!(
        driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .unwrap(),
        output,
    );
    assert_eq!(
        control.qualification_file_bytes(1024 * 1024).unwrap(),
        bytes
    );
    assert!(
        control
            .reserve_native(
                NativeRequest {
                    request_id: "r2".to_string(),
                    ..request(&driver)
                },
                /*maximum_in_flight*/ 1
            )
            .is_err()
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}
