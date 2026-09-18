use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::NduConvergenceDecisionV1;
use super::NduConvergenceError;
use super::NduConvergenceEvidenceV1;
use super::NduConvergenceExpectationV1;
use super::NduConvergencePolicyV1;
use super::NduMultipleSolutionDispositionV1;
use super::NduSubjectClassV1;
use super::issue_ndu_convergence_certificate_v1;
use super::validate_ndu_convergence_certificate_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32_ratio(numerator: i64, denominator: i64) -> FixedQ32 {
    FixedQ32::from_raw((numerator << 32) / denominator)
}

fn policy() -> NduConvergencePolicyV1 {
    NduConvergencePolicyV1 {
        policy_id: id("ndu-convergence-v1"),
        maximum_iterations: 64,
        maximum_residual_q32: q32_ratio(1, 1_000_000),
        maximum_spectral_radius_upper95_q32: q32_ratio(95, 100),
        maximum_conservation_residual_q32: FixedQ32::from_raw(1),
    }
}

fn evidence() -> NduConvergenceEvidenceV1 {
    NduConvergenceEvidenceV1 {
        certificate_id: id("certificate-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        iterations: 12,
        maximum_residual_q32: FixedQ32::ZERO,
        spectral_radius_upper95_q32: q32_ratio(90, 100),
        conservation_residual_q32: FixedQ32::from_raw(1),
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: id("learning-eval-independent"),
        candidate_producer_identity: id("utility-ndu"),
        support_digest: digest("independent-evidence"),
    }
}

#[test]
fn independent_supported_evidence_can_issue_an_accepted_certificate() {
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence(), &policy()).expect("certificate");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Accepted);
    assert!(!certificate.certificate_digest().is_zero());

    let expected = NduConvergenceExpectationV1 {
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
    };
    assert_eq!(
        validate_ndu_convergence_certificate_v1(&certificate, &expected)
            .expect("current context"),
        certificate.certificate_digest()
    );
}

#[test]
fn self_evaluation_is_rejected_before_certificate_issue() {
    let mut evidence = evidence();
    evidence.evaluator_identity = evidence.candidate_producer_identity.clone();
    assert_eq!(
        issue_ndu_convergence_certificate_v1(evidence, &policy())
            .expect_err("self evaluation must fail"),
        NduConvergenceError::SelfEvaluation
    );
}

#[test]
fn missing_independent_support_is_unavailable_not_accepted() {
    let mut evidence = evidence();
    evidence.support_digest = Digest32::ZERO;
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence, &policy()).expect("unavailable cert");
    assert_eq!(
        certificate.decision(),
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn spectral_radius_at_or_above_boundary_is_rejected() {
    let mut evidence = evidence();
    evidence.spectral_radius_upper95_q32 = q32_ratio(95, 100);
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence, &policy()).expect("rejected cert");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Rejected);
}

#[test]
fn unresolved_multiple_solution_is_rejected() {
    let mut evidence = evidence();
    evidence.multiple_solution_disposition =
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence, &policy()).expect("rejected cert");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Rejected);
}

#[test]
fn stale_or_foreign_context_cannot_reuse_an_accepted_certificate() {
    let certificate =
        issue_ndu_convergence_certificate_v1(evidence(), &policy()).expect("certificate");
    let expected = NduConvergenceExpectationV1 {
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("different-objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
    };
    assert_eq!(
        validate_ndu_convergence_certificate_v1(&certificate, &expected)
            .expect_err("stale objective must reject"),
        NduConvergenceError::ContextMismatch("objective_class")
    );
}
