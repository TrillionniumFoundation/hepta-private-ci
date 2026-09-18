use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture id: {error:?}"),
    }
}

fn certificate() -> NduConvergenceCertificateV1 {
    NduConvergenceCertificateV1 {
        certificate_id: id("ndu-convergence-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: Digest32::of_bytes(b"objective-class"),
        solver_digest: Digest32::of_bytes(b"solver"),
        initialization_digest: Digest32::of_bytes(b"initialization"),
        iterations: 32,
        maximum_residual_raw: 1_i64 << 10,
        spectral_radius_upper_95_raw: 4_000_000_000,
        conservation_residual_raw: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: "independent-evaluator".to_string(),
        decision: NduConvergenceDecisionV1::Accepted,
    }
}

fn context() -> NduConvergenceAdmissionContextV1 {
    NduConvergenceAdmissionContextV1 {
        expected_objective_class_digest: Digest32::of_bytes(b"objective-class"),
        expected_solver_digest: Digest32::of_bytes(b"solver"),
        candidate_producer_identity: id("ndu-producer"),
    }
}

#[test]
fn accepted_certificate_binds_independent_evidence() {
    let admitted = match admit_ndu_convergence_certificate_v1(certificate(), &context()) {
        Ok(value) => value,
        Err(error) => panic!("unexpected admission error: {error:?}"),
    };
    assert!(!admitted.certificate_digest.is_zero());
}

#[test]
fn self_evaluation_and_binding_drift_fail_closed() {
    let mut self_evaluated = certificate();
    self_evaluated.evaluator_identity = "ndu-producer".to_string();
    assert_eq!(
        admit_ndu_convergence_certificate_v1(self_evaluated, &context())
            .expect_err("self evaluation must reject"),
        NduConvergenceAdmissionError::SelfEvaluation
    );

    let mut wrong_solver = certificate();
    wrong_solver.solver_digest = Digest32::of_bytes(b"other-solver");
    assert_eq!(
        admit_ndu_convergence_certificate_v1(wrong_solver, &context())
            .expect_err("solver drift must reject"),
        NduConvergenceAdmissionError::SolverMismatch
    );
}

#[test]
fn accepted_decision_must_pass_every_convergence_gate() {
    let mut spectral = certificate();
    spectral.spectral_radius_upper_95_raw = SPECTRAL_RADIUS_UPPER_95_REJECT_AT_RAW;
    assert_eq!(
        admit_ndu_convergence_certificate_v1(spectral, &context())
            .expect_err("spectral boundary must reject"),
        NduConvergenceAdmissionError::SpectralRadiusGate
    );

    let mut residual = certificate();
    residual.maximum_residual_raw = MAXIMUM_RESIDUAL_RAW + 1;
    assert_eq!(
        admit_ndu_convergence_certificate_v1(residual, &context())
            .expect_err("residual boundary must reject"),
        NduConvergenceAdmissionError::ResidualGate
    );

    let mut conservation = certificate();
    conservation.conservation_residual_raw = CONSERVATION_RESIDUAL_LIMIT_RAW + 1;
    assert_eq!(
        admit_ndu_convergence_certificate_v1(conservation, &context())
            .expect_err("conservation boundary must reject"),
        NduConvergenceAdmissionError::ConservationGate
    );

    let mut multiple = certificate();
    multiple.multiple_solution_disposition =
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;
    assert_eq!(
        admit_ndu_convergence_certificate_v1(multiple, &context())
            .expect_err("unresolved multiple solution must reject"),
        NduConvergenceAdmissionError::MultipleSolutionUnresolved
    );
}

#[test]
fn evaluator_identity_follows_canonical_utf8_bound() {
    let mut empty = certificate();
    empty.evaluator_identity.clear();
    assert_eq!(
        admit_ndu_convergence_certificate_v1(empty, &context())
            .expect_err("empty evaluator identity must reject"),
        NduConvergenceAdmissionError::InvalidEvaluatorIdentity
    );

    let mut oversized = certificate();
    oversized.evaluator_identity = "x".repeat(257);
    assert_eq!(
        admit_ndu_convergence_certificate_v1(oversized, &context())
            .expect_err("oversized evaluator identity must reject"),
        NduConvergenceAdmissionError::InvalidEvaluatorIdentity
    );
}

#[test]
fn rejected_or_unavailable_certificate_is_recordable_without_becoming_accepted() {
    for decision in [
        NduConvergenceDecisionV1::Rejected,
        NduConvergenceDecisionV1::Unavailable,
    ] {
        let mut value = certificate();
        value.decision = decision;
        value.maximum_residual_raw = MAXIMUM_RESIDUAL_RAW + 100;
        let admitted = match admit_ndu_convergence_certificate_v1(value, &context()) {
            Ok(value) => value,
            Err(error) => panic!("non-accepted evidence should remain recordable: {error:?}"),
        };
        assert_eq!(admitted.certificate.decision, decision);
    }
}
