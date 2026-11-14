//! Real native owner and Memory fixtures; locally scoped test keys are not
//! production training or adoption evidence.

use std::future::Future;
use std::future::poll_fn;
use std::sync::Arc;
use std::sync::Mutex;
use std::task::Poll;

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
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
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

use crate::AgentdSharedReplayHostV1;
use crate::AgentdTerminalLearningOwnerV1;
use crate::TerminalLearningBudgetV1;
use crate::TerminalLearningErrorV1;
use crate::TerminalLearningRequestV1;
use crate::terminal_learning_channel_v1;

use super::AgentdFixture;
#[path = "../tests/support/terminal_cell_owner.rs"]
mod ledger_support;
use ledger_support::Fixture;
use ledger_support::decision;
use ledger_support::digest;
use ledger_support::id;
use ledger_support::outcome;
use ledger_support::sign;

struct FixtureOwners {
    _memory_root: TempDir,
    ledger_root: Fixture,
    daemon: AgentdFixture,
    ledger: Arc<Mutex<LedgerWriter>>,
    source: Arc<CognitiveStore>,
    access: CognitiveAccess,
    grant: SharedExperienceUseV1,
    replay: Arc<AgentdSharedReplayHostV1>,
    request: TerminalLearningRequestV1,
}

impl FixtureOwners {
    async fn new() -> Self {
        let daemon = AgentdFixture::new();
        let root = tempfile::tempdir().unwrap();
        let fleet = HeptaFleetRoot::parse(root.path().canonicalize().unwrap())
            .unwrap()
            .layout();
        let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000011").unwrap();
        let source = Arc::new(CognitiveStore::open(&fleet.agent(&owner_id)).await.unwrap());
        let access = CognitiveAccess::agent_private(owner_id);
        let consumer = FederationConsumerAccess::new(
            daemon.identity.agent_id.clone(),
            Sha256Digest::for_bytes(b"terminal-workspace"),
        );
        let citation = source
            .append_source(
                &access,
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::PersistedToolResult,
                    event_key: "terminal.source".into(),
                    content: b"observed terminal training support".to_vec(),
                    observed_at_unix_seconds: 100,
                },
            )
            .await
            .unwrap();
        let memory = source
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: "terminal.memory".into(),
                    revision: MemoryRevisionDraft {
                        scope: CognitiveScope::AgentPrivate,
                        content: "observed terminal training support".into(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await
            .unwrap();
        let real_now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;
        let grant = source
            .grant_shared_experience(
                &access,
                &SharedExperienceGrantV1 {
                    memory_id: memory.id.memory_id,
                    memory_revision: memory.id.revision,
                    consumer: consumer.clone(),
                    purpose: SharedExperiencePurposeV1::Replay {
                        parameter_scope: "terminal.local".into(),
                        artifact_consumer: daemon.identity.agent_id.clone(),
                    },
                    expires_at_unix_seconds: real_now + 3600,
                },
                /*expected_revision*/ 0,
            )
            .await
            .unwrap();
        let support: Digest32 = grant.source_support_digest().as_str().parse().unwrap();
        let ledger_root = Fixture::new();
        let mut ledger = ledger_root.writer();
        collect(
            &mut ledger,
            "sample.read",
            "read",
            FixedQ32::ONE.raw(),
            support,
        );
        collect(
            &mut ledger,
            "sample.stop",
            "abstain",
            /*value*/ 0,
            support,
        );
        let dataset_plan = DatasetFreezePlanV2 {
            snapshot_id: id("terminal.dataset"),
            objective_digest: digest("objective"),
            inclusion_policy_digest: digest("all-active-owner-episodes"),
        };
        let evidence = sign(
            ledger.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&ledger.snapshot().unwrap(), &dataset_plan).unwrap(),
        );
        let dataset = ledger
            .freeze_dataset(dataset_plan.clone(), &evidence, /*now*/ 50)
            .unwrap();
        let request = TerminalLearningRequestV1 {
            operation_id: id("terminal.operation"),
            source_policy_id: grant.policy_id().clone(),
            expected_source_support_digest: support,
            expected_dataset_digest: dataset.snapshot.dataset_digest,
            dataset_plan,
            dataset_evidence: evidence,
            profile: TerminalCellProfileV1 {
                artifact_id: id("terminal.candidate"),
                producer_id: id("operator.native.owner"),
                generation: Generation::new(/*value*/ 1).unwrap(),
                sensor_id: id("single-approved-state"),
                objective_digest: digest("objective"),
                run_snapshot_digest: digest("run-snapshot"),
                unit_profile_digest: digest("reward-units"),
                action_ids: vec![id("abstain"), id("read")],
                minimum_samples_per_action: 1,
            },
            budget: TerminalLearningBudgetV1 {
                maximum_ledger_records: 64,
                maximum_dataset_records: 64,
                maximum_wall_milliseconds: 30_000,
                maximum_artifact_bytes: 1_048_576,
            },
            deadline_unix_seconds: 90,
        };
        let replay = Arc::new(
            AgentdSharedReplayHostV1::new(
                Arc::clone(&source),
                consumer,
                "terminal.local".into(),
                daemon.identity.agent_id.clone(),
            )
            .unwrap(),
        );
        Self {
            _memory_root: root,
            ledger_root,
            daemon,
            ledger: Arc::new(Mutex::new(ledger)),
            source,
            access,
            grant,
            replay,
            request,
        }
    }

