//! Real Fleet, recovered SQLite host and activated durable Ledger fixtures.
//! Test metadata deliberately authorizes no fit; no user or Root consent claim.

use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SharedExperienceGrantV1;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::workspace_binding_digest;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::AgentdConfig;
use super::attach_production_operation_host;
use super::fixture::Fixture;
use crate::AgentdError;
use crate::AgentdSharedReplayHostV1;
use crate::PairedPreparationRegistration;
use crate::PairedRecordPinsV1;
use crate::PairedTerminalCompositionV1;
use crate::PairedTrainingMaterialManifestV1;
use crate::PairedTrainingPlanV1;
use crate::SharedTerminalCellError;
use crate::TerminalLearningBudgetV1;
use crate::TerminalLearningRequestV1;

#[allow(
    dead_code,
    reason = "reuse only the actual activated Ledger fixture for assembly controls"
)]
#[path = "../tests/support/terminal_cell_owner.rs"]
mod ledger_support;
use ledger_support::digest;
use ledger_support::id;
use ledger_support::sign;

fn ledger() -> (
    tempfile::TempDir,
    ledger_support::Fixture,
    Arc<Mutex<LedgerWriter>>,
) {
    // Use a unique test directory: including the shared fixture module must
    // not collide with its separate per-module serial in other native tests.
    let directory = tempfile::tempdir().unwrap();
    let fixture = ledger_support::Fixture {
        root: directory.path().join("factory-ledger"),
    };
    std::fs::create_dir(&fixture.root).unwrap();
    std::fs::File::create(fixture.root.join("ledger")).unwrap();
    std::fs::File::create(fixture.root.join("witness")).unwrap();
    let writer = fixture.writer();
    (directory, fixture, Arc::new(Mutex::new(writer)))
}

fn metadata(ledger: &Arc<Mutex<LedgerWriter>>) -> PairedTerminalCompositionV1 {
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: digest("fixture-failure"),
        failure_bytes: 1,
        correction_sha256: digest("fixture-correction"),
        correction_bytes: 1,
    };
    PairedTerminalCompositionV1 {
        original: PairedTrainingPlanV1 {
            preparation: PairedPreparationRegistration {
                study: digest("factory-study"),
                enrollment: digest("factory-enrollment"),
                frozen_materials: manifest.commitment().unwrap(),
                principal_id: "fixture.principal".into(),
                policy_generation: Generation::new(/*value*/ 1).unwrap(),
            },
            manifest,
            operation: digest("factory-original-operation"),
        },
        records: PairedRecordPinsV1 {
            failure_record_digest: digest("fixture-failure-canonical"),
            correction_record_digest: digest("fixture-correction-canonical"),
        },
        training: TerminalLearningRequestV1 {
            operation_id: id("factory-terminal-operation"),
            source_policy_id: Sha256Digest::for_bytes(b"not-a-grant"),
            expected_source_support_digest: digest("not-authorized-support"),
            expected_dataset_digest: digest("not-authorized-dataset"),
            dataset_plan: DatasetFreezePlanV2 {
                snapshot_id: id("factory-dataset"),
                objective_digest: digest("objective"),
                inclusion_policy_digest: digest("factory-inclusion"),
            },
            // This actual fixture signature covers deliberately different
            // bytes. Assembly accepts metadata; no training can use it.
            dataset_evidence: sign(
                ledger.lock().unwrap().verifier(),
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                b"factory-assembly-only-no-fit",
            ),
            profile: TerminalCellProfileV1 {
                artifact_id: id("factory-artifact"),
                producer_id: id("factory-producer"),
                generation: Generation::new(/*value*/ 1).unwrap(),
                sensor_id: id("fixture-state"),
                objective_digest: digest("objective"),
                run_snapshot_digest: digest("run-snapshot"),
                unit_profile_digest: digest("reward-units"),
                action_ids: vec![id("abstain")],
                minimum_samples_per_action: 1,
            },
            budget: TerminalLearningBudgetV1 {
                maximum_ledger_records: 64,
                maximum_dataset_records: 64,
                maximum_wall_milliseconds: 1_000,
                maximum_artifact_bytes: 1_048_576,
            },
            deadline_unix_seconds: 90,
        },
        failure_decision: digest("fixture-failure-decision"),
        failure_outcome: digest("fixture-failure-outcome"),
        correction_decision: digest("fixture-correction-decision"),
        correction_outcome: digest("fixture-correction-outcome"),
    }
}

