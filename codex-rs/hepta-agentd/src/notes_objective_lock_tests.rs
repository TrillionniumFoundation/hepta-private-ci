//! Real Fleet/SQLite/coordinator regression with explicit fixture admission.
//! No Root or AuthBus signing authority is supplied by this negative fixture.
use super::*;
use crate::AgentdConfig;
use crate::AgentdProductionWriterHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

async fn fixture() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdConfig,
    AgentdState,
    Arc<AgentdProductionWriterHost>,
    RunStartRecordV1,
)> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c082")?;
    let record = registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = AgentdConfig::load(
        fleet.as_path().to_path_buf(),
        owner.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    let identity = config.identity();
    let store = CognitiveStore::open(&identity.layout).await?;
    let cut = store.recovery_anchor().await?;
    store.close().await;
    let authority = ProductionAuthorityLease::from_verified_parts(
        identity.agent_id.clone(),
        Sha256Digest::for_bytes(b"notes-lock-negative-fixture"),
        /*authority_epoch*/ 13,
        /*owner_epoch*/ 17,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(b"notes-lock-fixture-token".to_vec())?,
    )?;
    let expected = authority.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, owner: &AgentId| -> Result<(), String> {
            if lease == &expected && owner == &expected.agent_id {
                Ok(())
            } else {
                Err("fixture owner differs".into())
            }
        },
    );
    let host = Arc::new(
        AgentdProductionWriterHost::open_with_recovery(
            &config,
            CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
            authority,
            verifier,
            "notes-lock-fixture",
            /*lease_generation*/ 1,
        )
        .await?,
    );
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    let state = AgentdState::new(
        config.identity().clone(),
        registry,
        /*event_capacity*/ 16,
    )?;
    state.refresh_generation()?;
    state.attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
    state.attach_production_operations(host.clone())?;
    state.mark_runtime_prerequisites_ready()?;
    // Only readiness is supplied; this negative fixture supplies neither an
    // authenticated request nor any dispatch target/grant capability.
    state.mark_app_server_ready()?;
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let run_id = "notes.drain-lock.fixture";
    let payload = serde_json::to_string(&serde_json::json!({
        "schema_version": 1, "action": "replace_note", "operation_id": run_id,
        "destination_id": target.destination_id(), "target": target,
        "expected_revision": 0, "text": "fixture must remain queued"
    }))?;
    let operation = notes_operation_intent(
        &target,
        &payload,
        StableId::new(state.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )
    .map_err(anyhow::Error::msg)?;
    let source_digest = operation.semantic_digest();
    host.writer()
        .prepare_operation(operation, NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    let now_ms = unix_now_ms()?;
    let digest = Digest32::of_bytes(b"notes-lock-negative-fixture");
    let record = RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: StableId::new("fixture.expired.issuer")?,
            key_epoch: 1,
            message_id: StableId::new("fixture.expired.message")?,
            sequence: 1,
            expires_at_ms: 1,
            scope_digest: digest,
            signed_body_digest: digest,
            signature: [0; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: StableId::new("fixture.notes")?,
            profile_revision: 1,
            profile_digest: digest,
            supplied_source_digest: source_digest,
            intent_digest: digest,
            admitted_source_digest: digest,
            observed_at_unix_micros: now_ms * 1_000,
            deadline_unix_micros: (now_ms + 60_000) * 1_000,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: StableId::new(run_id)?,
            objective_digest: digest,
            hard_constraint_digest: digest,
            preference_state_digest: digest,
            model_tuple_digest: digest,
            prompt_registry_digest: digest,
            artifact_set_digest: digest,
            authority_epoch: 13,
            generation: 2,
            fence_digest: objective_run_fence(state.identity(), 2).parse()?,
        },
        runtime_body_digest: digest,
        objective_semantic_bytes: b"fixture".to_vec(),
        objective_function_v1_digest: digest,
        objective_function_v1_bytes: b"fixture".to_vec(),
    };
    state
        .notes_objective
        .set(AgentdNotesObjectiveConfig {
            profile_digest: digest,
            target,
        })
        .unwrap();
    state
        .runs
        .lock()
        .unwrap()
        .start_revalidated_run_start(now_ms, &record)
        .map_err(run_error)?;
    Ok((directory, config, state, host, record))
}

