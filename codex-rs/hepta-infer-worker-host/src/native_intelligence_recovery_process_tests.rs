use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::AgentContextAttachment;
use codex_hepta_agentd::AgentRunSnapshot;
use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use core_test_support::responses;
use serde::Deserialize;
use serde::Serialize;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::NativeAdmission;
use crate::native_app_server::NativeWorkerConfig;
use crate::native_app_server::unix_time_ms;

use super::super::*;
use super::TERMINAL_PUBLICATION_HOOK;
use super::TerminalPublicationHook;

const CHILD_CASE_ENV: &str = "HEPTA_INTELLIGENCE_TERMINAL_RECOVERY_CASE";
const PROMPT: &str = "return the durable intelligence terminal marker";
const REQUEST_ID: &str = "intelligence-terminal-recovery";
const MODEL: &str = "mock-model";
const CRASH_EXIT: i32 = 75;

#[derive(Deserialize, Serialize)]
enum WorkerMode {
    CrashBeforePublication,
    Recover,
}

#[derive(Deserialize, Serialize)]
struct ChildCase {
    mode: WorkerMode,
    socket: PathBuf,
    agent: String,
    journal: PathBuf,
    authority: PathBuf,
    output: PathBuf,
    run: codex_hepta_agentd::AgentRunReconciliationState,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn settled_terminal_survives_worker_loss_before_agentd_publication() -> Result<()> {
    recovery_case(
        /*from_thread_read*/ false,
        "native_app_server::control::intelligence_recovery::tests::process::settled_terminal_survives_worker_loss_before_agentd_publication",
    )
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_app_server_terminal_reconciles_current_agentd_revision() -> Result<()> {
    recovery_case(
        /*from_thread_read*/ true,
        "native_app_server::control::intelligence_recovery::tests::process::retained_app_server_terminal_reconciles_current_agentd_revision",
    )
    .await
}

async fn recovery_case(from_thread_read: bool, test_name: &str) -> Result<()> {
    if let Some(path) = std::env::var_os(CHILD_CASE_ENV) {
        let case: ChildCase = serde_json::from_slice(&std::fs::read(path)?)?;
        return run_worker(case).await;
    }

    let server = responses::start_mock_server().await;
    let mut completed = responses::ev_completed("intelligence-recovery-response");
    completed["response"]["usage"]["output_tokens"] = serde_json::json!(17);
    completed["response"]["usage"]["total_tokens"] = serde_json::json!(17);
    let response_mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_response_created("intelligence-recovery-response"),
            responses::ev_assistant_message("intelligence-message", "durable terminal marker"),
            completed,
        ]),
    )
    .await;
    let directory = tempfile::Builder::new()
        .prefix("hitr-")
        .tempdir_in("/tmp")?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    let host = CognitiveTestHost::start(
        directory.path().join("host"),
        agent.clone(),
        MODEL,
        &format!("{}/v1", server.uri()),
        crate::native_app_server::tests::app_server_test_runtime_paths()?,
    )
    .await?;
    let owner = AgentdClient::new(
        host.control_socket().to_path_buf(),
        agent.clone(),
        /*spawn_generation*/ 1,
    )?;
    let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
    fence.extend_from_slice(agent.as_str().as_bytes());
    fence.extend_from_slice(&1_u64.to_be_bytes());
    fence.extend_from_slice(&1_u64.to_be_bytes());
    let snapshot = AgentRunSnapshot {
        run_id: "intelligence.terminal.run".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 9,
        generation: 1,
        fence_digest: Digest32::of_bytes(&fence).to_string(),
        deadline_ms: unix_time_ms()? + 120_000,
    };
    let admitted = owner.run_start(snapshot.clone()).await?;
    let run_id = snapshot.run_id.clone();
    owner
        .run_attach_context(
            admitted.revision,
            AgentContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
                context_digest: "a".repeat(64),
                compilation_receipt_digest: "b".repeat(64),
            },
        )
        .await?;
    let mut case = ChildCase {
        mode: WorkerMode::CrashBeforePublication,
        socket: host.control_socket().to_path_buf(),
        agent: agent.to_string(),
        journal: directory.path().join("worker.journal"),
        authority: directory.path().join("authority"),
        output: directory.path().join("recovered.json"),
        run: owner
            .run_reconciliation_state(run_id)
            .await?
            .ok_or("missing original admission snapshot")?,
    };
    run_child(directory.path(), test_name, &case, CRASH_EXIT).await?;
    let original = DurableInferenceControl::open(&case.journal, /*capacity*/ 8)?;
    let record = original
        .native_record(REQUEST_ID)
        .cloned()
        .ok_or("missing committed native terminal")?;
    let terminal = record
        .observation
        .clone()
        .ok_or("missing terminal observation")?;
    assert_eq!(record.state, NativeReservationState::Released);
    assert_eq!(
        record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.codex_deadline_ms),
        Some(case.run.snapshot.deadline_ms),
    );
    assert!(terminal.succeeded());
    assert_eq!(terminal.observed_output_tokens, Some(17));
    drop(original);

    let dispatched = owner
        .run_status(case.run.snapshot.run_id.clone())
        .await?
        .ok_or("missing run")?;
    assert_eq!(dispatched.phase, AgentRunPhase::Dispatched);
    assert!(!dispatched.terminal_observed);
    // Simulate the coordinator's normal uncertainty transition while the
    // worker is gone. Recovery must use this new revision, not the old attach.
    let uncertain = owner
        .run_observe_terminal(
            dispatched.run_id,
            dispatched.revision,
            AgentRunPhase::Indeterminate,
            /*terminal_observed*/ false,
        )
        .await?;
    if from_thread_read {
        // Keep an exact durable dispatch prefix; the new worker must obtain
        // terminal evidence from the real retained App Server thread/read.
        case.journal = directory.path().join("dispatch-prefix.journal");
        let mut prefix = DurableInferenceControl::open(&case.journal, /*capacity*/ 8)?;
        prefix.reserve_native(record.request, /*maximum_in_flight*/ 1)?;
        prefix.dispatch_native(
            REQUEST_ID,
            record.dispatch.ok_or("missing dispatch binding")?,
        )?;
        prefix.native_started(REQUEST_ID, terminal.turn_id.clone())?;
    }
    case.mode = WorkerMode::Recover;
    run_child(directory.path(), test_name, &case, /*expected_exit*/ 0).await?;
    let recovered: NativeRunOutput = serde_json::from_slice(&std::fs::read(&case.output)?)?;
    assert!(recovered.succeeded());
    assert_eq!(recovered.thread_id, terminal.thread_id);
    assert_eq!(recovered.turn_id, terminal.turn_id);
    assert_eq!(recovered.output, terminal.output);
    assert_eq!(
        recovered.observed_output_tokens,
        if from_thread_read { None } else { Some(17) }
    );
    let published = owner
        .run_status(case.run.snapshot.run_id.clone())
        .await?
        .ok_or("missing reconciled run")?;
    assert_eq!(published.phase, AgentRunPhase::Succeeded);
    assert!(published.terminal_observed);
    assert_eq!(published.revision, uncertain.revision + 1);
    assert_eq!(published.context_digest, case.run.receipt.context_digest);
    assert_eq!(
        published.compilation_receipt_digest,
        case.run.receipt.compilation_receipt_digest
    );
    assert_eq!(response_mock.requests().len(), 1);
    host.shutdown().await;
    Ok(())
}

