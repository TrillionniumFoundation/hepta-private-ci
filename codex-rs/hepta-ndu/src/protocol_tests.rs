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

fn agent_receipts() -> Vec<crate::NduSolverIterationReceipt> {
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
    ));
    receipts
}

fn context(subject_id: &str) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject_id),
        subject_class: SubjectClass::Agent,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(4)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let receipts = agent_receipts();
    let context = context("agent-a");
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
    let receipts = agent_receipts();
    let mut context = context("agent-a");
    context.objective_digest = Digest32::ZERO;

    let error =
        bind_solver_iteration_receipt_v1(&context, receipts.first().expect("first solver receipt"))
            .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}

#[test]
fn solver_receipt_cannot_be_rebound_to_another_subject() {
    let receipts = agent_receipts();
    let context = context("agent-b");

    let error =
        bind_solver_iteration_receipt_v1(&context, receipts.first().expect("first solver receipt"))
            .expect_err("subject mismatch must reject");
    assert_eq!(error, NduError::ProtocolSubjectMismatch);
    assert_eq!(error.code(), "NDU-E002");
}
