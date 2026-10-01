// Malformed static owner RPC scripts must fail the recovery regression.
#![allow(clippy::unwrap_used)]

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

#[derive(Clone, Copy)]
enum RecoveryOwnerScenario {
    Attached,
    Dispatched,
    Cancelling,
    CancelledSucceeded,
    LostStartAck,
    CancelledUnknown,
    CancelAtPublication,
}

async fn serve_recovery_owner(
    listener: UnixListener,
    agent_id: AgentId,
    scenario: RecoveryOwnerScenario,
) {
    let (phase, revision, cancel_reason) = match scenario {
        RecoveryOwnerScenario::Attached => (AgentRunPhase::ContextAttached, 2, None),
        RecoveryOwnerScenario::Dispatched | RecoveryOwnerScenario::CancelAtPublication => {
            (AgentRunPhase::Dispatched, 3, None)
        }
        RecoveryOwnerScenario::Cancelling => {
            (AgentRunPhase::Cancelling, 4, Some("operator_request"))
        }
        RecoveryOwnerScenario::CancelledSucceeded => {
            (AgentRunPhase::Succeeded, 5, Some("operator_request"))
        }
        RecoveryOwnerScenario::LostStartAck => (AgentRunPhase::Indeterminate, 4, None),
        RecoveryOwnerScenario::CancelledUnknown => {
            (AgentRunPhase::Indeterminate, 5, Some("operator_request"))
        }
    };
    let mut run = AgentRunReceipt {
        run_id: "r1".to_string(),
        revision,
        phase,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 1,
        generation: 2,
        fence_digest: "c".repeat(64),
        deadline_ms: u64::MAX,
        cancel_reason: cancel_reason.map(str::to_string),
        cancel_ack_deadline_ms: None,
        terminal_observed: phase == AgentRunPhase::Succeeded,
        idempotent: false,
    };
    loop {
        let (stream, _) = listener.accept().await.unwrap();
        let (reader, mut writer) = stream.into_split();
        let mut line = String::new();
        BufReader::new(reader).read_line(&mut line).await.unwrap();
        let request: AgentdRequest = serde_json::from_str(&line).unwrap();
        assert_eq!(request.spawn_generation, 1);
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
                assert_eq!(run_id, run.run_id);
                assert_eq!(phase, AgentRunPhase::Succeeded);
                assert!(terminal_observed);
                if matches!(scenario, RecoveryOwnerScenario::CancelAtPublication) {
                    // Another observer records late Completed after RunCancel.
                    // The old revision is acknowledged by same-phase idempotence.
                    assert_eq!((expected_revision, run.revision), (3, 3));
                    run.cancel_reason = Some("operator_request".to_string());
                    run.phase = AgentRunPhase::Succeeded;
                    run.revision = 5;
                    run.idempotent = true;
                } else {
                    assert_eq!(expected_revision, run.revision);
                    run.idempotent = run.phase == phase;
                    if !run.idempotent {
                        run.revision += 1;
                    }
                    run.phase = phase;
                }
                run.terminal_observed = true;
                terminal = true;
                AgentdPayload::RunReceipt(run.clone())
            }
            method => panic!("recovery contacted an effect endpoint: {method:?}"),
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
        if terminal {
            return;
        }
    }
}

#[tokio::test]
async fn current_control_cancellation_stops_new_recovery_but_exact_rehydrated_attachment_is_allowed()
 {
    for scenario in [
        RecoveryOwnerScenario::Attached,
        RecoveryOwnerScenario::Dispatched,
        RecoveryOwnerScenario::Cancelling,
        RecoveryOwnerScenario::CancelledSucceeded,
        RecoveryOwnerScenario::LostStartAck,
        RecoveryOwnerScenario::CancelledUnknown,
    ] {
        let (driver, path, binding, intent) = recovery_fixture();
        let listener = UnixListener::bind(&driver.config.agentd_socket).unwrap();
        let server = tokio::spawn(serve_recovery_owner(
            listener,
            driver.config.agent_id.clone(),
            scenario,
        ));
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        assert!(!control.native_record("r1").unwrap().cancel_requested);
        let mut terminal = full_thread_read_terminal(&intent);
        let original_fact = (
            terminal.status,
            terminal.output.clone(),
            terminal.codex_terminal_correlation_digest.clone(),
        );
        driver
            .revalidate_intelligence_recovery_v1(
                control.native_record("r1").unwrap(),
                &binding,
                &mut terminal,
            )
            .await;
        let expected = match scenario {
            RecoveryOwnerScenario::Attached
            | RecoveryOwnerScenario::Dispatched
            | RecoveryOwnerScenario::LostStartAck => NativeBoundaryStatus::Succeeded,
            RecoveryOwnerScenario::Cancelling
            | RecoveryOwnerScenario::CancelledSucceeded
            | RecoveryOwnerScenario::CancelAtPublication => NativeBoundaryStatus::Cancelled,
            RecoveryOwnerScenario::CancelledUnknown => NativeBoundaryStatus::Quarantined,
        };
        assert_eq!(terminal.boundary_status, expected);
        assert_eq!(
            terminal.succeeded(),
            expected == NativeBoundaryStatus::Succeeded
        );
        assert_eq!(
            (
                terminal.status,
                terminal.output.clone(),
                terminal.codex_terminal_correlation_digest.clone()
            ),
            original_fact
        );
        assert_eq!(
            control
                .settle_native("r1", terminal.clone())
                .unwrap()
                .observation,
            Some(terminal)
        );
        server.await.unwrap();
        std::fs::remove_file(&driver.config.agentd_socket).unwrap();
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn fresh_recovery_publication_cancel_race_is_frozen_as_cancelled() {
    let (driver, path, binding, intent) = recovery_fixture();
    let listener = UnixListener::bind(&driver.config.agentd_socket).unwrap();
    let server = tokio::spawn(serve_recovery_owner(
        listener,
        driver.config.agent_id.clone(),
        RecoveryOwnerScenario::CancelAtPublication,
    ));
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert!(!control.native_record("r1").unwrap().cancel_requested);
    let mut terminal = full_thread_read_terminal(&intent);
    assert!(terminal.succeeded());
    let physical_fact = (
        terminal.status,
        terminal.output.clone(),
        terminal.codex_terminal_correlation_digest.clone(),
    );
    driver
        .revalidate_intelligence_recovery_v1(
            control.native_record("r1").unwrap(),
            &binding,
            &mut terminal,
        )
        .await;
    assert_eq!(terminal.boundary_status, NativeBoundaryStatus::Cancelled);
    assert!(!terminal.succeeded());
    assert_eq!(
        (
            terminal.status,
            terminal.output.clone(),
            terminal.codex_terminal_correlation_digest.clone()
        ),
        physical_fact
    );
    assert_eq!(
        control
            .settle_native("r1", terminal.clone())
            .unwrap()
            .observation,
        Some(terminal.clone())
    );
    server.await.unwrap();
    std::fs::remove_file(&driver.config.agentd_socket).unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        control.native_record("r1").unwrap().observation,
        Some(terminal.clone())
    );
    let cached = driver
        .reconcile_intelligence(
            &mut control,
            admission(),
            "prompt".to_string(),
            binding,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(cached.execution, terminal);
    assert!(cached.reconciliation_required);
    drop(control);
    std::fs::remove_file(path).unwrap();
}
