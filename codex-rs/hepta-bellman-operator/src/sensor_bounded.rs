//! Explicit work-budget admission for the exact sensor-core reference algorithm.
//!
//! The reference implementation intentionally uses exact farthest-point
//! selection and exact pairwise geometry. Those operations are useful for a
//! qualification oracle but their nominal dimension/count maxima alone do not
//! bound CPU tightly enough. This wrapper computes a conservative coordinate-
//! distance work estimate and fails before entering the exact algorithm when
//! the configured source budget would be exceeded.

use std::error::Error as StdError;
use std::fmt;

use crate::reference::OperatorClosureError;
use crate::reference::OperatorSensorCoreManifestV1;
use crate::reference::SensorCoreDesignV1;

/// Conservative source-level budget for exact coordinate comparisons.
///
/// A selected host may impose a smaller profile budget. Raising this constant
/// requires a separate capacity review; this is not a target-host measurement.
const MAX_SENSOR_COORDINATE_WORK: u128 = 64_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SensorCoreBuildError {
    WorkBudgetExceeded { estimated: u128, maximum: u128 },
    Closure(OperatorClosureError),
}

impl fmt::Display for SensorCoreBuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SensorCoreBuildError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Closure(error) => Some(error),
            Self::WorkBudgetExceeded { .. } => None,
        }
    }
}

impl From<OperatorClosureError> for SensorCoreBuildError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Closure(value)
    }
}

/// Build a deterministic exact sensor core only when its worst-case coordinate
/// work fits the qualification-source budget.
pub fn build_sensor_core(
    design: SensorCoreDesignV1,
) -> Result<OperatorSensorCoreManifestV1, SensorCoreBuildError> {
    let candidate_count = design.candidates.len();
    let requested_count = design.requested_count;
    let dimensions = design
        .candidates
        .first()
        .map_or(0, |candidate| candidate.coordinates.len());
    if let Some(estimated) = estimate_coordinate_work(candidate_count, requested_count, dimensions)
        && estimated > MAX_SENSOR_COORDINATE_WORK
    {
        return Err(SensorCoreBuildError::WorkBudgetExceeded {
            estimated,
            maximum: MAX_SENSOR_COORDINATE_WORK,
        });
    }
    Ok(crate::reference::build_sensor_core(design)?)
}

fn estimate_coordinate_work(
    candidate_count: usize,
    requested_count: usize,
    dimensions: usize,
) -> Option<u128> {
    let n = candidate_count as u128;
    let k = requested_count as u128;
    let d = dimensions as u128;

    // Current exact implementation performs:
    // 1. all-pairs coordinate duplicate comparison;
    // 2. initial + per-selected-point candidate distance updates;
    // 3. all-pairs selected-point separation measurement.
    let candidate_pairs = n.checked_mul(n.saturating_sub(1))?.checked_div(2)?;
    let duplicate_work = candidate_pairs.checked_mul(d)?;
    let farthest_rounds = k.max(1);
    let farthest_work = n.checked_mul(farthest_rounds)?.checked_mul(d)?;
    let selected_pairs = k.checked_mul(k.saturating_sub(1))?.checked_div(2)?;
    let separation_work = selected_pairs.checked_mul(d)?;
    duplicate_work
        .checked_add(farthest_work)?
        .checked_add(separation_work)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_sensor_budget_accepts_small_reference_fixture() {
        assert!(
            estimate_coordinate_work(64, 16, 8).expect("estimate") < MAX_SENSOR_COORDINATE_WORK
        );
    }

    #[test]
    fn exact_sensor_budget_rejects_nominal_maxima_before_quadratic_work() {
        let estimated = estimate_coordinate_work(16_384, 4_096, 32).expect("estimate");
        assert!(estimated > MAX_SENSOR_COORDINATE_WORK);
    }

    #[test]
    fn exact_sensor_budget_accounts_for_selected_pair_geometry() {
        let low_selection = estimate_coordinate_work(1_024, 8, 16).expect("estimate");
        let high_selection = estimate_coordinate_work(1_024, 512, 16).expect("estimate");
        assert!(high_selection > low_selection);
    }
}
