use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use super::canonical_iteration_context_digest_v1;
use crate::AxisValue;
use crate::NduError;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::solve_preference_target;
use crate::solve_preference_target_with_context;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn context(subject: &str, event: &[u8]) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class: SubjectClass::Agent,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(event),
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

#[test]
fn local_step_requires_matching_complete_context_before_protocol_publication() {
    let context = context("agent-a", b"event");
    let context_digest = must(canonical_iteration_context_digest_v1(&context));
    let (_, _, receipts) = must(solve_preference_target_with_context(
        initial("agent-a"),
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest,
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
fn a_solver_receipt_cannot_be_rebound_to_another_context() {
    let original = context("agent-a", b"event-a");
    let context_digest = must(canonical_iteration_context_digest_v1(&original));
    let (_, _, receipts) = must(solve_preference_target_with_context(
        initial("agent-a"),
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest,
    ));
    let different = context("agent-a", b"event-b");

    assert_eq!(
        bind_solver_iteration_receipt_v1(
            &different,
            receipts.first().expect("first solver receipt"),
        )
        .expect_err("context rebinding must fail"),
        NduError::ProtocolContextMismatch
    );
}

#[test]
fn context_free_solver_evidence_cannot_be_published() {
    let publication = context("agent-a", b"event");
    let (_, _, receipts) = must(solve_preference_target(
        initial("agent-a"),
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
    ));

    assert_eq!(
        bind_solver_iteration_receipt_v1(
            &publication,
            receipts.first().expect("first solver receipt"),
        )
        .expect_err("unbound local solver evidence must not publish"),
        NduError::ProtocolContextMismatch
    );
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let valid = context("agent-a", b"event");
    let context_digest = must(canonical_iteration_context_digest_v1(&valid));
    let (_, _, receipts) = must(solve_preference_target_with_context(
        initial("agent-a"),
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest,
    ));

    let mut invalid = valid;
    invalid.objective_digest = Digest32::ZERO;
    let error =
        bind_solver_iteration_receipt_v1(&invalid, receipts.first().expect("first solver receipt"))
            .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}
