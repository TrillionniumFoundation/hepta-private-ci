use super::super::NativeRunStatus;
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread".to_string(),
        model_provider: "provider".to_string(),
        context_digest: "b".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: Some("c".repeat(64)),
        codex_request_digest: Some("d".repeat(64)),
        app_server_version: Some("1".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some("a".repeat(64)),
        codex_home_digest: Some("e".repeat(64)),
        codex_connection_id: Some(1),
        codex_session_id: Some("session".to_string()),
        codex_deadline_ms: Some(1),
        codex_authority_epoch: Some(1),
        codex_revocation_revision: Some(1),
        codex_revocation_head_sha256: Some("f".repeat(64)),
        codex_authority_witness_sha256: Some("1".repeat(64)),
    }
}

fn terminal() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread".to_string(),
        turn_id: "turn".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "complete output".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("2".repeat(64)),
    }
}

#[test]
fn recovery_releases_capacity_without_losing_usage_or_denied_boundary() {
    for boundary in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("journal");
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        control.reserve_native(request("r1"), 1).unwrap();
        control.dispatch_native("r1", dispatch()).unwrap();
        control.native_started("r1", "turn".to_string()).unwrap();
        let mut previous = terminal();
        previous.status = NativeRunStatus::Indeterminate;
        previous.terminal_observed = false;
        previous.boundary_status = boundary;
        previous.observed_output_tokens = Some(42);
        previous.stop_reason = Some("original denied boundary".to_string());
        previous.codex_terminal_correlation_digest = None;
        if boundary == NativeBoundaryStatus::Quarantined {
            previous.owner_authority = NativeOwnerAuthority::Lost {
                reason: "owner fenced".to_string(),
            };
        }
        control.settle_native("r1", previous.clone()).unwrap();
        drop(control);
        let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
        let mut recovered = terminal();
        retain_observed_facts(
            &mut recovered,
            reopened.native_record("r1").unwrap().observation.as_ref(),
        );
        let mut expected = previous;
        expected.status = NativeRunStatus::Completed;
        expected.terminal_observed = true;
        expected.codex_terminal_correlation_digest = Some("2".repeat(64));
        assert_eq!(recovered, expected);
        assert!(!recovered.succeeded());
        assert_eq!(
            reopened.settle_native("r1", recovered).unwrap().state,
            NativeReservationState::Released
        );
        reopened.reserve_native(request("r2"), 1).unwrap();
    }
}

#[test]
fn elapsed_final_revalidation_releases_only_the_proven_unsent_dispatch() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("journal");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    assert!(send_budget_before_effect(&mut control, token, 1).is_err());
    let stopped = control.native_record("r1").unwrap().clone();
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert!(stopped.pre_dispatch_stop.is_some());
    assert_eq!(stopped.observation, None);
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&stopped));
    reopened.reserve_native(request("r2"), 1).unwrap();
}

