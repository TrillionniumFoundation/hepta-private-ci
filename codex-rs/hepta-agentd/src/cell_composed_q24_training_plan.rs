//! Bind loaded Q24 material to an original frozen row rule and Training cut.
//! This validates supplied contract bytes, not physical training chronology,
//! Root registration, optimizer execution, costs, signatures or adoption.

use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::Digest32;

use super::CellQ24PrivateHeadV1;
use super::LoadedCellQ24ModelV1;

#[path = "cell_composed_q24_training.rs"]
mod training;
pub use training::CellQ24SgdRuleV1;
pub use training::CellQ24TrainedCandidateV1;
pub use training::CellQ24TrainingBatchV1;
pub use training::CellQ24TrainingErrorV1;
pub use training::CellQ24TrainingMetricsV1;
pub use training::CellQ24TrainingOutcomeV1;
pub use training::CellQ24TrainingSampleV1;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24TrainingPlanErrorV1 {
    #[error("Q24 training plan binding: {0}")]
    Binding(&'static str),
    #[error("learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("Q24 candidate material: {0}")]
    Model(#[from] CellGenerationErrorV2),
}

/// Canonical row constraint over a declared original optimizer rule. The host
/// must commit this digest through its original scope before Training; this
/// helper does not establish when that registration or optimization occurred.
pub fn cell_q24_single_head_update_rule_v1(
    baseline: &CellCompatibilityBundleV1,
    head: CellQ24PrivateHeadV1,
    optimizer_rule: Digest32,
) -> Result<Digest32, CellQ24TrainingPlanErrorV1> {
    if optimizer_rule.is_zero() {
        return Err(CellQ24TrainingPlanErrorV1::Binding("optimizer rule"));
    }
    let bundle = baseline.digest().map_err(LearningIterationError::from)?;
    let (tag, index) = match head {
        CellQ24PrivateHeadV1::Drive { index } => (1_u8, index),
        CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index),
    };
    Ok(Digest32::of_parts(&[
        b"hepta.cell.q24.single-head-training-rule.v1\0",
        bundle.as_array(),
        &[tag],
        &index.to_le_bytes(),
        optimizer_rule.as_array(),
    ]))
}

/// Resident immutable baseline, row, original prefix and scope. A caller must
/// supply its authentic original scope; structural equality here cannot create
/// Root custody or independent stage attestations. A failed check is an error,
/// not a NoUpdate decision.
pub struct CellQ24SingleHeadTrainingPlanV1 {
    baseline: Arc<LoadedCellQ24ModelV1>,
    head: CellQ24PrivateHeadV1,
    prefix: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
}

impl CellQ24SingleHeadTrainingPlanV1 {
    pub fn from_dataset_cut(
        snapshot: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        baseline: Arc<LoadedCellQ24ModelV1>,
        head: CellQ24PrivateHeadV1,
        optimizer_rule: Digest32,
    ) -> Result<Self, CellQ24TrainingPlanErrorV1> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        let index = match head {
            CellQ24PrivateHeadV1::Drive { index }
            | CellQ24PrivateHeadV1::Prediction { index } => usize::from(index),
        };
        if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
            || baseline.components() != &snapshot.request.selected_bundle.components
            || index >= baseline.output_width()
        {
            return Err(CellQ24TrainingPlanErrorV1::Binding("original Dataset cut"));
        }
        let rule = cell_q24_single_head_update_rule_v1(
            &snapshot.request.selected_bundle,
            head,
            optimizer_rule,
        )?;
        let expected = FrozenLearningScopeV2::freeze(
            &snapshot.request,
            &snapshot.owners,
            LearningUpdateScopeV2::Cell,
            rule,
        )?;
        if scope != expected {
            return Err(CellQ24TrainingPlanErrorV1::Binding("original frozen row rule"));
        }
        scope.validate_snapshot(&snapshot)?;
        Ok(Self {
            baseline,
            head,
            prefix: snapshot,
            scope,
        })
    }

    /// Read an exact one-Training extension and check its actual loaded bytes.
    /// Original stage owners remain responsible for optimizer/job/cost truth,
    /// current evidence and independent evaluation. No receipt is synthesized.
    pub fn validate_training_candidate(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        candidate: LoadedCellQ24ModelV1,
    ) -> Result<LoadedCellQ24ModelV1, CellQ24TrainingPlanErrorV1> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if snapshot.request != self.prefix.request
            || snapshot.owners != self.prefix.owners
            || snapshot.receipts.len() != self.prefix.receipts.len() + 1
            || !snapshot.receipts.starts_with(&self.prefix.receipts)
            || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
        {
            return Err(CellQ24TrainingPlanErrorV1::Binding("exact Training extension"));
        }
        self.scope.validate_snapshot(snapshot)?;
        let receipt = snapshot.receipts.last().ok_or(
            CellQ24TrainingPlanErrorV1::Binding("Training receipt"),
        )?;
        let LearningIterationObservationV1::Training { candidate: bundle, .. } =
            &receipt.observation
        else {
            return Err(CellQ24TrainingPlanErrorV1::Binding("Training observation"));
        };
        if candidate.components() != &bundle.components {
            return Err(CellQ24TrainingPlanErrorV1::Binding("original candidate bytes"));
        }
        Ok(self.baseline.validate_single_head_candidate(candidate, self.head)?)
    }
}
