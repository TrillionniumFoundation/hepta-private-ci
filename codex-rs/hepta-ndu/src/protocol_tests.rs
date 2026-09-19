use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use super::ndu_iteration_context_digest_v1;
use crate::AxisValue;
use crate::NduError;
use crate::PreferenceSolveOutcome;
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

fn context(subject_id: &str, subject_class: SubjectClass) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject_id),
        subject_class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let context = context("agent-a", SubjectClass::Agent);
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &context,
    ));
    let receipts = match outcome {
        PreferenceSolveOutcome::Converged { receipts, .. } => receipts,
        PreferenceSolveOutcome::Unavailable { .. } => panic!("expected convergence"),
    };
    let bound = must(bind_solver_iteration_receipt_v1(
        &context,
        receipts.first().expect("first solver receipt"),
    ));

    assert_eq!(bound.subject_id, context.subject_id);
    assert_eq!(bound.objective_digest, context.objective_digest);
    assert_eq!(bound.generation, context.generation);
    assert!(!bound.receipt_digest.is_zero());
    assert!(!bound.authority.grants_any());
}

#[test]
fn solver_rejects_subject_context_mismatch_before_emitting_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let error = solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &context("agent-b", SubjectClass::Agent),
    )
    .expect_err("cross-subject context must reject");

    assert_eq!(error, NduError::ProtocolContextMismatch);
}

#[test]
fn solver_receipt_cannot_be_rebound_to_different_context() {
    let original = context("agent-a", SubjectClass::Agent);
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &original,
    ));
    let receipts = match outcome {
        PreferenceSolveOutcome::Converged { receipts, .. } => receipts,
        PreferenceSolveOutcome::Unavailable { .. } => panic!("expected convergence"),
    };

    let mut rebound = original.clone();
    rebound.event_digest = Digest32::of_bytes(b"different-event");
    assert_ne!(
        must(ndu_iteration_context_digest_v1(&original)),
        must(ndu_iteration_context_digest_v1(&rebound))
    );
    assert_eq!(
        bind_solver_iteration_receipt_v1(
            &rebound,
            receipts.first().expect("first solver receipt"),
        )
        .expect_err("context rebinding must fail"),
        NduError::ProtocolContextMismatch
    );
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let valid_context = context("episode-a", SubjectClass::Episode);
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &valid_context,
    ));
    let receipts = match outcome {
        PreferenceSolveOutcome::Converged { receipts, .. } => receipts,
        PreferenceSolveOutcome::Unavailable { .. } => panic!("expected convergence"),
    };

    let mut invalid_context = valid_context;
    invalid_context.objective_digest = Digest32::ZERO;
    let error = bind_solver_iteration_receipt_v1(
        &invalid_context,
        receipts.first().expect("first solver receipt"),
    )
    .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}
