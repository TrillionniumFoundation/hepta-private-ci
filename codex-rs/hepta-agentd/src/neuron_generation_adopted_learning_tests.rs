//! Actual file/CURRENT/nonce and ordinary actor recovery with synthetic
//! training/evaluation and worker output. These do not qualify model quality,
//! production learning identities, or generic state-preserving migrations.

use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::super::support as host;
use super::support;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::AgentdGenerationUpdateRuntimeV1;
use crate::learning_updated_task_operation_id_v1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_runtime::verify_learning_use_readback_test_bytes;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;
use crate::prepare_agentd_generation_update_v1;
use crate::recover_agentd_generation_update_v1;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn candidate(baseline: &CellCompatibilityBundleV1) -> anyhow::Result<CellCompatibilityBundleV1> {
    let mut candidate = baseline.clone();
    candidate.artifact_id = StableId::new("fixture-selected-trained-candidate")?;
    candidate.generation = baseline.generation.next()?;
    candidate.components.cell_adapter = Some(d("different trained adapter"));
    candidate.rollback_predecessor = Some(baseline.digest()?);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: baseline.digest()?,
        dataset: d("dataset"),
        update_rule: d("update"),
        evaluation_profile: d("evaluation"),
    });
    Ok(candidate)
}

fn decision(
    f: &Fixture,
    candidate: CellCompatibilityBundleV1,
    composition_digest: Digest32,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let prior = learning_test_decision(f, learning_test_baseline()?, "none")?;
    let snapshot = prior.snapshot();
    let mut coordinator =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for receipt in &snapshot.receipts[..2] {
        coordinator.record(receipt.clone(), 20)?;
    }
    let candidate_bundle = candidate.digest()?;
    for observation in [
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 64,
        },
        LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile: d("evaluation"),
            disposition: LearningEvaluationDispositionV1::Qualified,
        },
        LearningIterationObservationV1::Proposal {
            candidate_bundle,
            proposal_id: snapshot.request.operation_id.clone(),
            composition_digest,
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    ] {
        coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
    }
    Ok(coordinator)
}

struct UpdatedRuntime {
    host: host::Fixture,
    publication: Fixture,
    coordinator: LearningIterationCoordinatorV1,
    runtime: AgentdGenerationUpdateRuntimeV1,
    control: support::Control,
    selection: LearningIterationObservationV1,
}

impl UpdatedRuntime {
    async fn read_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> anyhow::Result<LearningIterationObservationV1> {
        Ok(self
            .runtime
            .handle
            .read_learning_updated_selection(coordinator, &self.publication.old_config.manifest)
            .await?)
    }

    async fn read_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        intent: &CellGenerationIntentV2,
    ) -> anyhow::Result<LearningIterationObservationV1> {
        Ok(self
            .runtime
            .handle
            .read_learning_updated_next_use(
                coordinator,
                &self.publication.old_config.manifest,
                intent,
            )
            .await?)
    }

    async fn new() -> anyhow::Result<Self> {
        let mut host = host::Fixture::new().await;
        let baseline = learning_test_baseline()?;
        let candidate = candidate(&baseline)?;
        host.config.manifest.bundle_digest = baseline.digest()?.into_array();
        host.config.initial.manifest_digest = host.config.manifest.digest()?;
        let mut next = host.config.clone();
        next.initial.scope.run_id.push_str("-updated-learning-next");
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = d("updated learning next task").into_array();
        next.manifest.bundle_digest = candidate.digest()?.into_array();
        next.initial.manifest_digest = next.manifest.digest()?;
        let publication = Fixture::new_with_target(host.config.clone(), next)?;
        let coordinator = decision(&publication, candidate, d("proposal composition"))?;
        let operation_id = learning_updated_task_operation_id_v1(&coordinator)?.to_string();
        let prepared = prepare_agentd_generation_update_v1(
            publication.current.clone(),
            publication.authorities()?,
            publication.stopped_old()?,
            publication.selection()?,
            publication.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: operation_id.clone(),
            },
        )?;
        let intent_digest = prepared.intent_digest();
        let grant = publication.sign(prepared.final_use_binding())?;
        publication.lose_publication_ack();
        assert!(prepared.publish(&grant).is_err());
        assert_eq!(publication.authority.capacity()?.used_nonces, 1);
        let ready = recover_agentd_generation_update_v1(
            publication.reopen_current()?,
            publication.authorities()?,
            publication.selection()?,
            publication.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id,
                intent_digest,
            },
        )?;
        let selection = ready
            .read_learning_updated_selection(&coordinator, &publication.old_config.manifest)?;
        let control = support::Control::default();
        let runtime = ready.into_runtime(
            support::next_config(&mut host, 2).await?,
            control.clone(),
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        Ok(Self {
            host,
            publication,
            coordinator,
            runtime,
            control,
            selection,
        })
    }
}

