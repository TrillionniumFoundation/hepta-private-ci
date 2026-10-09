use super::*;

fn key(generation: u64, fence: u64, epoch: u64, digest: &str) -> FenceCacheBindingV1 {
    FenceCacheBindingV1 {
        scope: StableId::new("scope").unwrap(),
        generation: Generation::new(generation).unwrap(),
        route_fence: fence,
        revocation_epoch: epoch,
        binding_digest: Digest32::of_bytes(digest.as_bytes()),
    }
}

#[test]
fn epochs_and_fences_fail_closed_for_all_cache_families() {
    let mut caches = ScopedCachesV1::<u64,u64,u64,u64>::new(2).unwrap();
    let old = key(1, 1, 1, "a");
    let next = key(2, 2, 2, "b");
    for cache in [&mut caches.authority, &mut caches.ndu, &mut caches.worker, &mut caches.retrieval] {
        cache.observe_binding(old.clone()).unwrap();
        cache.put(10, &old, Arc::new(42), 20).unwrap();
        assert_eq!(*cache.get(11, &old).unwrap(), 42);
        assert!(cache.get(20, &old).is_none());
        cache.observe_binding(next.clone()).unwrap();
        assert!(cache.get(11, &old).is_none());
        assert_eq!(cache.observe_binding(old.clone()), Err(FenceCacheErrorV1::StaleBinding));
        assert_eq!(cache.observe_binding(key(2, 2, 2, "tamper")), Err(FenceCacheErrorV1::SameEpochConflict));
        assert_eq!(cache.put(11, &old, Arc::new(8), 20), Err(FenceCacheErrorV1::StaleBinding));
        cache.put(11, &next, Arc::new(73), 20).unwrap();
        cache.invalidate(key(2, 3, 3, "c")).unwrap();
        assert!(cache.get(12, &next).is_none());
    }
}

#[test]
fn no_global_eviction_scan_at_4096_scopes() {
    let mut cache = GenerationFenceCacheV1::<u64>::new(CacheFamilyV1::RetrievalClient, MAX_CACHED_SCOPES).unwrap();
    for i in 0..MAX_CACHED_SCOPES {
        let mut binding = key(1, 1, 1, "config");
        binding.scope = StableId::new(format!("scope{i}")).unwrap();
        cache.observe_binding(binding.clone()).unwrap();
        cache.put(0, &binding, Arc::new(i as u64), 100).unwrap();
        assert_eq!(*cache.get(10, &binding).unwrap(), i as u64);
    }
    assert_eq!(cache.scopes(), MAX_CACHED_SCOPES);
}
