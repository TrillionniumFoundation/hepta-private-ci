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
fn router_bounds_raw_input_before_sort_and_deduplication() {
    // A repeated ID is still one logical cell, but the raw input must not
    // consume unbounded sort/dedup CPU before the capacity check.
    assert_eq!(
        DeterministicRouterV1::new(vec![id("cell:repeated"); MAX_INDEX_ENTRIES + 1]),
        Err(CellWorkerError::IndexCapacity)
    );

    let cells = (0..MAX_INDEX_ENTRIES)
        .map(|index| id(&format!("cell:bounded:{index:05}")))
        .collect::<Vec<_>>();
    let router = DeterministicRouterV1::new(cells).expect("bounded router");
    assert_eq!(router.cells().len(), MAX_INDEX_ENTRIES);
    assert_eq!(
        DeterministicRouterV1::new(vec![id("cell:one"), id("cell:one")])
            .expect("small duplicate set")
            .cells(),
        &[id("cell:one")]
    );
    assert_eq!(
        DeterministicRouterV1::new(Vec::new()),
        Err(CellWorkerError::EmptyCellSet)
    );
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
fn worker_microbatch_limit_matches_immutable_feature_batch() {
    assert_eq!(
        SharedWorkerPoolV1::new(16_384, MAX_BATCH_ITEMS + 1),
        Err(CellWorkerError::BatchCapacity),
        "one worker dispatch must not exceed bounded shared-Encoder feature batches",
    );
    assert_eq!(
        SharedWorkerPoolV1::new(16_384, usize::MAX),
        Err(CellWorkerError::BatchCapacity),
    );
    assert_eq!(
        SharedWorkerPoolV1::new(1, 0),
        Err(CellWorkerError::ZeroBatchSize),
    );

    let mut pool = SharedWorkerPoolV1::new(MAX_BATCH_ITEMS + 1, MAX_BATCH_ITEMS)
        .expect("maximum admissible microbatch");
    for number in 0..=MAX_BATCH_ITEMS {
        pool.submit(request(
            u64::try_from(number).expect("bounded request index"),
            "scope:bounded",
        ))
        .expect("bounded queue admission");
    }
    assert_eq!(pool.drain().requests.len(), MAX_BATCH_ITEMS);
    assert_eq!(pool.drain().requests.len(), 1);
    assert_eq!(pool.metrics().groups_dequeued, 2);
    assert_eq!(pool.metrics().activations_dequeued, 1025);
    assert_eq!(pool.metrics().groups_committed, 0);
    assert_eq!(pool.metrics().activations_committed, 0);
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
    assert_eq!(pool.metrics().groups_dequeued, 1);
    assert_eq!(pool.metrics().activations_dequeued, 1);
    assert_eq!(pool.metrics().groups_committed, 0);
    assert_eq!(pool.metrics().activations_committed, 0);
    assert_eq!(pool.metrics().dropped_requests, 1);
    // Repeated empty drains are not scheduling events or durable commits.
    assert!(pool.drain().requests.is_empty());
    assert_eq!(pool.metrics().groups_dequeued, 1);
    assert_eq!(pool.metrics().groups_committed, 0);
}

#[test]
fn cache_rejects_same_generation_equivocation_and_older_rewrites() {
    let encoder = digest("frozen-encoder");
    let input = digest("same-input");
    let snapshot = |number, values| {
        ImmutableFeatureSnapshotV1::new_for_input(generation(number), encoder, input, values)
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
    cache
        .insert(scope.clone(), original.clone())
        .expect("first insert");
    cache
        .insert(scope.clone(), original)
        .expect("idempotent retry");

    assert_eq!(
        cache.insert(scope.clone(), snapshot(2, vec![3, 2, 1])),
        Err(CellWorkerError::FeatureSnapshotConflict),
        "same identity cannot produce two different feature vectors",
    );
    assert_eq!(
        cache
            .get(&key, generation(2))
            .expect("original remains")
            .features(),
        &[1, 2, 3],
    );

    cache
        .insert(scope.clone(), snapshot(3, vec![4, 5, 6]))
        .expect("forward generation replacement");
    assert_eq!(
        cache.insert(scope, snapshot(2, vec![1, 2, 3])),
        Err(CellWorkerError::StaleFeatureGeneration),
        "a retired generation must not replace the current snapshot",
    );
    assert!(cache.get(&key, generation(2)).is_none());
    assert_eq!(
        cache
            .get(&key, generation(3))
            .expect("new generation remains")
            .features(),
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
    index
        .register(old_key.clone(), id("cell:a"))
        .expect("old cell");
    index
        .register(old_key.clone(), id("cell:b"))
        .expect("other cell");
    index
        .register(other_shape.clone(), id("cell:c"))
        .expect("other shape");
    index
        .register(new_key.clone(), id("cell:d"))
        .expect("new model");
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