#[tokio::test]
async fn updated_candidate_uses_original_actor_and_recovers_without_another_reset()
-> anyhow::Result<()> {
    let mut f = UpdatedRuntime::new().await?;
    let baseline_manifest = f.publication.old_config.manifest.clone();
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    let operation = learning_updated_task_operation_id_v1(&f.coordinator)?;
    let selected = f.coordinator.candidate().cloned().unwrap();
    let no_update = learning_test_decision(&f.publication, learning_test_baseline()?, "none")?;
    assert!(learning_updated_task_operation_id_v1(&no_update).is_err());
    assert!(
        f.runtime
            .handle
            .read_learning_selection(&f.coordinator)
            .await
            .is_err()
    );
    assert!(f.read_selection(&no_update).await.is_err());
    let mut wrong_candidate = selected.clone();
    wrong_candidate.components.calibration = d("different candidate calibration");
    for other in [
        decision(&f.publication, wrong_candidate, d("proposal composition"))?,
        decision(
            &f.publication,
            selected.clone(),
            d("another qualified proposal"),
        )?,
    ] {
        assert_ne!(learning_updated_task_operation_id_v1(&other)?, operation);
        assert!(f.read_selection(&other).await.is_err());
    }
    for change_bundle in [false, true] {
        let mut wrong_manifest = baseline_manifest.clone();
        if change_bundle {
            wrong_manifest.bundle_digest = d("another baseline bundle").into_array();
        } else {
            wrong_manifest.runtime_digest = d("another prior runtime").into_array();
        }
        assert!(
            f.runtime
                .handle
                .read_learning_updated_selection(&f.coordinator, &wrong_manifest)
                .await
                .is_err()
        );
    }
    let selection = f.read_selection(&f.coordinator).await?;
    assert_eq!(selection, f.selection);
    f.coordinator
        .record(learning_test_receipt(&f.coordinator, selection), 20)?;
    assert_eq!(
        learning_updated_task_operation_id_v1(&f.coordinator)?,
        operation
    );
    assert!(f.publication.old_journal().is_err());
    let old_bytes = (
        f.publication.bytes("old-journal")?,
        f.publication.bytes("old-witness")?,
    );
    assert_eq!(
        f.runtime.handle.snapshot().await?,
        f.publication.target_config.initial
    );
    let request = support::request(
        &f.publication.target_config,
        f.runtime.handle.snapshot().await?,
    );
    let intent = request.intent()?;
    assert!(f.read_use(&f.coordinator, &intent).await.is_err());
    assert!(
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(&f.coordinator, &baseline_manifest, &intent)
            .await
            .is_err()
    );
    let receipt = f.runtime.handle.step(request.clone()).await?;
    let observed = f.runtime.handle.observe_generation().await?;
    let pending = f
        .runtime
        .handle
        .read_learning_updated_next_use_readback(&f.coordinator, &baseline_manifest, &intent)
        .await?;
    verify_learning_use_readback_test_bytes(
        &pending,
        &f.publication.target_config.manifest,
        &receipt,
        &observed,
        "adopted_pending",
    )?;
    let mut wrong_manifest = baseline_manifest.clone();
    wrong_manifest.runtime_digest = d("unrelated original runtime").into_array();
    assert!(
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(&f.coordinator, &wrong_manifest, &intent)
            .await
            .is_err()
    );
    let chunk = observed.pending_output().cloned().unwrap();
    let output_path = f.host.directory.path().join("updated-learning-output");
    std::fs::write(&output_path, &chunk.bytes)?;
    std::fs::File::open(&output_path)?.sync_all()?;
    std::fs::File::open(f.host.directory.path())?.sync_all()?;
    f.runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_bytes(&chunk.bytes).into_array(),
            CellTaskCostV2::new(observed.cost().identity())?,
        )
        .await?;
    assert!(f.runtime.handle.drain().await?);
    let first = f.read_use(&f.coordinator, &intent).await?;
    let LearningIterationObservationV1::NextUse {
        candidate_bundle,
        state_cutover_receipt,
        ..
    } = &first
    else {
        anyhow::bail!("updated candidate was mislabeled as retained use");
    };
    assert_eq!(*candidate_bundle, selected.digest()?);
    assert_ne!(
        *state_cutover_receipt,
        f.runtime.publication.publication_digest()?
    );
    assert_ne!(
        *state_cutover_receipt,
        f.runtime.publication.intent_digest()
    );
    let exported = f
        .runtime
        .handle
        .read_learning_updated_next_use_readback(&f.coordinator, &baseline_manifest, &intent)
        .await?;
    verify_learning_use_readback_test_bytes(
        &exported,
        &f.publication.target_config.manifest,
        &receipt,
        &f.runtime.handle.observe_generation().await?,
        "adopted_acked",
    )?;
    assert_ne!(pending, exported);
    let retained = (
        f.publication.bytes("current.json")?,
        f.publication.bytes("target-journal")?,
        f.publication.bytes("target-witness")?,
        f.publication.bytes("final-use/authority.claims")?,
    );
    let intent_digest = f.runtime.publication.intent_digest();
    tasks.shutdown().await;
    drop(f.runtime);
    drop(tasks);
    f.coordinator =
        LearningIterationCoordinatorV1::from_snapshot(f.coordinator.snapshot().clone())?;
    let ready = recover_agentd_generation_update_v1(
        f.publication.reopen_current()?,
        f.publication.authorities()?,
        f.publication.selection()?,
        f.publication.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: operation.to_string(),
            intent_digest,
        },
    )?;
    assert_eq!(
        ready.read_learning_updated_next_use(&f.coordinator, &baseline_manifest, &intent)?,
        first
    );
    f.runtime = ready.into_runtime(
        support::next_config(&mut f.host, 6).await?,
        f.control.clone(),
        f.host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    assert_eq!(f.read_use(&f.coordinator, &intent).await?, first);
    assert_eq!(
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(&f.coordinator, &baseline_manifest, &intent)
            .await?,
        exported
    );
    assert_eq!(f.runtime.handle.step(request).await?, receipt);
    let mut wrong = intent.clone();
    wrong.input_digest = d("uncommitted input").into_array();
    assert!(f.read_use(&f.coordinator, &wrong).await.is_err());
    assert!(
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(&f.coordinator, &baseline_manifest, &wrong)
            .await
            .is_err()
    );
    assert_eq!(
        (
            f.control.executions.load(Ordering::SeqCst),
            f.control.reads.load(Ordering::SeqCst)
        ),
        (1, 0)
    );
    assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
    assert_eq!(std::fs::read(output_path)?, chunk.bytes);
    assert_eq!(
        (
            f.publication.bytes("old-journal")?,
            f.publication.bytes("old-witness")?
        ),
        old_bytes
    );
    assert_eq!(
        (
            f.publication.bytes("current.json")?,
            f.publication.bytes("target-journal")?,
            f.publication.bytes("target-witness")?,
            f.publication.bytes("final-use/authority.claims")?,
        ),
        retained
    );
    f.coordinator
        .record(learning_test_receipt(&f.coordinator, first), 20)?;
    let completed =
        LearningIterationCoordinatorV1::from_snapshot(f.coordinator.snapshot().clone())?;
    assert_eq!(
        completed.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(
        learning_updated_task_operation_id_v1(&completed)?,
        operation
    );
    assert!(f.read_use(&completed, &intent).await.is_err());
    assert!(
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(&completed, &baseline_manifest, &intent)
            .await
            .is_err()
    );
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn updated_actor_rechecks_current_withdrawal_and_revocation() -> anyhow::Result<()> {
    for change in ["current", "withdrawal", "revocation"] {
        let mut f = UpdatedRuntime::new().await?;
        let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
        let selection_coordinator = f.coordinator.clone();
        let selection = f.read_selection(&selection_coordinator).await?;
        assert_eq!(selection, f.selection);
        f.coordinator
            .record(learning_test_receipt(&f.coordinator, selection), 20)?;
        let request = support::request(
            &f.publication.target_config,
            f.runtime.handle.snapshot().await?,
        );
        let intent = request.intent()?;
        f.runtime.handle.step(request).await?;
        assert!(matches!(
            f.read_use(&f.coordinator, &intent).await?,
            LearningIterationObservationV1::NextUse { .. }
        ));
        f.runtime
            .handle
            .read_learning_updated_next_use_readback(
                &f.coordinator,
                &f.publication.old_config.manifest,
                &intent,
            )
            .await?;
        let retained = (
            f.publication.bytes("target-journal")?,
            f.publication.bytes("target-witness")?,
        );
        match change {
            "current" => f.publication.advance_artifact_current()?,
            "withdrawal" => f.publication.withdraw()?,
            "revocation" => {
                let mut head = f.publication.authority.revocation_head()?;
                head.revision += 1;
                head.revoked_grant_ids
                    .insert(f.runtime.publication.signed_grant().grant.grant_id.clone());
                f.publication.authority.update_revocations(head)?;
            }
            _ => anyhow::bail!("unknown authority mutation"),
        }
        assert!(
            f.read_selection(&selection_coordinator).await.is_err(),
            "{change}"
        );
        assert!(
            f.read_use(&f.coordinator, &intent).await.is_err(),
            "{change}"
        );
        assert!(
            f.runtime
                .handle
                .read_learning_updated_next_use_readback(
                    &f.coordinator,
                    &f.publication.old_config.manifest,
                    &intent
                )
                .await
                .is_err(),
            "{change}"
        );
        assert_eq!(f.control.executions.load(Ordering::SeqCst), 1);
        assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
        assert_eq!(
            (
                f.publication.bytes("target-journal")?,
                f.publication.bytes("target-witness")?
            ),
            retained
        );
        tasks.shutdown().await;
    }
    Ok(())
}
