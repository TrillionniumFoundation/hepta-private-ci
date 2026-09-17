use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use crate::AxisValue;
use crate::NduError;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::solve_preference_target;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn valid_context(subject_id: &str, subject_class: SubjectClass) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject_id),
        subject_class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn first_receipt(
    subject_id: &str,
    subject_class: SubjectClass,
) -> crate::NduSolverIterationReceipt {
    let initial = must(PreferenceState::genesis(
        id(subject_id),
        subject_class,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let (_, _, receipts) = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
    ));
    receipts.into_iter().next().expect("first solver receipt")
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let receipt = first_receipt("agent-a", SubjectClass::Agent);
    let context = valid_context("agent-a", SubjectClass::Agent);
    let bound = must(bind_solver_iteration_receipt_v1(&context, &receipt));

    assert_eq!(bound.subject_id, context.subject_id);
    assert_eq!(bound.objective_digest, context.objective_digest);
    assert_eq!(bound.generation, context.generation);
    assert!(!bound.receipt_digest.is_zero());
    assert!(!bound.authority.grants_any());
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let receipt = first_receipt("episode-a", SubjectClass::Episode);
    let mut context = valid_context("episode-a", SubjectClass::Episode);
    context.objective_digest = Digest32::ZERO;

    let error = bind_solver_iteration_receipt_v1(&context, &receipt)
        .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}

#[test]
fn valid_local_receipt_cannot_be_rebound_to_another_subject() {
    let receipt = first_receipt("agent-a", SubjectClass::Agent);

    let wrong_id = valid_context("agent-b", SubjectClass::Agent);
    assert_eq!(
        bind_solver_iteration_receipt_v1(&wrong_id, &receipt)
            .expect_err("receipt subject identity must be frozen"),
        NduError::InvalidSolverReceipt
    );

    let wrong_class = valid_context("agent-a", SubjectClass::Episode);
    assert_eq!(
        bind_solver_iteration_receipt_v1(&wrong_class, &receipt)
            .expect_err("receipt subject class must be frozen"),
        NduError::InvalidSolverReceipt
    );
}

#[test]
fn malformed_local_solver_receipts_reject_before_protocol_publication() {
    let context = valid_context("agent-a", SubjectClass::Agent);
    let valid = first_receipt("agent-a", SubjectClass::Agent);

    let mut zero_iteration = valid.clone();
    zero_iteration.iteration = 0;
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, &zero_iteration)
            .expect_err("zero iteration must reject"),
        NduError::InvalidSolverReceipt
    );

    let mut oversized_iteration = valid.clone();
    oversized_iteration.iteration = 65;
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, &oversized_iteration)
            .expect_err("oversized iteration must reject"),
        NduError::InvalidSolverReceipt
    );

    let mut negative_residual = valid.clone();
    negative_residual.residual_raw = -1;
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, &negative_residual)
            .expect_err("negative residual must reject"),
        NduError::InvalidSolverReceipt
    );

    let mut skipped_revision = valid.clone();
    skipped_revision.next_revision = skipped_revision.predecessor_revision;
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, &skipped_revision)
            .expect_err("non-successor revision must reject"),
        NduError::InvalidSolverReceipt
    );

    let mut empty_state = valid;
    empty_state.state_digest = Digest32::ZERO;
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, &empty_state)
            .expect_err("empty state digest must reject"),
        NduError::InvalidSolverReceipt
    );
}
