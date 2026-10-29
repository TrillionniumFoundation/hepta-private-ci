//! Bind released lineage to the final fold declared before consumption.
//! Model/prediction commitments retain their caller-declared meaning: they
//! need not identify the temporal nuisance fitter or its predictions.

use std::collections::BTreeSet;

use super::CrossFoldPlanV1;
use super::Digest32;
use super::ProductEvaluationError;
use super::StableId;
use super::TemporalComparisonInputsV1;
use super::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct FrozenProductHoldoutV1 {
    training_lineage: Digest32,
    holdout_lineage: Digest32,
}

impl FrozenProductHoldoutV1 {
    pub(super) fn from_plan(plan: &CrossFoldPlanV1) -> Result<Self, ProductEvaluationError> {
        // The original cross-fold freezer also rejects missing or repeated
        // final windows. Retain their semantic commitments, not an opaque ID.
        let fold = plan
            .folds
            .iter()
            .find(|fold| fold.holdout_windows.contains(&plan.final_holdout_window_id))
            .ok_or(ProductEvaluationError::Binding("frozen final fold"))?;
        Ok(Self {
            training_lineage: lineage_digest([
                fold.training_principals.iter().collect(),
                fold.training_episodes.iter().collect(),
                fold.training_windows.iter().collect(),
            ]),
            holdout_lineage: lineage_digest([
                fold.holdout_principals.iter().collect(),
                fold.holdout_episodes.iter().collect(),
                fold.holdout_windows.iter().collect(),
            ]),
        })
    }

    pub(super) fn validate_inputs(
        &self,
        inputs: &TemporalComparisonInputsV1,
    ) -> Result<(), ProductEvaluationError> {
        let training = lineage_digest([
            inputs
                .training
                .iter()
                .map(|row| &row.principal_lineage)
                .collect(),
            inputs
                .training
                .iter()
                .map(|row| &row.episode_lineage)
                .collect(),
            inputs.training.iter().map(|row| &row.window_id).collect(),
        ]);
        let holdout = lineage_digest([
            inputs
                .targets
                .iter()
                .map(|row| &row.principal_lineage)
                .collect(),
            inputs
                .targets
                .iter()
                .map(|row| &row.episode_lineage)
                .collect(),
            inputs.targets.iter().map(|row| &row.window_id).collect(),
        ]);
        if training != self.training_lineage || holdout != self.holdout_lineage {
            return Err(ProductEvaluationError::Binding("frozen final fold lineage"));
        }
        Ok(())
    }

    pub(super) fn digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.intelligence-eval.product-final-fold.v1\0",
            self.training_lineage.as_array(),
            self.holdout_lineage.as_array(),
        ])
    }
}

fn lineage_digest(groups: [BTreeSet<&StableId>; 3]) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-fold-lineage.v1\0".to_vec();
    for group in groups {
        bytes.extend_from_slice(&(group.len() as u64).to_be_bytes());
        for id in group {
            push_id(&mut bytes, id);
        }
    }
    Digest32::of_bytes(&bytes)
}
