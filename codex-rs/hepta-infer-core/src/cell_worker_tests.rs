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
    assert_eq!(
        cache.try_invalidate_generation(generation(1)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache.invalidate_generation(generation(1));
    assert_eq!(cache.len(), 1, "stale cutover must not destroy live features");
    assert!(cache.get(&key, generation(2)).is_some());
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
    assert_eq!(
        cache.try_invalidate_generation(generation(2)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache.invalidate_generation(generation(2));
    assert_eq!(cache.len(), 1, "a stale cutover must leave live data intact");

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

#[test]
fn scoped_feature_cache_cutover_preserves_unrelated_scopes() {
    let encoder = digest("encoder:shared");
    let make_snapshot = |epoch, input: &str| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(epoch),
            encoder,
            digest(input),
            vec![10, 20, 30],
        )
        .expect("valid immutable feature")
    };
    let scope_a = id("scope:a");
    let scope_b = id("scope:b");
    let key_a = FeatureCacheKeyV1 {
        scope_id: scope_a.clone(),
        encoder_digest: encoder,
        input_digest: digest("input:a"),
    };
    let key_b = FeatureCacheKeyV1 {
        scope_id: scope_b.clone(),
        encoder_digest: encoder,
        input_digest: digest("input:b"),
    };
    let mut cache = FeatureCacheV1::default();
    cache
        .insert(scope_a.clone(), make_snapshot(2, "input:a"))
        .expect("scope A generation 2");
    cache
        .insert(scope_b.clone(), make_snapshot(1, "input:b"))
        .expect("scope B independent generation 1");

    cache
        .invalidate_scope_generation(scope_a.clone(), generation(3))
        .expect("only A crosses its generation fence");
    assert!(cache.get(&key_a, generation(2)).is_none());
    assert!(cache.get(&key_b, generation(1)).is_some());
    assert_eq!(cache.len(), 1, "unrelated scope is not evicted");

    assert_eq!(
        cache.insert(scope_a.clone(), make_snapshot(2, "input:a")),
        Err(CellWorkerError::StaleFeatureGeneration),
        "retired scope A generation cannot reappear",
    );
    assert_eq!(
        cache.invalidate_scope_generation(scope_a.clone(), generation(2)),
        Err(CellWorkerError::StaleFeatureGeneration),
        "stale cutover cannot lower scope A's watermark",
    );
    cache
        .insert(scope_a.clone(), make_snapshot(3, "input:a"))
        .expect("A successor remains admissible");
    cache
        .insert(scope_b.clone(), make_snapshot(1, "input:b"))
        .expect("B is unaffected by A's cutover");
    assert!(cache.get(&key_a, generation(3)).is_some());
    assert!(cache.get(&key_b, generation(1)).is_some());
}

#[test]
fn scoped_cutover_of_empty_scope_fences_old_reinsertion() {
    let mut cache = FeatureCacheV1::default();
    let scope = id("scope:empty");
    let snapshot = |epoch| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(epoch),
            digest("encoder"),
            digest("original"),
            vec![1, 2],
        )
        .expect("snapshot")
    };
    cache
        .invalidate_scope_generation(scope.clone(), generation(7))
        .expect("publish fence without cached key");
    assert!(cache.is_empty());
    assert_eq!(
        cache.insert(scope.clone(), snapshot(6)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache
        .insert(scope.clone(), snapshot(7))
        .expect("at-fence snapshot");
    cache
        .invalidate_scope_generation(scope, generation(7))
        .expect("idempotent exact cutover");
    assert_eq!(cache.len(), 1);
}

#[test]
fn new_scope_generation_fences_reads_of_stale_encoder_keys() {
    let mut cache = FeatureCacheV1::default();
    let scope = id("scope:learning");
    let old = ImmutableFeatureSnapshotV1::new_for_input(
        generation(4),
        digest("encoder:original"),
        digest("input:original"),
        vec![3, 4],
    )
    .expect("old snapshot");
    let new = ImmutableFeatureSnapshotV1::new_for_input(
        generation(5),
        digest("encoder:replacement"),
        digest("input:replacement"),
        vec![7, 8],
    )
    .expect("new snapshot");
    let old_key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: old.encoder_digest(),
        input_digest: old.input_digest(),
    };
    let new_key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: new.encoder_digest(),
        input_digest: new.input_digest(),
    };
    cache.insert(scope.clone(), old).expect("seed");
    assert!(cache.get(&old_key, generation(4)).is_some());
    cache.insert(scope, new).expect("advance scope watermark");
    assert!(
        cache.get(&old_key, generation(4)).is_none(),
        "stale snapshot must not remain readable after later scoped generation",
    );
    assert!(cache.get(&new_key, generation(5)).is_some());
}