#[test]
fn notes_objective_drain_does_not_reenter_run_mutex() -> anyhow::Result<()> {
    const CHILD: &str = "state::notes_objective::lock_tests::notes_objective_drain_child";
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--exact", CHILD, "--ignored", "--nocapture"])
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if let Some(status) = child.try_wait()? {
            anyhow::ensure!(status.success(), "Notes drain child failed: {status}");
            break;
        }
        if Instant::now() >= deadline {
            // This is only the test-owned deadlock probe, never a compiler or
            // a product process. Reap it so a failing regression cannot hang CI.
            child.kill()?;
            child.wait()?;
            anyhow::bail!("Notes drain deadlocked while refreshing Fleet");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}

#[tokio::test]
#[ignore = "executed by bounded parent process"]
async fn notes_objective_drain_child() -> anyhow::Result<()> {
    let (_directory, _config, state, host, record) = fixture().await?;
    let anchor = host.writer().recovery_anchor().await?;
    state.registry.compare_and_transition(
        &state.identity().agent_id,
        /*expected_generation*/ 2,
        AgentLifecycle::Draining,
    )?;
    // Fleet has advanced while this process still holds cached Running and an
    // Admitted run. The old implementation deadlocks in this exact call.
    assert_eq!(
        state.runtime.lock().unwrap().lifecycle,
        AgentLifecycle::Running
    );
    assert!(state.execute_notes_objective(&record).await.is_err());
    let run = state
        .runs
        .lock()
        .unwrap()
        .run(record.snapshot.run_id.as_str())
        .unwrap();
    assert_eq!(run.phase, RunPhase::Cancelled);
    assert!(run.terminal_observed);
    assert_eq!(
        host.writer()
            .status(record.snapshot.run_id.as_str())
            .await?,
        LocalOutcomeState::Queued
    );
    assert_eq!(host.writer().recovery_anchor().await?, anchor);
    Ok(())
}

#[tokio::test]
async fn notes_objective_unknown_reads_original_owner_without_renewing_expired_admission()
-> anyhow::Result<()> {
    let (_directory, _config, state, host, record) = fixture().await?;
    // Existing unresolved work must still consult the original operation;
    // expired/missing AuthBus is not permission for a new dispatch.
    let now_ms = unix_now_ms()?;
    {
        let mut runs = state.runs.lock().unwrap();
        let current = runs.run(record.snapshot.run_id.as_str()).unwrap();
        let attached = runs
            .attach_context(
                now_ms,
                current.revision,
                ContextAttachment {
                    run_id: record.snapshot.run_id.to_string(),
                    request_digest: record.admission.admitted_source_digest.to_string(),
                    objective_digest: record.snapshot.objective_digest.to_string(),
                    body_digest: record.runtime_body_digest.to_string(),
                    artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
                    authority_epoch: record.snapshot.authority_epoch,
                    generation: record.snapshot.generation,
                    fence_digest: record.snapshot.fence_digest.to_string(),
                    deadline_ms: record.admission.deadline_unix_micros.div_ceil(1_000),
                    context_digest: Digest32::of_bytes(b"fixture.context").to_string(),
                    compilation_receipt_digest: record.objective_function_v1_digest.to_string(),
                },
            )
            .map_err(run_error)?;
        runs.mark_dispatched(now_ms, record.snapshot.run_id.as_str(), attached.revision)
            .map_err(run_error)?;
        runs.mark_unresolved_indeterminate("fixture")
            .map_err(run_error)?;
    }
    let anchor = host.writer().recovery_anchor().await?;
    state.execute_notes_objective(&record).await?;
    assert_eq!(
        host.writer()
            .status(record.snapshot.run_id.as_str())
            .await?,
        LocalOutcomeState::Queued
    );
    assert_eq!(host.writer().recovery_anchor().await?, anchor);
    Ok(())
}
