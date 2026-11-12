//! Supplied comparison declarations and actual cost-coverage requirements.
//! No count, matched budget, role or measured cost is filled in by this loader.

use codex_hepta_types::StableId;
use serde::{Deserialize, Serialize};
use crate::{AgentdError, CellComparisonContractV1, CellCostCoverageV1,
    CellParameterCapacityV1, CellRequiredCostMetricV1, CellSelectiveUpdateV1,
    CellTrainingBudgetV1, CellTrainingObservationV1};
use super::deployment_error;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCapacityData {
    pub total_parameters: u64,
    pub trainable_parameters: u64,
    pub maximum_active_parameters: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTrainingBudgetData {
    pub examples_seen: u64,
    pub optimizer_steps: u64,
    pub parameter_updates: u64,
    pub compute_units: u64,
    pub compute_unit_contract: [u8; 32],
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSelectiveUpdateData {
    pub policy_digest: [u8; 32],
    pub eligibility_digest: [u8; 32],
    pub schedule_digest: [u8; 32],
    pub maximum_parameters_per_step: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTrainingObservationData {
    pub participant_id: String,
    pub capacity: OriginalCapacityData,
    pub cumulative: OriginalTrainingBudgetData,
    pub selective_update: OriginalSelectiveUpdateData,
    pub structure_before: [u8; 32],
    pub structure_after: [u8; 32],
    pub training_receipt_digest: [u8; 32],
}
impl OriginalTrainingObservationData {
    fn original(&self) -> Result<CellTrainingObservationV1, AgentdError> {
        Ok(CellTrainingObservationV1 {
            participant_id: StableId::new(&self.participant_id).map_err(deployment_error)?,
            capacity: CellParameterCapacityV1 {
                total_parameters: self.capacity.total_parameters,
                trainable_parameters: self.capacity.trainable_parameters,
                maximum_active_parameters: self.capacity.maximum_active_parameters,
            },
            cumulative: CellTrainingBudgetV1 {
                examples_seen: self.cumulative.examples_seen,
                optimizer_steps: self.cumulative.optimizer_steps,
                parameter_updates: self.cumulative.parameter_updates,
                compute_units: self.cumulative.compute_units,
                compute_unit_contract: self.cumulative.compute_unit_contract,
            },
            selective_update: CellSelectiveUpdateV1 {
                policy_digest: self.selective_update.policy_digest,
                eligibility_digest: self.selective_update.eligibility_digest,
                schedule_digest: self.selective_update.schedule_digest,
                maximum_parameters_per_step: self.selective_update.maximum_parameters_per_step,
            },
            structure_before: self.structure_before, structure_after: self.structure_after,
            training_receipt_digest: self.training_receipt_digest,
        })
    }
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalCostMetricData {
    Wall, Cpu, Energy, StorageRead, StorageWrite, StorageRetention, Communication,
}
impl OriginalCostMetricData {
    fn original(self) -> CellRequiredCostMetricV1 {
        match self {
            Self::Wall => CellRequiredCostMetricV1::Wall,
            Self::Cpu => CellRequiredCostMetricV1::Cpu,
            Self::Energy => CellRequiredCostMetricV1::Energy,
            Self::StorageRead => CellRequiredCostMetricV1::StorageRead,
            Self::StorageWrite => CellRequiredCostMetricV1::StorageWrite,
            Self::StorageRetention => CellRequiredCostMetricV1::StorageRetention,
            Self::Communication => CellRequiredCostMetricV1::Communication,
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalComparisonData {
    pub candidate: OriginalTrainingObservationData,
    pub fixed_expert: OriginalTrainingObservationData,
    pub metering_contract_digest: [u8; 32],
    pub required_metrics: Vec<OriginalCostMetricData>,
}
impl OriginalComparisonData {
    pub(super) fn original(&self) -> Result<CellComparisonContractV1, AgentdError> {
        Ok(CellComparisonContractV1 {
            candidate: self.candidate.original()?,
            fixed_expert: self.fixed_expert.original()?,
            cost_coverage: CellCostCoverageV1 {
                metering_contract_digest: self.metering_contract_digest,
                required_metrics: self.required_metrics.iter().copied()
                    .map(OriginalCostMetricData::original).collect(),
            },
        })
    }
}
