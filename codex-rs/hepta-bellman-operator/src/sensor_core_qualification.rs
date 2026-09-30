//! Public, behavior-oriented qualification receipt for bounded sensor-core builds.
//!
//! The receipt deliberately exposes the algorithm mode and a stable algorithm
//! identity instead of requiring qualification scripts to scan private function
//! names. Private refactors therefore cannot invalidate the contract while a
//! change in exact-versus-reduced semantics remains visible and digest-bound.

use codex_hepta_types::Digest32;

use crate::OperatorSensorCoreBuildReceiptV2;
use crate::SensorCoreBuildErrorV2;
use crate::SensorCoreDesignV1;
use crate::SensorCoreExecutionProfileV2;
use crate::build_sensor_core_v2;

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
    pub qualification_receipt_digest: Digest32,
}

/// Build a bounded sensor core and emit a semantic qualification receipt.
///
/// `selection_mode` is derived from the executed path, not from caller input.
/// The stable reduction algorithm identity and both working-set limits are
/// bound into the aggregate digest. Qualification consumes this receipt rather
/// than inspecting private source symbols.
pub fn build_sensor_core_qualified_v1(
    design: SensorCoreDesignV1,
    profile: SensorCoreExecutionProfileV2,
) -> Result<QualifiedSensorCoreBuildReceiptV1, SensorCoreBuildErrorV2> {
    let build = build_sensor_core_v2(design, profile)?;
    let selection_mode = if build.approximation_applied {
        SensorCoreSelectionModeV1::DeterministicallyReduced
    } else {
        SensorCoreSelectionModeV1::Exact
    };
    let reduction_algorithm_digest = Digest32::of_bytes(REDUCTION_ALGORITHM_ID_V1);
    let mut bytes = b"hepta.learning.operator.qualified-sensor-core.v1".to_vec();
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
    let qualification_receipt_digest = Digest32::of_bytes(&bytes);
    Ok(QualifiedSensorCoreBuildReceiptV1 {
        build,
        selection_mode,
        reduction_algorithm_digest,
        qualification_receipt_digest,
    })
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::OperatorResourceBudgetV1;
    use crate::SensorPointV1;

    fn id(value: impl Into<String>) -> StableId {
        StableId::new(value.into()).unwrap()
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

    fn profile(exact_candidate_limit: usize) -> SensorCoreExecutionProfileV2 {
        SensorCoreExecutionProfileV2 {
            budget: OperatorResourceBudgetV1::qualification_default(),
            exact_candidate_limit,
            maximum_working_candidates: exact_candidate_limit,
        }
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
    }

    #[test]
    fn reduced_mode_is_deterministic_and_has_bounded_geometry_degradation() {
        let exact = build_sensor_core_qualified_v1(design(64), profile(64)).unwrap();
        let reduced_left = build_sensor_core_qualified_v1(design(64), profile(16)).unwrap();
        let reduced_right = build_sensor_core_qualified_v1(design(64), profile(16)).unwrap();
        assert_eq!(reduced_left, reduced_right);
        let exact_fill = exact.build.manifest.fill_distance_q32.raw();
        let reduced_fill = reduced_left.build.manifest.fill_distance_q32.raw();
        assert!(reduced_fill <= exact_fill.saturating_mul(4));
        assert!(
            reduced_left.build.manifest.mesh_ratio_q32.raw()
                <= 4 * FixedQ32::ONE.raw()
        );
    }
}
