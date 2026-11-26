use super::*;
use codex_hepta_types::StableId;

const Q: i64 = 1 << 24;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"cell-split-head"),
        normalization_digest: Digest32::of_bytes(b"cell-split-normalization"),
        generation: checked(Generation::new(1)),
        width: 6,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 4,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn checkpoint() -> SparseCheckpoint {
    let input = SparseTick {
        scope_digest: Digest32::of_bytes(b"parent-scope"),
        objective_digest: Digest32::of_bytes(b"cell-split-objective"),
        ndu_digest: Digest32::of_bytes(b"cell-split-ndu"),
        body_digest: Digest32::of_bytes(b"cell-split-body"),
        input_digest: Digest32::of_bytes(b"cell-split-input"),
        sequence: 1,
        monotonic_micros: 10,
        drive_q24: vec![Q, Q / 2, Q / 4, 0, 0, 0],
        prediction_q24: vec![0; 6],
    };
    checked(sparse_tick(&config(), &input, None)).0
}

fn plan(
    temporal_partitions: Vec<Vec<usize>>,
    activation_partitions: Vec<Vec<usize>>,
) -> CellStateSplitPlanV1 {
    checked(CellStateSplitPlanV1::new(
        checked(StableId::new("cell.parent")),
        vec![
            checked(StableId::new("cell.child.a")),
            checked(StableId::new("cell.child.b")),
        ],
        vec![
            Digest32::of_bytes(b"scope-a"),
            Digest32::of_bytes(b"scope-b"),
        ],
        checked(Generation::new(1)),
        checked(Generation::new(2)),
        temporal_partitions,
        activation_partitions,
    ))
}

#[test]
fn exact_partition_projects_every_state_vector_and_binds_parent() {
    let checkpoint = checkpoint();
    let plan = plan(
        vec![vec![0, 2, 4], vec![1, 3, 5]],
        vec![vec![0, 2, 4], vec![1, 3, 5]],
    );
    let children = checked(checkpoint.split_state_v1(&plan));
    assert_eq!(children.len(), 2);
    assert_eq!(children[0].child_cell_id.as_str(), "cell.child.a");
    assert_eq!(children[0].temporal_q24, vec![Q, Q / 4, 0]);
    assert_eq!(children[1].temporal_q24, vec![Q / 2, 0, 0]);
    assert_eq!(children[0].activation_q24.len(), 3);
    assert_eq!(children[1].eligibility_q24.len(), 3);
    for child in &children {
        assert_eq!(child.parent_checkpoint_digest, checkpoint.digest());
        assert_eq!(child.parent_generation, checked(Generation::new(1)));
        assert_eq!(child.candidate_generation, checked(Generation::new(2)));
        assert!(child.verify_digest());
    }
}

#[test]
fn overlap_and_gap_are_rejected_before_projection() {
    let overlap = CellStateSplitPlanV1::shared_partition(
        checked(StableId::new("cell.parent")),
        vec![
            checked(StableId::new("cell.child.a")),
            checked(StableId::new("cell.child.b")),
        ],
        vec![
            Digest32::of_bytes(b"scope-a"),
            Digest32::of_bytes(b"scope-b"),
        ],
        checked(Generation::new(1)),
        checked(Generation::new(2)),
        vec![vec![0, 1], vec![1, 2]],
    );
    assert!(overlap.is_ok());
    assert_eq!(
        checkpoint().split_state_v1(&overlap.expect("shape is checked at dimensions")),
        Err(CellStateSplitError::InvalidPlan("overlapping partition"))
    );

    let gap = CellStateSplitPlanV1::shared_partition(
        checked(StableId::new("cell.parent")),
        vec![
            checked(StableId::new("cell.child.a")),
            checked(StableId::new("cell.child.b")),
        ],
        vec![
            Digest32::of_bytes(b"scope-a"),
            Digest32::of_bytes(b"scope-b"),
        ],
        checked(Generation::new(1)),
        checked(Generation::new(2)),
        vec![vec![0], vec![2]],
    );
    assert!(gap.is_ok());
    assert_eq!(
        checkpoint().split_state_v1(&gap.expect("shape is checked at dimensions")),
        Err(CellStateSplitError::InvalidPlan("incomplete partition"))
    );
}

#[test]
fn candidate_generation_must_be_the_exact_successor() {
    let invalid = CellStateSplitPlanV1::shared_partition(
        checked(StableId::new("cell.parent")),
        vec![
            checked(StableId::new("cell.child.a")),
            checked(StableId::new("cell.child.b")),
        ],
        vec![
            Digest32::of_bytes(b"scope-a"),
            Digest32::of_bytes(b"scope-b"),
        ],
        checked(Generation::new(1)),
        checked(Generation::new(3)),
        vec![vec![0, 1, 2], vec![3, 4, 5]],
    );
    assert_eq!(
        invalid,
        Err(CellStateSplitError::CandidateGenerationMismatch)
    );
}

#[test]
fn invalid_parent_checkpoint_is_rejected_and_child_digest_is_detectable() {
    let mut invalid = checkpoint();
    invalid.digest = Digest32::of_bytes(b"forged-checkpoint");
    let plan = plan(
        vec![vec![0, 2, 4], vec![1, 3, 5]],
        vec![vec![0, 2, 4], vec![1, 3, 5]],
    );
    assert_eq!(
        invalid.split_state_v1(&plan),
        Err(CellStateSplitError::InvalidCheckpoint)
    );

    let children = checked(checkpoint().split_state_v1(&plan));
    let mut forged = children[0].clone();
    forged.state_digest = Digest32::of_bytes(b"forged-child");
    assert!(!forged.verify_digest());
}
