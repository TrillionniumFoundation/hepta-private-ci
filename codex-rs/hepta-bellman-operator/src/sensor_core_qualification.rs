//! Public, behavior-oriented qualification receipt for bounded sensor-core builds.
//!
//! The receipt exposes the executed algorithm mode and validates geometry against
//! the complete input design, not only the reduced working set. Private refactors
//! therefore cannot invalidate the contract while omission of a cluster or
//! outlier cannot produce a misleadingly small working-set fill distance.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::OperatorResourceBudgetV1;
use crate::OperatorResourceKindV1;
use crate::OperatorSensorCoreBuildReceiptV2;
use crate::OperatorWorkErrorV1;
use crate::OperatorWorkMeter;
use crate::OperatorWorkSnapshotV1;
use crate::SensorCoreBuildErrorV2;
use crate::SensorCoreDesignV1;
use crate::SensorCoreExecutionProfileV2;
use crate::SensorPointV1;
use crate::build_sensor_core_v2;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;

const REDUCTION_ALGORITHM_ID_V1: &[u8] =
    b"hepta.learning.operator.sensor-core.fingerprint-stratified-fps.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorCoreSelectionModeV1 {
    Exact,
    DeterministicallyReduced,
}

impl SensorCoreSelectionModeV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Exact => "exact",
            Self::DeterministicallyReduced => "reduced",
        }
    }

    const fn tag(self) -> u8 {
        match self {
            Self::Exact => 0,
            Self::DeterministicallyReduced => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedSensorCoreBuildReceiptV1 {
    pub build: OperatorSensorCoreBuildReceiptV2,
    pub selection_mode: SensorCoreSelectionModeV1,
    pub reduction_algorithm_digest: Digest32,
    /// Covering radius measured over every submitted candidate.
    pub full_input_fill_distance_q32: FixedQ32,
    /// Full-input fill distance divided by selected-point separation radius.
    pub full_input_mesh_ratio_q32: FixedQ32,
    /// Aggregate build plus full-input geometry-validation work.
    pub total_work: OperatorWorkSnapshotV1,
    pub qualification_receipt_digest: Digest32,
}

/// Build a bounded sensor core and emit a semantic qualification receipt.
///
/// `selection_mode` is derived from the executed path, not caller input. The
/// algorithm identity, working-set limits, full-input geometry and total work
/// are digest-bound. Qualification consumes this receipt rather than inspecting
/// private source symbols.
pub fn build_sensor_core_qualified_v1(
    design: SensorCoreDesignV1,
    profile: SensorCoreExecutionProfileV2,
) -> Result<QualifiedSensorCoreBuildReceiptV1, SensorCoreBuildErrorV2> {
    let all_candidates = design.candidates.clone();
    let build = build_sensor_core_v2(design, profile)?;
    let selection_mode = if build.approximation_applied {
        SensorCoreSelectionModeV1::DeterministicallyReduced
    } else {
        SensorCoreSelectionModeV1::Exact
    };
    let (full_input_fill_distance_q32, full_input_mesh_ratio_q32, geometry_work) =
        validate_full_input_geometry(
            &all_candidates,
            &build.manifest.selected_points,
            build.manifest.separation_radius_q32,
            build.profile.budget,
            build.work.operations,
        )?;
    if full_input_mesh_ratio_q32.raw() > 4 * FixedQ32::ONE.raw() {
        return Err(SensorCoreBuildErrorV2::MeshRatio);
    }
    let total_work = OperatorWorkSnapshotV1 {
        operations: checked_add(build.work.operations, geometry_work.operations)?,
        estimated_bytes: build
            .work
            .estimated_bytes
            .max(geometry_work.estimated_bytes),
        elapsed_micros: build
            .work
            .elapsed_micros
            .max(geometry_work.elapsed_micros),
    };
    let reduction_algorithm_digest = Digest32::of_bytes(REDUCTION_ALGORITHM_ID_V1);
    let mut bytes = b"hepta.learning.operator.qualified-sensor-core.v2".to_vec();
    bytes.extend_from_slice(build.receipt_digest.as_array());
    bytes.push(selection_mode.tag());
    bytes.extend_from_slice(reduction_algorithm_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(build.profile.exact_candidate_limit)
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u64::try_from(build.profile.maximum_working_candidates)
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&full_input_fill_distance_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&full_input_mesh_ratio_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&total_work.operations.to_be_bytes());
    bytes.extend_from_slice(&total_work.estimated_bytes.to_be_bytes());
    bytes.extend_from_slice(&total_work.elapsed_micros.to_be_bytes());
    let qualification_receipt_digest = Digest32::of_bytes(&bytes);
    Ok(QualifiedSensorCoreBuildReceiptV1 {
        build,
        selection_mode,
        reduction_algorithm_digest,
        full_input_fill_distance_q32,
        full_input_mesh_ratio_q32,
        total_work,
        qualification_receipt_digest,
    })
}

fn validate_full_input_geometry(
    candidates: &[SensorPointV1],
    selected: &[SensorPointV1],
    separation_radius_q32: FixedQ32,
    budget: OperatorResourceBudgetV1,
    build_operations: u64,
) -> Result<(FixedQ32, FixedQ32, OperatorWorkSnapshotV1), SensorCoreBuildErrorV2> {
    let dimensions = candidates
        .first()
        .ok_or(SensorCoreBuildErrorV2::InternalInvariant)?
        .coordinates
        .len();
    let required = checked_mul(
        checked_mul(checked_u64(candidates.len())?, checked_u64(selected.len())?)?,
        checked_u64(dimensions)?,
    )?;
    let aggregate = checked_add(build_operations, required)?;
    if aggregate > budget.max_operations {
        return Err(SensorCoreBuildErrorV2::Work(
            OperatorWorkErrorV1::ResourceExhausted {
                resource: OperatorResourceKindV1::Operations,
                required: aggregate,
                limit: budget.max_operations,
            },
        ));
    }
    let mut meter = OperatorWorkMeter::new(budget)?;
    meter.preflight_operations(required)?;
    let mut maximum_nearest_squared = 0_u128;
    for candidate in candidates {
        let mut nearest = u128::MAX;
        for sensor in selected {
            nearest = nearest.min(distance_squared(candidate, sensor, &mut meter)?);
        }
        maximum_nearest_squared = maximum_nearest_squared.max(nearest);
    }
    let fill_raw = integer_sqrt(maximum_nearest_squared)?;
    let separation_raw = u128::try_from(separation_radius_q32.raw())
        .map_err(|_| SensorCoreBuildErrorV2::SensorSeparation)?;
    if separation_raw == 0 {
        return Err(SensorCoreBuildErrorV2::SensorSeparation);
    }
    let mesh_raw = fill_raw
        .checked_shl(32)
        .ok_or(SensorCoreBuildErrorV2::Arithmetic)?
        / separation_raw;
    Ok((
        fixed_from_u128(fill_raw)?,
        fixed_from_u128(mesh_raw)?,
        meter.finish()?,
    ))
}

fn distance_squared(
    left: &SensorPointV1,
    right: &SensorPointV1,
    meter: &mut OperatorWorkMeter,
) -> Result<u128, SensorCoreBuildErrorV2> {
    let mut total = 0_u128;
    for (left, right) in left.coordinates.iter().zip(&right.coordinates) {
        meter.consume(1)?;
        let delta = i128::from(left.raw()) - i128::from(right.raw());
        let magnitude = delta.unsigned_abs();
        total = total
            .checked_add(
                magnitude
                    .checked_mul(magnitude)
                    .ok_or(SensorCoreBuildErrorV2::Arithmetic)?,
            )
            .ok_or(SensorCoreBuildErrorV2::Arithmetic)?;
    }
    Ok(total)
}

fn integer_sqrt(value: u128) -> Result<u128, SensorCoreBuildErrorV2> {
    if value < 2 {
        return Ok(value);
    }
    let mut left = 1_u128;
    let mut right = value.min(u128::from(u64::MAX));
    while left <= right {
        let middle = left + (right - left) / 2;
        let quotient = value / middle;
        if middle == quotient {
            return Ok(middle);
        }
        if middle < quotient {
            left = middle
                .checked_add(1)
                .ok_or(SensorCoreBuildErrorV2::Arithmetic)?;
        } else {
            right = middle - 1;
        }
    }
    Ok(right)
}

fn fixed_from_u128(value: u128) -> Result<FixedQ32, SensorCoreBuildErrorV2> {
    let raw = i64::try_from(value).map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::StableId;

    use super::*;

    fn id(value: impl Into<String>) -> StableId {
        StableId::new(value.into()).unwrap()
    }

    fn profile(exact_candidate_limit: usize) -> SensorCoreExecutionProfileV2 {
        SensorCoreExecutionProfileV2 {
            budget: OperatorResourceBudgetV1::qualification_default(),
            exact_candidate_limit,
            maximum_working_candidates: exact_candidate_limit,
        }
    }

    fn design(candidate_count: usize) -> SensorCoreDesignV1 {
        let denominator = i64::try_from(candidate_count - 1).unwrap();
        SensorCoreDesignV1 {
            sensor_core_id: id("qualification-mode-core"),
            state_axis_digest: Digest32::of_bytes(b"qualification-mode-axis"),
            candidate_design_digest: Digest32::of_bytes(
                format!("qualification-mode-design-{candidate_count}").as_bytes(),
            ),
            seed_digest: Digest32::of_bytes(b"qualification-mode-seed"),
            requested_count: 4,
            candidates: (0..candidate_count)
                .map(|index| SensorPointV1 {
                    point_id: id(format!("point-{index:04}")),
                    coordinates: vec![FixedQ32::from_raw(
                        i64::try_from(index).unwrap() * FixedQ32::ONE.raw() / denominator,
                    )],
                })
                .collect(),
        }
    }

    fn diagonal_manifold(candidate_count: usize) -> SensorCoreDesignV1 {
        let denominator = i64::try_from(candidate_count - 1).unwrap();
        let mut value = design(candidate_count);
        value.candidate_design_digest = Digest32::of_bytes(b"diagonal-manifold");
        for (index, point) in value.candidates.iter_mut().enumerate() {
            let coordinate = FixedQ32::from_raw(
                i64::try_from(index).unwrap() * FixedQ32::ONE.raw() / denominator,
            );
            point.coordinates = vec![coordinate, coordinate];
        }
        value
    }

    fn clustered_with_outlier() -> SensorCoreDesignV1 {
        let mut value = design(64);
        value.candidate_design_digest = Digest32::of_bytes(b"clustered-outlier");
        for (index, point) in value.candidates.iter_mut().enumerate() {
            let raw = if index == 63 {
                FixedQ32::ONE.raw()
            } else {
                i64::try_from(index).unwrap() * FixedQ32::ONE.raw() / 630
            };
            point.coordinates = vec![FixedQ32::from_raw(raw)];
        }
        value
    }

    #[test]
    fn semantic_receipt_reports_exact_and_reduced_modes() {
        let exact = build_sensor_core_qualified_v1(design(16), profile(16)).unwrap();
        let reduced = build_sensor_core_qualified_v1(design(16), profile(8)).unwrap();
        assert_eq!(exact.selection_mode, SensorCoreSelectionModeV1::Exact);
        assert_eq!(exact.selection_mode.as_str(), "exact");
        assert_eq!(
            reduced.selection_mode,
            SensorCoreSelectionModeV1::DeterministicallyReduced
        );
        assert_eq!(reduced.selection_mode.as_str(), "reduced");
        assert_ne!(
            exact.qualification_receipt_digest,
            reduced.qualification_receipt_digest
        );
        assert_eq!(
            exact.reduction_algorithm_digest,
            reduced.reduction_algorithm_digest
        );
        assert_eq!(
            exact.full_input_fill_distance_q32,
            exact.build.manifest.fill_distance_q32
        );
        assert!(
            reduced.full_input_fill_distance_q32
                >= reduced.build.manifest.fill_distance_q32
        );
    }

    #[test]
    fn reduced_mode_is_deterministic_and_has_bounded_full_input_geometry() {
        let exact = build_sensor_core_qualified_v1(design(64), profile(64)).unwrap();
        let reduced_left = build_sensor_core_qualified_v1(design(64), profile(16)).unwrap();
        let reduced_right = build_sensor_core_qualified_v1(design(64), profile(16)).unwrap();
        assert_eq!(reduced_left, reduced_right);
        assert!(
            reduced_left.full_input_fill_distance_q32.raw()
                <= exact
                    .full_input_fill_distance_q32
                    .raw()
                    .saturating_mul(4)
        );
        assert!(
            reduced_left.full_input_mesh_ratio_q32.raw()
                <= 4 * FixedQ32::ONE.raw()
        );
        assert!(reduced_left.total_work.operations > reduced_left.build.work.operations);
    }

    #[test]
    fn low_dimensional_manifold_is_checked_against_every_input_point() {
        let receipt =
            build_sensor_core_qualified_v1(diagonal_manifold(64), profile(16)).unwrap();
        assert_eq!(
            receipt.selection_mode,
            SensorCoreSelectionModeV1::DeterministicallyReduced
        );
        assert!(receipt.full_input_fill_distance_q32 >= receipt.build.manifest.fill_distance_q32);
        assert!(receipt.full_input_mesh_ratio_q32.raw() <= 4 * FixedQ32::ONE.raw());
    }

    #[test]
    fn clustered_outlier_cannot_hide_behind_working_set_geometry() {
        match build_sensor_core_qualified_v1(clustered_with_outlier(), profile(16)) {
            Ok(receipt) => {
                assert!(
                    receipt.full_input_fill_distance_q32
                        >= receipt.build.manifest.fill_distance_q32
                );
                assert!(
                    receipt.full_input_mesh_ratio_q32.raw()
                        <= 4 * FixedQ32::ONE.raw()
                );
            }
            Err(SensorCoreBuildErrorV2::MeshRatio) => {}
            Err(error) => panic!("unexpected clustered/outlier failure: {error:?}"),
        }
    }

    #[test]
    fn full_input_geometry_work_is_budgeted() {
        let mut constrained = profile(16);
        constrained.budget.max_operations = 1_000;
        let result = build_sensor_core_qualified_v1(design(64), constrained);
        assert!(matches!(
            result,
            Err(SensorCoreBuildErrorV2::Work(
                OperatorWorkErrorV1::ResourceExhausted {
                    resource: OperatorResourceKindV1::Operations,
                    ..
                }
            ))
        ));
    }
}
