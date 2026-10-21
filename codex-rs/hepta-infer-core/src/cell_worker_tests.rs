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
