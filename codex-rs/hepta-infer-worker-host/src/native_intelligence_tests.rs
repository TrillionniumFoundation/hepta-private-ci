use super::*;

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

#[test]
fn intelligence_completed_after_local_stop_never_publishes_success() {
    for (boundary_status, expected_phase) in [
        (NativeBoundaryStatus::Succeeded, AgentRunPhase::Succeeded),
        (NativeBoundaryStatus::Failed, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Cancelled, AgentRunPhase::Cancelled),
        (NativeBoundaryStatus::Interrupted, AgentRunPhase::Cancelled),
        (NativeBoundaryStatus::TimedOut, AgentRunPhase::Failed),
        (NativeBoundaryStatus::Quarantined, AgentRunPhase::Failed),
    ] {
        let output = NativeRunOutput {
            boundary_status,
            ..completed()
        };
        assert_eq!(
            intelligence_terminal_phase(&output).unwrap(),
            expected_phase
        );
    }
    let denied = NativeRunOutput {
        stop_reason: Some("terminal publication requires reconciliation".to_string()),
        ..completed()
    };
    assert_eq!(
        intelligence_terminal_phase(&denied).unwrap(),
        AgentRunPhase::Failed
    );
    let unknown = NativeRunOutput {
        status: NativeRunStatus::Indeterminate,
        terminal_observed: false,
        ..completed()
    };
    assert!(intelligence_terminal_phase(&unknown).is_err());
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
        generation: 7,
        fence_digest: "d".repeat(64),
        deadline_ms: unix_time_ms().unwrap() + 60_000,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    }
}

#[test]
fn owner_cancellation_advances_only_the_exact_cursor_and_denies_execution() {
    let binding = handoff();
    let mut revision = 3;
    verify_intelligence_receipt(7, &binding, &mut revision, &dispatched()).unwrap();
    let cancelling = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Cancelling,
        cancel_reason: Some("operator cancelled at the owner".to_string()),
        ..dispatched()
    };
    assert_eq!(
        verify_intelligence_receipt(7, &binding, &mut revision, &cancelling),
        Err(LOCAL_CANCELLED.to_string())
    );
    assert_eq!(revision, 4);
    // Terminal observation must use the accepted cancellation revision, while
    // physical Completed remains separate from the local Cancelled boundary.
    let completed_after_cancel = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Cancelled,
        ..completed()
    };
    assert_eq!(
        intelligence_terminal_phase(&completed_after_cancel).unwrap(),
        AgentRunPhase::Cancelled
    );
}

#[test]
fn newer_or_mixed_owner_receipts_never_replace_the_dispatch_cursor() {
    for field in 0..6 {
        let mut receipt = dispatched();
        match field {
            0 => receipt.run_id = "other-run".to_string(),
            1 => receipt.generation += 1,
            2 => receipt.context_digest = Some("d".repeat(64)),
            3 => receipt.compilation_receipt_digest = Some("e".repeat(64)),
            4 => receipt.revision += 1,
            _ => receipt.phase = AgentRunPhase::Succeeded,
        }
        let mut revision = 3;
        assert!(verify_intelligence_receipt(7, &handoff(), &mut revision, &receipt).is_err());
        assert_eq!(revision, 3);
    }
    let mut stale = dispatched();
    stale.revision = 2;
    stale.phase = AgentRunPhase::Cancelling;
    stale.cancel_reason = Some("stale cancellation".to_string());
    let mut revision = 3;
    assert!(verify_intelligence_receipt(7, &handoff(), &mut revision, &stale).is_err());
    assert_eq!(revision, 3);
}

#[test]
fn owner_deadline_denies_a_still_dispatched_receipt_before_monitor_tick() {
    let expired = AgentRunReceipt {
        deadline_ms: unix_time_ms().unwrap().saturating_sub(1),
        ..dispatched()
    };
    let mut revision = 3;
    assert_eq!(
        verify_intelligence_receipt(7, &handoff(), &mut revision, &expired),
        Err(LOCAL_DEADLINE_ELAPSED.to_string())
    );
    assert_eq!(revision, 3);
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
    let reason = verify_intelligence_receipt(7, &handoff(), &mut revision, &cancelling)
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

#[test]
fn recovery_accepts_owner_commit_before_local_settlement_after_deadline() {
    // Agentd terminal publication can commit just before the worker crashes
    // without writing local settlement. Recovery observes that existing effect;
    // it is not asking for another live dispatch permit.
    let owner_committed = AgentRunReceipt {
        revision: 4,
        phase: AgentRunPhase::Succeeded,
        terminal_observed: true,
        deadline_ms: unix_time_ms().unwrap().saturating_sub(1),
        ..dispatched()
    };
    verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &completed()).unwrap();
    let mut revision = 3;
    assert!(verify_intelligence_receipt(7, &handoff(), &mut revision, &owner_committed).is_err());
    assert_eq!(revision, 3);
    let denied = NativeRunOutput {
        boundary_status: NativeBoundaryStatus::Quarantined,
        owner_authority: NativeOwnerAuthority::Lost {
            reason: "previous durable owner loss".to_string(),
        },
        ..completed()
    };
    assert!(
        verify_intelligence_recovery_receipt(7, &handoff(), &owner_committed, &denied).is_err()
    );
    assert!(
        verify_intelligence_recovery_receipt(8, &handoff(), &owner_committed, &completed())
            .is_err()
    );
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
                    current_generation: 7,
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
            7,
            &handoff(),
            &mut output,
            Instant::now() + RPC_TIMEOUT,
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
