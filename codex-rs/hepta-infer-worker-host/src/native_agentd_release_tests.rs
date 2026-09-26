//! Settled replay traverses the real Agentd client against a protocol fixture.
//! There is no model endpoint: any accidental physical dispatch must fail.
use super::*;
use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

fn settle(
    label: &str,
) -> (
    AppServerModelDriver,
    PathBuf,
    NativeRunOutput,
    tempfile::TempDir,
) {
    // macOS's default temp root can itself exhaust sockaddr_un.sun_path.
    let socket_root = tempfile::Builder::new()
        .prefix("ha-")
        .tempdir_in("/tmp")
        .unwrap();
    let (driver, path) =
        prepared_fixture_with_socket(label, true, Some(socket_root.path().join("owner.sock")));
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.native_started("r1", "turn-1".into()).unwrap();
    let output = NativeRunOutput {
        thread_id: "thread-1".into(),
        turn_id: "turn-1".into(),
        model: "model".into(),
        model_provider: "provider".into(),
        status: NativeRunStatus::Completed,
        boundary_status:
            codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Succeeded,
        output: "persisted answer".into(),
        observed_output_tokens: Some(3),
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("d".repeat(64)),
    };
    let settled = control.settle_native("r1", output.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    drop(control);
    (driver, path, output, socket_root)
}

fn receipt(binding: &NativeIntelligenceRunBinding) -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: binding.run_id.clone(),
        revision: 4,
        phase: AgentRunPhase::Succeeded,
        context_digest: Some(binding.context_digest.clone()),
        authority_epoch: 1,
        generation: 1,
        fence_digest: "a".repeat(64),
        deadline_ms: 9_999,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        compilation_receipt_digest: Some(binding.envelope_digest.clone()),
        terminal_observed: true,
        idempotent: false,
    }
}

#[tokio::test]
async fn durable_terminal_replay_releases_only_the_exact_agentd_projection() {
    for drop_release_reply in [false, true] {
        let (driver, path, expected, _socket_root) = settle("release-settled");
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let binding = control
            .native_record("r1")
            .unwrap()
            .prepared_input
            .as_ref()
            .unwrap()
            .intelligence
            .as_ref()
            .unwrap()
            .clone();
        let terminal = receipt(&binding);
        let socket = driver.config.agentd_socket.clone();
        let listener = tokio::net::UnixListener::bind(&socket).unwrap();
        let agent = driver.config.agent_id.clone();
        let server = tokio::spawn(async move {
            let mut seen = Vec::new();
            for index in 0..2 {
                let (stream, _) = listener.accept().await.unwrap();
                let (read, mut write) = stream.into_split();
                let mut bytes = Vec::new();
                BufReader::new(read)
                    .read_until(b'\n', &mut bytes)
                    .await
                    .unwrap();
                let request: AgentdRequest = serde_json::from_slice(&bytes).unwrap();
                let payload = match request.method {
                    AgentdMethod::RunStatus { run_id } if index == 0 => {
                        assert_eq!(run_id, binding.run_id);
                        seen.push("status");
                        AgentdPayload::RunStatus {
                            run: Some(terminal.clone()),
                        }
                    }
                    AgentdMethod::RunReleaseClosed {
                        run_id,
                        expected_revision,
                    } if index == 1 => {
                        assert_eq!(run_id, binding.run_id);
                        assert_eq!(expected_revision, terminal.revision);
                        seen.push("release");
                        if drop_release_reply {
                            return seen;
                        }
                        AgentdPayload::RunReceipt(terminal.clone())
                    }
                    other => panic!("unexpected operation during terminal replay: {other:?}"),
                };
                let response = AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    agent_id: agent.clone(),
                    spawn_generation: 1,
                    current_generation: 1,
                    payload,
                };
                let mut bytes = serde_json::to_vec(&response).unwrap();
                bytes.push(b'\n');
                write.write_all(&bytes).await.unwrap();
            }
            seen
        });
        let bytes_before = std::fs::read(&path).unwrap();
        let actual = driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(actual, expected);
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(5), server)
                .await
                .unwrap()
                .unwrap(),
            vec!["status", "release"]
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes_before);
        // A lost cleanup ACK or an unavailable Agentd cannot turn a settled
        // duplicate into a failed operation or another provider dispatch.
        assert_eq!(
            driver
                .resume(&mut control, admission(), &CancellationToken::new())
                .await
                .unwrap(),
            expected
        );
        drop(control);
        let _ = std::fs::remove_file(socket);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn mismatched_or_unresolved_agentd_rows_are_never_released() {
    for field in 0..6 {
        let (driver, path, expected, _socket_root) = settle("release-conflict");
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let binding = control
            .native_record("r1")
            .unwrap()
            .prepared_input
            .as_ref()
            .unwrap()
            .intelligence
            .as_ref()
            .unwrap()
            .clone();
        let mut terminal = receipt(&binding);
        match field {
            0 => terminal.context_digest = Some("f".repeat(64)),
            1 => terminal.compilation_receipt_digest = Some("f".repeat(64)),
            2 => terminal.generation += 1,
            3 => terminal.phase = AgentRunPhase::Indeterminate,
            4 => terminal.terminal_observed = false,
            _ => terminal.run_id.push_str("-other"),
        }
        let socket = driver.config.agentd_socket.clone();
        let listener = tokio::net::UnixListener::bind(&socket).unwrap();
        let agent = driver.config.agent_id.clone();
        let done = CancellationToken::new();
        let server_done = done.clone();
        let server = tokio::spawn(async move {
            let mut status_count = 0;
            loop {
                let (stream, _) = tokio::select! {
                    _ = server_done.cancelled() => return status_count,
                    result = listener.accept() => result.unwrap(),
                };
                let (read, mut write) = stream.into_split();
                let mut bytes = Vec::new();
                BufReader::new(read)
                    .read_until(b'\n', &mut bytes)
                    .await
                    .unwrap();
                let request: AgentdRequest = serde_json::from_slice(&bytes).unwrap();
                assert!(
                    matches!(request.method, AgentdMethod::RunStatus { .. }),
                    "a conflicting row must never be mutated"
                );
                status_count += 1;
                let response = AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    agent_id: agent.clone(),
                    spawn_generation: 1,
                    current_generation: 1,
                    payload: AgentdPayload::RunStatus {
                        run: Some(terminal.clone()),
                    },
                };
                let mut bytes = serde_json::to_vec(&response).unwrap();
                bytes.push(b'\n');
                write.write_all(&bytes).await.unwrap();
            }
        });
        let before = std::fs::read(&path).unwrap();
        let actual = driver
            .resume(&mut control, admission(), &CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(actual, expected);
        done.cancel();
        assert_eq!(server.await.unwrap(), 1);
        assert_eq!(std::fs::read(&path).unwrap(), before);
        drop(control);
        let _ = std::fs::remove_file(socket);
        std::fs::remove_file(path).unwrap();
    }
}
