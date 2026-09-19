use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::NduIterationContextV1;
use super::PreferenceState;
use super::SolveDisposition;
use super::SubjectHierarchyEdgeV1;
use super::SubjectHierarchyV1;
use super::UpdateGeneration;
use super::canonical_subject_hierarchy_digest;
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

fn generation(value: u64) -> Generation {
    must(Generation::new(value))
}

fn context(subject_id: &str, subject_class: SubjectClass) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject_id),
        subject_class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: generation(4),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn hierarchy(edges: Vec<SubjectHierarchyEdgeV1>) -> SubjectHierarchyV1 {
    let hierarchy_digest = must(canonical_subject_hierarchy_digest(&edges));
    SubjectHierarchyV1 {
        hierarchy_digest,
        edges,
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
    let solver_context = context("agent-a", SubjectClass::Agent);
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("evidence-quality"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &solver_context,
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
        receipts.last().expect("terminal receipt").residual_raw()
    );
    assert_eq!(
        termination.maximum_residual_raw,
        receipts
            .iter()
            .map(|receipt| receipt.residual_raw())
            .chain(std::iter::once(FixedQ32::ONE.raw()))
            .max()
            .expect("maximum residual")
    );
    assert_eq!(termination.context_digest, receipts[0].context_digest());
}

#[test]
fn related_parent_and_child_updates_cannot_share_generation() {
    let graph = hierarchy(vec![SubjectHierarchyEdgeV1 {
        parent_subject_id: id("domain-a"),
        parent_subject_class: SubjectClass::Domain,
        child_subject_id: id("agent-a"),
        child_subject_class: SubjectClass::Agent,
    }]);
    let error = must_err(validate_staged_updates(
        &[
            UpdateGeneration {
                generation: generation(7),
                subject_id: id("domain-a"),
                subject_class: SubjectClass::Domain,
                artifact_id: id("domain-candidate"),
            },
            UpdateGeneration {
                generation: generation(7),
                subject_id: id("agent-a"),
                subject_class: SubjectClass::Agent,
                artifact_id: id("agent-candidate"),
            },
        ],
        &graph,
    ));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_subjects_may_update_in_one_generation() {
    let graph = hierarchy(vec![
        SubjectHierarchyEdgeV1 {
            parent_subject_id: id("system-a"),
            parent_subject_class: SubjectClass::System,
            child_subject_id: id("domain-a"),
            child_subject_class: SubjectClass::Domain,
        },
        SubjectHierarchyEdgeV1 {
            parent_subject_id: id("domain-b"),
            parent_subject_class: SubjectClass::Domain,
            child_subject_id: id("agent-b"),
            child_subject_class: SubjectClass::Agent,
        },
    ]);
    must(validate_staged_updates(
        &[
            UpdateGeneration {
                generation: generation(7),
                subject_id: id("domain-a"),
                subject_class: SubjectClass::Domain,
                artifact_id: id("domain-candidate"),
            },
            UpdateGeneration {
                generation: generation(7),
                subject_id: id("agent-b"),
                subject_class: SubjectClass::Agent,
                artifact_id: id("agent-candidate"),
            },
        ],
        &graph,
    ));
}

#[test]
fn hierarchy_digest_drift_fails_closed() {
    let edges = vec![SubjectHierarchyEdgeV1 {
        parent_subject_id: id("domain-a"),
        parent_subject_class: SubjectClass::Domain,
        child_subject_id: id("agent-a"),
        child_subject_class: SubjectClass::Agent,
    }];
    let graph = SubjectHierarchyV1 {
        hierarchy_digest: Digest32::of_bytes(b"different-hierarchy"),
        edges,
    };
    assert!(matches!(
        must_err(validate_staged_updates(&[], &graph)),
        NduError::InvalidHierarchyRelation(_)
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
    let solver_context = context("episode-a", SubjectClass::Episode);

    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("utility"),
                value: FixedQ32::ONE,
            }],
            FixedQ32::from_raw(1_i64 << 27),
            &solver_context,
        )),
        NduError::InvalidEta
    );
}

#[test]
fn preference_dimension_above_64_rejects_at_genesis() {
    let values = (0..65)
        .map(|index| AxisValue {
            axis: id(&format!("axis-{index}")),
            value: FixedQ32::ZERO,
        })
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-a"),
            SubjectClass::Agent,
            values,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );
}

#[test]
fn out_of_range_genesis_and_target_reject_before_iteration() {
    let invalid = FixedQ32::from_raw(2_i64 << 32);
    assert!(matches!(
        must_err(PreferenceState::genesis(
            id("agent-a"),
            SubjectClass::Agent,
            vec![AxisValue {
                axis: id("utility"),
                value: invalid,
            }],
        )),
        NduError::PreferenceValueOutOfRange(_)
    ));

    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ZERO,
        }],
    ));
    let solver_context = context("agent-a", SubjectClass::Agent);
    assert!(matches!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("utility"),
                value: invalid,
            }],
            FixedQ32::from_raw(1_i64 << 30),
            &solver_context,
        )),
        NduError::PreferenceValueOutOfRange(_)
    ));
}

#[test]
fn already_converged_solve_is_revision_stable() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ONE,
        }],
    ));
    let expected = initial.clone();
    let solver_context = context("agent-a", SubjectClass::Agent);
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ONE,
        }],
        FixedQ32::from_raw(1_i64 << 30),
        &solver_context,
    ));

    assert_eq!(terminal, expected);
    assert_eq!(termination.disposition, SolveDisposition::Converged);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn iteration_exhaustion_is_unavailable_not_success() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ZERO,
        }],
    ));
    let solver_context = context("agent-a", SubjectClass::Agent);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("utility"),
                value: FixedQ32::ONE,
            }],
            FixedQ32::from_raw(1_i64 << 28),
            &solver_context,
        )),
        NduError::SolverUnavailable
    );
}

#[test]
fn solver_context_must_match_preference_subject() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: id("utility"),
            value: FixedQ32::ZERO,
        }],
    ));
    let wrong_context = context("agent-b", SubjectClass::Agent);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![AxisValue {
                axis: id("utility"),
                value: FixedQ32::ONE,
            }],
            FixedQ32::from_raw(1_i64 << 30),
            &wrong_context,
        )),
        NduError::ProtocolContextMismatch
    );
}