    fn native_owner(&self) -> AgentdTerminalLearningOwnerV1 {
        AgentdTerminalLearningOwnerV1::new(
            self.daemon.identity.agent_id.clone(),
            id("operator.native.owner"),
            Arc::clone(&self.ledger),
            Arc::clone(&self.replay),
            /*maximum_jobs*/ 4,
        )
        .unwrap()
    }
}

fn collect(ledger: &mut LedgerWriter, prefix: &str, selected: &str, value: i64, support: Digest32) {
    let mut request = decision();
    request.record_id = id(&format!("{prefix}.decision"));
    request.episode_id = id(&format!("{prefix}.episode"));
    request.selected_candidate_id = id(selected);
    request.support_digest = support;
    let signed = sign(
        ledger.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let predecessor = ledger.witness_frontier().unwrap().anchor.chain_digest;
    let decision = ledger
        .append_decision(predecessor, request, &signed, /*now*/ 50)
        .unwrap();
    let mut observed = outcome(
        &format!("{prefix}.record"),
        &format!("{prefix}.outcome"),
        /*predecessor*/ None,
        value,
    );
    observed.episode_id = id(&format!("{prefix}.episode"));
    let signed = sign(
        ledger.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    ledger
        .append_outcome(decision.chain_digest, observed, &signed, /*now*/ 50)
        .unwrap();
}

#[tokio::test]
async fn supervised_profile_freezes_fits_and_reads_back_actual_native_candidate() {
    let fixtures = FixtureOwners::new().await;
    let before = fixtures.ledger.lock().unwrap().witness_frontier().unwrap();
    let (handle, bootstrap) = terminal_learning_channel_v1(
        fixtures.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixtures.native_owner(),
        /*capacity*/ 2,
    )
    .unwrap();
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run_with_clock(
        fixtures.daemon.state(),
        cancellation.clone(),
        || Ok(50),
    ));
    let receipt = handle.submit(fixtures.request.clone()).await.unwrap();
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        receipt.source.support_digest,
        fixtures.request.expected_source_support_digest
    );
    assert_eq!(receipt.source.policy_id, *fixtures.grant.policy_id());
    assert_eq!(
        receipt.candidate.dataset().snapshot.dataset_digest,
        fixtures.request.expected_dataset_digest
    );
    assert_eq!((receipt.source_records, receipt.training_samples), (4, 2));
    let artifact = receipt.candidate.artifact();
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(
        &receipt.payload,
        &TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&receipt.payload),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            generation: artifact.generation,
        },
    )
    .unwrap();
    assert_eq!(
        loaded
            .predict(&id("single-approved-state"), &id("read"))
            .unwrap()
            .value,
        FixedQ32::ONE
    );
    assert_eq!(
        loaded
            .predict(&id("single-approved-state"), &id("abstain"))
            .unwrap()
            .value,
        FixedQ32::ZERO
    );
    // The complete native receipt, including measured work, is reconciled.
    assert_eq!(
        handle.readback(fixtures.request.clone()).await.unwrap(),
        receipt
    );
    assert_eq!(
        handle.submit(fixtures.request.clone()).await.unwrap(),
        receipt
    );
    assert_eq!(
        fixtures.ledger.lock().unwrap().witness_frontier().unwrap(),
        before
    );
    let mut changed = fixtures.request.clone();
    changed.profile.generation = Generation::new(/*value*/ 2).unwrap();
    assert_eq!(
        handle.submit(changed).await.unwrap_err(),
        TerminalLearningErrorV1::Conflict
    );
    fixtures
        .source
        .revoke_shared_experience(&fixtures.access, &fixtures.grant)
        .await
        .unwrap();
    assert!(matches!(
        handle.readback(fixtures.request.clone()).await,
        Err(TerminalLearningErrorV1::Owner(_))
    ));
    cancellation.cancel();
    worker.await.unwrap().unwrap();
}