#[test]
fn feature_cache_reclaims_retired_keys_without_touching_other_scopes() {
    let mut cache = FeatureCacheV1::default();
    let scope = id("scope:changing");
    let other_scope = id("scope:independent");
    let encoder = digest("encoder:shared");
    let snapshot = |epoch, input: &str| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(epoch),
            encoder,
            digest(input),
            vec![1, 2, 3],
        )
        .expect("immutable feature")
    };
    let old_key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: encoder,
        input_digest: digest("old:a"),
    };
    let other_key = FeatureCacheKeyV1 {
        scope_id: other_scope.clone(),
        encoder_digest: encoder,
        input_digest: digest("unrelated"),
    };
    let successor_key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: encoder,
        input_digest: digest("successor"),
    };
    cache.insert(scope.clone(), snapshot(3, "old:a")).expect("old A");
    cache.insert(scope.clone(), snapshot(3, "old:b")).expect("old B");
    cache
        .insert(other_scope, snapshot(1, "unrelated"))
        .expect("independent scope");
    assert_eq!(cache.len(), 3);

    cache
        .insert(scope.clone(), snapshot(4, "successor"))
        .expect("advance one scope");
    assert_eq!(cache.len(), 2, "old scoped entries must release capacity");
    assert!(cache.get(&old_key, generation(3)).is_none());
    assert!(cache.get(&successor_key, generation(4)).is_some());
    assert!(
        cache.get(&other_key, generation(1)).is_some(),
        "independent older generation must remain cached"
    );
    assert_eq!(
        cache.insert(scope, snapshot(3, "old:a")),
        Err(CellWorkerError::StaleFeatureGeneration)
    );
}

#[test]
fn feature_cache_reuses_full_capacity_for_new_scope_generation() {
    let mut cache = FeatureCacheV1::default();
    let scope = id("scope:full");
    let encoder = digest("encoder:full");
    for index in 0..MAX_INDEX_ENTRIES {
        let snapshot = ImmutableFeatureSnapshotV1::new_for_input(
            generation(1),
            encoder,
            digest(&format!("source:{index:05}")),
            vec![i64::try_from(index).expect("bounded index")],
        )
        .expect("valid snapshot");
        cache.insert(scope.clone(), snapshot).expect("fill cache");
    }
    assert_eq!(cache.len(), MAX_INDEX_ENTRIES);
    let original_key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: encoder,
        input_digest: digest("source:00000"),
    };
    let foreign_scope = id("scope:foreign");
    let foreign = ImmutableFeatureSnapshotV1::new_for_input(
        generation(1),
        encoder,
        digest("foreign"),
        vec![1],
    )
    .expect("foreign snapshot");
    assert_eq!(
        cache.insert(foreign_scope.clone(), foreign),
        Err(CellWorkerError::IndexCapacity),
        "a full cache must not evict another scope's live entries"
    );
    assert!(
        !cache.scope_high_watermarks.contains_key(&foreign_scope),
        "failed admission must not burn a scope fence"
    );
    assert!(cache.get(&original_key, generation(1)).is_some());

    let successor = ImmutableFeatureSnapshotV1::new_for_input(
        generation(2),
        encoder,
        digest("successor"),
        vec![9],
    )
    .expect("successor snapshot");
    cache.insert(scope.clone(), successor).expect("retire old keys");
    assert_eq!(cache.len(), 1, "expired keys must not starve new generation");
    assert!(cache.get(&original_key, generation(1)).is_none());
    assert_eq!(
        cache.insert(
            scope,
            ImmutableFeatureSnapshotV1::new_for_input(
                generation(1),
                encoder,
                digest("old-retry"),
                vec![5],
            )
            .expect("old snapshot"),
        ),
        Err(CellWorkerError::StaleFeatureGeneration)
    );
}

