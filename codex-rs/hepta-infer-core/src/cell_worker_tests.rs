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

fn request(index: u64, scope: &str) -> QueuedCellRequestV1 {
    QueuedCellRequestV1 {
        request_id: id(&format!("request:{index}")),
        cell_id: id(&format!("cell:{index}")),
        scope_id: id(scope),
        feature_generation: generation(1),
    }
}

#[test]
fn router_is_deterministic_and_sorted() {
    let router = DeterministicRouterV1::new(vec![id("cell:b"), id("cell:a")]).expect("router");
    let first = router.route(digest("seed"));
    assert_eq!(first, router.route(digest("seed")));
    assert_eq!(router.cells(), &[id("cell:a"), id("cell:b")]);
}

#[test]
fn stale_feature_generation_is_not_readable() {
    let snapshot = ImmutableFeatureSnapshotV1::encode(generation(2), digest("encoder"), b"input")
        .expect("snapshot");
    let key = FeatureCacheKeyV1 {
        scope_id: id("scope:a"),
        encoder_digest: snapshot.encoder_digest(),
        input_digest: snapshot.input_digest(),
    };
    let mut cache = FeatureCacheV1::default();
    cache.insert(key.clone().scope_id, snapshot).expect("cache");
    assert!(cache.get(&key, generation(1)).is_none());
    assert!(cache.get(&key, generation(2)).is_some());
    cache.invalidate_generation(generation(2));
    assert_eq!(cache.len(), 1);
    cache.invalidate_generation(generation(1));
    assert_eq!(cache.len(), 0);
}

#[test]
fn compatible_model_index_is_stable() {
    let key = CompatibleModelKeyV1 {
        model_digest: digest("model"),
        encoder_digest: digest("encoder"),
        output_width: 8,
    };
    let mut index = CompatibleModelIndexV1::default();
    index.register(key.clone(), id("cell:b")).expect("register");
    index.register(key.clone(), id("cell:a")).expect("register");
    assert_eq!(index.lookup(&key), vec![id("cell:a"), id("cell:b")]);
}

#[test]
fn shared_pool_reports_group_and_drop_metrics() {
    let mut pool = SharedWorkerPoolV1::new(1, 1).expect("pool");
    pool.submit(request(1, "scope:a")).expect("submit");
    assert_eq!(
        pool.submit(request(2, "scope:b")),
        Err(CellWorkerError::Queue(CellBatchError::QueueFull))
    );
    let batch = pool.drain();
    assert_eq!(batch.requests.len(), 1);
    assert_eq!(pool.metrics().groups_committed, 1);
    assert_eq!(pool.metrics().activations_committed, 1);
    assert_eq!(pool.metrics().dropped_requests, 1);
}

#[test]
fn cache_rejects_same_generation_equivocation_and_older_rewrites() {
    let encoder = digest("frozen-encoder");
    let input = digest("same-input");
    let snapshot = |number, values| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(number),
            encoder,
            input,
            values,
        )
        .expect("valid immutable feature snapshot")
    };
    let scope = id("scope:a");
    let key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: encoder,
        input_digest: input,
    };
    let mut cache = FeatureCacheV1::default();
    let original = snapshot(2, vec![1, 2, 3]);
    cache.insert(scope.clone(), original.clone()).expect("first insert");
    cache.insert(scope.clone(), original).expect("idempotent retry");

    assert_eq!(
        cache.insert(scope.clone(), snapshot(2, vec![3, 2, 1])),
        Err(CellWorkerError::FeatureSnapshotConflict),
        "same identity cannot produce two different feature vectors",
    );
    assert_eq!(
        cache.get(&key, generation(2)).expect("original remains").features(),
        &[1, 2, 3],
    );

    cache.insert(scope.clone(), snapshot(3, vec![4, 5, 6]))
        .expect("forward generation replacement");
    assert_eq!(
        cache.insert(scope, snapshot(2, vec![1, 2, 3])),
        Err(CellWorkerError::StaleFeatureGeneration),
        "a retired generation must not replace the current snapshot",
    );
    assert!(cache.get(&key, generation(2)).is_none());
    assert_eq!(
        cache.get(&key, generation(3)).expect("new generation remains").features(),
        &[4, 5, 6],
    );
}

