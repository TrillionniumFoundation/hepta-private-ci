use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot() -> ImmutableFeatureSnapshotV1 {
    ImmutableFeatureSnapshotV1::new(generation(1), digest("encoder"), vec![1, 2, 3])
        .expect("snapshot")
}

#[test]
fn zero_delta_preserves_the_no_update_baseline() {
    let head = CellAdapterHeadV1::new(id("cell:a"), id("organ:a"), generation(1), digest("encoder"), vec![2, 3, 5], 7)
        .expect("head");
    let successor = head.with_delta(&[0, 0, 0]).expect("zero delta");
    assert_eq!(head.activate(&snapshot()), successor.activate(&snapshot()));
}

#[test]
fn shared_snapshot_is_reused_by_multiple_heads() {
    let snapshot = snapshot();
    let first =
        CellAdapterHeadV1::new(id("cell:a"), id("organ:a"), generation(1), digest("encoder"), vec![1, 1, 1], 0)
            .expect("head");
    let second =
        CellAdapterHeadV1::new(id("cell:b"), id("organ:a"), generation(1), digest("encoder"), vec![1, 1, 1], 0)
            .expect("head");
    assert_eq!(
        first
            .activate(&snapshot)
            .expect("activation")
            .feature_generation,
        generation(1)
    );
    assert_eq!(
        second
            .activate(&snapshot)
            .expect("activation")
            .feature_generation,
        generation(1)
    );
    let stale = ImmutableFeatureSnapshotV1::new(generation(2), digest("encoder"), vec![1, 2, 3])
        .expect("successor snapshot");
    assert_eq!(
        first.activate(&stale),
        Err(CellBatchError::GenerationMismatch)
    );
}

#[test]
fn feature_and_activation_batches_preserve_generation() {
    let first = snapshot();
    let second = ImmutableFeatureSnapshotV1::new(generation(1), digest("encoder"), vec![3, 2, 1])
        .expect("snapshot");
    let batch = FeatureBatchV1::new(vec![first, second]).expect("feature batch");
    let head = CellAdapterHeadV1::new(id("cell:a"), id("organ:a"), generation(1), digest("encoder"), vec![1, 1, 1], 0)
        .expect("head");
    let activations = head.activate_batch(&batch).expect("activation batch");
    assert_eq!(activations.feature_generation, generation(1));
    assert_eq!(activations.activations.len(), 2);
    assert_eq!(FeatureBatchV1::new(vec![]), Err(CellBatchError::EmptyBatch));
}

#[test]
fn state_migration_is_exact_successor_only() {
    let state = CellStateV1 {
        cell_id: id("cell:a"),
        generation: generation(1),
        hidden_state_digest: digest("state"),
    };
    assert_eq!(
        state.migrate_to(generation(2)).expect("successor"),
        CellStateV1 {
            cell_id: id("cell:a"),
            generation: generation(2),
            hidden_state_digest: digest("state"),
        }
    );
    assert_eq!(
        state.migrate_to(generation(3)),
        Err(CellBatchError::GenerationNotSuccessor)
    );
}

#[test]
fn queue_is_bounded_and_round_robin_fair() {
    let mut queue = FairCellQueueV1::new(3).expect("queue");
    for (index, scope) in [(1, "scope:a"), (2, "scope:a"), (3, "scope:b")] {
        queue
            .push(QueuedCellRequestV1 {
                request_id: id(&format!("request:{index}")),
                cell_id: id(&format!("cell:{index}")),
                scope_id: id(scope),
                feature_generation: generation(1),
            })
            .expect("enqueue");
    }
    assert_eq!(
        queue.push(QueuedCellRequestV1 {
            request_id: id("request:4"),
            cell_id: id("cell:4"),
            scope_id: id("scope:a"),
            feature_generation: generation(1),
        }),
        Err(CellBatchError::QueueFull)
    );
    let first = queue.drain_batch(2);
    assert_eq!(first[0].scope_id, id("scope:a"));
    assert_eq!(first[1].scope_id, id("scope:b"));
    assert_eq!(queue.len(), 1);
}

#[test]
fn same_generation_with_different_encoders_is_not_batch_compatible() {
    let expected = snapshot();
    let incompatible = ImmutableFeatureSnapshotV1::new(
        generation(1),
        digest("different-encoder"),
        vec![1, 2, 3],
    )
    .expect("snapshot");
    assert_eq!(
        FeatureBatchV1::new(vec![expected, incompatible]),
        Err(CellBatchError::EncoderMismatch)
    );
}

#[test]
fn cell_head_rejects_same_width_features_from_the_wrong_encoder() {
    let head = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![2, 3, 5],
        7,
    )
    .expect("head");
    let incompatible = ImmutableFeatureSnapshotV1::new(
        generation(1),
        digest("different-encoder"),
        vec![1, 2, 3],
    )
    .expect("snapshot");
    assert_eq!(
        head.activate(&incompatible),
        Err(CellBatchError::EncoderMismatch)
    );
}
