use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;
use crate::ConditionalMomentSampleV1;
use crate::CovarianceConventionV1;
use crate::NduCovarianceProfileV1;
use crate::admit_covariance_profile;
use crate::estimate_conditional_moments;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profile() -> AdmittedCovarianceProfileV1 {
    match admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("units"),
        driver_dimension: 1,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-9,
        maximum_condition: 1e6,
        maximum_absolute_sample: 1e6,
        maximum_absolute_z: 1e6,
        maximum_relative_residual: 1e-8,
    }) {
        Ok(value) => value,
        Err(error) => panic!("invalid test covariance profile: {error:?}"),
    }
}

fn binding() -> NduStochasticEvidenceBindingV1 {
    NduStochasticEvidenceBindingV1 {
        artifact_id: id("ndu-coefficient-1"),
        objective_class_digest: digest("objective-class"),
        coefficient_manifest_digest: digest("coefficient-manifest"),
        normalization_digest: digest("normalization"),
        runtime_tuple_digest: digest("runtime"),
        conditioning_spec_digest: digest("conditioning"),
        q24_conversion_evidence_digest: digest("q24-conversion"),
        conditional_identification_evidence_digest: digest("conditional-identification"),
        well_posedness_certificate_digest: digest("well-posedness"),
        independent_convergence_certificate_digest: digest("convergence"),
        rollback_digest: digest("rollback"),
        expires_unix_ms: 2_000,
    }
}

#[test]
fn every_external_evidence_class_is_digest_bound() {
    let profile = profile();
    let admitted = match admit_stochastic_evidence_binding_v1(
        binding(),
        &profile,
        digest("objective-class"),
        1_000,
    ) {
        Ok(value) => value,
        Err(error) => panic!("unexpected admission error: {error:?}"),
    };
    assert!(!admitted.admission_digest.is_zero());

    let mut missing = binding();
    missing.conditional_identification_evidence_digest = Digest32::ZERO;
    assert_eq!(
        admit_stochastic_evidence_binding_v1(
            missing,
            &profile,
            digest("objective-class"),
            1_000,
        )
        .expect_err("missing identification evidence must reject"),
        NduStochasticAdmissionError::MissingDigest("conditional_identification_evidence")
    );
}

#[test]
fn expired_or_wrong_objective_binding_rejects() {
    let profile = profile();
    assert_eq!(
        admit_stochastic_evidence_binding_v1(
            binding(),
            &profile,
            digest("wrong-objective"),
            1_000,
        )
        .expect_err("wrong objective must reject"),
        NduStochasticAdmissionError::ObjectiveClassMismatch
    );
    assert_eq!(
        admit_stochastic_evidence_binding_v1(
            binding(),
            &profile,
            digest("objective-class"),
            2_000,
        )
        .expect_err("expired evidence must reject"),
        NduStochasticAdmissionError::Expired
    );
}

#[test]
fn admitted_evidence_is_bound_into_the_regression_result() {
    let profile = profile();
    let samples = [
        ConditionalMomentSampleV1 {
            conditioning_digest: digest("stratum"),
            duration_micros: 1_000_000,
            increment: vec![-1.0],
            utility: vec![-3.0],
        },
        ConditionalMomentSampleV1 {
            conditioning_digest: digest("stratum"),
            duration_micros: 1_000_000,
            increment: vec![1.0],
            utility: vec![3.0],
        },
    ];
    let moments = match estimate_conditional_moments(&samples, digest("source"), &profile) {
        Ok(value) => value,
        Err(error) => panic!("unexpected moment error: {error:?}"),
    };
    let admitted = match admit_stochastic_evidence_binding_v1(
        binding(),
        &profile,
        digest("objective-class"),
        1_000,
    ) {
        Ok(value) => value,
        Err(error) => panic!("unexpected admission error: {error:?}"),
    };
    let bound =
        match solve_backward_regression_with_admission(&moments, &profile, &admitted, 1_500) {
            Ok(value) => value,
            Err(error) => panic!("unexpected regression error: {error:?}"),
        };
    assert_eq!(bound.stochastic_admission_digest, admitted.admission_digest);
    assert!((bound.estimate.z[0][0] - 3.0).abs() < 1e-12);
}

