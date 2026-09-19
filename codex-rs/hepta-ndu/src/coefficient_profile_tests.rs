use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::NduCoefficientProfileError;
use super::NduCoefficientProfileV1;
use super::admit_ndu_coefficient_profile;
use super::quantize_z_to_q24;
use crate::CovarianceConventionV1;
use crate::NduCovarianceProfileV1;
use crate::ZEstimateV1;
use crate::admit_covariance_profile;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn covariance() -> crate::AdmittedCovarianceProfileV1 {
    admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-8,
        maximum_condition: 1e6,
        maximum_absolute_sample: 1e6,
        maximum_absolute_z: 100.0,
        maximum_relative_residual: 1e-10,
    })
    .expect("admitted covariance profile")
}

fn profile(covariance: &crate::AdmittedCovarianceProfileV1) -> NduCoefficientProfileV1 {
    NduCoefficientProfileV1 {
        manifest_digest: digest("manifest"),
        normalization_digest: digest("normalization"),
        runtime_tuple_digest: digest("runtime"),
        coordinate_digest: digest("original-coordinate-order"),
        covariance_profile_digest: covariance.digest(),
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        expires_unix_ms: 1_000,
    }
}

#[test]
fn coefficient_profile_binds_covariance_dimensions_units_and_q24_output() {
    let covariance = covariance();
    let admitted =
        admit_ndu_coefficient_profile(profile(&covariance), &covariance).expect("admitted profile");
    let estimate = ZEstimateV1 {
        z: vec![vec![3.25, -1.0]],
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        covariance_profile_digest: covariance.digest(),
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let receipt = quantize_z_to_q24(&estimate, &admitted, 500).expect("q24 projection");

    assert_eq!(receipt.values, vec![vec![3_i64 * (1 << 24) + (1 << 22), -(1 << 24)]]);
    assert_eq!(receipt.maximum_absolute_error, 0.0);
    assert_eq!(receipt.source_evidence_digest, estimate.evidence_digest);
    assert!(!receipt.output_digest.is_zero());
    assert!(!receipt.conversion_evidence_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn coefficient_profile_rejects_covariance_or_units_drift() {
    let covariance = covariance();
    let mut wrong = profile(&covariance);
    wrong.covariance_profile_digest = digest("other-covariance");
    assert_eq!(
        admit_ndu_coefficient_profile(wrong, &covariance)
            .expect_err("covariance identity must bind"),
        NduCoefficientProfileError::ProfileMismatch
    );

    let mut wrong = profile(&covariance);
    wrong.units_digest = digest("other-units");
    assert_eq!(
        admit_ndu_coefficient_profile(wrong, &covariance)
            .expect_err("unit identity must bind"),
        NduCoefficientProfileError::ProfileMismatch
    );
}

#[test]
fn q24_projection_rejects_expired_or_dimension_drifted_evidence() {
    let covariance = covariance();
    let admitted =
        admit_ndu_coefficient_profile(profile(&covariance), &covariance).expect("admitted profile");
    let estimate = ZEstimateV1 {
        z: vec![vec![1.0, 2.0]],
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        covariance_profile_digest: covariance.digest(),
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        quantize_z_to_q24(&estimate, &admitted, 1_000)
            .expect_err("expired profile must reject"),
        NduCoefficientProfileError::Expiry
    );

    let bad_dimension = ZEstimateV1 {
        z: vec![vec![1.0]],
        ..estimate
    };
    assert_eq!(
        quantize_z_to_q24(&bad_dimension, &admitted, 500)
            .expect_err("dimension drift must reject"),
        NduCoefficientProfileError::Dimension
    );
}

#[test]
fn q24_projection_rejects_z_from_another_covariance_profile() {
    let covariance = covariance();
    let admitted =
        admit_ndu_coefficient_profile(profile(&covariance), &covariance).expect("admitted profile");
    let estimate = ZEstimateV1 {
        z: vec![vec![1.0, 2.0]],
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        covariance_profile_digest: digest("different-covariance-profile"),
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        quantize_z_to_q24(&estimate, &admitted, 500)
            .expect_err("Z covariance provenance must match coefficient admission"),
        NduCoefficientProfileError::ProfileMismatch
    );
}

#[test]
fn q24_profile_refuses_a_z_bound_that_cannot_fit_i64() {
    let covariance = admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("driver-units"),
        driver_dimension: 1,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-8,
        maximum_condition: 1e6,
        maximum_absolute_sample: 1e6,
        maximum_absolute_z: 1e12,
        maximum_relative_residual: 1e-10,
    })
    .expect("numeric covariance profile itself allows the shadow f64 range");
    let specification = NduCoefficientProfileV1 {
        manifest_digest: digest("manifest"),
        normalization_digest: digest("normalization"),
        runtime_tuple_digest: digest("runtime"),
        coordinate_digest: digest("coordinate"),
        covariance_profile_digest: covariance.digest(),
        units_digest: digest("driver-units"),
        driver_dimension: 1,
        utility_dimension: 1,
        expires_unix_ms: 1_000,
    };
    assert_eq!(
        admit_ndu_coefficient_profile(specification, &covariance)
            .expect_err("Q24 fixed point must remain representable"),
        NduCoefficientProfileError::ConversionRange
    );
}
