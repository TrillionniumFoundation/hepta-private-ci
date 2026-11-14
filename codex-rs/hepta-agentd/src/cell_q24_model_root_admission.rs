//! Validate the actual factory response against the still-borrowed Trainer
//! and independent B observation. No wire data can construct that response
//! capability; this projection creates no owner, key or native qualification.

use super::*;
use crate::root_q24_model_factory::OriginalRootModelMaterialV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;

pub(in crate::cell_q24_model_proposal) struct RootAdmission {
    pub(in crate::cell_q24_model_proposal) dataset: LearningIterationSnapshotV1,
    pub(in crate::cell_q24_model_proposal) scope: Digest32,
    pub(in crate::cell_q24_model_proposal) binding: Digest32,
    pub(in crate::cell_q24_model_proposal) admission: Admission,
}

pub(in crate::cell_q24_model_proposal) fn validate_original_root_material(
    original: &OriginalRootModelMaterialV1<'_, '_>,
) -> Result<RootAdmission, Error> {
    original.require_current_training_source()?;
    let training = original.training_snapshot();
    original.scope().validate_snapshot(training)?;
    let mut completed = LearningIterationCoordinatorV1::from_snapshot(training.clone())?;
    let trained = training
        .receipts
        .last()
        .ok_or(Error::Binding("actual Training absent"))?;
    if completed.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || trained != original.training_receipt()
        || !matches!(
            original.evaluation_receipt().observation,
            LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::Qualified,
                ..
            }
        )
    {
        return Err(Error::Binding(
            "actual qualified Root Model inputs required",
        ));
    }
    let candidate = completed
        .candidate()
        .ok_or(Error::Binding("original candidate"))?
        .digest()
        .map_err(LearningIterationError::from)?;
    let mut dataset =
        LearningIterationCoordinatorV1::new(training.request.clone(), training.owners.clone())?;
    for receipt in &training.receipts[..training.receipts.len() - 1] {
        dataset.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    if dataset.next_stage() != Some(LearningIterationStageV1::Training)
        || dataset.snapshot().head_digest != trained.predecessor
    {
        return Err(Error::Binding("original Model Dataset prefix differs"));
    }
    completed.record(
        original.evaluation_receipt().clone(),
        original.evaluation_receipt().observed_unix_seconds,
    )?;
    let scope = original.scope().binding();
    let binding = model_owner_binding(
        dataset.snapshot().head_digest,
        scope,
        trained.evidence_digest,
    );
    let material: Digest32 = original
        .projection()
        .material
        .parse()
        .map_err(|_| Error::Binding("original Root Model material digest"))?;
    if material.is_zero() || material.to_string() != original.projection().material {
        return Err(Error::Binding("canonical Root Model material required"));
    }
    let admission = Admission {
        cut: completed.snapshot().clone(),
        candidate,
        material,
    };
    let expected = RootQ24ModelProjectionDataV1 {
        scope: scope.to_string(),
        dataset_head: dataset.snapshot().head_digest.to_string(),
        training_head: training.head_digest.to_string(),
        evaluation_head: admission.cut.head_digest.to_string(),
        candidate: candidate.to_string(),
        owner_binding: binding.to_string(),
        material: material.to_string(),
        proposal_binding: admission.key(binding).binding_digest.to_string(),
    };
    if original.projection() != &expected {
        return Err(Error::Binding("original Root Model projection differs"));
    }
    original.require_current_training_source()?;
    Ok(RootAdmission {
        dataset: dataset.snapshot().clone(),
        scope,
        binding,
        admission,
    })
}