#[cfg(unix)]
#[tokio::test]
async fn cached_terminal_reconciles_a_lost_agentd_ack_without_provider_replay() {
    use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
    use codex_hepta_agentd::AgentdMethod;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdRequest;
    use codex_hepta_agentd::AgentdResponse;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    use tokio::net::UnixListener;
    use tokio_util::sync::CancellationToken;

    for (boundary, expected_phase, acknowledged_phase) in [
        (
            NativeBoundaryStatus::Succeeded,
            AgentRunPhase::Succeeded,
            AgentRunPhase::Succeeded,
        ),
        (
            NativeBoundaryStatus::Cancelled,
            AgentRunPhase::Cancelled,
            AgentRunPhase::Cancelled,
        ),
        (
            NativeBoundaryStatus::TimedOut,
            AgentRunPhase::Cancelled,
            AgentRunPhase::Cancelled,
        ),
        (
            NativeBoundaryStatus::Quarantined,
            AgentRunPhase::Failed,
            AgentRunPhase::Failed,
        ),
        (
            NativeBoundaryStatus::Cancelled,
            AgentRunPhase::Cancelled,
            AgentRunPhase::Succeeded,
        ),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("agentd.sock");
        let listener = UnixListener::bind(&socket).unwrap();
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
        let binding = NativeIntelligenceRunBinding {
            run_id: "intelligence".to_string(),
            expected_revision: 1,
            context_digest: "3".repeat(64),
            envelope_digest: "4".repeat(64),
        };
        let driver = AppServerModelDriver::new(super::super::NativeWorkerConfig {
            agentd_socket: socket.clone(),
            agent_id: agent_id.clone(),
            generation: 1,
            model: "model".to_string(),
            timeout: Duration::from_secs(5),
        })
        .unwrap();
        let mut control =
            DurableInferenceControl::open(directory.path().join("journal"), 8).unwrap();
        let mut admitted = request("r1");
        admitted.principal_id = agent_id.to_string();
        admitted.payload_digest = super::super::control::digest(
            &serde_json::to_vec(&(
                "hepta.native-intelligence-request.v2",
                "prompt",
                Option::<String>::None,
                &socket,
                5000_u128,
                &binding.run_id,
                binding.expected_revision,
                &binding.context_digest,
                &binding.envelope_digest,
            ))
            .unwrap(),
        );
        control.reserve_native(admitted, 1).unwrap();
        control.dispatch_native("r1", dispatch()).unwrap();
        control.native_started("r1", "turn".to_string()).unwrap();
        let expected = NativeRunOutput {
            boundary_status: boundary,
            ..terminal()
        };
        control.settle_native("r1", expected.clone()).unwrap();
        let expected_binding = binding.clone();
        let server = tokio::spawn(async move {
            for step in 0..3 {
                let (stream, _) = listener.accept().await.unwrap();
                let (reader, mut writer) = stream.into_split();
                let mut line = String::new();
                BufReader::new(reader).read_line(&mut line).await.unwrap();
                let request: AgentdRequest = serde_json::from_str(&line).unwrap();
                if step == 1 {
                    let AgentdMethod::RunObserveTerminal {
                        expected_revision,
                        phase,
                        terminal_observed,
                        ..
                    } = request.method
                    else {
                        panic!("expected terminal publication");
                    };
                    assert_eq!(
                        (expected_revision, phase, terminal_observed),
                        (2, expected_phase, true)
                    );
                    // The owner commits, then the acknowledgement transport dies.
                    continue;
                }
                assert!(matches!(request.method, AgentdMethod::RunStatus { .. }));
                let receipt = AgentRunReceipt {
                    run_id: expected_binding.run_id.clone(),
                    revision: if step == 0 { 2 } else { 3 },
                    phase: if step == 0 {
                        AgentRunPhase::Dispatched
                    } else {
                        acknowledged_phase
                    },
                    context_digest: Some(expected_binding.context_digest.clone()),
                    compilation_receipt_digest: Some(expected_binding.envelope_digest.clone()),
                    authority_epoch: 1,
                    generation: 1,
                    fence_digest: "5".repeat(64),
                    deadline_ms: 1,
                    cancel_reason: None,
                    cancel_ack_deadline_ms: None,
                    terminal_observed: step == 2,
                    idempotent: step == 2,
                };
                let response = AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    agent_id: agent_id.clone(),
                    spawn_generation: 1,
                    current_generation: 1,
                    payload: AgentdPayload::RunStatus { run: Some(receipt) },
                };
                let mut bytes = serde_json::to_vec(&response).unwrap();
                bytes.push(b'\n');
                writer.write_all(&bytes).await.unwrap();
            }
            assert!(
                tokio::time::timeout(Duration::from_millis(50), listener.accept())
                    .await
                    .is_err()
            );
        });
        for attempt in 0..2 {
            let result = driver
                .run_intelligence(
                    &mut control,
                    super::super::NativeAdmission {
                        request_id: "r1".to_string(),
                        maximum_in_flight: 1,
                    },
                    "prompt".to_string(),
                    None,
                    binding.clone(),
                    &CancellationToken::new(),
                )
                .await;
            if attempt == 0 || expected_phase != acknowledged_phase {
                assert!(result.is_err());
            } else {
                assert_eq!(result.unwrap(), expected);
            }
            assert_eq!(
                control.native_record("r1").unwrap().observation,
                Some(expected.clone())
            );
        }
        server.await.unwrap();
    }
}
