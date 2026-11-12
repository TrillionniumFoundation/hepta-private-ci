//! Closed remote material admission. The live capability was obtained outside
//! the Trainer lane. Its pure verifier cannot manufacture a Cell or Runner seal.

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::CellQ24ModelProposalErrorV1 as Error;
use super::Admission;
use super::original_binding;
use crate::CellQ24TrainingOwnerV1;
use crate::OriginalCellEvaluationModelMaterialV1;

pub(in super::super) fn validate_current_material<T: AnchorWitnessStore>(
    trainer: &mut CellQ24TrainingOwnerV1<T>,
    dataset_cut: &LearningIterationSnapshotV1,
    scope: Digest32,
    owner_binding: Digest32,
    training_cut: &LearningIterationSnapshotV1,
    training_attestation: &SignedLearningEvidenceV1,
    material: &OriginalCellEvaluationModelMaterialV1,
    now: u64,
) -> Result<Admission, Error> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(training_cut.clone())?;
    let original = CellQ24TrainingOwnerV1::read_learning_observation(trainer, dataset_cut)?;
    let training = training_cut
        .receipts
        .last()
        .ok_or(Error::Binding("original Training receipt"))?;
    if training_cut.request != dataset_cut.request
        || training_cut.owners != dataset_cut.owners
        || training_cut.receipts.len() != dataset_cut.receipts.len() + 1
        || !training_cut.receipts.starts_with(&dataset_cut.receipts)
        || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || original.scope_binding() != scope
        || original_binding(dataset_cut, &original) != owner_binding
        || original.iteration_head() != training.predecessor
        || original.evidence_digest() != training.evidence_digest
        || original.observation() != &training.observation
    {
        return Err(Error::Binding("exact original Training extension"));
    }
    // This is the sole sealed material API. It authenticates complete original
    // T/E/Product/execution evidence, both manifests, and the unchanged current
    // material window. An Ineligible result cannot produce this input.
    let current = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::Binding("original Model clock before Unix epoch"))?
        .as_secs();
    if current < now {
        return Err(Error::Binding("original Model clock moved backwards"));
    }
    let input = material
        .require_original_model_input(training_cut, training_attestation, current)
        .map_err(|error| Error::OriginalEvaluationMaterial(Box::new(error)))?;
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("trained candidate"))?
        .digest()
        .map_err(LearningIterationError::from)?;
    if input.candidate() != candidate
        || !matches!(&input.evaluation().observation,
            LearningIterationObservationV1::Evaluation {
                candidate_bundle, evaluation_profile,
                disposition: LearningEvaluationDispositionV1::Qualified,
            } if *candidate_bundle == candidate
                && *evaluation_profile == training_cut.request.evaluation_profile)
    {
        return Err(Error::Binding(
            "actual Qualified original candidate material",
        ));
    }
    coordinator.record(
        input.evaluation().clone(),
        input.evaluation().observed_unix_seconds,
    )?;
    Ok(Admission {
        cut: coordinator.snapshot().clone(),
        candidate,
        material: input.material_digest(),
    })
}
