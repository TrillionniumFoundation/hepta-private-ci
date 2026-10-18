use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn request() -> TrainingRequest {
    TrainingRequest {
        artifact_id: id("bellman-1"),
        producer_id: id("trainer-1"),
        generation: must(Generation::new(1)),
        gamma: FixedQ32::from_raw(1_i64 << 31),
        dataset: DatasetSnapshot {
            snapshot_id: id("dataset-1"),
            objective_digest: Digest32::of_bytes(b"objective"),
            source_head_digest: Digest32::of_bytes(b"head"),
            transitions: vec![
                Transition {
                    sample_id: id("b"),
                    state_id: id("s"),
                    action_id: id("a"),
                    reward: FixedQ32::ONE,
                    next_value: FixedQ32::ONE,
                    terminal: false,
                    support_digest: Digest32::of_bytes(b"support"),
                },
                Transition {
                    sample_id: id("a"),
                    state_id: id("s2"),
                    action_id: id("a2"),
                    reward: FixedQ32::ZERO,
                    next_value: FixedQ32::ONE,
                    terminal: true,
                    support_digest: Digest32::of_bytes(b"support2"),
                },
            ],
        },
    }
}

#[test]
fn deterministic_and_canonical() {
    let first = must(train(request()));
    let mut reordered = request();
    reordered.dataset.transitions.reverse();
    let second = must(train(reordered));
    assert_eq!(first, second);
    assert_eq!(first.targets[0].sample_id, id("a"));
}

#[test]
fn terminal_transition_has_no_bootstrap() {
    let artifact = must(train(request()));
    assert_eq!(artifact.targets[0].target, FixedQ32::ZERO);
}

#[test]
fn invalid_gamma_fails_closed() {
    let mut value = request();
    value.gamma = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1);
    assert_eq!(train(value), Err(Error::InvalidGamma));
}

#[test]
fn duplicate_sample_fails() {
    let mut value = request();
    value
        .dataset
        .transitions
        .push(value.dataset.transitions[0].clone());
    assert!(matches!(train(value), Err(Error::DuplicateSample(_))));
}

#[test]
fn target_builder_uses_signed_nearest_ties_even_like_reference() {
    let mut value = request();
    value.dataset.transitions.truncate(1);
    value.dataset.transitions[0].reward = FixedQ32::ZERO;
    for (continuation, expected) in [(1, 0), (3, 2), (5, 2), (-1, 0), (-3, -2), (-5, -2)] {
        value.dataset.transitions[0].next_value = FixedQ32::from_raw(continuation);
        let artifact = must(build_targets(value.clone()));
        assert_eq!(
            artifact.targets,
            vec![BellmanTarget {
                sample_id: id("b"),
                target: FixedQ32::from_raw(expected),
            }]
        );
        let reference = must(evaluate_bellman_reference(BellmanReferencePlanV1 {
            plan_id: id("reference"),
            objective_digest: value.dataset.objective_digest,
            sensor_core_digest: Digest32::of_bytes(b"sensor-core"),
            gamma: value.gamma,
            sensor_ids: vec![id("s")],
            action_ids: vec![id("a"), id("b")],
            cells: ["a", "b"]
                .into_iter()
                .map(|action| BellmanReferenceCellV1 {
                    sensor_id: id("s"),
                    action_id: id(action),
                    reward: FixedQ32::ZERO,
                    continuation_value: FixedQ32::from_raw(continuation),
                    terminal: false,
                    evidence_digest: Digest32::of_bytes(action.as_bytes()),
                })
                .collect(),
        }));
        assert_eq!(artifact.targets[0].target, reference.targets[0].target);
    }
}
