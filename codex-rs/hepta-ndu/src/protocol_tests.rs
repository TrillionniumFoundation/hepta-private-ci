use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::NduIterationContextV1;
use super::bind_solver_iteration_receipt_v1;
use super::canonical_iteration_context_digest;
use crate::AxisValue;
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

fn context(
    subject: &str,
    class: SubjectClass,
    objective: &[u8],
    generation: u64,
) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class: class,
        objective_digest: Digest32::of_bytes(objective),
        generation: must(Generation::new(generation)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn first_receipt(context: &NduIterationContextV1) -> crate::NduSolverIterationReceipt {
    let initial = must(PreferenceState::genesis(
        context.subject_id.clone(),
        context.subject_class,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let context_digest = must(canonical_iteration_context_digest(context));
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest,
    ));
    let PreferenceSolveOutcome::Converged {
        iteration_receipts,
        ..
    } = outcome
    else {
        panic!("expected convergence");
    };
    iteration_receipts
        .into_iter()
        .next()
        .expect("first solver receipt")
}

#[test]
fn local_step_requires_complete_context_before_protocol_publication() {
    let context = context("agent-a", SubjectClass::Agent, b"objective", 4);
    let receipt = first_receipt(&context);
    let bound = must(bind_solver_iteration_receipt_v1(&context, &receipt));

    assert_eq!(bound.subject_id, context.subject_id);
    assert_eq!(bound.objective_digest, context.objective_digest);
    assert_eq!(bound.generation, context.generation);
    assert!(!bound.receipt_digest.is_zero());
    assert!(!bound.authority.grants_any());
}

#[test]
fn solver_receipt_cannot_be_rebound_to_another_context() {
    let original = context("agent-a", SubjectClass::Agent, b"objective-a", 4);
    let receipt = first_receipt(&original);
    let changed = context("agent-b", SubjectClass::Agent, b"objective-b", 4);

    let error = bind_solver_iteration_receipt_v1(&changed, &receipt)
        .expect_err("context re-binding must reject");
    assert_eq!(error, crate::NduError::SolverContextMismatch);
}

#[test]
fn zero_context_digest_rejects_before_protocol_publication() {
    let valid = context("episode-a", SubjectClass::Episode, b"objective", 1);
    let receipt = first_receipt(&valid);
    let invalid = NduIterationContextV1 {
        subject_id: id("episode-a"),
        subject_class: SubjectClass::Episode,
        objective_digest: Digest32::ZERO,
        generation: must(Generation::new(1)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    };

    let error = bind_solver_iteration_receipt_v1(&invalid, &receipt)
        .expect_err("zero objective digest must reject");
    assert_eq!(error.code(), "NDU-E002");
}
