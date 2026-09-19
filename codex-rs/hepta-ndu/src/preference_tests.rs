use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::PreferenceSolveOutcome;
use super::PreferenceState;
use super::SolveDisposition;
use super::UpdateGeneration;
use super::solve_preference_target;
use super::validate_staged_updates;
use crate::AxisValue;
use crate::NduError;
use crate::SubjectClass;

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

fn context(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn one_axis_state(value: FixedQ32) -> PreferenceState {
    must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value,
        }],
    ))
}

#[test]
fn damped_preference_update_emits_local_solver_receipts() {
    let initial = one_axis_state(FixedQ32::ZERO);
    let predecessor = initial.state_digest;
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context("solver-context"),
    ));
    let PreferenceSolveOutcome::Converged {
        state: terminal,
        termination,
        iteration_receipts,
    } = outcome
    else {
        panic!("expected convergence");
    };

    assert_eq!(termination.disposition, SolveDisposition::Converged);
    assert_eq!(termination.predecessor_digest, predecessor);
    assert!(!iteration_receipts.is_empty());
    assert!(terminal.revision.get() > 1);
    assert!(terminal.values[0].value <= FixedQ32::ONE);
    assert_eq!(
        usize::try_from(termination.iterations).expect("bounded iteration count"),
        iteration_receipts.len()
    );
    assert_eq!(
        termination.terminal_residual_raw,
        iteration_receipts
            .last()
            .expect("terminal receipt")
            .residual_raw
    );
    assert_eq!(
        termination.maximum_residual_raw,
        iteration_receipts
            .iter()
            .map(|receipt| receipt.residual_raw)
            .max()
            .expect("maximum residual")
    );
    assert!(
        iteration_receipts
            .iter()
            .all(|receipt| receipt.context_digest == context("solver-context"))
    );
}

#[test]
fn already_converged_solve_is_a_true_noop() {
    let initial = one_axis_state(FixedQ32::ZERO);
    let original = initial.clone();
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ZERO,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        context("noop-context"),
    ));
    let PreferenceSolveOutcome::Converged {
        state,
        termination,
        iteration_receipts,
    } = outcome
    else {
        panic!("expected no-op convergence");
    };

    assert_eq!(state, original);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert_eq!(termination.terminal_state_digest, original.state_digest);
    assert!(iteration_receipts.is_empty());
}

#[test]
fn preference_dimension_and_value_bounds_fail_at_api_boundary() {
    let too_many = (0..65)
        .map(|index| AxisValue {
            axis: id(&format!("axis-{index}")),
            value: FixedQ32::ZERO,
        })
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-many"),
            SubjectClass::Agent,
            too_many,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );

    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-range"),
            SubjectClass::Agent,
            vec![AxisValue {
                axis: id("x"),
                value: FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
            }],
        )),
        NduError::PreferenceValueOutOfRange("x".to_string())
    );

    let initial = one_axis_state(FixedQ32::ZERO);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("evidence-quality"),
                value: FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
            }],
            FixedQ32::from_raw(1_i64 << 30),
            context("range-context"),
        )),
        NduError::PreferenceValueOutOfRange("evidence-quality".to_string())
    );
}

#[test]
fn iteration_bound_is_unavailable_and_does_not_publish_candidate_state() {
    let initial = one_axis_state(FixedQ32::from_raw(-FixedQ32::ONE.raw()));
    let original = initial.clone();
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 28),
        context("exhaustion-context"),
    ));
    let PreferenceSolveOutcome::Unavailable {
        predecessor,
        termination,
        iteration_receipts,
    } = outcome
    else {
        panic!("expected bounded unavailable outcome");
    };

    assert_eq!(predecessor, original);
    assert_eq!(
        termination.disposition,
        SolveDisposition::IterationBoundReached
    );
    assert_eq!(termination.iterations, 64);
    assert_eq!(iteration_receipts.len(), 64);
    assert!(termination.terminal_residual_raw > 1_i64 << 12);
    assert_ne!(termination.terminal_state_digest, predecessor.state_digest);
}

#[test]
fn actual_parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(id("domain-a")),
            parent_subject_class: Some(SubjectClass::Domain),
            artifact_id: id("agent-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_hierarchy_levels_may_update_in_same_generation() {
    let generation = must(Generation::new(8));
    must(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-b"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(id("domain-b")),
            parent_subject_class: Some(SubjectClass::Domain),
            artifact_id: id("agent-candidate"),
        },
    ]));
}

#[test]
fn invalid_hierarchy_parent_reference_fails_closed() {
    let generation = must(Generation::new(9));
    assert_eq!(
        must_err(validate_staged_updates(&[UpdateGeneration {
            generation,
            subject_id: id("episode-a"),
            subject_class: SubjectClass::Episode,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("episode-candidate"),
        }])),
        NduError::InvalidHierarchyParent("episode-a".to_string())
    );
}

#[test]
fn eta_outside_registered_bounds_fails() {
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ZERO,
        }],
    ));

    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("utility"),
                value: FixedQ32::ONE,
            }],
            FixedQ32::from_raw(1_i64 << 27),
            context("eta-context"),
        )),
        NduError::InvalidEta
    );
}
