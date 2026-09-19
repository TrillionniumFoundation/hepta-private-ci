use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::NduBoundedObjectRefV1;
use super::NduCoefficientDimensionsV1;
use super::NduCoefficientManifestError;
use super::NduCoefficientManifestV1;
use super::NduFixedPointScalesV1;
use super::admit_coefficient_manifest_v1;
use crate::AdmittedCovarianceProfileV1;
use crate::CovarianceConventionV1;
use crate::NduCovarianceProfileV1;
use crate::SubjectClass;
use crate::admit_covariance_profile;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn object(value: &str, encoded_bytes: u32) -> NduBoundedObjectRefV1 {
    NduBoundedObjectRefV1 {
        canonical_digest: digest(value),
        encoded_bytes,
    }
}

fn profile(utility_dimension: usize, driver_dimension: usize) -> AdmittedCovarianceProfileV1 {
    must(admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("covariance-units"),
        driver_dimension,
        utility_dimension,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-6,
        maximum_condition: 100.0,
        maximum_absolute_sample: 100.0,
        maximum_absolute_z: 10.0,
        maximum_relative_residual: 1e-9,
    }))
}

fn manifest() -> NduCoefficientManifestV1 {
    NduCoefficientManifestV1 {
        artifact_id: id("ndu-coefficients-v1"),
        subject_class: SubjectClass::Agent,
        objective_class_digest: digest("objective-class"),
        dimensions: NduCoefficientDimensionsV1 {
            preference: 16,
            utility: 2,
            driver: 3,
        },
        dimensions_encoded_bytes: 128,
        fixed_point_scales: NduFixedPointScalesV1 {
            preference_fractional_bits: 32,
            utility_fractional_bits: 32,
            coefficient_fractional_bits: 24,
        },
        fixed_point_scales_encoded_bytes: 96,
        coefficient_bounds: object("coefficient-bounds", 512),
        lipschitz_bounds: object("lipschitz-bounds", 512),
        monotonicity_bounds: object("monotonicity-bounds", 256),
        normalization_digest: digest("normalization"),
        runtime_tuple_digest: digest("runtime-tuple"),
        predecessor_artifact_id: Some(id("ndu-coefficients-v0")),
        expires_unix_ms: 50_000,
        rollback_digest: digest("rollback"),
    }
}

#[test]
fn typed_manifest_admission_binds_registered_covariance_profile() {
    let covariance = profile(2, 3);
    let admitted = must(admit_coefficient_manifest_v1(
        manifest(),
        &covariance,
        10_000,
    ));

    assert_eq!(admitted.covariance_profile_digest(), covariance.digest());
    assert!(!admitted.manifest_digest().is_zero());
    assert!(!admitted.admission_digest.is_zero());
    assert!(!admitted.authority.grants_any());
}

#[test]
fn canonical_v1_dimension_and_scale_bounds_fail_closed() {
    let covariance = profile(2, 3);
    let mut too_wide = manifest();
    too_wide.dimensions.preference = 65;
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            too_wide,
            &covariance,
            10_000,
        )),
        NduCoefficientManifestError::InvalidDimensions
    );

    let mut wrong_scale = manifest();
    wrong_scale.fixed_point_scales.coefficient_fractional_bits = 23;
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            wrong_scale,
            &covariance,
            10_000,
        )),
        NduCoefficientManifestError::InvalidFixedPointScale
    );
}

#[test]
fn manifest_expiry_and_covariance_dimension_mismatch_reject() {
    let covariance = profile(2, 3);
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            manifest(),
            &covariance,
            50_001,
        )),
        NduCoefficientManifestError::Expired
    );

    let wrong_covariance = profile(1, 3);
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            manifest(),
            &wrong_covariance,
            10_000,
        )),
        NduCoefficientManifestError::CovarianceDimensionMismatch
    );
}

#[test]
fn bounded_object_limits_and_missing_semantics_reject() {
    let covariance = profile(2, 3);
    let mut oversized = manifest();
    oversized.coefficient_bounds.encoded_bytes = 16_385;
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            oversized,
            &covariance,
            10_000,
        )),
        NduCoefficientManifestError::BoundedObjectSize("coefficient bounds")
    );

    let mut missing = manifest();
    missing.normalization_digest = Digest32::ZERO;
    assert_eq!(
        must_err(admit_coefficient_manifest_v1(
            missing,
            &covariance,
            10_000,
        )),
        NduCoefficientManifestError::MissingDigest("normalization")
    );
}

#[test]
fn manifest_digest_binds_predecessor_and_bounded_objects() {
    let covariance = profile(2, 3);
    let first = must(admit_coefficient_manifest_v1(
        manifest(),
        &covariance,
        10_000,
    ));

    let mut changed = manifest();
    changed.predecessor_artifact_id = Some(id("ndu-coefficients-v-other"));
    let second = must(admit_coefficient_manifest_v1(
        changed,
        &covariance,
        10_000,
    ));
    assert_ne!(first.manifest_digest(), second.manifest_digest());

    let mut changed_object = manifest();
    changed_object.lipschitz_bounds = object("different-lipschitz", 512);
    let third = must(admit_coefficient_manifest_v1(
        changed_object,
        &covariance,
        10_000,
    ));
    assert_ne!(first.manifest_digest(), third.manifest_digest());
}
