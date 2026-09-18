use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::PreferenceState;
use super::SolveDisposition;
use super::UpdateGeneration;
use super::solve_preference_target_with_context;
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

fn context_digest() -> Digest32 {
    Digest32::of_bytes(b"solver-context")
}

fn axis(name: &str, value: FixedQ32) -> AxisValue {
    AxisValue {
        axis: id(name),
        value,
    }
}

#[test]
fn damped_preference_update_emits_context_bound_solver_receipts() {
    let initial = must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        vec![axis("evidence-quality", FixedQ32::ZERO)],
    ));
    let predecessor = initial.state_digest;
    let context = context_digest();
    let (terminal, termination, receipts) = must(solve_preference_target_with_context(
        initial,
        vec![axis("evidence-quality", FixedQ32::ONE)],
        FixedQ32::from_raw(1_i64 << 30),
        context,
    ));

    assert_eq!(termination.disposition, SolveDisposition::Converged);
    assert_eq!(termination.predecessor_digest, predecessor);
    assert_eq!(termination.context_digest(), context);
    assert!(!receipts.is_empty());
    assert!(receipts.iter().all(|receipt| receipt.context_digest() == context));
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
        predecessor_maximum(&receipts, FixedQ32::ONE.raw())
    );
}

fn predecessor_maximum(receipts: &[super::NduSolverIterationReceipt], initial_residual: i64) -> i64 {
    receipts
        .iter()
        .map(|receipt| receipt.residual_raw)
        .fold(initial_residual, i64::max)
}

#[test]
fn already_converged_solve_is_a_true_no_op() {
    let initial = must(PreferenceState::genesis(
        id("agent-noop"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    let revision = initial.revision;
    let digest = initial.state_digest;
    let (terminal, termination, receipts) = must(solve_preference_target_with_context(
        initial,
        vec![axis("quality", FixedQ32::ZERO)],
        FixedQ32::from_raw(1_i64 << 30),
        context_digest(),
    ));

    assert_eq!(terminal.revision, revision);
    assert_eq!(terminal.state_digest, digest);
    assert_eq!(termination.iterations, 0);
    assert_eq!(termination.terminal_residual_raw, 0);
    assert!(receipts.is_empty());
}

#[test]
fn preference_dimension_and_value_bounds_fail_at_the_api_boundary() {
    let too_many = (0..65)
        .map(|index| axis(&format!("axis-{index}"), FixedQ32::ZERO))
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
            vec![axis(
                "quality",
                FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
            )],
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );

    let initial = must(PreferenceState::genesis(
        id("target-check"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    assert_eq!(
        must_err(solve_preference_target_with_context(
            initial,
            vec![axis(
                "quality",
                FixedQ32::from_raw(-FixedQ32::ONE.raw() - 1),
            )],
            FixedQ32::from_raw(1_i64 << 30),
            context_digest(),
        )),
        NduError::PreferenceValueOutOfRange("quality".to_string())
    );
}

#[test]
fn exhausted_solver_is_unavailable_not_a_successful_state_transition() {
    let initial = must(PreferenceState::genesis(
        id("slow-agent"),
        SubjectClass::Agent,
        vec![axis("quality", FixedQ32::ZERO)],
    ));
    assert_eq!(
        must_err(solve_preference_target_with_context(
            initial,
            vec![axis("quality", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 28),
            context_digest(),
        )),
        NduError::IterationBoundReached
    );
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
            parent_subject_id: Some(id("system-a")),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(domain),
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
            parent_subject_id: Some(id("system-a")),
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_id: id("agent-b"),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(id("domain-b")),
            artifact_id: id("agent-candidate"),
        },
    ]));
}

#[test]
fn malformed_hierarchy_edges_fail_closed() {
    let generation = must(Generation::new(9));
    let domain = id("domain-a");
    assert_eq!(
        must_err(validate_staged_updates(&[
            UpdateGeneration {
                generation,
                subject_id: domain.clone(),
                subject_class: SubjectClass::Domain,
                parent_subject_id: Some(id("system-a")),
                artifact_id: id("domain-candidate"),
            },
            UpdateGeneration {
                generation,
                subject_id: id("episode-a"),
                subject_class: SubjectClass::Episode,
                parent_subject_id: Some(domain),
                artifact_id: id("episode-candidate"),
            },
        ])),
        NduError::InvalidHierarchyParent {
            parent: "domain-a".to_string(),
            child: "episode-a".to_string(),
        }
    );

    let self_id = id("agent-self");
    assert_eq!(
        must_err(validate_staged_updates(&[UpdateGeneration {
            generation,
            subject_id: self_id.clone(),
            subject_class: SubjectClass::Agent,
            parent_subject_id: Some(self_id),
            artifact_id: id("agent-self-artifact"),
        }])),
        NduError::HierarchySelfParent("agent-self".to_string())
    );
}

#[test]
fn eta_outside_registered_bounds_fails() {
    let initial = must(PreferenceState::genesis(
        id("episode-a"),
        SubjectClass::Episode,
        vec![axis("utility", FixedQ32::ZERO)],
    ));

    assert_eq!(
        must_err(solve_preference_target_with_context(
            initial,
            vec![axis("utility", FixedQ32::ONE)],
            FixedQ32::from_raw(1_i64 << 27),
            context_digest(),
        )),
        NduError::InvalidEta
    );
}
