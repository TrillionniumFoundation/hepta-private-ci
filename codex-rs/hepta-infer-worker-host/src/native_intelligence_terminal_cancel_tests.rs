use super::*;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixListener;

fn observation_binding() -> NativeIntelligenceObservationBindingV1 {
    NativeIntelligenceObservationBindingV1 {
        run: NativeIntelligenceRunBinding {
            run_id: "run-a".to_string(),
            expected_revision: 2,
            context_digest: "a".repeat(64),
            envelope_digest: "b".repeat(64),
            prompt_digest: "d".repeat(64),
        },
        revision: 3,
        generation: 2,
    }
}

fn dispatched_receipt() -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: "run-a".to_string(),
        revision: 3,
        phase: AgentRunPhase::Dispatched,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 1,
        generation: 2,
        fence_digest: "c".repeat(64),
        deadline_ms: u64::MAX,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: false,
    }
}

#[tokio::test]
async fn same_phase_terminal_receipt_preserves_cancel_after_final_status_check() {
    let directory = tempfile::tempdir().unwrap();
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket).unwrap();
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
    let owner = AgentdClient::new(socket, agent_id.clone(), 1).unwrap();
    let mut guard = observation_binding();
    let server = tokio::spawn(async move {
        let mut receipt = dispatched_receipt();
        for index in 0..6 {
            let (stream, _) = listener.accept().await.unwrap();
            let (reader, mut writer) = stream.into_split();
            let mut line = String::new();
            BufReader::new(reader).read_line(&mut line).await.unwrap();
            let request: AgentdRequest = serde_json::from_str(&line).unwrap();
            assert_eq!(request.spawn_generation, 1);
            let payload = match request.method {
                AgentdMethod::RunStatus { run_id } if index == 0 => {
                    assert_eq!(run_id, receipt.run_id);
                    AgentdPayload::RunStatus {
                        run: Some(receipt.clone()),
                    }
                }
                AgentdMethod::RunObserveTerminal {
                    run_id,
                    expected_revision,
                    phase,
                    terminal_observed,
                } if index > 0 => {
                    assert_eq!(
                        (run_id, expected_revision, terminal_observed),
                        ("run-a".to_string(), 3, true)
                    );
                    assert_eq!(
                        phase,
                        if index == 5 {
                            AgentRunPhase::Cancelled
                        } else {
                            AgentRunPhase::Succeeded
                        }
                    );
                    // Between the status check and publication, RunCancel
                    // advanced to revision 4; another observer published the
                    // same physical terminal at revision 5. The coordinator's
                    // same-phase idempotent path returns that current receipt.
                    receipt.revision = 5;
                    receipt.phase = phase;
                    receipt.cancel_reason = Some("operator_request".to_string());
                    receipt.terminal_observed = true;
                    receipt.idempotent = true;
                    AgentdPayload::RunReceipt(receipt.clone())
                }
                method => panic!("unexpected final terminal RPC: {method:?}"),
            };
            let response = AgentdResponse {
                schema_version: request.schema_version,
                request_id: request.request_id,
                agent_id: agent_id.clone(),
                spawn_generation: 1,
                current_generation: 2,
                payload,
            };
            let mut bytes = serde_json::to_vec(&response).unwrap();
            bytes.push(b'\n');
            writer.write_all(&bytes).await.unwrap();
        }
    });
    let mut output = output();
    output.owner_authority = NativeOwnerAuthority::ObservedReady;
    assert!(
        observe_for_test(
            &mut output,
            terminal("thread-a", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    guard
        .revalidate_terminal(&owner, &mut output, Instant::now() + Duration::from_secs(2))
        .await;
    assert!(output.succeeded());
    let physical_observation = output.clone();
    let error = commit_intelligence_terminal(&owner, &guard.run, guard.revision, &output)
        .await
        .unwrap_err();
    assert_eq!(error.to_string(), LOCAL_CANCELLED);
    assert_eq!(output, physical_observation);
    for boundary in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        output.boundary_status = boundary;
        let observed = output.clone();
        commit_intelligence_terminal(&owner, &guard.run, guard.revision, &output)
            .await
            .unwrap();
        assert_eq!(output, observed);
        assert!(!output.succeeded());
    }
    let mut interrupted = super::output();
    interrupted.owner_authority = NativeOwnerAuthority::ObservedReady;
    assert!(
        observe_for_test(
            &mut interrupted,
            terminal("thread-a", "turn-a", TurnStatus::Interrupted)
        )
        .unwrap()
    );
    let observed = interrupted.clone();
    commit_intelligence_terminal(&owner, &guard.run, guard.revision, &interrupted)
        .await
        .unwrap();
    assert_eq!(interrupted, observed);
    assert!(!interrupted.succeeded());
    server.await.unwrap();
}

#[tokio::test]
async fn pre_send_control_gate_aborts_cancel_or_mixed_run_with_live_proof_and_persists_no_effect() {
    let mut cancelled = dispatched_receipt();
    cancelled.phase = AgentRunPhase::Cancelling;
    cancelled.revision = 4;
    cancelled.cancel_reason = Some("operator_request".to_string());
    let mut mixed = dispatched_receipt();
    mixed.generation = 3;
    for (receipt, expected_reason) in [
        (cancelled, Some(LOCAL_CANCELLED)),
        (
            mixed,
            Some("intelligence run identity changed during observation"),
        ),
        (dispatched_receipt(), None),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("agentd.sock");
        let listener = UnixListener::bind(&socket).unwrap();
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
        let owner = AgentdClient::new(socket, agent_id.clone(), 1).unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let (reader, mut writer) = stream.into_split();
            let mut line = String::new();
            BufReader::new(reader).read_line(&mut line).await.unwrap();
            let request: AgentdRequest = serde_json::from_str(&line).unwrap();
            assert_eq!(request.spawn_generation, 1);
            assert_eq!(
                request.method,
                AgentdMethod::RunStatus {
                    run_id: "run-a".to_string()
                }
            );
            let response = AgentdResponse {
                schema_version: request.schema_version,
                request_id: request.request_id,
                agent_id,
                spawn_generation: 1,
                current_generation: 2,
                payload: AgentdPayload::RunStatus { run: Some(receipt) },
            };
            let mut bytes = serde_json::to_vec(&response).unwrap();
            bytes.push(b'\n');
            writer.write_all(&bytes).await.unwrap();
        });
        let journal = directory.path().join("native.journal");
        let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 8).unwrap();
        let request = NativeRequest {
            request_id: "run-a".to_string(),
            principal_id: "agent-1".to_string(),
            worker_generation: 1,
            model: "provider-model".to_string(),
            payload_digest: "a".repeat(64),
        };
        control
            .reserve_native(request.clone(), /*maximum_in_flight*/ 1)
            .unwrap();
        let (prepared_dispatch, proof) = control
            .dispatch_native_with_pre_effect_abort(
                "run-a",
                NativeDispatch {
                    thread_id: "thread-a".to_string(),
                    model_provider: "provider".to_string(),
                    context_digest: "b".repeat(64),
                    owner_context_digest: Some("c".repeat(64)),
                    codex_payload_digest: Some("e".repeat(64)),
                    codex_request_digest: Some("c".repeat(64)),
                    app_server_version: Some("test-app-server".to_string()),
                    protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
                    codex_source_admission_digest: Some("f".repeat(64)),
                    codex_home_digest: Some("1".repeat(64)),
                    codex_connection_id: Some(7),
                    codex_session_id: Some("session-a".to_string()),
                    codex_deadline_ms: Some(10_000),
                    codex_authority_epoch: Some(9),
                    codex_revocation_revision: Some(3),
                    codex_revocation_head_sha256: Some("3".repeat(64)),
                    codex_authority_witness_sha256: Some("2".repeat(64)),
                },
            )
            .unwrap();
        let mut guard = observation_binding();
        let gated = guard
            .before_send(
                &owner,
                &mut control,
                proof,
                Instant::now() + Duration::from_secs(2),
            )
            .await;
        if let Some(expected_reason) = expected_reason {
            assert_eq!(gated.unwrap_err().to_string(), expected_reason);
        } else {
            // An unchanged owner cut preserves the same unconsumed proof.
            assert_eq!(control.native_record("run-a"), Some(&prepared_dispatch));
            control
                .abort_native_before_effect(gated.unwrap(), "test ended before send".to_string())
                .unwrap();
        }
        let stopped = control.native_record("run-a").unwrap().clone();
        assert_eq!(
            (
                stopped.state,
                stopped.turn_id.as_ref(),
                stopped.observation.as_ref(),
                stopped.pre_dispatch_stop.as_deref()
            ),
            (
                NativeReservationState::Released,
                None,
                None,
                Some(expected_reason.unwrap_or("test ended before send"))
            )
        );
        assert_eq!(stopped.request, request);
        drop(control);
        let mut reopened = DurableInferenceControl::open(&journal, /*capacity*/ 8).unwrap();
        assert_eq!(reopened.native_record("run-a"), Some(&stopped));
        assert_eq!(
            reopened
                .reserve_native(request, /*maximum_in_flight*/ 1)
                .unwrap(),
            stopped
        );
        server.await.unwrap();
    }
}
