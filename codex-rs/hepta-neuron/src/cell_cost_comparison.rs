//! Complete task-cycle cost comparison, using the existing owner's ledger.
//!
//! These checks bind the comparison contract; they do not authenticate a meter
//! or prove quality. Failed candidates must remain in the task's ledger. A
//! missing stage or measurement cannot establish a resource saving.

use crate::CellCostMetricsV2;
use crate::CellCostOutcomeV2;
use crate::CellTaskCostErrorV2;
use crate::CellTaskCostIdentityV2;
use crate::CellTaskCostV2;

/// Explicit common conditions for comparing implementations with different
/// source identities. Every member must be present and equal for both runs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCostComparisonBasisV2 {
    pub inputs: [u8; 32],
    pub resource_budget: [u8; 32],
    /// Execution environment and configuration, not implementation source.
    pub executor: [u8; 32],
    pub metering_contract: [u8; 32],
    pub evaluation: [u8; 32],
}

/// A run includes every attempt in one task cycle. Elapsed time is measured
/// separately from additive work time, because parallel phases may overlap.
pub struct CellCostComparisonRunV2<'a> {
    pub basis: &'a CellCostComparisonBasisV2,
    pub costs: &'a CellTaskCostV2,
    pub elapsed_micros: Option<u64>,
}

/// Signed candidate-minus-baseline differences. Negative means less resource
/// use, not a quality improvement or permission to adopt the candidate.
/// Both immutable ledger identities retain their distinct implementation origins.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCostDifferenceV2 {
    pub baseline_identity: CellTaskCostIdentityV2,
    pub candidate_identity: CellTaskCostIdentityV2,
    pub elapsed_micros: i128,
    pub wall_work_micros: i128,
    pub cpu_micros: i128,
    pub energy_microjoules: i128,
    pub storage_read_bytes: i128,
    pub storage_write_bytes: i128,
    pub storage_byte_micros: i128,
    pub communication_bytes: i128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellCostComparisonErrorV2 {
    Ledger(CellTaskCostErrorV2),
    IncompatibleBasis,
    IncompleteCycle,
}

impl std::fmt::Display for CellCostComparisonErrorV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellCostComparisonErrorV2 {}

pub fn compare_cell_task_costs_v2(
    baseline: CellCostComparisonRunV2<'_>,
    candidate: CellCostComparisonRunV2<'_>,
) -> Result<CellCostDifferenceV2, CellCostComparisonErrorV2> {
    let basis = baseline.basis;
    let baseline_identity = baseline.costs.identity();
    let candidate_identity = candidate.costs.identity();
    if candidate.basis != basis
        || baseline_identity.task_digest != candidate_identity.task_digest
        || [
            basis.inputs,
            basis.resource_budget,
            basis.executor,
            basis.metering_contract,
            basis.evaluation,
        ]
        .contains(&[0; 32])
    {
        return Err(CellCostComparisonErrorV2::IncompatibleBasis);
    }
    let complete = |run: &CellCostComparisonRunV2<'_>| {
        let summary = run
            .costs
            .summary()
            .map_err(CellCostComparisonErrorV2::Ledger)?;
        // Envelopes do not add charges, but their unresolved outcomes still
        // prevent a complete task-cycle comparison.
        if run
            .costs
            .entries()
            .iter()
            .any(|entry| entry.outcome == CellCostOutcomeV2::Unknown)
        {
            return Err(CellCostComparisonErrorV2::IncompleteCycle);
        }
        let elapsed = run
            .elapsed_micros
            .ok_or(CellCostComparisonErrorV2::IncompleteCycle)?;
        let metrics = summary
            .complete_metrics()
            .ok_or(CellCostComparisonErrorV2::IncompleteCycle)?;
        Ok((elapsed, metrics))
    };
    let (before_elapsed, before) = complete(&baseline)?;
    let (after_elapsed, after) = complete(&candidate)?;
    let delta = |left: Option<u64>, right: Option<u64>| match (left, right) {
        (Some(left), Some(right)) => Ok(i128::from(right) - i128::from(left)),
        _ => Err(CellCostComparisonErrorV2::IncompleteCycle),
    };
    let CellCostMetricsV2 {
        wall_micros,
        cpu_micros,
        energy_microjoules,
        storage_read_bytes,
        storage_write_bytes,
        storage_byte_micros,
        communication_bytes,
    } = after;
    Ok(CellCostDifferenceV2 {
        baseline_identity,
        candidate_identity,
        elapsed_micros: i128::from(after_elapsed) - i128::from(before_elapsed),
        wall_work_micros: delta(before.wall_micros, wall_micros)?,
        cpu_micros: delta(before.cpu_micros, cpu_micros)?,
        energy_microjoules: delta(before.energy_microjoules, energy_microjoules)?,
        storage_read_bytes: delta(before.storage_read_bytes, storage_read_bytes)?,
        storage_write_bytes: delta(before.storage_write_bytes, storage_write_bytes)?,
        storage_byte_micros: delta(before.storage_byte_micros, storage_byte_micros)?,
        communication_bytes: delta(before.communication_bytes, communication_bytes)?,
    })
}

#[cfg(test)]
#[path = "cell_cost_comparison_tests.rs"]
mod tests;
