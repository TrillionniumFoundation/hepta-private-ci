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

fn fixture_snapshot(
    generation: Generation,
    encoder_digest: Digest32,
    source_input: &str,
    features: Vec<i64>,
) -> Result<ImmutableFeatureSnapshotV1, CellBatchError> {
    ImmutableFeatureSnapshotV1::new_for_input(
        generation,
        encoder_digest,
        digest(source_input),
        features,
    )
}

fn snapshot() -> ImmutableFeatureSnapshotV1 {
    fixture_snapshot(generation(1), digest("encoder"), "src:123", vec![1, 2, 3])
        .expect("snapshot")
}

#[test]
fn zero_delta_preserves_the_no_update_baseline() {
    let head = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![2, 3, 5],
        7,
    )
    .expect("head");
    let successor = head.with_delta(&[0, 0, 0]).expect("zero delta");
    assert_eq!(head.activate(&snapshot()), successor.activate(&snapshot()));
}

#[test]
fn active_head_rejects_nonzero_same_generation_parameter_changes() {
    let head = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![2, 3, 5],
        7,
    )
    .expect("head");
    let baseline = head.activate(&snapshot()).expect("baseline");
    assert_eq!(
        head.with_delta(&[1, 0, 0]),
        Err(CellBatchError::ParameterUpdateRequiresSuccessor),
        "an altered head must not retain active generation",
    );
    assert_eq!(head.with_delta(&[0, 0]), Err(CellBatchError::DeltaWidth),);
    assert_eq!(
        head.activate(&snapshot())
            .expect("old generation preserved"),
        baseline
    );
}

#[test]
fn candidate_weight_updates_require_an_exact_successor_generation() {
    let head = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![2, 3, 5],
        7,
    )
    .expect("head");
    assert_eq!(
        head.with_successor_delta(generation(1), &[1, 0, 0]),
        Err(CellBatchError::GenerationNotSuccessor),
    );
    assert_eq!(
        head.with_successor_delta(generation(3), &[1, 0, 0]),
        Err(CellBatchError::GenerationNotSuccessor),
    );
    assert_eq!(
        head.with_successor_delta(generation(2), &[1, 0]),
        Err(CellBatchError::DeltaWidth),
    );

    let candidate = head
        .with_successor_delta(generation(2), &[1, 0, 0])
        .expect("candidate in successor generation");
    assert_eq!(head.generation, generation(1));
    assert_eq!(candidate.generation, generation(2));
    assert_eq!(
        candidate.activate(&snapshot()),
        Err(CellBatchError::GenerationMismatch),
        "a candidate must not evaluate an active generation's snapshot",
    );
    let successor_snapshot =
        fixture_snapshot(generation(2), digest("encoder"), "src:123", vec![1, 2, 3])
            .expect("successor feature");
    assert_eq!(
        candidate
            .activate(&successor_snapshot)
            .expect("successor activation")
            .score,
        head.activate(&snapshot()).expect("old activation").score + 1
    );
}

#[test]
fn shared_snapshot_is_reused_by_multiple_heads() {
    let snapshot = snapshot();
    let first = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![1, 1, 1],
        0,
    )
    .expect("head");
    let second = CellAdapterHeadV1::new(
        id("cell:b"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![1, 1, 1],
        0,
    )
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
    let stale = fixture_snapshot(generation(2), digest("encoder"), "src:123", vec![1, 2, 3])
        .expect("successor snapshot");
    assert_eq!(
        first.activate(&stale),
        Err(CellBatchError::GenerationMismatch)
    );
}

#[test]
fn feature_and_activation_batches_preserve_generation() {
    let first = snapshot();
    let second = fixture_snapshot(generation(1), digest("encoder"), "src:321", vec![3, 2, 1])
        .expect("snapshot");
    let batch = FeatureBatchV1::new(vec![first, second]).expect("feature batch");
    let head = CellAdapterHeadV1::new(
        id("cell:a"),
        id("organ:a"),
        generation(1),
        digest("encoder"),
        vec![1, 1, 1],
        0,
    )
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
    let incompatible =
        fixture_snapshot(generation(1), digest("different-encoder"), "src:123", vec![1, 2, 3])
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
    let incompatible =
        fixture_snapshot(generation(1), digest("different-encoder"), "src:123", vec![1, 2, 3])
            .expect("snapshot");
    assert_eq!(
        head.activate(&incompatible),
        Err(CellBatchError::EncoderMismatch)
    );
}

#[test]
fn equal_feature_values_do_not_alias_distinct_source_input_digests() {
    let first = fixture_snapshot(generation(1), digest("encoder"), "source:a", vec![7, 7, 7])
        .expect("first source");
    let second = fixture_snapshot(generation(1), digest("encoder"), "source:b", vec![7, 7, 7])
        .expect("second source");
    assert_eq!(first.features(), second.features());
    assert_ne!(first.input_digest(), second.input_digest());
    assert_eq!(
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(1),
            digest("encoder"),
            Digest32::ZERO,
            vec![7, 7, 7],
        ),
        Err(CellBatchError::ZeroDigest("input"))
    );
}
