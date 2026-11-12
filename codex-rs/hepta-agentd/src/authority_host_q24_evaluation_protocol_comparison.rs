//! Pinned matching declarations. Native Cell cost and comparison validation
//! remains mandatory; these fields do not prove training work occurred.

use super::*;
use crate::CellComparisonContractV1;
use crate::CellCostCoverageV1;
use crate::CellParameterCapacityV1;
use crate::CellRequiredCostMetricV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;
use crate::CellTrainingObservationV1;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ComparisonData {
    candidate: ArmData,
    fixed_expert: ArmData,
    fixed_training_receipt: [u8; 32],
    metering_contract: [u8; 32],
    required_metrics: Vec<CostMetric>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArmData {
    total_parameters: u64,
    trainable_parameters: u64,
    maximum_active_parameters: u64,
    examples_seen: u64,
    optimizer_steps: u64,
    parameter_updates: u64,
    compute_units: u64,
    compute_unit_contract: [u8; 32],
    update_policy: [u8; 32],
    update_eligibility: [u8; 32],
    update_schedule: [u8; 32],
    maximum_parameters_per_step: u64,
    structure_before: [u8; 32],
    structure_after: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum CostMetric {
    Wall,
    Cpu,
    Energy,
    StorageRead,
    StorageWrite,
    StorageRetention,
    Communication,
}

impl ComparisonData {
    pub(super) fn realize(
        &self,
        candidate: StableId,
        fixed_expert: StableId,
        original_training_receipt: Digest32,
    ) -> CellComparisonContractV1 {
        CellComparisonContractV1 {
            candidate: self
                .candidate
                .convert(candidate, original_training_receipt.into_array()),
            fixed_expert: self
                .fixed_expert
                .convert(fixed_expert, self.fixed_training_receipt),
            cost_coverage: CellCostCoverageV1 {
                metering_contract_digest: self.metering_contract,
                required_metrics: self
                    .required_metrics
                    .iter()
                    .map(|metric| match metric {
                        CostMetric::Wall => CellRequiredCostMetricV1::Wall,
                        CostMetric::Cpu => CellRequiredCostMetricV1::Cpu,
                        CostMetric::Energy => CellRequiredCostMetricV1::Energy,
                        CostMetric::StorageRead => CellRequiredCostMetricV1::StorageRead,
                        CostMetric::StorageWrite => CellRequiredCostMetricV1::StorageWrite,
                        CostMetric::StorageRetention => CellRequiredCostMetricV1::StorageRetention,
                        CostMetric::Communication => CellRequiredCostMetricV1::Communication,
                    })
                    .collect(),
            },
        }
    }
}

impl ArmData {
    fn convert(
        &self,
        participant_id: StableId,
        training_receipt_digest: [u8; 32],
    ) -> CellTrainingObservationV1 {
        CellTrainingObservationV1 {
            participant_id,
            capacity: CellParameterCapacityV1 {
                total_parameters: self.total_parameters,
                trainable_parameters: self.trainable_parameters,
                maximum_active_parameters: self.maximum_active_parameters,
            },
            cumulative: CellTrainingBudgetV1 {
                examples_seen: self.examples_seen,
                optimizer_steps: self.optimizer_steps,
                parameter_updates: self.parameter_updates,
                compute_units: self.compute_units,
                compute_unit_contract: self.compute_unit_contract,
            },
            selective_update: CellSelectiveUpdateV1 {
                policy_digest: self.update_policy,
                eligibility_digest: self.update_eligibility,
                schedule_digest: self.update_schedule,
                maximum_parameters_per_step: self.maximum_parameters_per_step,
            },
            structure_before: self.structure_before,
            structure_after: self.structure_after,
            training_receipt_digest,
        }
    }
}
