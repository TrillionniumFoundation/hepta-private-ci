//! Synthetic data, never production receipts or evidence of learning benefit.
//! The privileged process tests independently use actual registered Root CAS.

use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(crate) const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
pub(crate) const OWNER: &str = "learning-checkpoint-process-fixture";

pub(crate) fn snapshots() -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let id = |value: &str| StableId::new(value);
    let d = |value: &str| Digest32::of_bytes(value.as_bytes());
    let request = LearningIterationRequestV1 {
        operation_id: id("checkpoint-operation")?,
        principal_id: id("fixture-principal")?,
        agent_id: id(AGENT)?,
        cell_id: id("fixture-cell")?,
        source_run_id: id("fixture-run")?,
        completed_task_receipt: d("completed"),
        selected_artifact_digest: d("artifact"),
        evaluation_profile: d("frozen-evaluation"),
        selected_bundle: crate::neuron_generation_update_bootstrap::learning_test_baseline()?,
        envelope: IterationEnvelopeV1 {
            envelope_id: id("fixture-envelope")?,
            base_commit: d("commit"),
            base_tree: d("tree"),
            objective_digest: d("objective"),
            grammar_digest: d("grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 1024,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 100,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 10,
            maximum_dataset_bytes: 1024,
            maximum_training_steps: 10,
            maximum_training_milliseconds: 1000,
            maximum_artifact_bytes: 1024,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: d("fixture-trust"),
        experience: id("fixture-experience")?,
        dataset: id("fixture-dataset")?,
        trainer: id("fixture-trainer")?,
        evaluator: id("fixture-evaluator")?,
        proposal: id("fixture-proposal")?,
        selector: id("fixture-selector")?,
        next_use_observer: id("fixture-observer")?,
    };
    let completed_task_receipt = request.completed_task_receipt;
    let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
    let mut states = vec![coordinator.snapshot().clone()];
    for observation in [
        LearningIterationObservationV1::Experience {
            episode_digest: d("episode"),
            completed_task_receipt,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: d("dataset"),
            episode_digest: d("episode"),
            withdrawal_frontier: d("withdrawal"),
            rows: 1,
            bytes: 1,
        },
    ] {
        coordinator.record(
            crate::neuron_generation_update_bootstrap::learning_test_receipt(
                &coordinator,
                observation,
            ),
            20,
        )?;
        states.push(coordinator.snapshot().clone());
    }
    let mut candidate = coordinator.snapshot().request.selected_bundle.clone();
    let source_bundle = candidate.digest()?;
    candidate.artifact_id = id("fixture-candidate")?;
    candidate.generation = candidate.generation.next()?;
    candidate.rollback_predecessor = Some(source_bundle);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle,
        dataset: d("dataset"),
        update_rule: d("fixture-rule"),
        evaluation_profile: coordinator.snapshot().request.evaluation_profile,
    });
    coordinator.record(
        crate::neuron_generation_update_bootstrap::learning_test_receipt(
            &coordinator,
            LearningIterationObservationV1::Training {
                candidate: Box::new(candidate),
                steps: 1,
                milliseconds: 1,
                artifact_bytes: 1,
            },
        ),
        20,
    )?;
    states.push(coordinator.snapshot().clone());
    Ok(states)
}
