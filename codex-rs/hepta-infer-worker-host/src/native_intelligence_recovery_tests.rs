use super::*;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixListener;

fn cached_fixture() -> (
    AppServerModelDriver,
    PathBuf,
    DurableInferenceControl,
    NativeIntelligenceRunBinding,
    NativeRunOutput,
) {
    let (driver, path) = fixture("intelligence-terminal-recovery");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let binding = NativeIntelligenceRunBinding {
        run_id: "r1".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
        prompt_digest: digest(b"prompt"),
    };
    let mut native = request(&driver);
    native.payload_digest = native_source_payload_digest(
        "prompt",
        &None,
        &driver.config.agentd_socket,
        driver.config.timeout.as_millis(),
        Some(&binding),
    )
    .unwrap();
    control.reserve_native(native, 1).unwrap();
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
    let output = NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status:
            codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Succeeded,
        output: "durable physical result".to_string(),
        observed_output_tokens: Some(17),
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("c".repeat(64)),
    };
    control.settle_native("r1", output.clone()).unwrap();
    (driver, path, control, binding, output)
}

async fn serve_owner(listener: UnixListener, initial: AgentRunPhase) -> AgentRunReceipt {
    let mut run = AgentRunReceipt {
        run_id: "r1".to_string(),
        revision: if initial == AgentRunPhase::ContextAttached {
            2
        } else {
            3
        },
        phase: initial,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 1,
        generation: 1,
        fence_digest: "d".repeat(64),
        deadline_ms: u64::MAX,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: initial == AgentRunPhase::Succeeded,
        idempotent: false,
    };
    loop {
        let (stream, _) = listener.accept().await.unwrap();
        let (reader, mut writer) = stream.into_split();
        let mut line = String::new();
        BufReader::new(reader).read_line(&mut line).await.unwrap();
        let request: AgentdRequest = serde_json::from_str(&line).unwrap();
        let mut terminal = false;
        let payload = match request.method {
            AgentdMethod::Health => AgentdPayload::Health(
                serde_json::from_value(serde_json::json!({
                    "promotion_ready": true, "ready": true, "fenced": false, "lifecycle": "running",
                    "process_id": 1, "workspace": "/tmp", "home_root": "/tmp", "run_root": "/tmp"
                }))
                .unwrap(),
            ),
            AgentdMethod::RunStatus { run_id } => {
                assert_eq!(run_id, run.run_id);
                AgentdPayload::RunStatus {
                    run: Some(run.clone()),
                }
            }
            AgentdMethod::RunMarkDispatched {
                run_id,
                expected_revision,
            } => {
                assert_eq!(
                    (run_id, expected_revision, run.phase),
                    (
                        run.run_id.clone(),
                        run.revision,
                        AgentRunPhase::ContextAttached
                    )
                );
                run.phase = AgentRunPhase::Dispatched;
                run.revision += 1;
                AgentdPayload::RunReceipt(run.clone())
            }
            AgentdMethod::RunObserveTerminal {
                run_id,
                expected_revision,
                phase,
                terminal_observed,
            } => {
                assert_eq!(
                    (run_id, expected_revision, phase, terminal_observed),
                    (
                        run.run_id.clone(),
                        run.revision,
                        AgentRunPhase::Succeeded,
                        true
                    )
                );
                run.idempotent = run.phase == phase;
                if !run.idempotent {
                    run.revision += 1;
                }
                run.phase = phase;
                run.terminal_observed = true;
                terminal = true;
                AgentdPayload::RunReceipt(run.clone())
            }
            method => panic!("recovery contacted an execution endpoint: {method:?}"),
        };
        let response = AgentdResponse {
            schema_version: request.schema_version,
            request_id: request.request_id,
            agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
            spawn_generation: request.spawn_generation,
            current_generation: 1,
            payload,
        };
        let mut bytes = serde_json::to_vec(&response).unwrap();
        bytes.push(b'\n');
        writer.write_all(&bytes).await.unwrap();
        if terminal {
            return run;
        }
    }
}

#[tokio::test]
async fn cached_terminal_reconciles_agentd_without_contacting_model() {
    for phase in [
        AgentRunPhase::ContextAttached,
        AgentRunPhase::Dispatched,
        AgentRunPhase::Indeterminate,
        AgentRunPhase::Succeeded,
    ] {
        let (driver, path, control, binding, expected) = cached_fixture();
        drop(control);
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let listener = UnixListener::bind(&driver.config.agentd_socket).unwrap();
        let server = tokio::spawn(serve_owner(listener, phase));
        let output = driver
            .reconcile_intelligence(
                &mut control,
                admission(),
                "prompt".to_string(),
                binding,
                &CancellationToken::new(),
            )
            .await
            .unwrap();
        assert_eq!(output.execution, expected);
        assert!(!output.reconciliation_required);
        assert_eq!(output.reconciliation_reason, None);
        assert_eq!(
            control.native_record("r1").unwrap().observation,
            Some(expected)
        );
        let terminal = tokio::time::timeout(Duration::from_secs(2), server)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            (terminal.phase, terminal.terminal_observed),
            (AgentRunPhase::Succeeded, true)
        );
        std::fs::remove_file(&driver.config.agentd_socket).unwrap();
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn unavailable_terminal_control_preserves_exact_native_observation() {
    let (driver, path, mut control, binding, expected) = cached_fixture();
    let output = driver
        .reconcile_intelligence(
            &mut control,
            admission(),
            "prompt".to_string(),
            binding,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(output.execution, expected);
    assert!(output.reconciliation_required);
    assert_eq!(
        output.reconciliation_reason,
        Some("terminal reconciliation owner unavailable")
    );
    assert_eq!(
        control.native_record("r1").unwrap().observation,
        Some(expected)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconciliation_only_cannot_create_a_native_reservation() {
    let (driver, path) = fixture("intelligence-no-replay");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let binding = NativeIntelligenceRunBinding {
        run_id: "r1".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
        prompt_digest: digest(b"prompt"),
    };
    let error = driver
        .reconcile_intelligence(
            &mut control,
            admission(),
            "prompt".to_string(),
            binding,
            &CancellationToken::new(),
        )
        .await
        .expect_err("fresh execution is forbidden");
    assert!(error.to_string().contains("exact durable dispatch"));
    assert_eq!(control.native_record("r1"), None);
    drop(control);
    std::fs::remove_file(path).unwrap();
}