#[tokio::test]
async fn exact_owner_evidence_and_dataset_budget_are_enforced() {
    let fixtures = FixtureOwners::new().await;
    let native = fixtures.native_owner();
    assert_eq!(
        native
            .readback(fixtures.request.clone(), /*now*/ 50)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
    let mut forged = fixtures.request.clone();
    forged.operation_id = id("terminal.forged");
    forged.dataset_evidence.signature[0] ^= 1;
    assert!(matches!(
        native.train(forged, /*now*/ 50).await,
        Err(TerminalLearningErrorV1::Owner(_))
    ));
    let mut over_budget = fixtures.request.clone();
    over_budget.operation_id = id("terminal.budget");
    over_budget.budget.maximum_dataset_records = 3;
    assert_eq!(
        native
            .train(over_budget.clone(), /*now*/ 50)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::Capacity
    );
    over_budget.budget.maximum_dataset_records = 64;
    assert_eq!(
        native.train(over_budget, /*now*/ 50).await.unwrap_err(),
        TerminalLearningErrorV1::Conflict
    );
    let wrong_source = AgentdSharedReplayHostV1::new(
        Arc::clone(&fixtures.source),
        FederationConsumerAccess::new(
            fixtures.daemon.identity.agent_id.clone(),
            Sha256Digest::for_bytes(b"terminal-workspace"),
        ),
        "wrong.parameter.scope".into(),
        fixtures.daemon.identity.agent_id.clone(),
    )
    .unwrap();
    let denied = AgentdTerminalLearningOwnerV1::new(
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
        Arc::clone(&fixtures.ledger),
        Arc::new(wrong_source),
        /*maximum_jobs*/ 2,
    )
    .unwrap();
    assert!(matches!(
        denied.train(fixtures.request.clone(), /*now*/ 50).await,
        Err(TerminalLearningErrorV1::Owner(_))
    ));
}

#[tokio::test]
async fn native_queue_refuses_overflow_and_lost_acknowledgement_remains_unknown() {
    let fixtures = FixtureOwners::new().await;
    let (handle, bootstrap) = terminal_learning_channel_v1(
        fixtures.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixtures.native_owner(),
        /*capacity*/ 1,
    )
    .unwrap();
    let mut queued = Box::pin(handle.submit(fixtures.request.clone()));
    poll_fn(|context| {
        assert!(queued.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    assert_eq!(
        handle.submit(fixtures.request.clone()).await.unwrap_err(),
        TerminalLearningErrorV1::QueueFull
    );
    drop(bootstrap);
    assert_eq!(
        queued.await.unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
}

#[tokio::test]
async fn recovered_ledger_does_not_invent_a_durable_iteration_checkpoint() {
    let fixtures = FixtureOwners::new().await;
    let native = fixtures.native_owner();
    let receipt = native
        .train(fixtures.request.clone(), /*now*/ 50)
        .await
        .unwrap();
    let frontier = fixtures.ledger.lock().unwrap().witness_frontier().unwrap();
    drop(native);
    let writer = Arc::try_unwrap(fixtures.ledger)
        .ok()
        .unwrap()
        .into_inner()
        .unwrap();
    drop(writer);
    let recovered = fixtures.ledger_root.recover_writer(/*limit*/ 64, frontier);
    recovered
        .revalidate_dataset_snapshot(receipt.candidate.dataset(), /*now*/ 50)
        .unwrap();
    let restarted = AgentdTerminalLearningOwnerV1::new(
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
        Arc::new(Mutex::new(recovered)),
        Arc::clone(&fixtures.replay),
        /*maximum_jobs*/ 4,
    )
    .unwrap();
    assert_eq!(
        restarted
            .readback(fixtures.request, /*now*/ 50)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain,
    );
}
