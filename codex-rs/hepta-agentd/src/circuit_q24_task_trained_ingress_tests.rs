//! A genuine ordinary task supplies the training vector; the original durable
//! trainer performs bounded SGD and the same ordinary profile consumes its
//! changed heads. The target rule, stage credential metadata and subsequent
//! version selection use explicit fixtures. No independent B/evaluation or
//! learning Selection receipt is invented, and no quality/adoption acceptance
//! is asserted by this controlled publication exercise.

use std::fs::File;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::CellQ24SingleHeadTrainingPlanV1;
use crate::CellQ24TrainingBatchV1;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerV1;
use crate::CellQ24TrainingSampleV1;
use crate::LoadedCellQ24ModelV1;
use crate::cell_q24_single_head_update_rule_v1;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

fn training_cut(publication: &CircuitTaskSourcePublicationV1, bundle: CellCompatibilityBundleV1) -> anyhow::Result<(LearningIterationSnapshotV1, CellQ24TrainingBatchV1)> {
    let input = publication.input();
    let dataset = Digest32::of_parts(&[b"fixture-frozen-success-target-2q24", publication.publication_digest().as_array(), &input.observation]);
    let sample = input.observation[10..].chunks_exact(8)
        .map(|bytes| bytes.try_into().map(i64::from_le_bytes)).collect::<Result<Vec<_>, _>>()?;
    let batch = CellQ24TrainingBatchV1::new(dataset, vec![CellQ24TrainingSampleV1 { input: sample, target: 2 * Q }])?;
    let episode = publication.publication_digest();
    let completed = publication.history_digest().as_str().parse::<Digest32>()?;
    let request = LearningIterationRequestV1 {
        operation_id: cell::id("ordinary-q24-original-training"),
        principal_id: StableId::new(input.scope.principal_digest.to_string())?,
        agent_id: input.scope.agent_id.clone(), cell_id: input.scope.cell_id.clone(), source_run_id: input.scope.run_id.clone(),
        completed_task_receipt: completed, selected_artifact_digest: bundle.components.base,
        selected_bundle: bundle, evaluation_profile: cell::d("fixture-future-evaluation-profile"),
        envelope: IterationEnvelopeV1 {
            envelope_id: cell::id("ordinary-q24-frozen-envelope"), base_commit: cell::d("engineering-source-candidate"),
            base_tree: cell::d("engineering-source-tree"), objective_digest: input.objective_digest,
            grammar_digest: cell::d("fixture-single-row-grammar"), maximum_files: 1, maximum_diff_bytes: 4_096,
            maximum_candidates: 1, maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 60,
        },
        budget: LearningIterationBudgetV1 { maximum_dataset_rows: 1, maximum_dataset_bytes: 16_384,
            maximum_training_steps: 2, maximum_training_milliseconds: 10_000, maximum_artifact_bytes: 4_096 },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: cell::d("explicit-fixture-stage-credentials"),
        experience: cell::id("fixture-experience"), dataset: cell::id("fixture-dataset"),
        trainer: cell::id("fixture-trainer"), evaluator: cell::id("unused-fixture-evaluator"),
        proposal: cell::id("unused-fixture-proposal"), selector: cell::id("unused-fixture-selector"),
        next_use_observer: cell::id("unused-fixture-observer"),
    };
    let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
    for observation in [
        LearningIterationObservationV1::Experience { episode_digest: episode, completed_task_receipt: completed },
        LearningIterationObservationV1::Dataset { snapshot_digest: dataset, episode_digest: episode,
            withdrawal_frontier: publication.publication_digest(), rows: batch.rows(), bytes: batch.encoded().len() as u64 },
    ] {
        coordinator.record(learning_test_receipt(&coordinator, observation), /*now_unix_seconds*/ 20)?;
    }
    assert_eq!(coordinator.next_stage(), Some(LearningIterationStageV1::Training));
    assert_eq!(coordinator.snapshot().receipts.len(), 2);
    Ok((coordinator.snapshot().clone(), batch))
}

fn plan(baseline: Arc<LoadedCellQ24ModelV1>, prefix: &LearningIterationSnapshotV1, batch: &CellQ24TrainingBatchV1, rule: CellQ24SgdRuleV1) -> anyhow::Result<CellQ24SingleHeadTrainingPlanV1> {
    let head = CellQ24PrivateHeadV1::Drive { index: 0 };
    let optimizer = rule.digest(batch)?;
    let scope = FrozenLearningScopeV2::freeze(&prefix.request, &prefix.owners, LearningUpdateScopeV2::Cell,
        cell_q24_single_head_update_rule_v1(&prefix.request.selected_bundle, head, optimizer)?)?;
    Ok(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(prefix.clone(), scope, baseline, head, optimizer)?)
}

fn file(root: &Path, name: &str) -> anyhow::Result<File> {
    Ok(OpenOptions::new().read(true).write(true).create(true).truncate(false).open(root.join(name))?)
}

fn witness(root: &Path, prefix: &LearningIterationSnapshotV1) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(file(root, "training.witness")?, JournalScope {
        scope_digest: prefix.head_digest, objective_digest: prefix.request.envelope.objective_digest,
    }, Generation::new(1)?, /*max_records*/ 16)?)
}

