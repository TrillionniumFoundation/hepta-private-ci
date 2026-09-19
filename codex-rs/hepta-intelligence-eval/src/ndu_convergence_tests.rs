use std::fmt::Debug;

use codex_hepta_ndu::NduSolverTerminationReceipt;
use codex_hepta_ndu::SolveDisposition;
use codex_hepta_ndu::SubjectClass;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::NduConvergenceDecisionV1;
use super::NduConvergenceError;
use super::NduConvergenceEvaluationV1;
use super::NduMultipleSolutionDispositionV1;
use super::evaluate_ndu_convergence_v1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn termination(disposition: SolveDisposition) -> NduSolverTerminationReceipt {
    NduSolverTerminationReceipt {
        disposition,
        iterations: 12,
        terminal_residual_raw: 128,
        maximum_residual_raw: 512,
        projection_count: 2,
        predecessor_digest: digest("predecessor"),
        terminal_state_digest: digest("terminal"),
    }
}

fn evaluation() -> NduConvergenceEvaluationV1 {
    NduConvergenceEvaluationV1 {
        certificate_id: id("ndu-convergence-1"),
        subject_class: SubjectClass::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        operating_region_digest: digest("operating-region"),
        perturbation_evidence_digest: digest("perturbation"),
        conservation_evidence_digest: digest("conservation"),
        support_digest: digest("support"),
        evaluator_identity: id("independent-evaluator"),
        candidate_producer_identity: id("ndu-producer"),
        termination: termination(SolveDisposition::Converged),
        spectral_radius_upper_95_q32: FixedQ32::from_raw(
            FixedQ32::ONE.raw() * 9 / 10,
        ),
        conservation_residual_q32: FixedQ32::from_raw(1),
        resource_residual_q32: FixedQ32::from_raw(1),
        risk_residual_ppm: 10,
        boundary_residual_p99_ppm: 10_000,
        standardized_martingale_mean_abs_ppm: 19_999,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
    }
}

#[test]
fn independent_complete_evidence_can_be_accepted_without_authority() {
    let certificate = must(evaluate_ndu_convergence_v1(evaluation()));

    assert_eq!(certificate.decision, NduConvergenceDecisionV1::Accepted);
    assert_eq!(certificate.iterations, 12);
    assert_eq!(certificate.maximum_residual_q32, 512);
    assert!(!certificate.evidence_digest.is_zero());
    assert!(!certificate.authority.grants_any());
}

#[test]
fn producer_cannot_self_issue_independent_convergence() {
    let mut input = evaluation();
    input.evaluator_identity = input.candidate_producer_identity.clone();

    assert_eq!(
        must_err(evaluate_ndu_convergence_v1(input)),
        NduConvergenceError::SelfEvaluation
    );
}

#[test]
fn bounded_solver_exhaustion_is_unavailable_not_accepted() {
    let mut input = evaluation();
    input.termination = termination(SolveDisposition::IterationBoundReached);

    assert_eq!(
        must(evaluate_ndu_convergence_v1(input)).decision,
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn spectral_radius_at_nominal_threshold_is_rejected() {
    let mut input = evaluation();
    input.spectral_radius_upper_95_q32 = FixedQ32::from_raw(
        ((i128::from(FixedQ32::ONE.raw()) * 95) / 100) as i64,
    );

    assert_eq!(
        must(evaluate_ndu_convergence_v1(input)).decision,
        NduConvergenceDecisionV1::Rejected
    );
}

#[test]
fn conservation_and_resource_thresholds_fail_closed() {
    for case in 0..4 {
        let mut input = evaluation();
        match case {
            0 => input.conservation_residual_q32 = FixedQ32::from_raw(2),
            1 => input.resource_residual_q32 = FixedQ32::from_raw(-2),
            2 => input.risk_residual_ppm = 11,
            _ => input.boundary_residual_p99_ppm = 10_001,
        }
        assert_eq!(
            must(evaluate_ndu_convergence_v1(input)).decision,
            NduConvergenceDecisionV1::Rejected
        );
    }
}

#[test]
fn unresolved_multiple_solution_is_unavailable() {
    let mut input = evaluation();
    input.multiple_solution_disposition =
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;

    assert_eq!(
        must(evaluate_ndu_convergence_v1(input)).decision,
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn evidence_digest_binds_independent_support_and_operating_region() {
    let first = must(evaluate_ndu_convergence_v1(evaluation()));
    let mut changed = evaluation();
    changed.operating_region_digest = digest("other-region");
    let second = must(evaluate_ndu_convergence_v1(changed));

    assert_ne!(first.evidence_digest, second.evidence_digest);
}
