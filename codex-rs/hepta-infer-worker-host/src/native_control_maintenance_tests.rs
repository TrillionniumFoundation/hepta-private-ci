use super::*;
use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_infer_core::durable_control::native::NativeTerminalOwnerBinding;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixListener;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn prepare_dispatch(
    control: &mut DurableInferenceControl,
    id: &str,
) -> Result<NativePreEffectAbortToken> {
    control.reserve_native(
        NativeRequest {
            request_id: id.to_string(),
            principal_id: AGENT.to_string(),
            worker_generation: 1,
            model: "test-model".to_string(),
            payload_digest: "a".repeat(64),
        },
        2,
    )?;
    let dispatch = NativeDispatch {
        thread_id: format!("thread-{id}"),
        model_provider: "test-provider".to_string(),
        context_digest: "b".repeat(64),
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
    };
    let (_, token) = control.dispatch_native_with_pre_effect_abort_bound(
        id,
        dispatch,
        NativeTerminalOwnerBinding {
            run_id: format!("owner-{id}"),
            owner_dispatch_revision: 4,
            context_digest: "b".repeat(64),
            envelope_digest: "c".repeat(64),
        },
    )?;
    Ok(token)
}

fn prepare(control: &mut DurableInferenceControl, id: &str) -> Result<NativeRunRecord> {
    let token = prepare_dispatch(control, id)?;
    Ok(control.prepare_native_abort_before_effect(
        token,
        format!("owner-{id}"),
        4,
        "d".repeat(64),
        "final authorization refused".to_string(),
    )?)
}

fn prepare_terminal(control: &mut DurableInferenceControl, id: &str) -> Result<NativeRunRecord> {
    drop(prepare_dispatch(control, id)?);
    control.native_started(id, "turn-1".to_string())?;
    Ok(control.settle_native(
        id,
        NativeRunOutput {
            thread_id: format!("thread-{id}"),
            turn_id: "turn-1".to_string(),
            model: "test-model".to_string(),
            model_provider: "test-provider".to_string(),
            status: NativeRunStatus::Failed,
            boundary_status: NativeBoundaryStatus::Failed,
            output: String::new(),
            observed_output_tokens: Some(3),
            terminal_observed: true,
            stop_reason: Some("provider failed".to_string()),
            owner_authority: NativeOwnerAuthority::ObservedReady,
            codex_terminal_correlation_digest: None,
        },
    )?)
}

async fn serve_terminal(
    listener: &UnixListener,
    expected: &NativeRunRecord,
    owner_phase: AgentRunPhase,
) -> Result<()> {
    let owner = expected
        .terminal_owner
        .as_ref()
        .ok_or("terminal owner missing")?;
    let mut receipt = AgentRunReceipt {
        run_id: owner.run_id.clone(),
        revision: owner.owner_dispatch_revision,
        phase: AgentRunPhase::Dispatched,
        context_digest: Some(owner.context_digest.clone()),
        compilation_receipt_digest: Some(owner.envelope_digest.clone()),
        authority_epoch: 1,
        generation: 1,
        fence_digest: "e".repeat(64),
        deadline_ms: 1,
        dispatch_binding_digest: Some("d".repeat(64)),
        pre_effect_abort_commitment_digest: None,
        pre_effect_abort_proof_digest: None,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    };
    if owner_phase == AgentRunPhase::Failed {
        receipt.revision += 1;
        receipt.phase = AgentRunPhase::Failed;
        receipt.terminal_observed = true;
    }
    let (stream, _) = listener.accept().await?;
    let (reader, mut writer) = stream.into_split();
    let mut bytes = String::new();
    BufReader::new(reader).read_line(&mut bytes).await?;
    let request: AgentdRequest = serde_json::from_str(&bytes)?;
    match request.method {
        AgentdMethod::RunStatus { run_id } => assert_eq!(run_id, owner.run_id),
        other => panic!("terminal reconciliation issued an unexpected query: {other:?}"),
    }
    let response = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: request.request_id,
        agent_id: AgentId::parse(AGENT)?,
        spawn_generation: 1,
        current_generation: 1,
        payload: AgentdPayload::RunStatus { run: Some(receipt) },
    };
    let mut bytes = serde_json::to_vec(&response)?;
    bytes.push(b'\n');
    writer.write_all(&bytes).await?;
    if owner_phase == AgentRunPhase::Failed {
        return Ok(());
    }
    // Simulate Agentd committing the exact publication then losing its reply.
    let (stream, _) = listener.accept().await?;
    let mut bytes = String::new();
    BufReader::new(stream).read_line(&mut bytes).await?;
    let request: AgentdRequest = serde_json::from_str(&bytes)?;
    match request.method {
        AgentdMethod::RunObserveTerminal {
            run_id,
            expected_revision,
            phase,
            terminal_observed,
        } => {
            assert_eq!(
                (run_id, expected_revision, phase, terminal_observed),
                (
                    owner.run_id.clone(),
                    owner.owner_dispatch_revision,
                    AgentRunPhase::Failed,
                    true
                )
            );
        }
        other => panic!("terminal reconciliation issued an unexpected mutation: {other:?}"),
    }
    Ok(())
}

