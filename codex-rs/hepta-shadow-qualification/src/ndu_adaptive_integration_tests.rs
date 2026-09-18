use codex_hepta_intelligence_eval::NduConvergenceDecisionV1;
use codex_hepta_intelligence_eval::NduConvergenceEvidenceV1;
use codex_hepta_intelligence_eval::NduConvergenceExpectationV1;
use codex_hepta_intelligence_eval::NduConvergencePolicyV1;
use codex_hepta_intelligence_eval::NduMultipleSolutionDispositionV1;
use codex_hepta_intelligence_eval::NduSubjectClassV1;
use codex_hepta_intelligence_eval::issue_ndu_convergence_certificate_v1;
use codex_hepta_intelligence_eval::validate_ndu_convergence_certificate_v1;
use codex_hepta_ndu::CovarianceConventionV1;
use codex_hepta_ndu::NduCovarianceProfileV1;
use codex_hepta_ndu::NduStochasticAdmissionEvidenceV1;
use codex_hepta_ndu::admit_covariance_profile;
use codex_hepta_ndu::admit_stochastic_profile_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn ratio(numerator: i64, denominator: i64) -> FixedQ32 {
    FixedQ32::from_raw((numerator << 32) / denominator)
}

fn policy() -> NduConvergencePolicyV1 {
    NduConvergencePolicyV1 {
        policy_id: id("ndu-convergence-policy-v1"),
        maximum_iterations: 64,
        maximum_residual_q32: ratio(1, 1_000_000),
        maximum_spectral_radius_upper95_q32: ratio(95, 100),
        maximum_conservation_residual_q32: FixedQ32::from_raw(1),
    }
}

fn evidence(spectral: FixedQ32) -> NduConvergenceEvidenceV1 {
    NduConvergenceEvidenceV1 {
        certificate_id: id("ndu-certificate-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        iterations: 10,
        maximum_residual_q32: FixedQ32::ZERO,
        spectral_radius_upper95_q32: spectral,
        conservation_residual_q32: FixedQ32::from_raw(1),
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: id("learning-eval-independent"),
        candidate_producer_identity: id("utility-ndu"),
        support_digest: digest("independent-support"),
    }
}

fn covariance() -> codex_hepta_ndu::AdmittedCovarianceProfileV1 {
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

fn expectation() -> NduConvergenceExpectationV1 {
    NduConvergenceExpectationV1 {
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
    }
}

#[test]
fn independent_convergence_digest_is_required_by_ndu_stochastic_admission() {
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence(ratio(90, 100)), &policy())
            .expect("certificate");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Accepted);
    let convergence_digest =
        validate_ndu_convergence_certificate_v1(&certificate, &expectation())
            .expect("current accepted certificate");
    let covariance = covariance();

    let admitted = admit_stochastic_profile_v1(
        &NduStochasticAdmissionEvidenceV1 {
            objective_digest: digest("objective"),
            coefficient_manifest_digest: digest("coefficient"),
            coordinate_conversion_receipt_digest: digest("conversion"),
            conditional_identification_digest: digest("identification"),
            well_posedness_certificate_digest: digest("well-posedness"),
            convergence_certificate_digest: convergence_digest,
        },
        &covariance,
    )
    .expect("stochastic admission");

    assert!(!admitted.admission_digest().is_zero());
    assert!(!admitted.authority().grants_any());
}

#[test]
fn rejected_independent_convergence_never_reaches_ndu_admission() {
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence(ratio(95, 100)), &policy())
            .expect("certificate");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Rejected);
    assert!(
        validate_ndu_convergence_certificate_v1(&certificate, &expectation()).is_err(),
        "rejected convergence cannot produce an admission digest"
    );
}
