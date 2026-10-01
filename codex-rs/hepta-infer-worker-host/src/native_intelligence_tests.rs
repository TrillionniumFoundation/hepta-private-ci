use super::*;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

fn completed() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "model-a".to_string(),
        model_provider: "provider-a".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "observed prefix and recovered suffix".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some("a".repeat(64)),
    }
}

fn handoff() -> NativeIntelligenceRunBinding {
    NativeIntelligenceRunBinding {
        run_id: "run-a".to_string(),
        expected_revision: 2,
        context_digest: "b".repeat(64),
        envelope_digest: "c".repeat(64),
    }
}

fn dispatched() -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: "run-a".to_string(),
        revision: 3,
        phase: AgentRunPhase::Dispatched,
        context_digest: Some("b".repeat(64)),
        compilation_receipt_digest: Some("c".repeat(64)),
        authority_epoch: 1,
        generation: 8,
        fence_digest: "d".repeat(64),
        deadline_ms: unix_time_ms().unwrap() + 60_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    }
}

#[test]
fn recovered_completion_and_final_owner_check_keep_cancellation_or_loss_denied() {
    let cancelling = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Cancelling,
        cancel_reason: Some("operator cancelled while worker was stopped".to_string()),
        ..dispatched()
    };
    let mut revision = 3;
    let reason = verify_intelligence_receipt(8, &handoff(), &mut revision, &cancelling)
        .expect_err("an exact owner cancellation denies recovered success");
    let mut recovered = completed();
    apply_intelligence_failure(&mut recovered, reason);
    assert_eq!(
        recovered,
        NativeRunOutput {
            boundary_status: NativeBoundaryStatus::Cancelled,
            stop_reason: Some(LOCAL_CANCELLED.to_string()),
            ..completed()
        }
    );
    assert!(!recovered.succeeded());
    let lost = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Quarantined,
        owner_authority: NativeOwnerAuthority::Lost {
            reason: "owning generation fenced".to_string(),
        },
        stop_reason: Some("owning generation fenced".to_string()),
        ..completed()
    };
    let mut final_output = lost.clone();
    apply_intelligence_failure(&mut final_output, LOCAL_CANCELLED.to_string());
    assert_eq!(final_output, lost);
}

#[cfg(unix)]
#[tokio::test]
async fn live_owner_checks_pin_lifecycle_separately_from_transport_spawn() -> Result<()> {
    use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
    use codex_hepta_agentd::AgentdMethod;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdRequest;
    use codex_hepta_agentd::AgentdResponse;
    use codex_hepta_contracts::AgentId;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    use tokio::net::UnixListener;

    for (current_generation, run_generation, accepted) in [
        (8, 8, true),
        (8, 7, false),
        (9, 8, false),
        (9, 9, false),
        (6, 8, false),
        (0, 8, false),
    ] {
        let directory = tempfile::tempdir()?;
        let socket = directory.path().join("owner.sock");
        let listener = UnixListener::bind(&socket)?;
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
        let client = AgentdClient::new(socket, agent_id.clone(), 7)?;
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await?;
            let (reader, mut writer) = tokio::io::split(stream);
            let mut reader = BufReader::new(reader);
            let mut bytes = Vec::new();
            reader.read_until(b'\n', &mut bytes).await?;
            let request: AgentdRequest = serde_json::from_slice(&bytes)?;
            assert_eq!(request.spawn_generation, 7);
            assert_eq!(
                request.method,
                AgentdMethod::RunStatus {
                    run_id: "run-a".to_string()
                }
            );
            let response = AgentdResponse {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id,
                spawn_generation: 7,
                current_generation,
                payload: AgentdPayload::RunStatus {
                    run: Some(AgentRunReceipt {
                        generation: run_generation,
                        ..dispatched()
                    }),
                },
            };
            let mut bytes = serde_json::to_vec(&response)?;
            bytes.push(b'\n');
            writer.write_all(&bytes).await?;
            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        });
        let pinned = IntelligenceOwnerCursor {
            generation: 8,
            revision: 3,
        };
        let mut cursor = pinned;
        let result = verify_intelligence_execution(
            &client,
            &handoff(),
            &mut cursor,
            Instant::now() + RPC_TIMEOUT,
        )
        .await;
        assert_eq!(result.is_ok(), accepted);
        if current_generation < 7 {
            assert!(
                result
                    .as_ref()
                    .is_err_and(|reason| reason.contains("precedes its process spawn"))
            );
        }
        assert_eq!(cursor, pinned);
        let server_result = tokio::time::timeout(RPC_TIMEOUT, server).await?;
        server_result??;
    }
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn recovered_terminal_uses_current_owner_cas_and_denies_concurrent_revision() -> Result<()> {
    use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
    use codex_hepta_agentd::AgentdMethod;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdRequest;
    use codex_hepta_agentd::AgentdResponse;
    use codex_hepta_contracts::AgentId;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    use tokio::net::UnixListener;

    for reject_cas in [false, true] {
        let directory = tempfile::tempdir()?;
        let socket = directory.path().join("owner.sock");
        let listener = UnixListener::bind(&socket)?;
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
        let client = AgentdClient::new(socket, agent_id.clone(), 7)?;
        let server = tokio::spawn(async move {
            for index in 0..2 {
                let (stream, _) = listener.accept().await?;
                let (reader, mut writer) = tokio::io::split(stream);
                let mut reader = BufReader::new(reader);
                let mut bytes = Vec::new();
                reader.read_until(b'\n', &mut bytes).await?;
                let request: AgentdRequest = serde_json::from_slice(&bytes)?;
                let payload = match request.method {
                    AgentdMethod::RunStatus { run_id } if index == 0 => {
                        assert_eq!(run_id, "run-a");
                        AgentdPayload::RunStatus {
                            run: Some(dispatched()),
                        }
                    }
                    AgentdMethod::RunObserveTerminal {
                        run_id,
                        expected_revision,
                        phase,
                        terminal_observed,
                    } if index == 1 => {
                        assert_eq!(
                            (run_id, expected_revision, phase, terminal_observed),
                            ("run-a".to_string(), 3, AgentRunPhase::Succeeded, true)
                        );
                        if reject_cas {
                            AgentdPayload::Error {
                                code: "revision_conflict".to_string(),
                                message: "owner cancellation advanced to revision 4".to_string(),
                            }
                        } else {
                            AgentdPayload::RunReceipt(AgentRunReceipt {
                                revision: 4,
                                phase: AgentRunPhase::Succeeded,
                                terminal_observed: true,
                                idempotent: false,
                                ..dispatched()
                            })
                        }
                    }
                    _ => return Err("unexpected recovery owner request".into()),
                };
                let response = AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    agent_id: agent_id.clone(),
                    spawn_generation: 7,
                    current_generation: 8,
                    payload,
                };
                let mut bytes = serde_json::to_vec(&response)?;
                bytes.push(b'\n');
                writer.write_all(&bytes).await?;
            }
            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        });
        let mut output = completed();
        let result = reconcile_intelligence_terminal(
            &client,
            &handoff(),
            &mut output,
            Instant::now() + RPC_TIMEOUT,
            &CancellationToken::new(),
        )
        .await;
        if let Err(reason) = result {
            apply_intelligence_failure(&mut output, reason);
        }
        assert_eq!(output.succeeded(), !reject_cas);
        let server_result = tokio::time::timeout(RPC_TIMEOUT, server).await?;
        server_result??;
    }
    Ok(())
}
