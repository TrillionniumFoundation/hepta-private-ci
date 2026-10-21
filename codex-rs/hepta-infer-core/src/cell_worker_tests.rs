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
fn cache_rejects_conflicting_feature_identity_without_eviction() {
    let scope = id("scope:a");
    let encoder = digest("encoder");
    let input = digest("same-input");
    let first =
        ImmutableFeatureSnapshotV1::new_for_input(generation(1), encoder, input, vec![1, 2])
            .expect("first snapshot");
    let key = FeatureCacheKeyV1 {
        scope_id: scope.clone(),
        encoder_digest: encoder,
        input_digest: input,
    };
    let mut cache = FeatureCacheV1::default();
    cache
        .insert(scope.clone(), first.clone())
        .expect("initial admission");
    cache
        .insert(scope.clone(), first.clone())
        .expect("identical replay is idempotent");

    let substituted =
        ImmutableFeatureSnapshotV1::new_for_input(generation(1), encoder, input, vec![1, 3])
            .expect("substituted features");
    assert_eq!(
        cache.insert(scope.clone(), substituted),
        Err(CellWorkerError::ConflictingFeatureSnapshot)
    );
    assert_eq!(cache.get(&key, generation(1)), Some(&first));
    assert_eq!(cache.len(), 1);

    let successor =
        ImmutableFeatureSnapshotV1::new_for_input(generation(2), encoder, input, vec![3, 4])
            .expect("successor features");
    assert_eq!(
        cache.insert(scope.clone(), successor.clone()),
        Err(CellWorkerError::ConflictingFeatureSnapshot)
    );
    assert_eq!(cache.get(&key, generation(1)), Some(&first));
    assert!(cache.get(&key, generation(2)).is_none());

    // Reconfiguration is explicit: the owner first fences the old generation.
    cache.invalidate_generation(generation(2));
    cache
        .insert(scope, successor.clone())
        .expect("fresh generation after invalidation");
    assert_eq!(cache.get(&key, generation(2)), Some(&successor));
    assert!(cache.get(&key, generation(1)).is_none());
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
