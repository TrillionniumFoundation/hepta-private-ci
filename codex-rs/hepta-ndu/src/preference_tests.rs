use std::fmt::Debug;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

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

fn value(axis: &str, raw: i64) -> AxisValue {
    AxisValue {
        axis: id(axis),
        value: FixedQ32::from_raw(raw),
    }
}

#[test]
fn damped_preference_update_emits_local_solver_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![value("evidence-quality", 0)],
    ));
    let predecessor = initial.state_digest;
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![value("evidence-quality", FixedQ32::ONE.raw())],
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
        receipts.last().expect("terminal receipt").residual_raw()
    );
    assert_eq!(
        termination.maximum_residual_raw,
        receipts
            .iter()
            .map(super::NduSolverIterationReceipt::residual_raw)
            .chain(std::iter::once(FixedQ32::ONE.raw()))
            .max()
            .expect("maximum residual")
    );
    assert!(
        receipts
            .iter()
            .all(|receipt| receipt.context_digest().is_none())
    );
}

#[test]
fn already_converged_solve_is_revision_stable() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![value("quality", FixedQ32::ONE.raw() / 2)],
    ));
    let revision = initial.revision;
    let digest = initial.state_digest;
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![value("quality", FixedQ32::ONE.raw() / 2)],
        FixedQ32::from_raw(1_i64 << 30),
    ));

    assert_eq!(terminal.revision, revision);
    assert_eq!(terminal.state_digest, digest);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn preference_dimension_and_value_bounds_fail_closed() {
    let values = (0..65)
        .map(|index| value(&format!("axis-{index}"), 0))
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-a"),
            SubjectClass::Agent,
            values,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );

    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-a"),
            SubjectClass::Agent,
            vec![value("quality", FixedQ32::ONE.raw() + 1)],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );

    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![value("quality", 0)],
    ));
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![value("quality", FixedQ32::ONE.raw() + 1)],
            FixedQ32::from_raw(1_i64 << 30),
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn iteration_bound_is_unavailable_not_successful_state() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![value("quality", -FixedQ32::ONE.raw())],
    ));
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![value("quality", FixedQ32::ONE.raw())],
            FixedQ32::from_raw(1_i64 << 28),
        )),
        NduError::PreferenceSolverUnavailable
    );
}

#[test]
fn parent_and_child_updates_cannot_share_generation() {
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
fn unrelated_hierarchy_updates_may_share_generation() {
    let generation = must(Generation::new(7));
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
fn malformed_hierarchy_link_fails_closed() {
    let generation = must(Generation::new(7));
    assert_eq!(
        must_err(validate_staged_updates(&[UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("agent-candidate"),
        }])),
        NduError::InvalidHierarchyLink("agent-a".to_string())
    );
}

#[test]
fn eta_outside_registered_bounds_fails() {
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![value("utility", 0)],
    ));

    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![value("utility", FixedQ32::ONE.raw())],
            FixedQ32::from_raw(1_i64 << 27),
        )),
        NduError::InvalidEta
    );
}
