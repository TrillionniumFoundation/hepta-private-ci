use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NduConvergenceDecisionV1;
use super::NduConvergenceError;
use super::NduConvergenceEvidenceV1;
use super::NduMultipleSolutionDispositionV1;
use super::NduSubjectClassV1;
use super::canonical_ndu_convergence_certificate_digest_v1;
use super::evaluate_ndu_convergence_v1;

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

fn q32_ratio(numerator: i64, denominator: i64) -> i64 {
    ((i128::from(numerator) << 32) / i128::from(denominator)) as i64
}

fn evidence() -> NduConvergenceEvidenceV1 {
    NduConvergenceEvidenceV1 {
        certificate_id: id("ndu-certificate-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        current_objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        iterations: 12,
        maximum_residual_q32: 1_i64 << 12,
        spectral_radius_upper95_q32: q32_ratio(94, 100),
        conservation_residual_q32: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: id("independent-evaluator"),
        candidate_producer_identity: id("candidate-producer"),
        operating_region_digest: digest("operating-region"),
        perturbation_support_digest: digest("perturbation-support"),
        stability_support_digest: digest("stability-support"),
        conservation_support_digest: digest("conservation-support"),
    }
}

#[test]
fn independent_supported_evidence_can_be_accepted() {
    let certificate = must(evaluate_ndu_convergence_v1(&evidence()));
    assert_eq!(certificate.decision, NduConvergenceDecisionV1::Accepted);
    assert!(!canonical_ndu_convergence_certificate_digest_v1(&certificate).is_zero());
}

#[test]
fn self_evaluation_is_rejected_before_certificate_issuance() {
    let mut input = evidence();
    input.evaluator_identity = input.candidate_producer_identity.clone();
    assert_eq!(
        evaluate_ndu_convergence_v1(&input).expect_err("self evaluation must fail"),
        NduConvergenceError::SelfEvaluation
    );
}

#[test]
fn missing_independent_support_is_unavailable() {
    let mut input = evidence();
    input.perturbation_support_digest = Digest32::ZERO;
    let certificate = must(evaluate_ndu_convergence_v1(&input));
    assert_eq!(certificate.decision, NduConvergenceDecisionV1::Unavailable);
}

#[test]
fn stale_objective_or_failed_numeric_gate_rejects() {
    let mut stale = evidence();
    stale.current_objective_class_digest = digest("new-objective-class");
    assert_eq!(
        must(evaluate_ndu_convergence_v1(&stale)).decision,
        NduConvergenceDecisionV1::Rejected
    );

    let mut spectral = evidence();
    spectral.spectral_radius_upper95_q32 = q32_ratio(95, 100);
    assert_eq!(
        must(evaluate_ndu_convergence_v1(&spectral)).decision,
        NduConvergenceDecisionV1::Rejected
    );

    let mut residual = evidence();
    residual.maximum_residual_q32 = (1_i64 << 12) + 1;
    assert_eq!(
        must(evaluate_ndu_convergence_v1(&residual)).decision,
        NduConvergenceDecisionV1::Rejected
    );

    let mut conservation = evidence();
    conservation.conservation_residual_q32 = 2;
    assert_eq!(
        must(evaluate_ndu_convergence_v1(&conservation)).decision,
        NduConvergenceDecisionV1::Rejected
    );
}

#[test]
fn unresolved_multiple_solution_is_unavailable() {
    let mut input = evidence();
    input.multiple_solution_disposition =
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;
    assert_eq!(
        must(evaluate_ndu_convergence_v1(&input)).decision,
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn certificate_digest_binds_the_independent_decision() {
    let accepted = must(evaluate_ndu_convergence_v1(&evidence()));
    let mut rejected_input = evidence();
    rejected_input.spectral_radius_upper95_q32 = q32_ratio(96, 100);
    let rejected = must(evaluate_ndu_convergence_v1(&rejected_input));

    assert_ne!(
        canonical_ndu_convergence_certificate_digest_v1(&accepted),
        canonical_ndu_convergence_certificate_digest_v1(&rejected)
    );
}
