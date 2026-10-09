use super::*;
use crate::bounded_batch::BatchLaneKeyV1;
use codex_hepta_types::Digest32;

fn d(x: &str) -> Digest32 {
    Digest32::of_bytes(x.as_bytes())
}

fn lane(generation: u64, epoch: u64, fence: &str) -> BatchLaneKeyV1 {
    BatchLaneKeyV1 {
        scope_digest: d("scope"),
        model_digest: d("model"),
        generation,
        fence_digest: d(fence),
        authority_epoch: epoch,
        revocation_frontier_digest: d(&format!("frontier:{epoch}")),
    }
}

fn id(x: &str) -> StableId {
    StableId::new(x).expect("id")
}

#[test]
fn all_cache_domains_are_read_only_and_fence_bound() {
    for domain in [
        CacheDomainV1::Authority,
        CacheDomainV1::Ndu,
        CacheDomainV1::Worker,
        CacheDomainV1::Retrieval,
    ] {
        let old = lane(3, 7, "fence:old");
        let mut cache = GenerationScopedCacheV1::new(domain, old, 2).expect("cache");
        let snapshot = Arc::new(vec![7, 8, 9]);
        cache.insert(old, id("snapshot"), Arc::clone(&snapshot)).expect("insert");
        let selected = cache.get(old, &id("snapshot")).expect("hit");
        assert!(Arc::ptr_eq(&selected, &snapshot));
        assert_eq!(
            cache.insert(old, id("snapshot"), Arc::new(vec![100])),
            Err(CacheErrorV1::AlreadyPresent)
        );
        assert_eq!(cache.rotate(old), Ok(false));
        assert_eq!(cache.rotate(lane(3, 7, "fence:changed")), Err(CacheErrorV1::StaleLane));
        assert_eq!(cache.rotate(lane(2, 8, "fence:new")), Err(CacheErrorV1::StaleLane));
        let next = lane(3, 8, "fence:new");
        assert_eq!(cache.rotate(next), Ok(true));
        assert_eq!(cache.get(old, &id("snapshot")), None);
        assert_eq!(cache.get(next, &id("snapshot")), None);
        assert!(cache.is_empty());
        cache.insert(next, id("snapshot"), Arc::new(vec![10])).expect("new snapshot");
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.insert(old, id("stale"), Arc::new(vec![1])), Err(CacheErrorV1::StaleLane));
    }
}

#[test]
fn capacity_cannot_be_evicted_to_bypass_generation() {
    let active = lane(1, 1, "fence");
    let mut cache = GenerationScopedCacheV1::new(CacheDomainV1::Retrieval, active, 1).expect("cache");
    cache.insert(active, id("one"), Arc::new(1_u64)).expect("first");
    assert_eq!(cache.insert(active, id("two"), Arc::new(2_u64)), Err(CacheErrorV1::CapacityExceeded));
    let next = lane(2, 1, "fence:next");
    assert!(cache.rotate(next).expect("authorized generation"));
    cache.insert(next, id("two"), Arc::new(2_u64)).expect("new");
    assert_eq!(*cache.get(next, &id("two")).expect("hit"), 2);
}
