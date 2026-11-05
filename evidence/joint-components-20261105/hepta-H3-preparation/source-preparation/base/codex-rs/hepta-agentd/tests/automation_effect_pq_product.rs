#![cfg(target_os = "linux")]
//! One controlled real-process composition. The supervisor fences Draining
//! before its owned SIGKILL; this is not an unannounced power-loss or full-host
//! restore qualification. Fixture keys and services do not prove custody.

use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_agentd::AutomationEffectObservation;
use codex_hepta_agentd::AutomationEffectReconcileState;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_supervisor::SupervisorEventKind;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use codex_model_provider::PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER;
use core_test_support::responses;
use serde_json::Value;
use tokio::time::sleep;
use tokio::time::timeout;

mod support;
use support::fleet::AgentFixture;
use support::fleet::FleetHarness;
#[path = "support/automation_effect_binary.rs"]
mod binary;
#[path = "support/automation_effect_operator.rs"]
mod operator;
#[path = "support/automation_effect_provider.rs"]
mod provider;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c59";
const PROVIDER_SCOPE: &str = "provider/controlled-process-v1";
const DESTINATION: &str = "provider:controlled-process";
const WIRE: &[u8] = b"{\"effect\":\"deliver\"}";

fn expected_terminal_successor(fleet: &FleetHarness, agent: &AgentFixture) -> Result<u64> {
    let registry = fleet.registry.load()?;
    let record = registry
        .agent(&agent.agent_id)
        .context("registered owner")?;
    ensure!(
        matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ),
        "policy preparation requires an actually terminal owner"
    );
    ensure!(
        !fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .context("owner snapshot")?
            .active,
        "old process is still owned"
    );
    ensure!(
        !agent
            .layout
            .run_root()
            .join("supervisor-process.json")
            .exists(),
        "old exact process lease remains"
    );
    // With this single supervisor and no concurrent registry writers, the
    // original start_slot performs one CAS to Starting using this successor.
    // The actual leased spawn and process identity are checked after start.
    record
        .lifecycle
        .generation
        .checked_add(1)
        .context("generation overflow")
}

fn live_identity(
    fleet: &FleetHarness,
    agent: &AgentFixture,
    expected: u64,
    pid: u32,
) -> Result<()> {
    let snapshot = fleet
        .supervisor
        .snapshot(&agent.agent_id)
        .context("live supervisor snapshot")?;
    ensure!(
        snapshot.active
            && snapshot.spawn_generation == Some(expected)
            && snapshot.process_system_id == Some(u64::from(pid)),
        "actual owner PID/generation differs from the signed policy"
    );
    let lease: Value = serde_json::from_slice(&fs::read(
        agent.layout.run_root().join("supervisor-process.json"),
    )?)?;
    ensure!(
        lease["spawn_generation"] == serde_json::json!(expected)
            && lease["identity"]["system_id"] == serde_json::json!(pid),
        "durable process lease differs from supervisor and daemon"
    );
    Ok(())
}

async fn kill_owned_and_wait(fleet: &mut FleetHarness, agent: &AgentFixture) -> Result<Value> {
    fleet.supervisor.kill(&agent.agent_id)?;
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(
            report.faults.is_empty(),
            "owned kill faults: {:?}",
            report.faults
        );
        let snapshot = fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .context("killed owner snapshot")?;
        if !snapshot.active {
            let exit = snapshot
                .events
                .iter()
                .rev()
                .find_map(|event| match event.kind {
                    SupervisorEventKind::Exited(exit) => Some(exit),
                    _ => None,
                })
                .context("actual exit observation")?;
            ensure!(
                !exit.success && exit.code.is_none(),
                "owned daemon did not exit through the requested fatal signal"
            );
            ensure!(
                snapshot
                    .events
                    .iter()
                    .any(|event| event.kind == SupervisorEventKind::KillRequested),
                "supervisor did not record the owned kill"
            );
            let next = expected_terminal_successor(fleet, agent)?;
            return Ok(
                serde_json::json!({"requested_signal":"SIGKILL","supervisor_pre_fenced_draining":true,"observed_exit_success":exit.success,"observed_exit_code":exit.code,"exact_lease_removed":true,"next_starting_generation":next}),
            );
        }
        ensure!(
            Instant::now() < deadline,
            "owned daemon did not actually exit"
        );
        sleep(Duration::from_millis(10)).await;
    }
}