async fn run_worker(case: ChildCase) -> Result<()> {
    let binding = NativeIntelligenceRunBinding {
        snapshot: case.run.snapshot,
        expected_revision: case.run.receipt.revision,
        context_digest: case
            .run
            .receipt
            .context_digest
            .ok_or("missing context digest")?,
        envelope_digest: case
            .run
            .receipt
            .compilation_receipt_digest
            .ok_or("missing envelope digest")?,
    };
    let mut driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: case.socket,
        agent_id: AgentId::parse(&case.agent)?,
        generation: 1,
        model: MODEL.to_string(),
        timeout: Duration::from_secs(180),
    })?;
    let mut control = DurableInferenceControl::open(&case.journal, /*capacity*/ 8)?;
    if matches!(case.mode, WorkerMode::CrashBeforePublication) {
        std::fs::create_dir_all(&case.authority)?;
        let (authorizer, _issuer) =
            crate::final_use_authorizer::tests::independent_test_authorizer(
                &case.authority,
                /*expected_claims*/ 1,
            )
            .await?;
        driver = driver.with_turn_start_authorizer(Arc::new(authorizer));
        let hook = Arc::new(TerminalPublicationHook {
            reached: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(),
        });
        *TERMINAL_PUBLICATION_HOOK.lock().expect("test hook lock") = Some(Arc::clone(&hook));
        let cancellation = CancellationToken::new();
        tokio::select! {
            result = driver.run_intelligence(
                &mut control,
                NativeAdmission { request_id: REQUEST_ID.to_string(), maximum_in_flight: 1 },
                PROMPT.to_string(),
                /*context_query*/ None,
                binding,
                &cancellation,
            ) => return Err(format!("worker returned before terminal fault point: {result:?}").into()),
            _ = hook.reached.notified() => {
                // No destructors run: the only recovery input is the native
                // journal already synced before the cross-owner acknowledgement.
                std::process::exit(CRASH_EXIT);
            }
        }
    }

    // Recovery intentionally has no final-use authorizer. It must only read
    // retained evidence and reconcile Agentd, never dispatch a second turn.
    let mut recovered = None;
    for _ in 0..2 {
        let output = driver
            .run_intelligence(
                &mut control,
                NativeAdmission {
                    request_id: REQUEST_ID.to_string(),
                    maximum_in_flight: 1,
                },
                PROMPT.to_string(),
                /*context_query*/ None,
                binding.clone(),
                &CancellationToken::new(),
            )
            .await?;
        if let Some(previous) = &recovered {
            assert_eq!(previous, &output);
        }
        assert_eq!(
            control
                .native_record(REQUEST_ID)
                .and_then(|record| record.observation.as_ref()),
            Some(&output),
        );
        recovered = Some(output);
    }
    std::fs::write(
        case.output,
        serde_json::to_vec(&recovered.ok_or("missing recovered output")?)?,
    )?;
    Ok(())
}

async fn run_child(
    root: &Path,
    test_name: &str,
    case: &ChildCase,
    expected_exit: i32,
) -> Result<()> {
    let case_path = root.join("child-case.json");
    std::fs::write(&case_path, serde_json::to_vec(case)?)?;
    let log_path = root.join("child.log");
    let log = std::fs::File::create(&log_path)?;
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--exact", test_name, "--nocapture"])
        .env(CHILD_CASE_ENV, &case_path)
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log))
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(45);
    loop {
        if let Some(status) = child.try_wait()? {
            assert_eq!(
                status.code(),
                Some(expected_exit),
                "{}",
                std::fs::read_to_string(log_path)?
            );
            return Ok(());
        }
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            return Err(format!(
                "worker child timed out: {}",
                std::fs::read_to_string(log_path)?
            )
            .into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}