fn acknowledgement(record: &NativeRunRecord) -> Result<AgentRunReceipt> {
    let abort = record
        .pre_effect_abort
        .as_ref()
        .ok_or("abort proof missing")?;
    Ok(AgentRunReceipt {
        run_id: abort.owner_run_id.clone(),
        revision: abort.owner_dispatch_revision + 1,
        phase: AgentRunPhase::AbortedBeforeEffect,
        context_digest: Some("b".repeat(64)),
        compilation_receipt_digest: Some("c".repeat(64)),
        authority_epoch: 1,
        generation: 1,
        fence_digest: "e".repeat(64),
        deadline_ms: 1,
        dispatch_binding_digest: Some(abort.dispatch_binding_digest.clone()),
        pre_effect_abort_commitment_digest: Some(abort.commitment_digest.clone()),
        pre_effect_abort_proof_digest: Some(abort.proof_digest.clone()),
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: true,
    })
}

async fn serve_abort(
    listener: &UnixListener,
    expected: &NativeRunRecord,
    receipt: Option<AgentRunReceipt>,
) -> Result<()> {
    let (stream, _) = listener.accept().await?;
    let (reader, mut writer) = stream.into_split();
    let mut bytes = String::new();
    BufReader::new(reader).read_line(&mut bytes).await?;
    let request: AgentdRequest = serde_json::from_str(&bytes)?;
    let abort = expected
        .pre_effect_abort
        .as_ref()
        .ok_or("abort proof missing")?;
    match request.method {
        AgentdMethod::RunAbortBeforeEffect {
            run_id,
            expected_revision,
            dispatch_binding_digest,
            abort_nonce_hex,
            proof_digest,
            reason,
        } => {
            assert_eq!(
                (
                    run_id,
                    expected_revision,
                    dispatch_binding_digest,
                    abort_nonce_hex,
                    proof_digest,
                    reason
                ),
                (
                    abort.owner_run_id.clone(),
                    abort.owner_dispatch_revision,
                    abort.dispatch_binding_digest.clone(),
                    abort.abort_nonce_hex.clone(),
                    abort.proof_digest.clone(),
                    abort.reason.clone()
                )
            );
        }
        other => panic!("abort recovery issued an unexpected request: {other:?}"),
    }
    if let Some(receipt) = receipt {
        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: AgentId::parse(AGENT)?,
            spawn_generation: 1,
            current_generation: 1,
            payload: AgentdPayload::RunReceipt(receipt),
        };
        let mut bytes = serde_json::to_vec(&response)?;
        bytes.push(b'\n');
        writer.write_all(&bytes).await?;
    }
    Ok(())
}

fn driver(socket: std::path::PathBuf) -> Result<AppServerModelDriver> {
    AppServerModelDriver::new(super::super::NativeWorkerConfig {
        agentd_socket: socket,
        agent_id: AgentId::parse(AGENT)?,
        generation: 1,
        model: "test-model".to_string(),
        timeout: Duration::from_secs(1),
    })
}

#[tokio::test]
async fn lost_abort_ack_reopens_original_proof_and_retires_only_after_exact_ack() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket)?;
    let path = directory.path().join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 8)?;
    let pending = prepare(&mut control, "lost-ack")?;
    let mut driver = driver(socket)?;
    let server = serve_abort(&listener, &pending, None);
    let (receipt, served) = tokio::join!(
        driver.maintain_native_control(&mut control, Duration::from_secs(5)),
        server
    );
    served?;
    let receipt = receipt?;
    assert_eq!(
        (
            receipt.aborts_attempted,
            receipt.aborts_confirmed,
            receipt.aborts_unresolved
        ),
        (1, 0, 1)
    );
    assert_eq!(control.native_record("lost-ack"), Some(&pending));
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8)?;
    // An operator-selected provider model can change without granting a replay
    // of this old request or stranding its already persisted abort proof.
    driver.config.model = "new-provider-model".to_string();
    let server = serve_abort(&listener, &pending, Some(acknowledgement(&pending)?));
    let (receipt, served) = tokio::join!(
        driver.maintain_native_control(&mut control, Duration::from_secs(5)),
        server
    );
    served?;
    let receipt = receipt?;
    assert_eq!(
        (
            receipt.aborts_attempted,
            receipt.aborts_confirmed,
            receipt.aborts_unresolved
        ),
        (1, 1, 0)
    );
    assert_eq!(
        receipt
            .history
            .ok_or("maintenance history omitted")?
            .archived_records,
        1
    );
    let settled = control
        .native_record_resolved("lost-ack")?
        .ok_or("resolved native record missing")?;
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(settled.pre_effect_abort, pending.pre_effect_abort);
    assert!(settled.observation.is_none());
    assert!(settled.turn_id.is_none());
    assert!(control.native_record("lost-ack").is_none());
    assert_eq!(control.reserve_native(pending.request.clone(), 2)?, settled);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8)?;
    assert_eq!(control.reserve_native(pending.request, 2)?, settled);
    prepare(&mut control, "new-work")?;
    Ok(())
}

