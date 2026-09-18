use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use super::solve_preference_target_for_context;
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

fn context(subject: &str, objective: &[u8]) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class: SubjectClass::Agent,
        objective_digest: Digest32::of_bytes(objective),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn initial(subject: &str) -> PreferenceState {
    must(PreferenceState::genesis(
        id(subject),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ))
}

fn target() -> Vec<AxisValue> {
    vec![AxisValue {
        axis: id("quality"),
        value: FixedQ32::ONE,
    }]
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let context = context("agent-a", b"objective");
    let (_, _, receipts) = must(solve_preference_target_for_context(
        &context,
        initial("agent-a"),
        target(),
        FixedQ32::from_raw(1_i64 << 30),
    ));
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
fn zero_context_digest_rejects_before_protocol_publication() {
    let (_, _, receipts) = must(solve_preference_target(
        initial("agent-a"),
        target(),
        FixedQ32::from_raw(1_i64 << 30),
    ));
    let context = NduIterationContextV1 {
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        objective_digest: Digest32::ZERO,
        generation: must(Generation::new(1)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    };

    let error =
        bind_solver_iteration_receipt_v1(&context, receipts.first().expect("first solver receipt"))
            .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}

#[test]
fn unbound_local_receipt_cannot_be_published() {
    let context = context("agent-a", b"objective");
    let (_, _, receipts) = must(solve_preference_target(
        initial("agent-a"),
        target(),
        FixedQ32::from_raw(1_i64 << 30),
    ));
    assert_eq!(
        bind_solver_iteration_receipt_v1(
            &context,
            receipts.first().expect("first solver receipt"),
        )
        .expect_err("local receipt must bind canonical context before publication"),
        NduError::SolverContextRequired
    );
}

#[test]
fn receipt_cannot_be_rebound_to_another_context() {
    let first = context("agent-a", b"objective-a");
    let second = context("agent-a", b"objective-b");
    let (_, _, receipts) = must(solve_preference_target_for_context(
        &first,
        initial("agent-a"),
        target(),
        FixedQ32::from_raw(1_i64 << 30),
    ));
    assert_eq!(
        bind_solver_iteration_receipt_v1(
            &second,
            receipts.first().expect("first solver receipt"),
        )
        .expect_err("cross-context rebind must fail"),
        NduError::SolverContextMismatch
    );
}

#[test]
fn solve_context_must_match_subject() {
    let context = context("agent-a", b"objective");
    assert_eq!(
        solve_preference_target_for_context(
            &context,
            initial("agent-b"),
            target(),
            FixedQ32::from_raw(1_i64 << 30),
        )
        .expect_err("subject drift must fail before solving"),
        NduError::SolverContextMismatch
    );
}
