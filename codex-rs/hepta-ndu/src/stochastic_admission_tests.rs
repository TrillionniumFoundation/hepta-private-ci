use codex_hepta_types::Digest32;

use super::NduStochasticAdmissionEvidenceV1;
use super::admit_stochastic_profile_v1;
use crate::CovarianceConventionV1;
use crate::NduCovarianceProfileV1;
use crate::admit_covariance_profile;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profile() -> crate::AdmittedCovarianceProfileV1 {
    admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("units"),
        driver_dimension: 2,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-8,
        maximum_condition: 1e6,
        maximum_absolute_sample: 100.0,
        maximum_absolute_z: 100.0,
        maximum_relative_residual: 1e-10,
    })
    .expect("valid covariance profile")
}

#[test]
fn stochastic_admission_binds_every_required_evidence_gate() {
    let evidence = NduStochasticAdmissionEvidenceV1 {
        objective_digest: digest("objective"),
        coefficient_manifest_digest: digest("coefficient"),
        coordinate_conversion_receipt_digest: digest("conversion"),
        conditional_identification_digest: digest("identification"),
        well_posedness_certificate_digest: digest("well-posedness"),
        convergence_certificate_digest: digest("convergence"),
    };
    let admitted = admit_stochastic_profile_v1(&evidence, &profile()).expect("admitted");
    assert!(!admitted.admission_digest().is_zero());
    assert!(!admitted.authority().grants_any());
}

#[test]
fn stochastic_admission_fails_closed_on_missing_independent_convergence() {
    let evidence = NduStochasticAdmissionEvidenceV1 {
        objective_digest: digest("objective"),
        coefficient_manifest_digest: digest("coefficient"),
        coordinate_conversion_receipt_digest: digest("conversion"),
        conditional_identification_digest: digest("identification"),
        well_posedness_certificate_digest: digest("well-posedness"),
        convergence_certificate_digest: Digest32::ZERO,
    };
    assert_eq!(
        admit_stochastic_profile_v1(&evidence, &profile())
            .expect_err("missing convergence must reject"),
        super::NduStochasticAdmissionError::MissingEvidence("convergence")
    );
}
