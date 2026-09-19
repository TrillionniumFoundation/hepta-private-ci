use std::fmt::Debug;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::HierarchyParentV1;
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
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![axis("evidence-quality", FixedQ32::ONE)],
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
            .map(crate::NduSolverIterationReceipt::residual_raw)
            .max()
            .expect("maximum residual")
            .max(FixedQ32::ONE.raw())
    );
    assert!(
        receipts
            .iter()
            .all(|receipt| receipt.context_digest().is_zero())
    );
}

#[test]
fn already_converged_target_is_a_true_noop() {
    let initial = must(PreferenceState::genesis(
        id("episode-noop"),
        SubjectClass::Episode,
        vec![axis("utility", FixedQ32::from_raw(1234))],
    ));
    let expected = initial.clone();
    let target = initial.values.clone();

    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        target,
        FixedQ32::from_raw(1_i64 << 30),
    ));

    assert_eq!(terminal, expected);
    assert_eq!(termination.disposition, SolveDisposition::Converged);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert_eq!(termination.maximum_residual_raw, 0);
    assert_eq!(termination.projection_count, 0);
    assert!(receipts.is_empty());
}

#[test]
fn parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let domain = id("domain-a");
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: domain.clone(),
            subject_class: SubjectClass::Domain,
            parent: Some(HierarchyParentV1 {
                subject_id: id("system-a"),
                subject_class: SubjectClass::System,
            }),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            parent: Some(HierarchyParentV1 {
                subject_id: domain,
                subject_class: SubjectClass::Domain,
            }),
            artifact_id: id("agent-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
}

#[test]
fn unrelated_hierarchy_subjects_may_update_in_one_generation() {
    let generation = must(Generation::new(8));
    must(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent: Some(HierarchyParentV1 {
                subject_id: id("system-a"),
                subject_class: SubjectClass::System,
            }),
            artifact_id: id("domain-a-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-b"),
            subject_class: SubjectClass::Agent,
            parent: Some(HierarchyParentV1 {
                subject_id: id("domain-b"),
                subject_class: SubjectClass::Domain,
            }),
            artifact_id: id("agent-b-candidate"),
        },
    ]));
}

#[test]
fn malformed_hierarchy_parent_is_rejected() {
    let generation = must(Generation::new(9));
    let error = must_err(validate_staged_updates(&[UpdateGeneration {
        generation,
        subject_id: id("episode-a"),
        subject_class: SubjectClass::Episode,
        parent: Some(HierarchyParentV1 {
            subject_id: id("system-a"),
            subject_class: SubjectClass::System,
        }),
        artifact_id: id("episode-candidate"),
    }]));

    assert_eq!(
        error,
        NduError::InvalidHierarchyLink("episode-a".to_string())
    );
}

#[test]
fn preference_dimension_is_bounded_at_genesis() {
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
fn preference_values_are_rejected_before_solver_projection() {
    let too_large = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1);
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-invalid"),
            SubjectClass::Agent,
            vec![axis("quality", too_large)],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );

    let initial = must(PreferenceState::genesis(
        id("agent-valid"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis("quality", too_large)],
            FixedQ32::from_raw(1_i64 << 30),
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn iteration_budget_exhaustion_is_unavailable_not_a_terminal_state() {
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![axis("utility", FixedQ32::from_raw(-FixedQ32::ONE.raw()))],
    ));
    let error = must_err(solve_preference_target(
        initial,
        vec![axis("utility", FixedQ32::ONE)],
        FixedQ32::from_raw(1_i64 << 28),
    ));

    assert!(matches!(
        error,
        NduError::ConvergenceUnavailable(residual) if residual > (1_i64 << 12)
    ));
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
