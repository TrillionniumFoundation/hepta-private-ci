use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::NduSolverIterationReceipt;
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
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
    ));

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
            // The solve receipt includes the initial residual, before damping.
            .chain(std::iter::once(FixedQ32::ONE.raw()))
            .max()
            .expect("maximum residual including initial state")
    );
    assert!(receipts.iter().all(|receipt| receipt.validate().is_ok()));
}

#[test]
fn already_converged_solve_is_revision_stable_no_op() {
    let initial = must(PreferenceState::genesis(
        id("agent-noop"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
    ));
    let revision = initial.revision;
    let digest = initial.state_digest;

    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
        FixedQ32::from_raw(1_i64 << 30),
    ));

    assert_eq!(terminal.revision, revision);
    assert_eq!(terminal.state_digest, digest);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert_eq!(termination.maximum_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn preference_dimension_and_value_bounds_fail_at_boundary() {
    let too_many = (0..65)
        .map(|index| AxisValue {
            axis: id(&format!("axis-{index}")),
            value: FixedQ32::ZERO,
        })
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("too-wide"),
            SubjectClass::Agent,
            too_many,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );

    assert_eq!(
        must_err(PreferenceState::genesis(
            id("out-of-range"),
            SubjectClass::Agent,
            vec![AxisValue {
                axis: id("quality"),
                value: FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
            }],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );

    let initial = must(PreferenceState::genesis(
        id("target-check"),
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
                value: FixedQ32::from_raw(-FixedQ32::ONE.raw() - 1),
            }],
            FixedQ32::from_raw(1_i64 << 30),
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn iteration_exhaustion_is_unavailable() {
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ZERO,
        }],
    ));

    let error = must_err(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 28),
    ));
    match error {
        NduError::IterationExhausted {
            iterations,
            terminal_residual_raw,
        } => {
            assert_eq!(iterations, 64);
            assert!(terminal_residual_raw > (1_i64 << 12));
        }
        other => panic!("expected iteration exhaustion, received {other:?}"),
    }
}

#[test]
fn parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            parent_subject_id: Some(id("system-a")),
            subject_class: SubjectClass::Domain,
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            parent_subject_id: Some(id("domain-a")),
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_hierarchy_updates_can_share_generation() {
    let generation = must(Generation::new(8));
    must(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            parent_subject_id: Some(id("system-a")),
            subject_class: SubjectClass::Domain,
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-b"),
            parent_subject_id: Some(id("domain-b")),
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate"),
        },
    ]));
}

#[test]
fn one_subject_cannot_select_two_artifacts_in_one_generation() {
    let generation = must(Generation::new(9));
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            parent_subject_id: Some(id("domain-a")),
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate-a"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            parent_subject_id: Some(id("domain-a")),
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate-b"),
        },
    ]));

    assert_eq!(
        error,
        NduError::ConflictingStagedArtifact {
            generation: 9,
            subject: "agent-a".to_string(),
        }
    );
}

#[test]
fn impossible_local_receipt_invariants_are_rejected() {
    let revision = must(Revision::new(1));
    let next_revision = must(Revision::new(2));
    let invalid = NduSolverIterationReceipt {
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        iteration: 0,
        predecessor_revision: revision,
        next_revision,
        residual_raw: 0,
        projection_count: 0,
        state_digest: Digest32::of_bytes(b"state"),
    };

    assert_eq!(
        must_err(invalid.validate()),
        NduError::InvalidSolverReceipt("iteration")
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
        )),
        NduError::InvalidEta
    );
}
