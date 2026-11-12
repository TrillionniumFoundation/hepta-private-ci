//! Fixed comparison declarations, separate from the later original Cell cuts.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_types::Digest32;

use super::Error;
use crate::CellComparisonContractV1;
use crate::CellCostCoverageV1;
use crate::CellParameterCapacityV1;
use crate::CellRequiredCostMetricV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;
use crate::CellTrainingObservationV1;

/// The complete comparison policy is fixed before the original T profile is
/// signed. These declarations do not authenticate inherited training history.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyComparisonPolicyV2 {
    pub capacity: CellParameterCapacityV1,
    pub cumulative: CellTrainingBudgetV1,
    pub selective_update: CellSelectiveUpdateV1,
    pub baseline_training_receipt_digest: [u8; 32],
    pub cost_coverage: CellCostCoverageV1,
}

impl OriginalCircuitOnPolicyComparisonPolicyV2 {
    pub(super) fn normalize(&mut self) -> Result<(), Error> {
        let capacity = &self.capacity;
        let training = &self.cumulative;
        let updates = &self.selective_update;
        let maximum = training.optimizer_steps
            .checked_mul(updates.maximum_parameters_per_step)
            .ok_or(Error::Binding("comparison training update overflow"))?;
        if capacity.total_parameters == 0
            || capacity.trainable_parameters == 0
            || capacity.maximum_active_parameters == 0
            || capacity.trainable_parameters > capacity.total_parameters
            || capacity.maximum_active_parameters > capacity.total_parameters
            || training.examples_seen == 0
            || training.optimizer_steps == 0
            || training.parameter_updates == 0
            || training.compute_units == 0
            || updates.maximum_parameters_per_step == 0
            || updates.maximum_parameters_per_step > capacity.trainable_parameters
            || training.parameter_updates > maximum
            || [
                training.compute_unit_contract,
                updates.policy_digest,
                updates.eligibility_digest,
                updates.schedule_digest,
                self.baseline_training_receipt_digest,
                self.cost_coverage.metering_contract_digest,
            ].contains(&[0; 32])
        {
            return Err(Error::Binding("complete fixed comparison declarations"));
        }
        let metrics = &mut self.cost_coverage.required_metrics;
        metrics.sort_unstable();
        if metrics.len() > 7
            || !metrics.contains(&CellRequiredCostMetricV1::Wall)
            || !metrics.contains(&CellRequiredCostMetricV1::Cpu)
            || metrics.windows(2).any(|pair| pair[0] == pair[1])
        {
            return Err(Error::Binding("complete fixed cost coverage"));
        }
        Ok(())
    }

    /// Only these observed fields are late: the unique original T candidate,
    /// its original receipt payload, and the two actually read Cell structures.
    pub(super) fn observed(
        &self,
        training: &LearningIterationSnapshotV1,
        candidate_structure: [u8; 32],
        baseline_structure: [u8; 32],
    ) -> Result<CellComparisonContractV1, Error> {
        let original = LearningIterationCoordinatorV1::from_snapshot(training.clone())?;
        let candidate = original.candidate()
            .ok_or(Error::Binding("unique original signed T candidate"))?;
        let receipt = training.receipts.get(2)
            .ok_or(Error::Binding("original T receipt payload"))?;
        if candidate_structure == [0; 32] || baseline_structure == [0; 32] {
            return Err(Error::Binding("actual nonzero Cell structures"));
        }
        let observation = |participant_id, structure_before, structure_after, training_receipt_digest| {
            CellTrainingObservationV1 {
                participant_id,
                capacity: self.capacity.clone(),
                cumulative: self.cumulative.clone(),
                selective_update: self.selective_update.clone(),
                structure_before,
                structure_after,
                training_receipt_digest,
            }
        };
        Ok(CellComparisonContractV1 {
            candidate: observation(
                candidate.artifact_id.clone(),
                baseline_structure,
                candidate_structure,
                Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(receipt)?)
                    .into_array(),
            ),
            fixed_expert: observation(
                training.request.selected_bundle.artifact_id.clone(),
                baseline_structure,
                baseline_structure,
                self.baseline_training_receipt_digest,
            ),
            cost_coverage: self.cost_coverage.clone(),
        })
    }
}