fn end() -> tokio::time::Instant {
    tokio::time::Instant::now() + Duration::from_secs(/*secs*/ 30)
}

#[tokio::test]
async fn original_host_installs_fixed_policy_and_cannot_reset_owner_after_drop()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, _peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let original = config.production_writer_host().unwrap().writer();
    // Production operation attachment clones this host. A clone made before
    // assembly must share the same once-only claim after the first owner drops.
    let cloned_host = Arc::new(config.production_writer_host().unwrap().as_ref().clone());
    let identity = config.identity().clone();
    let (_directory, _ledger_fixture, ledger) = ledger();
    let before = ledger.lock().unwrap().snapshot()?;
    let pins = metadata(&ledger);
    let (mut config, handle, inbox) = config
        .with_original_terminal_learning_owners_v1(
            Arc::clone(&ledger),
            id("factory-producer"),
            "terminal.local".into(),
            /*maximum_jobs*/ 4,
            /*capacity*/ 1,
            pins.clone(),
            end(),
        )
        .await?;
    assert!(Arc::ptr_eq(
        &original,
        &config.production_writer_host().unwrap().writer()
    ));
    let bootstrap = config.take_terminal_learning_bootstrap().unwrap();
    bootstrap.require_identity(config.identity())?;
    bootstrap.require_original_paired_policy(&pins.original, pins.records)?;
    drop((bootstrap, handle, inbox));
    let result = config
        .with_original_terminal_learning_owners_v1(
            Arc::clone(&ledger),
            id("factory-producer"),
            "terminal.local".into(),
            /*maximum_jobs*/ 4,
            /*capacity*/ 1,
            pins.clone(),
            end(),
        )
        .await;
    assert!(
        matches!(result, Err(AgentdError::Invalid(message)) if message.contains("already assembled"))
    );
    let cloned_config = AgentdConfig::load(
        identity.fleet_root,
        identity.agent_id,
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root,
        identity.home_root,
        identity.workspace,
    )?
    .with_production_writer_host(cloned_host)?;
    let result = cloned_config
        .with_original_terminal_learning_owners_v1(
            Arc::clone(&ledger),
            id("factory-producer"),
            "terminal.local".into(),
            /*maximum_jobs*/ 4,
            /*capacity*/ 1,
            pins,
            end(),
        )
        .await;
    assert!(
        matches!(result, Err(AgentdError::Invalid(message)) if message.contains("already assembled"))
    );
    assert_eq!(ledger.lock().unwrap().snapshot()?, before);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn unavailable_or_configured_owner_and_deadline_refuse_before_live_verifier()
