use std::fmt::Debug;

use codex_hepta_types::Digest32;
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

fn context(subject: &str, subject_class: SubjectClass, generation: u64) -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id(subject),
        subject_class,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(generation)),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
    }
}

fn axis(name: &str, value: FixedQ32) -> AxisValue {
    AxisValue {
        axis: id(name),
        value,
    }
}

#[test]
fn damped_preference_update_emits_context_bound_local_solver_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![axis("evidence-quality", FixedQ32::ZERO)],
    ));
    let predecessor = initial.state_digest;
    let solver_context = context("agent-a", SubjectClass::Agent, 4);
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![axis("evidence-quality", FixedQ32::ONE)],
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
    assert_eq!(termination.context_digest(), receipts[0].context_digest());
}

#[test]
fn already_converged_target_is_a_true_noop() {
    let initial = must(PreferenceState::genesis(
        id("agent-noop"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::from_raw(1234))],
    ));
    let initial_clone = initial.clone();
    let solver_context = context("agent-noop", SubjectClass::Agent, 5);
    let (terminal, termination, receipts) = must(solve_preference_target(
        initial,
        vec![axis("quality", FixedQ32::from_raw(1234))],
        FixedQ32::from_raw(1_i64 << 30),
        &solver_context,
    ));

    assert_eq!(terminal, initial_clone);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert_eq!(termination.maximum_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn preference_dimension_and_value_bounds_fail_at_the_api_boundary() {
    let too_many = (0..65)
        .map(|index| axis(&format!("axis-{index}"), FixedQ32::ZERO))
        .collect();
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-wide"),
            SubjectClass::Agent,
            too_many,
        )),
        NduError::PreferenceDimensionLimitExceeded
    );
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-empty"),
            SubjectClass::Agent,
            Vec::new(),
        )),
        NduError::PreferenceDimensionLimitExceeded
    );
    assert_eq!(
        must_err(PreferenceState::genesis(
            id("agent-oob"),
            SubjectClass::Agent,
            vec![axis(
                "quality",
                FixedQ32::from_raw(FixedQ32::ONE.raw() + 1)
            )],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn out_of_range_target_fails_before_iteration_or_projection() {
    let initial = must(PreferenceState::genesis(
        id("agent-target"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let solver_context = context("agent-target", SubjectClass::Agent, 6);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis(
                "quality",
                FixedQ32::from_raw(FixedQ32::ONE.raw() + 1)
            )],
            FixedQ32::from_raw(1_i64 << 30),
            &solver_context,
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn iteration_bound_exhaustion_is_unavailable_not_a_successful_state() {
    let initial = must(PreferenceState::genesis(
        id("agent-slow"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let solver_context = context("agent-slow", SubjectClass::Agent, 7);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis("quality", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 28),
            &solver_context,
        )),
        NduError::IterationBoundReached
    );
}

#[test]
fn actual_parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(8));
    let system_id = id("system-a");
    let domain_id = id("domain-a");
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: system_id.clone(),
            subject_class: SubjectClass::System,
            parent_subject_id: None,
            parent_subject_class: None,
            artifact_id: id("system-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: domain_id,
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(system_id),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("domain-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(8));
}

#[test]
fn unrelated_hierarchy_subjects_may_update_in_one_generation() {
    let generation = must(Generation::new(9));
    must(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("domain-a-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-b"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(id("domain-b")),
            parent_subject_class: Some(SubjectClass::Domain),
            artifact_id: id("agent-b-candidate"),
        },
    ]));
}

#[test]
fn invalid_hierarchy_parent_class_fails_closed() {
    let generation = must(Generation::new(10));
    let error = must_err(validate_staged_updates(&[UpdateGeneration {
        generation,
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        parent_subject_id: Some(id("system-a")),
        parent_subject_class: Some(SubjectClass::System),
        artifact_id: id("agent-candidate"),
    }]));
    assert!(matches!(error, NduError::InvalidHierarchyRelation { .. }));
}

#[test]
fn duplicate_subject_or_artifact_in_one_generation_rejects() {
    let generation = must(Generation::new(11));
    let duplicate_subject = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("artifact-a"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("artifact-b"),
        },
    ]));
    assert_eq!(
        duplicate_subject,
        NduError::DuplicateSubjectUpdate("domain-a".to_string())
    );

    let duplicate_artifact = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_id: id("domain-a"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-a")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("artifact-shared"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("domain-b"),
            subject_class: SubjectClass::Domain,
            parent_subject_id: Some(id("system-b")),
            parent_subject_class: Some(SubjectClass::System),
            artifact_id: id("artifact-shared"),
        },
    ]));
    assert_eq!(
        duplicate_artifact,
        NduError::DuplicateArtifactUpdate("artifact-shared".to_string())
    );
}

#[test]
fn solver_context_must_match_the_preference_subject() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let wrong_context = context("agent-b", SubjectClass::Agent, 12);
    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis("quality", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 30),
            &wrong_context,
        )),
        NduError::SolverContextMismatch
    );
}

#[test]
fn eta_outside_registered_bounds_fails() {
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![axis("utility", FixedQ32::ZERO)],
    ));
    let solver_context = context("episode-a", SubjectClass::Episode, 13);

    assert_eq!(
        must_err(solve_preference_target(
            initial,
            vec![axis("utility", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 27),
            &solver_context,
        )),
        NduError::InvalidEta
    );
}