#[tokio::test]
async fn q24_ordinary_fresh_task_consumes_original_trainer_changed_head_after_version_publication() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (baseline, bundle, definition_a) = support::model(root.path())?;
    let parent_heads = fs::read(root.path().join("heads"))?;
    let a = support::admission("ordinary-trained-A").await?;
    let source_a = support::source(&a, [Q, Q / 4])?;
    let config_a = support::configuration(&baseline, &bundle, &definition_a, &source_a, /*generation*/ 1)?;
    let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
    let published_a = support::publish_initial(&version, definition_a.clone(), source_a)?;
    let mut a = support::start(a, published_a, Arc::clone(&baseline), bundle.clone()).await?;
    let publication_a = execute(&a, /*request_id*/ 1).await?;
    let (prefix, batch) = training_cut(&publication_a, bundle.clone())?;
    let rule = CellQ24SgdRuleV1 { epochs: 2, learning_rate_q24: Q / 2 };
    let mut trainer = CellQ24TrainingOwnerV1::create(file(root.path(), "training.journal")?, witness(root.path(), &prefix)?,
        plan(Arc::clone(&baseline), &prefix, &batch, rule)?, batch.clone(), rule)?;
    let CellQ24TrainingOutcomeV1::Candidate(trained) = trainer.fit_or_readback(&AtomicBool::new(false))? else {
        anyhow::bail!("real bounded training did not produce changed bytes")
    };
    assert_eq!(trained.metrics.optimizer_steps, 2);
    assert!(trained.metrics.squared_error_after_q48 < trained.metrics.squared_error_before_q48);
    assert_ne!(trained.heads, parent_heads);
    let observed = trainer.read_learning_observation(&prefix)?;
    assert!(matches!(observed.observation(), LearningIterationObservationV1::Training { candidate, .. } if **candidate == trained.bundle));
    drop(trainer);
    let training_bytes = (fs::read(root.path().join("training.journal"))?, fs::read(root.path().join("training.witness"))?);
    let mut trainer = CellQ24TrainingOwnerV1::recover(file(root.path(), "training.journal")?, witness(root.path(), &prefix)?,
        plan(Arc::clone(&baseline), &prefix, &batch, rule)?, batch, rule)?;
    let CellQ24TrainingOutcomeV1::Candidate(reopened) = trainer.fit_or_readback(&AtomicBool::new(true))? else {
        anyhow::bail!("completed original candidate was lost")
    };
    assert_eq!((&reopened.bundle, &reopened.heads, &reopened.metrics), (&trained.bundle, &trained.heads, &trained.metrics));
    assert_eq!(trainer.read_learning_observation(&prefix)?, observed);
    assert_eq!((fs::read(root.path().join("training.journal"))?, fs::read(root.path().join("training.witness"))?), training_bytes);
    let completion_a = a.retirement.drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
    a.stop().await?;
    drop(a);

    let model = Arc::new(reopened.model);
    let candidate = reopened.bundle;
    let definition_c = support::definition(&model, &candidate)?;
    let c = support::admission("ordinary-trained-C").await?;
    let source_c = support::source(&c, [Q / 4, Q])?;
    let config_c = support::configuration(&model, &candidate, &definition_c, &source_c, /*generation*/ 2)?;
    // Controlled test credentials authorize the real candidate manifest through
    // the original artifact owner. There is no claimed quality evaluation.
    let selected = version.publish_next_selection(&config_c.manifest, "actual-trained-q24-head")?;
    let prepared = crate::prepare_agentd_generation_cold_drained_update_v1(
        version.reopen_current()?, version.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: version.file("target-journal")?, witness: version.witness("target-witness", &config_a)?,
            config: config_a, max_records: RECORDS,
        }, selected,
        version.named_target_create("trained-C-journal", "trained-C-witness", config_c)?,
        AgentdGenerationUpdateRequestV1 { operation_id: "ordinary-q24-trained-C".into() },
    )?;
    let signed = version.sign(prepared.final_use_binding())?;
    let published_c = prepared.publish(&signed)?.into_circuit_feature_task(definition_c.clone(), source_c, completion_a)?;
    let mut c = support::start(c, published_c, model, candidate.clone()).await?;
    let publication_c = execute(&c, /*request_id*/ 1).await?;
    let receipt = read_receipt(&c, &definition_c, &publication_c)?;
    assert_eq!(receipt.representation.drive_q24[0], 79 * Q / 128);
    assert_eq!(&receipt.representation.drive_q24[1..], &[Q, 0, 0, 0]);
    assert_eq!(receipt.representation.prediction_q24, vec![Q / 4, Q, 0, 0, 0]);
    assert_eq!(receipt.bundle_digest, candidate.digest()?);
    assert_eq!(candidate.rollback_predecessor, Some(bundle.digest()?));
    assert_eq!(fs::read(root.path().join("heads"))?, parent_heads);
    assert_eq!(execute(&c, /*request_id*/ 2).await?, publication_c);
    let _completion_c = c.retirement.drain_completed_task(&c.cell, c.source.as_ref(), &c.runtime.identity)?;
    c.stop().await?;
    Ok(())
}
