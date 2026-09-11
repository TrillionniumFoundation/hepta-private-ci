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
            .max()
            .expect("maximum residual")
    );
}

#[test]
fn parent_and_child_updates_cannot_share_generation() {
    let generation = must(Generation::new(7));
    let error = must_err(validate_staged_updates(&[
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Domain,
            artifact_id: id("domain-candidate"),
        },
        UpdateGeneration {
            generation,
            subject_class: SubjectClass::Agent,
            artifact_id: id("agent-candidate"),
        },
    ]));

    assert_eq!(error, NduError::SimultaneousHierarchyUpdate(7));
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