#[test]
fn global_cutover_rejects_a_scope_that_is_already_newer() {
    let scope_a = id("scope:newer");
    let scope_b = id("scope:other");
    let encoder = digest("encoder:shared");
    let input_a = digest("input:newer");
    let input_b = digest("input:other");
    let make_snapshot = |epoch, input| {
        ImmutableFeatureSnapshotV1::new_for_input(
            generation(epoch),
            encoder,
            input,
            vec![1, 2, 3],
        )
        .expect("snapshot")
    };
    let key_a = FeatureCacheKeyV1 {
        scope_id: scope_a.clone(),
        encoder_digest: encoder,
        input_digest: input_a,
    };
    let key_b = FeatureCacheKeyV1 {
        scope_id: scope_b.clone(),
        encoder_digest: encoder,
        input_digest: input_b,
    };

    let mut cache = FeatureCacheV1::default();
    cache
        .insert(scope_a, make_snapshot(9, input_a))
        .expect("newer scope");
    cache
        .insert(scope_b, make_snapshot(8, input_b))
        .expect("independent older scope");
    let before = cache.clone();
    assert_eq!(
        cache.try_invalidate_generation(generation(8)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    assert_eq!(cache, before, "rejection must be transactional");
    cache.invalidate_generation(generation(8));
    assert_eq!(cache, before, "legacy entry point must also fail closed");
    assert!(cache.get(&key_a, generation(9)).is_some());
    assert!(cache.get(&key_b, generation(8)).is_some());

    cache
        .try_invalidate_generation(generation(9))
        .expect("monotone fleet-wide cutover");
    assert!(cache.get(&key_a, generation(9)).is_some());
    assert!(cache.get(&key_b, generation(8)).is_none());
    assert_eq!(cache.len(), 1);
}

#[test]
fn empty_global_cache_floor_is_not_rolled_back() {
    let mut cache = FeatureCacheV1::default();
    cache
        .try_invalidate_generation(generation(12))
        .expect("initial fleet fence");
    let before = cache.clone();
    assert_eq!(
        cache.try_invalidate_generation(generation(11)),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
    cache.invalidate_generation(generation(11));
    assert_eq!(cache, before, "stale cutover preserves empty-scope fence");

    let older = ImmutableFeatureSnapshotV1::new_for_input(
        generation(11),
        digest("encoder"),
        digest("input"),
        vec![1, 2],
    )
    .expect("snapshot");
    assert_eq!(
        cache.insert(id("scope:unseen"), older),
        Err(CellWorkerError::StaleFeatureGeneration),
    );
}

#[test]
fn shared_worker_does_not_mix_generations_or_skip_deferred_scope_heads() {
    let mut pool = SharedWorkerPoolV1::new(5, 4).expect("pool");
    let mut b1 = request(2, "scope:b");
    b1.feature_generation = generation(2);
    let mut a2 = request(4, "scope:a");
    a2.feature_generation = generation(2);
    let mut b2 = request(5, "scope:b");
    b2.feature_generation = generation(2);

    pool.submit(request(1, "scope:a")).expect("first generation");
    pool.submit(b1).expect("other generation");
    pool.submit(request(3, "scope:c")).expect("compatible scope");
    pool.submit(a2).expect("successor within same scope");
    pool.submit(b2).expect("successor within deferred scope");

    let first = pool.drain();
    assert_eq!(
        first.requests.iter().map(|r| r.request_id.as_str()).collect::<Vec<_>>(),
        vec!["request:1", "request:3"],
    );
    assert!(first
        .requests
        .iter()
        .all(|r| r.feature_generation == generation(1)));

    let second = pool.drain();
    assert_eq!(second.requests.len(), 3);
    assert!(second
        .requests
        .iter()
        .all(|r| r.feature_generation == generation(2)));
    assert!(pool.drain().requests.is_empty());

    // An empty drain and deferred incompatible heads are not dropped.
    assert_eq!(pool.metrics().groups_dequeued, 2);
    assert_eq!(pool.metrics().activations_dequeued, 5);
    assert_eq!(pool.metrics().groups_committed, 0);
    assert_eq!(pool.metrics().activations_committed, 0);
    assert_eq!(pool.metrics().dropped_requests, 0);
}

