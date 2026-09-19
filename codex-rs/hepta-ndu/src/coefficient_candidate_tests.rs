use std::fmt::Debug;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::materialize_q24_coefficient_candidate_v1;
use crate::AdmittedCovarianceProfileV1;
use crate::AdmittedNduCoefficientManifestV1;
use crate::CovarianceConventionV1;
use crate::CovarianceError;
use crate::NduBoundedObjectRefV1;
use crate::NduCoefficientDimensionsV1;
use crate::NduCoefficientManifestV1;
use crate::NduCovarianceProfileV1;
use crate::NduFixedPointScalesV1;
use crate::SubjectClass;
use crate::ZEstimateV1;
use crate::admit_coefficient_manifest_v1;
use crate::admit_covariance_profile;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profile(
    units: &str,
    driver_dimension: usize,
    maximum_absolute_z: f64,
) -> AdmittedCovarianceProfileV1 {
    must(admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest(units),
        driver_dimension,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-6,
        maximum_condition: 100.0,
        maximum_absolute_sample: 100.0,
        maximum_absolute_z,
        maximum_relative_residual: 1e-9,
    }))
}

fn bounded(value: &str, encoded_bytes: u32) -> NduBoundedObjectRefV1 {
    NduBoundedObjectRefV1 {
        canonical_digest: digest(value),
        encoded_bytes,
    }
}

fn manifest(
    profile: &AdmittedCovarianceProfileV1,
    artifact_id: &str,
) -> AdmittedNduCoefficientManifestV1 {
    must(admit_coefficient_manifest_v1(
        NduCoefficientManifestV1 {
            artifact_id: id(artifact_id),
            subject_class: SubjectClass::Agent,
            objective_class_digest: digest("objective-class"),
            dimensions: NduCoefficientDimensionsV1 {
                preference: 16,
                utility: u16::try_from(profile.specification.utility_dimension)
                    .unwrap_or(u16::MAX),
                driver: u16::try_from(profile.specification.driver_dimension)
                    .unwrap_or(u16::MAX),
            },
            dimensions_encoded_bytes: 128,
            fixed_point_scales: NduFixedPointScalesV1 {
                preference_fractional_bits: 32,
                utility_fractional_bits: 32,
                coefficient_fractional_bits: 24,
            },
            fixed_point_scales_encoded_bytes: 96,
            coefficient_bounds: bounded("coefficient-bounds", 512),
            lipschitz_bounds: bounded("lipschitz-bounds", 512),
            monotonicity_bounds: bounded("monotonicity-bounds", 256),
            normalization_digest: digest("normalization"),
            runtime_tuple_digest: digest("runtime-tuple"),
            predecessor_artifact_id: Some(id("predecessor")),
            expires_unix_ms: 50_000,
            rollback_digest: digest("rollback"),
        },
        profile,
        10_000,
    ))
}

fn estimate(profile: &AdmittedCovarianceProfileV1, z: Vec<f64>) -> ZEstimateV1 {
    ZEstimateV1 {
        z: vec![z],
        profile_digest: profile.digest(),
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        evidence_digest: digest("source-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn q24_materialization_uses_signed_nearest_ties_even() {
    let profile = profile("units-v1", 4, 10.0);
    let manifest = manifest(&profile, "coefficient-manifest");
    let scale = 16_777_216.0;
    let estimate = estimate(
        &profile,
        vec![2.5 / scale, 3.5 / scale, -2.5 / scale, -3.5 / scale],
    );

    let candidate = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        &manifest,
        digest("operating-region"),
    ));

    assert_eq!(candidate.coefficients_raw, vec![2, 4, -2, -4]);
    assert_eq!(candidate.maximum_absolute_conversion_error_numerator, 1);
    assert_eq!(
        candidate.maximum_absolute_conversion_error_denominator,
        1_u64 << 25
    );
    assert_eq!(candidate.profile_digest, profile.digest());
    assert_eq!(
        candidate.coefficient_manifest_digest,
        manifest.manifest_digest()
    );
    assert_eq!(
        candidate.coefficient_admission_digest,
        manifest.admission_digest
    );
    assert!(!candidate.evidence_digest.is_zero());
    assert!(!candidate.authority.grants_any());
}

#[test]
fn coefficient_materialization_rejects_estimate_profile_rebinding() {
    let first = profile("units-a", 1, 10.0);
    let second = profile("units-b", 1, 10.0);
    let estimate = estimate(&first, vec![0.5]);
    let manifest = manifest(&second, "coefficient-manifest");

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &second,
            &manifest,
            digest("operating-region"),
        ),
        Err(CovarianceError::EstimateMismatch)
    );
}

#[test]
fn coefficient_materialization_rejects_manifest_profile_rebinding() {
    let first = profile("units-a", 1, 10.0);
    let second = profile("units-b", 1, 10.0);
    let estimate = estimate(&first, vec![0.5]);
    let rebound_manifest = manifest(&second, "coefficient-manifest");

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &first,
            &rebound_manifest,
            digest("operating-region"),
        ),
        Err(CovarianceError::ManifestMismatch)
    );
}

#[test]
fn q24_range_overflow_fails_closed_without_clipping() {
    let profile = profile("wide-units", 1, 1e12);
    let estimate = estimate(&profile, vec![6e11]);
    let manifest = manifest(&profile, "coefficient-manifest");

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &profile,
            &manifest,
            digest("operating-region"),
        ),
        Err(CovarianceError::QuantizationRange)
    );
}

#[test]
fn operating_region_and_manifest_admission_are_digest_bound() {
    let profile = profile("units-v1", 1, 10.0);
    let estimate = estimate(&profile, vec![0.25]);
    let first_manifest = manifest(&profile, "coefficient-manifest-a");
    let second_manifest = manifest(&profile, "coefficient-manifest-b");

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &profile,
            &first_manifest,
            Digest32::ZERO,
        ),
        Err(CovarianceError::MissingDigest)
    );

    let first = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        &first_manifest,
        digest("operating-region"),
    ));
    let second = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        &second_manifest,
        digest("operating-region"),
    ));
    assert_ne!(first.evidence_digest, second.evidence_digest);
}