-> Result<(), Box<dyn Error>> {
    for case in 0..4 {
        let (mut config, fixture) = Fixture::new().await?;
        let (inputs, probes, _peer) = fixture.inputs()?;
        if case != 0 {
            attach_production_operation_host(&mut config, inputs).await?;
        }
        let (_directory, _ledger_fixture, ledger) = ledger();
        let pins = metadata(&ledger);
        if case == 3 {
            let (installed, _handle, _inbox) = config
                .with_original_terminal_learning_owners_v1(
                    Arc::clone(&ledger),
                    id("factory-producer"),
                    "terminal.local".into(),
                    /*maximum_jobs*/ 4,
                    /*capacity*/ 1,
                    pins.clone(),
                    end(),
                )
                .await?;
            config = installed;
        }
        let calls = probes.verifier.calls.load(Ordering::SeqCst);
        let deadline = match case {
            1 => tokio::time::Instant::now() - Duration::from_secs(/*secs*/ 1),
            2 => tokio::time::Instant::now() + Duration::from_secs(/*secs*/ 31),
            _ => end(),
        };
        let result = config
            .with_original_terminal_learning_owners_v1(
                ledger,
                id("factory-producer"),
                "terminal.local".into(),
                /*maximum_jobs*/ 4,
                /*capacity*/ 1,
                pins,
                deadline,
            )
            .await;
        assert!(result.is_err());
        assert_eq!(probes.verifier.calls.load(Ordering::SeqCst), calls);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn assembly_rechecks_original_live_authority_before_claim() -> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, _peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let calls = probes.verifier.calls.load(Ordering::SeqCst);
    probes
        .verifier
        .reject_at_call
        .store(calls + 2, Ordering::SeqCst);
    let (_directory, _ledger_fixture, ledger) = ledger();
    let pins = metadata(&ledger);
    let result = config
        .with_original_terminal_learning_owners_v1(
            ledger,
            id("factory-producer"),
            "terminal.local".into(),
            /*maximum_jobs*/ 4,
            /*capacity*/ 1,
            pins,
            end(),
        )
        .await;
    assert!(matches!(result, Err(AgentdError::ProductionWriter(_))));
    assert_eq!(probes.verifier.calls.load(Ordering::SeqCst), calls + 2);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    Ok(())
}

async fn grant_before_recovery(
    config: &AgentdConfig,
    fixture: &mut Fixture,
) -> Result<Sha256Digest, Box<dyn Error>> {
    let store = CognitiveStore::open(&config.identity().layout).await?;
    let access = CognitiveAccess::agent_private(config.identity().agent_id.clone());
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::PersistedToolResult,
                event_key: "factory.source".into(),
                content: b"fixture retained support".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "factory.memory".into(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "fixture retained support".into(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await?;
    let grant = store
        .grant_shared_experience(
            &access,
            &SharedExperienceGrantV1 {
                memory_id: memory.id.memory_id,
                memory_revision: memory.id.revision,
                consumer: FederationConsumerAccess::new(
                    config.identity().agent_id.clone(),
                    workspace_binding_digest(&config.identity().workspace),
                ),
                purpose: SharedExperiencePurposeV1::Replay {
                    parameter_scope: "terminal.local".into(),
                    artifact_consumer: config.identity().agent_id.clone(),
                },
                expires_at_unix_seconds: 4_000_000_000,
            },
            /*expected_revision*/ 0,
        )
        .await?;
    // The qualification recovery cut includes these actual pre-recovery rows.
    // The product factory never captures its own authorization or issues a grant.
    fixture.cut = store.recovery_anchor().await?;
    store.close().await;
    Ok(grant.policy_id().clone())
}

#[tokio::test]
async fn recovered_replay_checks_actual_workspace_and_both_live_writer_fences()
-> Result<(), Box<dyn Error>> {
    let (mut config, mut fixture) = Fixture::new().await?;
    let policy = grant_before_recovery(&config, &mut fixture).await?;
    let (inputs, probes, _peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config.production_writer_host().unwrap();
    let runtime = host.cognitive_runtime();
    let source = runtime.available_store().unwrap();
    let build = |workspace| {
        AgentdSharedReplayHostV1::from_original_production_owner(
            Arc::clone(source),
            FederationConsumerAccess::new(config.identity().agent_id.clone(), workspace),
            "terminal.local".into(),
            config.identity().agent_id.clone(),
            host.writer(),
        )
        .unwrap()
    };
    let replay = build(workspace_binding_digest(&config.identity().workspace));
    let original = replay.training_source(&policy).await?;
    assert!(
        build(Sha256Digest::for_bytes(b"different-workspace"))
            .training_source(&policy)
            .await
            .is_err()
    );
    for refuse_at in [1, 2] {
        let calls = probes.verifier.calls.load(Ordering::SeqCst);
        probes
            .verifier
            .reject_at_call
            .store(calls + refuse_at, Ordering::SeqCst);
        assert!(matches!(
            replay.training_source(&policy).await,
            Err(SharedTerminalCellError::Binding(
                "original production writer is not current"
            ))
        ));
        assert_eq!(
            probes.verifier.calls.load(Ordering::SeqCst),
            calls + refuse_at
        );
        probes
            .verifier
            .reject_at_call
            .store(/*val*/ 0, Ordering::SeqCst);
        assert_eq!(
            replay.training_source(&policy).await?.policy_id(),
            original.policy_id()
        );
    }
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    Ok(())
}