fn checkpoint(directory: &Path, name: &str, value: &Value) -> Result<()> {
    use std::io::Write;
    let path = directory.join(name);
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)?;
    file.write_all(&serde_json::to_vec_pretty(value)?)?;
    file.sync_all()?;
    fs::File::open(directory)?.sync_all()?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn pq_effect_survives_owned_agentd_kill_after_provider_fsync_without_resend() -> Result<()> {
    let source = binary::source_identity()?;
    let evidence_root = match std::env::var_os("HEPTA_PQ_EFFECT_PROCESS_EVIDENCE_DIR") {
        Some(path) => PathBuf::from(path),
        None => std::env::current_exe()?
            .parent()
            .context("test executable directory")?
            .join("pq-effect-process-evidence"),
    };
    ensure!(
        evidence_root.is_absolute(),
        "process witness directory must be absolute"
    );
    fs::create_dir_all(&evidence_root)?;
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let evidence = evidence_root.join(format!("{}-{stamp}", std::process::id()));
    fs::create_dir(&evidence)?;
    checkpoint(&evidence, "source.json", &source)?;
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT, "pq-effect-process-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let recovery_args = agent.recovery_args();
    let recovery_file = PathBuf::from(&recovery_args[1]);
    let recovery_trust = PathBuf::from(&recovery_args[3]);
    let initial_recovery = fs::read(&recovery_file)?;
    let initial_recovery_trust = fs::read(&recovery_trust)?;
    let provider = provider::LostAckProvider::start()?;
    let first_generation = expected_terminal_successor(&fleet, &agent)?;
    let mut owner = operator::Operator::new(&agent, first_generation, &provider.uri)?;
    let intent = AuthorizedEffectIntent {
        run_id: "controlled-process-effect-run".into(),
        step_id: "effect".into(),
        attempt: 1,
        operation_id: "provider.deliver".into(),
        subject_id: agent.agent_id.to_string(),
        destination_id: DESTINATION.into(),
        payload_digest: Sha256Digest::for_bytes(WIRE),
        final_use_scope_digest: owner.scope()?,
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    operator::prepare_effect(&agent, &intent, owner.now).await?;
    let grant = owner.grant(&intent)?;
    let key = ProviderEffectKey::for_taskflow_v2(
        PROVIDER_SCOPE,
        &agent.agent_id,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?;
    provider.expect(ProviderEffectIntent::new(
        key.clone(),
        intent.payload_digest.clone(),
    ))?;
    fleet.start_with_automation_effect_host_file(&agent, &owner.path)?;
    let (first, health) = fleet.wait_new_spawn(&agent, 0).await?;
    live_identity(&fleet, &agent, first_generation, health.process_id)?;
    let first_binary = binary::retain_live_daemon(
        health.process_id,
        first_generation,
        &agent,
        &evidence,
        &source,
    )?;
    checkpoint(&evidence, "first-process.json", &first_binary)?;
    let first = Arc::new(first);
    let dispatch_client = Arc::clone(&first);
    let dispatch_intent = intent.clone();
    let dispatch_grant = grant.clone();
    let dispatch = tokio::spawn(async move {
        dispatch_client
            .automation_execute_effect(
                dispatch_intent,
                WIRE,
                dispatch_grant,
                "controlled-lost-ack".into(),
            )
            .await
    });
    let deadline = Instant::now() + Duration::from_secs(10);
    while provider.applies.load(Ordering::SeqCst) != 1 {
        ensure!(
            !dispatch.is_finished(),
            "ordinary dispatch ended before the provider fsync barrier"
        );
        ensure!(
            Instant::now() < deadline,
            "provider never durably applied the operation"
        );
        sleep(Duration::from_millis(2)).await;
    }
    ensure!(
        !dispatch.is_finished(),
        "client already received a result before the crash window"
    );
    let applied: Value = serde_json::from_slice(&fs::read(&provider.record_path)?)?;
    ensure!(
        applied["effect_key"] == serde_json::json!(key.as_str())
            && applied["payload_sha256"] == serde_json::json!(intent.payload_digest.as_str()),
        "provider applied a different occurrence"
    );
    let claimed_frontier = *owner.frontier.frontier.lock().unwrap();
    checkpoint(
        &evidence,
        "provider-fsync-before-kill.json",
        &serde_json::json!({"provider_record":applied,"post_count":provider.posts.load(Ordering::SeqCst),"physical_apply_count":provider.applies.load(Ordering::SeqCst),"client_result_pending":true,"ack_bytes_sent":0,"authority_frontier":claimed_frontier}),
    )?;
    let killed = kill_owned_and_wait(&mut fleet, &agent).await?;
    provider.release_without_ack();
    ensure!(
        timeout(Duration::from_secs(3), dispatch).await??.is_err(),
        "killed daemon unexpectedly acknowledged the effect"
    );
    checkpoint(&evidence, "first-process-exit.json", &killed)?;
    ensure!(
        fs::read(&recovery_file)? == initial_recovery
            && fs::read(&recovery_trust)? == initial_recovery_trust,
        "fixture recovery authority was refreshed to bypass admission"
    );
    ensure!(
        *owner.frontier.frontier.lock().unwrap() == claimed_frontier,
        "external effect frontier reset across daemon death"
    );
    let second_generation = expected_terminal_successor(&fleet, &agent)?;
    ensure!(
        second_generation > first_generation,
        "recovery did not advance the owner generation"
    );
    owner.authorize_recovery_generation(second_generation)?;
    fleet.start_with_automation_effect_host_file(&agent, &owner.path)?;
    let (second, health2) = fleet.wait_new_spawn(&agent, first_generation).await?;
    live_identity(&fleet, &agent, second_generation, health2.process_id)?;
    let second_binary = binary::retain_live_daemon(
        health2.process_id,
        second_generation,
        &agent,
        &evidence,
        &source,
    )?;
    ensure!(
        (
            second_binary["pid"].clone(),
            second_binary["start_ticks"].clone()
        ) != (
            first_binary["pid"].clone(),
            first_binary["start_ticks"].clone()
        ),
        "recovery did not create a new process identity"
    );
    ensure!(
        second_binary["sha256"] == first_binary["sha256"],
        "restart selected another Agentd executable"
    );
    checkpoint(&evidence, "second-process.json", &second_binary)?;
    ensure!(
        first.health().await.is_err(),
        "old client generation crossed the new ordinary boundary"
    );
    ensure!(
        second
            .automation_execute_effect(
                intent.clone(),
                WIRE,
                grant.clone(),
                "old-generation-dispatch".into()
            )
            .await
            .is_err(),
        "old generation grant dispatched after restart"
    );
    ensure!(
        provider.posts.load(Ordering::SeqCst) == 1,
        "recovery resent the physical request"
    );
    let missing = second
        .automation_reconcile_effect(
            intent.run_id.clone(),
            intent.step_id.clone(),
            intent.attempt,
        )
        .await?;
    ensure!(
        missing.state == AutomationEffectReconcileState::Indeterminate && missing.effect.is_none(),
        "temporary lookup absence became permission to retry"
    );
    let observed = second
        .automation_reconcile_effect(
            intent.run_id.clone(),
            intent.step_id.clone(),
            intent.attempt,
        )
        .await?;
    ensure!(
        observed.state == AutomationEffectReconcileState::Terminal,
        "current owner did not recover the original operation"
    );
    let terminal = observed
        .effect
        .clone()
        .context("ordinary terminal readback")?;
    ensure!(
        terminal.observation == AutomationEffectObservation::Succeeded,
        "provider completion was lost"
    );
    let local = second
        .automation_reconcile_effect(
            intent.run_id.clone(),
            intent.step_id.clone(),
            intent.attempt,
        )
        .await?;
    ensure!(
        local == observed,
        "local terminal readback differs from the settled result"
    );
    ensure!(
        provider.posts.load(Ordering::SeqCst) == 1
            && provider.applies.load(Ordering::SeqCst) == 1
            && provider.lookups.load(Ordering::SeqCst) == 2,
        "unexpected send/application/lookup count"
    );
    ensure!(
        *owner.frontier.frontier.lock().unwrap() == claimed_frontier,
        "lookup consumed new dispatch authority or reset the frontier"
    );
    ensure!(
        fs::read(&recovery_file)? == initial_recovery
            && fs::read(&recovery_trust)? == initial_recovery_trust,
        "restart changed its original recovery evidence"
    );
    let second_exit = kill_owned_and_wait(&mut fleet, &agent).await?;
    let store = AutomationStore::open(&agent.layout).await?;
    let settled = store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .context("original durable effect attempt")?;
    let ack = settled
        .provider_ack
        .context("provider operation read back from durable owner")?;
    ensure!(
        ack.key == key
            && serde_json::json!(ack.provider_operation_id_sha256.as_str())
                == applied["provider_operation_id_sha256"],
        "durable receipt substituted another operation"
    );
    let receipt = store
        .read_terminal_authorized_taskflow_effect(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .context("durable terminal")?;
    ensure!(
        receipt.receipt_digest == terminal.receipt_digest,
        "ordinary readback differs from original durable terminal"
    );
    store.close().await;
    let used_nonces = owner.final_nonce_count(&agent)?;
    ensure!(
        used_nonces == 1,
        "original FinalUse nonce was lost or another one was consumed"
    );
    checkpoint(
        &evidence,
        "completed.json",
        &serde_json::json!({"scope":"controlled ordinary process composition; supervisor pre-fences before SIGKILL; no full-host restore or independent custody claim",
        "source":source,"first_process":first_binary,"second_process":second_binary,"provider_record":applied,
        "provider_ack":ack,"terminal":terminal,"post_count":1,"physical_apply_count":1,"lookup_count":2,"used_nonces":used_nonces,
        "frontier_retained":claimed_frontier,"frontier_cas_count":owner.frontier.cas_count.load(Ordering::SeqCst),"protected_fixture_clock":owner.clock.now.load(Ordering::SeqCst),"initial_evidence_frontier_sha256":Sha256Digest::for_bytes(&initial_recovery),"initial_evidence_trust_sha256":Sha256Digest::for_bytes(&initial_recovery_trust),"cleanup_exit":second_exit}),
    )?;
    Ok(())
}
