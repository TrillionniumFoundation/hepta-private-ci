use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NduConvergenceDecisionV1;
use super::NduConvergenceError;
use super::NduConvergenceEvidenceV1;
use super::NduMultipleSolutionDispositionV1;
use super::NduSubjectClassV1;
use super::decide_ndu_convergence_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn evidence() -> NduConvergenceEvidenceV1 {
    NduConvergenceEvidenceV1 {
        certificate_id: id("certificate-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        iterations: 16,
        maximum_residual_q32: 1 << 10,
        spectral_radius_upper95_q32: (90_i64 * (1_i64 << 32)) / 100,
        conservation_residual_q32: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: id("learning-eval-independent"),
        candidate_producer_identity: id("utility-ndu"),
        perturbation_evidence_digest: digest("perturbation"),
        stability_evidence_digest: digest("stability"),
        conservation_evidence_digest: digest("conservation"),
    }
}

#[test]
fn independent_supported_evidence_can_issue_accepted_deny_all_certificate() {
    let certificate = decide_ndu_convergence_v1(evidence()).expect("valid decision");
    assert_eq!(certificate.decision, NduConvergenceDecisionV1::Accepted);
    assert!(!certificate.certificate_digest.is_zero());
    assert!(!certificate.authority.grants_any());
}

#[test]
fn spectral_radius_at_or_above_limit_rejects() {
    let mut evidence = evidence();
    evidence.spectral_radius_upper95_q32 = (95_i64 * (1_i64 << 32)) / 100;
    let certificate = decide_ndu_convergence_v1(evidence).expect("valid rejected decision");
    assert_eq!(certificate.decision, NduConvergenceDecisionV1::Rejected);
}

#[test]
fn exhausted_or_high_residual_solver_rejects() {
    let mut exhausted = evidence();
    exhausted.iterations = 65;
    assert_eq!(
        decide_ndu_convergence_v1(exhausted)
            .expect("valid rejected decision")
            .decision,
        NduConvergenceDecisionV1::Rejected
    );

    let mut high_residual = evidence();
    high_residual.maximum_residual_q32 = (1 << 12) + 1;
    assert_eq!(
        decide_ndu_convergence_v1(high_residual)
            .expect("valid rejected decision")
            .decision,
        NduConvergenceDecisionV1::Rejected
    );
}

#[test]
fn unresolved_solution_or_missing_independent_support_is_unavailable() {
    let mut unresolved = evidence();
    unresolved.multiple_solution_disposition =
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;
    assert_eq!(
        decide_ndu_convergence_v1(unresolved)
            .expect("valid unavailable decision")
            .decision,
        NduConvergenceDecisionV1::Unavailable
    );

    let mut missing_support = evidence();
    missing_support.perturbation_evidence_digest = Digest32::ZERO;
    assert_eq!(
        decide_ndu_convergence_v1(missing_support)
            .expect("valid unavailable decision")
            .decision,
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn evaluator_cannot_certify_its_own_candidate() {
    let mut self_evaluation = evidence();
    self_evaluation.evaluator_identity = self_evaluation.candidate_producer_identity.clone();
    assert_eq!(
        decide_ndu_convergence_v1(self_evaluation)
            .expect_err("self evaluation must fail"),
        NduConvergenceError::SelfEvaluation
    );
}

#[test]
fn certificate_digest_binds_independent_support_evidence() {
    let first = decide_ndu_convergence_v1(evidence()).expect("first decision");
    let mut changed = evidence();
    changed.perturbation_evidence_digest = digest("different-perturbation");
    let second = decide_ndu_convergence_v1(changed).expect("second decision");
    assert_ne!(first.certificate_digest, second.certificate_digest);
}