#[test]
fn retired_model_and_cell_eviction_are_idempotent() {
    let old_model = digest("old-model");
    let new_model = digest("new-model");
    let old_key = CompatibleModelKeyV1 {
        model_digest: old_model,
        encoder_digest: digest("encoder"),
        output_width: 8,
    };
    let other_shape = CompatibleModelKeyV1 {
        model_digest: old_model,
        encoder_digest: digest("encoder"),
        output_width: 16,
    };
    let new_key = CompatibleModelKeyV1 {
        model_digest: new_model,
        encoder_digest: digest("encoder"),
        output_width: 8,
    };
    let mut index = CompatibleModelIndexV1::default();
    index.register(old_key.clone(), id("cell:a")).expect("old cell");
    index.register(old_key.clone(), id("cell:b")).expect("other cell");
    index.register(other_shape.clone(), id("cell:c")).expect("other shape");
    index.register(new_key.clone(), id("cell:d")).expect("new model");
    assert_eq!(index.entry_count, 4);

    assert!(index.unregister(&old_key, &id("cell:a")));
    assert!(!index.unregister(&old_key, &id("cell:a")));
    assert_eq!(index.lookup(&old_key), vec![id("cell:b")]);
    assert_eq!(index.entry_count, 3);

    assert_eq!(index.invalidate_model(old_model), 2);
    assert_eq!(index.invalidate_model(old_model), 0);
    assert!(index.lookup(&old_key).is_empty());
    assert!(index.lookup(&other_shape).is_empty());
    assert_eq!(index.lookup(&new_key), vec![id("cell:d")]);
    assert_eq!(index.entry_count, 1);
    assert_eq!(index.entries.len(), 1);
}

#[test]
fn cache_cutover_keeps_monotone_floor_across_scopes_and_eviction() {
    let encoder = digest("shared-encoder");
    let input = digest("frozen-input");
    let snapshot = |epoch| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(epoch),
            encoder,
            input,
            vec![1, 2, 3],
        )
        .expect("valid feature")
    };
    let mut cache = FeatureCacheV1::default();
    cache.insert(id("scope:a"), snapshot(2)).expect("seed generation");
    cache.invalidate_generation(generation(3));
    assert!(cache.is_empty());

    // Eviction must not make a previously accepted stale generation writable.
    assert_eq!(
        cache.insert(id("scope:a"), snapshot(2)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    // Even a scope that has not cached a feature respects the cutover floor.
    assert_eq!(
        cache.insert(id("scope:new"), snapshot(2)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache.insert(id("scope:a"), snapshot(3)).expect("current generation");
    cache.invalidate_generation(generation(2));
    assert!(cache.is_empty());

    // A stale invalidation request must not lower the epoch floor.
    assert_eq!(
        cache.insert(id("scope:new"), snapshot(2)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache.insert(id("scope:new"), snapshot(4)).expect("forward generation");
}

#[test]
fn cache_watermark_spans_different_encoder_and_input_keys_within_scope() {
    let first = ImmutableFeatureSnapshotV1::new_for_input(
        generation(8),
        digest("encoder:a"),
        digest("input:a"),
        vec![4, 5],
    )
    .expect("first snapshot");
    let previous = ImmutableFeatureSnapshotV1::new_for_input(
        generation(7),
        digest("encoder:b"),
        digest("input:b"),
        vec![6, 7],
    )
    .expect("previous snapshot");
    let successor = ImmutableFeatureSnapshotV1::new_for_input(
        generation(9),
        digest("encoder:b"),
        digest("input:b"),
        vec![8, 9],
    )
    .expect("successor snapshot");
    let mut cache = FeatureCacheV1::default();
    cache.insert(id("scope:a"), first).expect("seed scope");
    assert_eq!(
        cache.insert(id("scope:a"), previous.clone()),
        Err(CellWorkerError::StaleFeatureGeneration),
        "a different encoder must not evade the scope generation watermark",
    );
    // Independent scopes may have different generations before an explicit
    // global cutover is announced.
    cache.insert(id("scope:b"), previous.clone()).expect("other scope");
    cache.insert(id("scope:a"), successor).expect("scope successor");
    assert_eq!(
        cache.insert(id("scope:a"), previous),
        Err(CellWorkerError::StaleFeatureGeneration),
        "a stale write cannot resurrect a retired encoder key",
    );
}
