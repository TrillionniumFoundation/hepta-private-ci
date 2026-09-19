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
use crate::NduIterationContextV1;
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

fn context(subject_id: &str, subject_class: SubjectClass) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject_id),
        subject_class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(7)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

#[test]
fn damped_preference_update_emits_local_solver_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let predecessor = initial.state_digest;
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &context("agent-a", SubjectClass::Agent),
    ));
    let (terminal, termination, receipts) = match outcome {
        PreferenceSolveOutcome::Converged {
            state,
            termination,
            receipts,
        } => (state, termination, receipts),
        PreferenceSolveOutcome::Unavailable { .. } => panic!("expected convergence"),
    };

    assert_eq!(termination.disposition, SolveDisposition::Converged);
    assert_eq!(termination.predecessor_digest, predecessor);
    assert!(!receipts.is_empty());
    assert!(terminal.revision.get() > 1);
    assert!(terminal.values[0].value <= FixedQ32::ONE);
    assert_eq!(
        usize::try_from(termination.iterations).expect("bounded iteration count"),
        receipts.len()
    );
    assert_eq!(
        termination.terminal_residual_raw,
        receipts.last().expect("terminal receipt").residual_raw
    );
    assert_eq!(
        termination.maximum_residual_raw,
        receipts
            .iter()
            .map(|receipt| receipt.residual_raw)
            .max()
            .expect("maximum residual")
    );
}

#[test]
fn already_converged_state_is_a_zero_iteration_noop() {
    let initial = must(PreferenceState::genesis(
        id("agent-noop"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let original = initial.clone();
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &context("agent-noop", SubjectClass::Agent),
    ));

    let PreferenceSolveOutcome::Converged {
        state,
        termination,
        receipts,
    } = outcome
    else {
        panic!("no-op state must be converged");
    };
    assert_eq!(state, original);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn preference_dimension_limit_is_enforced_at_genesis() {
    let values = (0..65)
        .map(|index| AxisValue {
            axis: id(&format!("axis-{index}")),
            value: FixedQ32::ZERO,
        })
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-wide"),
            SubjectClass::Agent,
            values,
        )),
        NduError::DimensionLimitExceeded
    );
}

#[test]
fn preference_values_must_be_in_closed_unit_interval() {
    let outside = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1);
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-invalid"),
            SubjectClass::Agent,
            vec![AxisValue {
                axis: id("quality"),
                value: outside,
            }],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_owned())
    );

    let initial = must(PreferenceState::genesis(
        id("agent-target"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("quality"),
                value: outside,
            }],
            FixedQ32::from_raw(1_i64 << 30),
            &context("agent-target", SubjectClass::Agent),
        )),
        NduError::PreferenceValueOutOfRange("quality".to_owned())
    );
}

#[test]
fn iteration_exhaustion_returns_unavailable_without_a_persistable_state() {
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::from_raw(-FixedQ32::ONE.raw()),
        }],
    ));
    let outcome = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 28),
        &context("agent-slow", SubjectClass::Agent),
    ));

    let PreferenceSolveOutcome::Unavailable {
        termination,
        receipts,
    } = outcome
    else {
        panic!("slow solve must exhaust the bounded iteration budget");
    };
    assert_eq!(termination.disposition, SolveDisposition::IterationBoundReached);
    assert_eq!(termination.iterations, 64);
    assert_eq!(receipts.len(), 64);
    assert!(termination.terminal_residual_raw > (1_i64 << 12));
}

#[test]
fn parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let domain = id("domain-candidate");
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Domain,
            artifact_id: domain.clone(),
            parent_artifact_id: None,
        },
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate"),
            parent_artifact_id: Some(domain),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_hierarchy_updates_may_share_generation() {
    let generation = must(Generation::new(7));
    must(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Domain,
            artifact_id: id("domain-a"),
            parent_artifact_id: None,
        },
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-b"),
            parent_artifact_id: Some(id("domain-b")),
        },
    ]));
}

#[test]
fn malformed_hierarchy_edge_fails_closed() {
    let generation = must(Generation::new(9));
    let domain = id("domain-a");
    assert!(matches!(
        must_err(validate_staged_updates(&[
            UpdateGeneration {
                generation,
                subject_class: SubjectClass::Domain,
                artifact_id: domain.clone(),
                parent_artifact_id: None,
            },
            UpdateGeneration {
                generation,
                subject_class: SubjectClass::Episode,
                artifact_id: id("episode-a"),
                parent_artifact_id: Some(domain),
            },
        ])),
        NduError::InvalidHierarchyRelation { .. }
    ));
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
            &context("episode-a", SubjectClass::Episode),
        )),
        NduError::InvalidEta
    );
}
