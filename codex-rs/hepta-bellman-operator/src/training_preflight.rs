//! Allocation-free profile validation for the signed owner materialization path.

use crate::MAX_SIGNED_OPERATOR_ROWS;
use crate::OperatorDatasetBindingError;
use crate::TabularOperatorPlanV1;

/// Reject impossible support budgets before signature canonicalization, sorting
/// or owner record materialization. This does not replace per-cell validation.
pub fn preflight_signed_tabular_v3(
    plan: &TabularOperatorPlanV1,
) -> Result<(), OperatorDatasetBindingError> {
    validate_shape(
        plan.sensor_ids.len(),
        plan.action_ids.len(),
        plan.minimum_samples_per_cell,
        plan.samples.len(),
    )
}

pub(crate) fn validate_shape(
    sensors: usize,
    actions: usize,
    minimum: usize,
    rows: usize,
) -> Result<(), OperatorDatasetBindingError> {
    if sensors == 0
        || sensors > 4096
        || actions == 0
        || actions > 128
        || minimum == 0
        || rows == 0
        || rows > MAX_SIGNED_OPERATOR_ROWS
    {
        return Err(OperatorDatasetBindingError::Bounds);
    }
    let required = sensors
        .checked_mul(actions)
        .and_then(|cells| cells.checked_mul(minimum))
        .ok_or(OperatorDatasetBindingError::Bounds)?;
    if required > rows {
        return Err(OperatorDatasetBindingError::Bounds);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_signed_profile_boundary_is_admitted() {
        assert!(validate_shape(32, 128, 1, 4096).is_ok());
        assert!(validate_shape(16, 128, 2, 4096).is_ok());
        assert!(validate_shape(1, 1, 4096, 4096).is_ok());
    }

    #[test]
    fn impossible_support_rejects_before_work() {
        for dimensions in [
            (32, 128, 2, 4096),
            (1, 1, 3, 2),
            (0, 1, 1, 1),
            (1, 0, 1, 1),
            (1, 1, 0, 1),
            (1, 1, 1, 0),
            (1, 1, 1, 4097),
            (4097, 1, 1, 4096),
            (1, 129, 1, 4096),
            (2, 2, usize::MAX, 4096),
        ] {
            assert!(
                validate_shape(dimensions.0, dimensions.1, dimensions.2, dimensions.3).is_err()
            );
        }
    }

    #[test]
    fn all_small_shapes_match_independent_integer_oracle() {
        for sensors in 0..=8 {
            for actions in 0..=8 {
                for minimum in 0..=8 {
                    for rows in 0..=64 {
                        let expected = sensors > 0
                            && actions > 0
                            && minimum > 0
                            && rows > 0
                            && sensors * actions * minimum <= rows;
                        assert_eq!(
                            validate_shape(sensors, actions, minimum, rows).is_ok(),
                            expected
                        );
                    }
                }
            }
        }
    }
}
