use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use super::canonical_iteration_context_digest;
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

fn context(subject: &str, class: SubjectClass, event: &[u8]) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class: class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(event),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let solver_context = context("agent-a", SubjectClass::Agent, b"event");
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
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
        &solver_context,
    ));
    let local = receipts.first().expect("first solver receipt");
    assert_eq!(
        local.context_digest(),
        must(canonical_iteration_context_digest(&solver_context))
    );
    let bound = must(bind_solver_iteration_receipt_v1(&solver_context, local));

    assert_eq!(bound.subject_id, solver_context.subject_id);
    assert_eq!(bound.objective_digest, solver_context.objective_digest);
    assert_eq!(bound.generation, solver_context.generation);
    assert!(!bound.receipt_digest.is_zero());
    assert!(!bound.authority.grants_any());
}

#[test]
fn solver_receipt_cannot_be_rebound_to_another_context() {
    let original_context = context("agent-a", SubjectClass::Agent, b"event-a");
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
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
        &original_context,
    ));
    let different_context = context("agent-a", SubjectClass::Agent, b"event-b");
    let error = bind_solver_iteration_receipt_v1(
        &different_context,
        receipts.first().expect("first solver receipt"),
    )
    .expect_err("context replay must fail");
    assert_eq!(error, NduError::SolverContextMismatch);
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let solver_context = context("episode-a", SubjectClass::Episode, b"event");
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
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
        &solver_context,
    ));
    let invalid_context = NduIterationContextV1 {
        objective_digest: Digest32::ZERO,
        ..solver_context
    };

    let error = bind_solver_iteration_receipt_v1(
        &invalid_context,
        receipts.first().expect("first solver receipt"),
    )
    .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}

#[test]
fn solver_rejects_incomplete_context_before_emitting_any_receipt() {
    let invalid_context = NduIterationContextV1 {
        subject_id: id("episode-a"),
        subject_class: SubjectClass::Episode,
        objective_digest: Digest32::ZERO,
        generation: must(Generation::new(1)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    };
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
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
        &invalid_context,
    )
    .expect_err("invalid context must fail before solver evidence exists");
    assert_eq!(error, NduError::EmptyProtocolDigest("objective"));
}
