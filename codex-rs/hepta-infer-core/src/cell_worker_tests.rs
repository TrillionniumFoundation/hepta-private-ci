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
fn compatible_index_rejects_cross_model_cell_alias_until_retirement() {
    let original = CompatibleModelKeyV1 {
        model_digest: digest("model:a"),
        encoder_digest: digest("encoder:a"),
        output_width: 8,
    };
    let alternate = CompatibleModelKeyV1 {
        model_digest: digest("model:b"),
        encoder_digest: digest("encoder:b"),
        output_width: 8,
    };
    let cell = id("cell:stable");
    let mut index = CompatibleModelIndexV1::default();
    index
        .register(original.clone(), cell.clone())
        .expect("first registration");
    index
        .register(original.clone(), cell.clone())
        .expect("identical registration is idempotent");
    assert_eq!(
        index.register(alternate.clone(), cell.clone()),
        Err(CellWorkerError::CellModelConflict)
    );
    assert_eq!(index.lookup(&original), vec![cell.clone()]);
    assert!(index.lookup(&alternate).is_empty());

    assert!(index.unregister(&cell));
    assert!(!index.unregister(&cell));
    assert!(index.lookup(&original).is_empty());
    index
        .register(alternate.clone(), cell.clone())
        .expect("new key after explicit retirement");
    assert_eq!(index.lookup(&alternate), vec![cell]);
}

#[test]
fn compatible_index_retirement_keeps_other_cells_and_reclaims_empty_keys() {
    let key = CompatibleModelKeyV1 {
        model_digest: digest("model:shared"),
        encoder_digest: digest("encoder:shared"),
        output_width: 8,
    };
    let mut index = CompatibleModelIndexV1::default();
    for number in 0..128 {
        let cell = id(&format!("cell:transient:{number}"));
        index.register(key.clone(), cell.clone()).expect("register");
        assert!(index.unregister(&cell));
        assert!(index.lookup(&key).is_empty());
    }
    index.register(key.clone(), id("cell:keep")).expect("register");
    index.register(key.clone(), id("cell:retire")).expect("register");
    assert!(index.unregister(&id("cell:retire")));
    assert_eq!(index.lookup(&key), vec![id("cell:keep")]);
}
