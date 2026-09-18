use std::fmt::Debug;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::PreferenceSolveResult;
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

fn axis(name: &str, value: FixedQ32) -> AxisValue {
    AxisValue {
        axis: id(name),
        value,
    }
}

#[test]
fn damped_preference_update_emits_local_solver_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![axis("evidence-quality", FixedQ32::ZERO)],
    ));
    let predecessor = initial.state_digest;
    let result = must(solve_preference_target(
        initial,
        vec![axis("evidence-quality", FixedQ32::ONE)],
        FixedQ32::from_raw(1_i64 << 30),
    ));
    let PreferenceSolveResult::Converged {
        state: terminal,
        termination,
        receipts,
    } = result
    else {
        panic!("fixture must converge");
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
fn direct_parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let system = id("system");
    let domain = id("domain-a");
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: domain.clone(),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(system),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(domain),
            parent_subject_class: Some(SubjectClass::Domain),
            artifact_id: id("agent-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_hierarchy_subjects_may_update_in_same_generation() {
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
fn malformed_hierarchy_parent_is_rejected() {
    let generation = must(Generation::new(2));
    let error = must_err(validate_staged_updates(&[UpdateGeneration {
        generation,
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        parent_subject_id: Some(id("system")),
        parent_subject_class: Some(SubjectClass::System),
        artifact_id: id("agent-candidate"),
    }]));
    assert!(matches!(error, NduError::InvalidHierarchyParent { .. }));
}

#[test]
fn eta_outside_registered_bounds_fails() {
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![axis("utility", FixedQ32::ZERO)],
    ));

    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis("utility", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 27),
        )),
        NduError::InvalidEta
    );
}

#[test]
fn preference_dimension_above_64_rejects_at_genesis() {
    let values = (0..65)
        .map(|index| axis(&format!("axis-{index:02}"), FixedQ32::ZERO))
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-wide"),
            SubjectClass::Agent,
            values,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );
}

#[test]
fn preference_values_must_be_within_closed_unit_interval() {
    let too_high = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1);
    let error = must_err(PreferenceState::genesis(
        id("agent-high"),
        SubjectClass::Agent,
        vec![axis("quality", too_high)],
    ));
    assert_eq!(
        error,
        NduError::PreferenceValueOutOfRange("quality".to_owned())
    );

    let initial = must(PreferenceState::genesis(
        id("agent-target"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let error = must_err(solve_preference_target(
        initial,
        vec![axis("quality", too_high)],
        FixedQ32::from_raw(1_i64 << 30),
    ));
    assert_eq!(
        error,
        NduError::PreferenceValueOutOfRange("quality".to_owned())
    );
}

#[test]
fn already_converged_solve_does_not_advance_revision() {
    let initial = must(PreferenceState::genesis(
        id("agent-noop"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let revision = initial.revision;
    let digest = initial.state_digest;
    let result = must(solve_preference_target(
        initial,
        vec![axis("quality", FixedQ32::ZERO)],
        FixedQ32::from_raw(1_i64 << 30),
    ));
    let PreferenceSolveResult::Converged {
        state,
        termination,
        receipts,
    } = result
    else {
        panic!("no-op must converge");
    };
    assert_eq!(state.revision, revision);
    assert_eq!(state.state_digest, digest);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn iteration_bound_is_unavailable_and_exposes_no_state() {
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let result = must(solve_preference_target(
        initial,
        vec![axis("quality", FixedQ32::ONE)],
        FixedQ32::from_raw(1_i64 << 28),
    ));
    let PreferenceSolveResult::Unavailable {
        termination,
        receipts,
    } = result
    else {
        panic!("minimum eta fixture must hit the iteration bound");
    };
    assert_eq!(
        termination.disposition,
        SolveDisposition::UnavailableIterationBoundReached
    );
    assert_eq!(termination.iterations, 64);
    assert_eq!(receipts.len(), 64);
}