#[tokio::test]
async fn mismatched_abort_receipts_never_release_or_fabricate_an_observation() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket)?;
    let mut control = DurableInferenceControl::open(directory.path().join("control.journal"), 8)?;
    let pending = prepare(&mut control, "mismatch")?;
    let mut driver = driver(socket)?;
    for change in 0..8 {
        let mut ack = acknowledgement(&pending)?;
        match change {
            0 => ack.run_id = "different-owner".to_string(),
            1 => ack.generation += 1,
            2 => ack.revision += 1,
            3 => ack.phase = AgentRunPhase::Dispatched,
            4 => ack.dispatch_binding_digest = Some("f".repeat(64)),
            5 => ack.pre_effect_abort_commitment_digest = Some("f".repeat(64)),
            6 => ack.pre_effect_abort_proof_digest = Some("f".repeat(64)),
            7 => ack.terminal_observed = true,
            _ => unreachable!(),
        }
        let (receipt, served) = tokio::join!(
            driver.maintain_native_control(&mut control, Duration::from_secs(5)),
            serve_abort(&listener, &pending, Some(ack))
        );
        served?;
        let receipt = receipt?;
        assert_eq!(
            (
                receipt.aborts_attempted,
                receipt.aborts_confirmed,
                receipt.aborts_unresolved
            ),
            (1, 0, 1)
        );
        assert_eq!(control.native_record("mismatch"), Some(&pending));
        assert_eq!(
            receipt
                .history
                .ok_or("maintenance history omitted")?
                .archived_records,
            0
        );
    }
    Ok(())
}

#[tokio::test]
async fn acknowledged_history_retires_while_corrupt_cleanup_remains_unavailable() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket)?;
    std::fs::write(
        directory.path().join("runtime-codex-cleanup-v1.sqlite3"),
        b"corrupted independent cleanup store",
    )?;
    let mut control = DurableInferenceControl::open(directory.path().join("control.journal"), 8)?;
    let pending = prepare(&mut control, "original-ack")?;
    let mut driver = driver(socket)?;
    let (receipt, served) = tokio::join!(
        driver.maintain_native_control(&mut control, Duration::from_secs(5)),
        serve_abort(&listener, &pending, Some(acknowledgement(&pending)?))
    );
    served?;
    let receipt = receipt?;
    assert_eq!(receipt.aborts_confirmed, 1);
    assert_eq!(
        receipt
            .history
            .ok_or("maintenance history omitted")?
            .archived_records,
        1
    );
    assert!(receipt.cleanup.is_none());
    assert!(receipt.cleanup_error.is_some());
    assert!(driver.cleanup_owner.get().await.is_err());
    assert_eq!(
        control
            .native_record_resolved("original-ack")?
            .ok_or("resolved native record missing")?
            .state,
        NativeReservationState::Released
    );
    Ok(())
}

#[tokio::test]
async fn idle_owner_recovers_lost_terminal_publication_ack_then_archives_without_replaying_effect()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket)?;
    let path = directory.path().join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 8)?;
    let settled = prepare_terminal(&mut control, "terminal")?;
    let mut driver = driver(socket)?;
    let (receipt, served) = tokio::join!(
        driver.maintain_native_control(&mut control, Duration::from_secs(5)),
        serve_terminal(&listener, &settled, AgentRunPhase::Dispatched)
    );
    served?;
    let receipt = receipt?;
    assert_eq!(
        (
            receipt.terminal_publications_attempted,
            receipt.terminal_publications_acknowledged,
            receipt.terminal_publications_unresolved
        ),
        (1, 0, 1)
    );
    assert_eq!(
        receipt
            .history
            .ok_or("maintenance history omitted")?
            .archived_records,
        0
    );
    let pending = control
        .native_record("terminal")
        .ok_or("native terminal record missing")?
        .clone();
    assert!(
        pending
            .terminal_publication
            .as_ref()
            .ok_or("terminal publication missing")?
            .pending()
    );
    assert_eq!(pending.observation, settled.observation);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8)?;
    let (receipt, served) = tokio::join!(
        driver.maintain_native_control(&mut control, Duration::from_secs(5)),
        serve_terminal(&listener, &pending, AgentRunPhase::Failed)
    );
    served?;
    let receipt = receipt?;
    assert_eq!(
        (
            receipt.terminal_publications_attempted,
            receipt.terminal_publications_acknowledged,
            receipt.terminal_publications_unresolved
        ),
        (1, 1, 0)
    );
    assert_eq!(
        receipt
            .history
            .ok_or("maintenance history omitted")?
            .archived_records,
        1
    );
    assert!(control.native_record("terminal").is_none());
    let archived = control
        .native_record_resolved("terminal")?
        .ok_or("resolved native record missing")?;
    assert_eq!(archived.observation, settled.observation);
    assert!(
        !archived
            .terminal_publication
            .as_ref()
            .ok_or("terminal publication missing")?
            .pending()
    );
    assert_eq!(control.reserve_native(settled.request, 2)?, archived);
    Ok(())
}
