//! Frozen comparison declarations, checked against the actual Cell cost owners.
//! Counts and training-receipt references are not self-authenticating: the
//! existing independent signers must attest the resulting frozen evidence.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellTaskCostSummaryV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;

use super::CellEvaluationErrorV1;

/// Count shared components once, including encoder, routing and output heads.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellParameterCapacityV1 {
    pub total_parameters: u64,
    pub trainable_parameters: u64,
    pub maximum_active_parameters: u64,
}

/// Cumulative work includes inherited pretraining and every candidate search
/// run charged by the preregistered allocation convention, not only the last fit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellTrainingBudgetV1 {
    pub examples_seen: u64,
    pub optimizer_steps: u64,
    pub parameter_updates: u64,
    pub compute_units: u64,
    pub compute_unit_contract: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellSelectiveUpdateV1 {
    pub policy_digest: [u8; 32],
    pub eligibility_digest: [u8; 32],
    pub schedule_digest: [u8; 32],
    pub maximum_parameters_per_step: u64,
}

/// Host-supplied observations become signed plan content, never a new proof of
/// training history. A nonzero receipt reference alone proves no such history.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellTrainingObservationV1 {
    pub participant_id: StableId,
    pub capacity: CellParameterCapacityV1,
    pub cumulative: CellTrainingBudgetV1,
    pub selective_update: CellSelectiveUpdateV1,
    pub structure_before: [u8; 32],
    pub structure_after: [u8; 32],
    pub training_receipt_digest: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CellRequiredCostMetricV1 {
    Wall,
    Cpu,
    Energy,
    StorageRead,
    StorageWrite,
    StorageRetention,
    Communication,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellCostCoverageV1 {
    /// Common units, shared-work allocation and meter-coverage convention.
    /// Model implementation sources remain separately bound to each manifest.
    pub metering_contract_digest: [u8; 32],
    pub required_metrics: Vec<CellRequiredCostMetricV1>,
}

impl CellCostCoverageV1 {
    pub fn wall_and_cpu(metering_contract_digest: [u8; 32]) -> Self {
        Self {
            metering_contract_digest,
            required_metrics: vec![
                CellRequiredCostMetricV1::Wall,
                CellRequiredCostMetricV1::Cpu,
            ],
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellComparisonContractV1 {
    pub candidate: CellTrainingObservationV1,
    pub fixed_expert: CellTrainingObservationV1,
    pub cost_coverage: CellCostCoverageV1,
}

impl CellComparisonContractV1 {
    pub(super) fn validate(&mut self) -> Result<(), CellEvaluationErrorV1> {
        use CellEvaluationErrorV1::Binding;
        let left = &self.candidate;
        let right = &self.fixed_expert;
        if left.participant_id == right.participant_id
            || left.capacity != right.capacity
            || left.cumulative != right.cumulative
            || left.selective_update != right.selective_update
            || right.structure_before != right.structure_after
        {
            return Err(Binding(
                "matched capacity, cumulative budget or selective updates",
            ));
        }
        for arm in [left, right] {
            let capacity = &arm.capacity;
            let training = &arm.cumulative;
            let updates = &arm.selective_update;
            let maximum_updates = training
                .optimizer_steps
                .checked_mul(updates.maximum_parameters_per_step)
                .ok_or(Binding("training update overflow"))?;
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
                || training.parameter_updates > maximum_updates
                || [
                    training.compute_unit_contract,
                    updates.policy_digest,
                    updates.eligibility_digest,
                    updates.schedule_digest,
                    arm.structure_before,
                    arm.structure_after,
                    arm.training_receipt_digest,
                ]
                .contains(&[0; 32])
            {
                return Err(Binding("incomplete training observations"));
            }
        }
        let coverage = &mut self.cost_coverage;
        coverage.required_metrics.sort_unstable();
        if coverage.metering_contract_digest == [0; 32]
            || coverage.required_metrics.len() > 7
            || !coverage
                .required_metrics
                .contains(&CellRequiredCostMetricV1::Wall)
            || !coverage
                .required_metrics
                .contains(&CellRequiredCostMetricV1::Cpu)
            || coverage
                .required_metrics
                .windows(2)
                .any(|pair| pair[0] == pair[1])
        {
            return Err(Binding("cost coverage contract"));
        }
        Ok(())
    }
}

/// Read-only evidence export. It cannot be supplied instead of a live journal
/// to freeze or evaluate, and has no Deserialize path into a sealed plan.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellEvaluationArmRecordV1 {
    pub manifest: CellBackendManifestV2,
    pub journal_cut: Digest32,
    pub snapshot_digest: [u8; 32],
    pub cost: CellTaskCostV2,
}

impl CellEvaluationArmRecordV1 {
    pub(super) fn read<W: AnchorWitnessStore>(
        journal: &CellGenerationJournalV2<W>,
        observation: &CellTrainingObservationV1,
        coverage: &CellCostCoverageV1,
    ) -> Result<Self, CellEvaluationErrorV1> {
        use CellEvaluationErrorV1::Binding;
        if !journal
            .is_drained()
            .map_err(CellEvaluationErrorV1::Journal)?
        {
            return Err(Binding("Cell owner is not drained"));
        }
        let manifest = journal.manifest();
        let cost = journal
            .task_cost()
            .map_err(CellEvaluationErrorV1::Journal)?;
        let summary = cost.summary().map_err(|_| Binding("cost ledger"))?;
        if cost.identity().source_digest != manifest.source_digest
            || observation.structure_after != manifest.evolution.structure
            || !summary.missing_stages.is_empty()
            || cost
                .entries()
                .iter()
                .any(|entry| entry.outcome == CellCostOutcomeV2::Unknown)
        {
            return Err(Binding("owner identity, structure or cost stage coverage"));
        }
        validate_required_metrics(&summary, coverage)?;
        Ok(Self {
            manifest: manifest.clone(),
            journal_cut: journal
                .continuity_checkpoint()
                .map_err(CellEvaluationErrorV1::Journal)?,
            snapshot_digest: journal
                .snapshot()
                .map_err(CellEvaluationErrorV1::Journal)?
                .digest()
                .map_err(CellEvaluationErrorV1::Journal)?,
            cost: cost.clone(),
        })
    }
}

fn validate_required_metrics(
    summary: &CellTaskCostSummaryV2,
    coverage: &CellCostCoverageV1,
) -> Result<(), CellEvaluationErrorV1> {
    for metric in &coverage.required_metrics {
        let total = match metric {
            CellRequiredCostMetricV1::Wall => summary.wall_work_micros,
            CellRequiredCostMetricV1::Cpu => summary.cpu_micros,
            CellRequiredCostMetricV1::Energy => summary.energy_microjoules,
            CellRequiredCostMetricV1::StorageRead => summary.storage_read_bytes,
            CellRequiredCostMetricV1::StorageWrite => summary.storage_write_bytes,
            CellRequiredCostMetricV1::StorageRetention => summary.storage_byte_micros,
            CellRequiredCostMetricV1::Communication => summary.communication_bytes,
        };
        if total.unknown_entries != 0 {
            return Err(CellEvaluationErrorV1::Binding(
                "required cost metric is unknown",
            ));
        }
    }
    Ok(())
}
