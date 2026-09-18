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
use crate::PreferenceSolveResult;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::solve_preference_target;
use crate::solve_preference_target_with_context_digest;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn context(subject: &str, class: SubjectClass, generation: u64) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class: class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(generation)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn first_bound_receipt(
    solver_context: &NduIterationContextV1,
) -> crate::NduSolverIterationReceipt {
    let initial = must(PreferenceState::genesis(
        solver_context.subject_id.clone(),
        solver_context.subject_class,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let context_digest = must(canonical_iteration_context_digest(solver_context));
    let result = must(solve_preference_target_with_context_digest(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest,
    ));
    result
        .receipts()
        .first()
        .expect("first solver receipt")
        .clone()
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let context = context("agent-a", SubjectClass::Agent, 4);
    let receipt = first_bound_receipt(&context);
    let bound = must(bind_solver_iteration_receipt_v1(&context, &receipt));

    assert_eq!(bound.subject_id, context.subject_id);
    assert_eq!(bound.objective_digest, context.objective_digest);
    assert_eq!(bound.generation, context.generation);
    assert!(!bound.receipt_digest.is_zero());
    assert!(!bound.authority.grants_any());
}

#[test]
fn receipt_cannot_be_rebound_to_a_different_context() {
    let original = context("agent-a", SubjectClass::Agent, 4);
    let receipt = first_bound_receipt(&original);
    let changed = context("agent-b", SubjectClass::Agent, 4);
    assert_eq!(
        bind_solver_iteration_receipt_v1(&changed, &receipt)
            .expect_err("context rebinding must fail"),
        NduError::ProtocolContextMismatch
    );
}

#[test]
fn fabricated_or_unbound_local_receipt_cannot_be_published() {
    let context = context("episode-a", SubjectClass::Episode, 1);
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let result = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
    ));
    let receipt = result
        .receipts()
        .first()
        .expect("unbound local receipt");
    assert_eq!(
        bind_solver_iteration_receipt_v1(&context, receipt)
            .expect_err("unbound receipt must not publish"),
        NduError::ProtocolContextMismatch
    );
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let mut context = context("episode-a", SubjectClass::Episode, 1);
    context.objective_digest = Digest32::ZERO;
    let error = canonical_iteration_context_digest(&context)
        .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}

#[test]
fn bound_solver_result_exposes_receipts_without_requiring_state_on_failure() {
    let context = context("agent-slow", SubjectClass::Agent, 9);
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let result = must(solve_preference_target_with_context_digest(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 28),
        must(canonical_iteration_context_digest(&context)),
    ));
    assert!(matches!(
        &result,
        PreferenceSolveResult::Unavailable { .. }
    ));
    assert!(result.converged_state().is_none());
    assert!(!result.receipts().is_empty());
}
