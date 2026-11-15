use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::NduCoefficientProfileError;
use super::NduCoefficientProfileV1;
use super::admit_ndu_coefficient_profile;
use super::project_z_estimate_to_coefficient_q24;
use crate::CovarianceConventionV1;
use crate::NduCovarianceProfileV1;
use crate::NduZConversionProfileV1;
use crate::ZCoordinateConventionV1;
use crate::ZEstimateV1;
use crate::admit_covariance_profile;
use crate::admit_z_conversion_profile;

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
    .expect("covariance")
}

fn conversion() -> crate::AdmittedZConversionProfileV1 {
    admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    })
    .expect("conversion")
}

fn specification(
    covariance: &crate::AdmittedCovarianceProfileV1,
    conversion: &crate::AdmittedZConversionProfileV1,
) -> NduCoefficientProfileV1 {
    NduCoefficientProfileV1 {
        artifact_manifest_digest: digest("artifact-manifest"),
        normalization_digest: digest("normalization"),
        runtime_tuple_digest: digest("runtime"),
        covariance_profile_digest: covariance.digest(),
        z_conversion_profile_digest: conversion.digest(),
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        expires_unix_ms: 10_000,
    }
}

#[test]
fn coefficient_profile_binds_covariance_conversion_units_and_dimensions() {
    let covariance = covariance();
    let conversion = conversion();
    let admitted = admit_ndu_coefficient_profile(
        specification(&covariance, &conversion),
        &covariance,
        &conversion,
    )
    .expect("profile");

    assert_eq!(admitted.covariance_profile_digest(), covariance.digest());
    assert_eq!(admitted.z_conversion_profile_digest(), conversion.digest());
    assert_eq!(admitted.units_digest(), digest("driver-units"));

    let mut wrong = specification(&covariance, &conversion);
    wrong.z_conversion_profile_digest = digest("wrong-conversion");
    assert_eq!(
        admit_ndu_coefficient_profile(wrong, &covariance, &conversion).expect_err("profile drift"),
        NduCoefficientProfileError::ProfileMismatch
    );
}

#[test]
fn q24_projection_requires_exact_covariance_provenance() {
    let covariance = covariance();
    let conversion = conversion();
    let admitted = admit_ndu_coefficient_profile(
        specification(&covariance, &conversion),
        &covariance,
        &conversion,
    )
    .expect("profile");
    let estimate = ZEstimateV1 {
        z: vec![vec![3.0, -1.0]],
        covariance_profile_digest: covariance.digest(),
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let projected = project_z_estimate_to_coefficient_q24(&estimate, &admitted, &conversion, 5_000)
        .expect("projection");

    assert_eq!(projected.q24_raw, vec![vec![3 * (1 << 24), -(1 << 24)]]);
    assert_eq!(projected.coefficient_profile_digest, admitted.digest());
    assert!(!projected.output_digest.is_zero());
    assert!(!projected.authority.grants_any());

    let wrong = ZEstimateV1 {
        covariance_profile_digest: digest("other-covariance"),
        ..estimate
    };
    assert_eq!(
        project_z_estimate_to_coefficient_q24(&wrong, &admitted, &conversion, 5_000)
            .expect_err("wrong covariance"),
        NduCoefficientProfileError::ProfileMismatch
    );
}

#[test]
fn expired_coefficient_profile_rejects_projection() {
    let covariance = covariance();
    let conversion = conversion();
    let mut spec = specification(&covariance, &conversion);
    spec.expires_unix_ms = 5_000;
    let admitted = admit_ndu_coefficient_profile(spec, &covariance, &conversion).expect("profile");
    let estimate = ZEstimateV1 {
        z: vec![vec![0.0, 0.0]],
        covariance_profile_digest: covariance.digest(),
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        project_z_estimate_to_coefficient_q24(&estimate, &admitted, &conversion, 5_000)
            .expect_err("expiry"),
        NduCoefficientProfileError::Expiry
    );
}

#[test]
fn projection_numeric_mutation_rejects_even_with_original_metadata()
-> Result<(), Box<dyn std::error::Error>> {
    let covariance = covariance();
    let conversion = conversion();
    let admitted = admit_ndu_coefficient_profile(
        specification(&covariance, &conversion),
        &covariance,
        &conversion,
    )?;
    let estimate = ZEstimateV1 {
        z: vec![vec![3.0, -1.0]],
        covariance_profile_digest: covariance.digest(),
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        evidence_digest: digest("numeric-integrity"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let projection =
        project_z_estimate_to_coefficient_q24(&estimate, &admitted, &conversion, 5_000)?;
    super::validate_ndu_coefficient_projection_v1(&admitted, &projection)?;
    for column in 0..2 {
        let mut changed = projection.clone();
        changed.q24_raw[0][column] ^= 1;
        assert_eq!(
            super::validate_ndu_coefficient_projection_v1(&admitted, &changed),
            Err(NduCoefficientProfileError::ProfileMismatch)
        );
    }
    let mut wrong_shape = projection;
    wrong_shape.q24_raw[0].push(0);
    assert_eq!(
        super::validate_ndu_coefficient_projection_v1(&admitted, &wrong_shape),
        Err(NduCoefficientProfileError::Dimension)
    );
    Ok(())
}
