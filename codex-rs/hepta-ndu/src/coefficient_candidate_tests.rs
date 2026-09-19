use std::fmt::Debug;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::materialize_q24_coefficient_candidate_v1;
use crate::AdmittedCovarianceProfileV1;
use crate::CovarianceConventionV1;
use crate::CovarianceError;
use crate::NduCovarianceProfileV1;
use crate::ZEstimateV1;
use crate::admit_covariance_profile;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
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
    let scale = 16_777_216.0;
    let estimate = estimate(
        &profile,
        vec![2.5 / scale, 3.5 / scale, -2.5 / scale, -3.5 / scale],
    );

    let candidate = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        digest("coefficient-manifest"),
        digest("operating-region"),
    ));

    assert_eq!(candidate.coefficients_raw, vec![2, 4, -2, -4]);
    assert_eq!(candidate.maximum_absolute_conversion_error_numerator, 1);
    assert_eq!(
        candidate.maximum_absolute_conversion_error_denominator,
        1_u64 << 25
    );
    assert_eq!(candidate.profile_digest, profile.digest());
    assert!(!candidate.evidence_digest.is_zero());
    assert!(!candidate.authority.grants_any());
}

#[test]
fn coefficient_materialization_rejects_profile_rebinding() {
    let first = profile("units-a", 1, 10.0);
    let second = profile("units-b", 1, 10.0);
    let estimate = estimate(&first, vec![0.5]);

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &second,
            digest("coefficient-manifest"),
            digest("operating-region"),
        ),
        Err(CovarianceError::EstimateMismatch)
    );
}

#[test]
fn q24_range_overflow_fails_closed_without_clipping() {
    let profile = profile("wide-units", 1, 1e12);
    let estimate = estimate(&profile, vec![6e11]);

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &profile,
            digest("coefficient-manifest"),
            digest("operating-region"),
        ),
        Err(CovarianceError::QuantizationRange)
    );
}

#[test]
fn manifest_and_operating_region_are_required_and_digest_bound() {
    let profile = profile("units-v1", 1, 10.0);
    let estimate = estimate(&profile, vec![0.25]);

    assert_eq!(
        materialize_q24_coefficient_candidate_v1(
            &estimate,
            &profile,
            Digest32::ZERO,
            digest("operating-region"),
        ),
        Err(CovarianceError::MissingDigest)
    );

    let first = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        digest("coefficient-manifest-a"),
        digest("operating-region"),
    ));
    let second = must(materialize_q24_coefficient_candidate_v1(
        &estimate,
        &profile,
        digest("coefficient-manifest-b"),
        digest("operating-region"),
    ));
    assert_ne!(first.evidence_digest, second.evidence_digest);
}
