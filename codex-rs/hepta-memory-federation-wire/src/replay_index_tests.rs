use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable identity")
}

fn admit(cache: &mut ReplayCacheV1, peer: &str, slot: u64, expiry: u64, now: u64) {
    let mut nonce = [1; 32];
    nonce[..8].copy_from_slice(&slot.to_be_bytes());
    cache
        .admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id(peer),
                receiver_peer_id: &id("local"),
                key_id: &id("key"),
                generation: 1,
                nonce: &nonce,
            },
            expiry,
            now,
        )
        .expect("admission");
}

fn check_indexes(cache: &ReplayCacheV1) {
    let mut counts = BTreeMap::new();
    let mut expiries = BTreeSet::new();
    for (key, entry) in &cache.entries {
        *counts.entry(entry.credential_scope).or_insert(0) += 1;
        expiries.insert((entry.expires_unix_ms, *key));
    }
    assert_eq!(cache.credential_counts, counts);
    assert_eq!(cache.expiries, expiries);
}

#[test]
fn bounded_cleanup_reclaims_only_expired_entries_and_exact_partition_counts() {
    let mut cache = ReplayCacheV1::with_limits(256, 128).expect("cache");
    for slot in 0..128 {
        admit(&mut cache, "expired", slot, 20, 10);
    }
    admit(&mut cache, "live", 0, 100, 10);
    let mut removed = 0;
    loop {
        let count = cache.purge_expired_bounded(20, 7).expect("bounded cleanup");
        assert!(count <= 7);
        removed += count;
        check_indexes(&cache);
        if count == 0 {
            break;
        }
    }
    assert_eq!(removed, 128);
    assert_eq!(cache.len(), 1);
    assert_eq!(cache.credential_counts.len(), 1);
    admit(&mut cache, "expired", 200, 50, 21);
    check_indexes(&cache);
}

#[test]
fn admission_cleanup_is_bounded_and_does_not_scan_away_the_whole_backlog() {
    let mut cache = ReplayCacheV1::with_limits(512, 256).expect("cache");
    for slot in 0..200 {
        admit(&mut cache, "old", slot, 20, 10);
    }
    admit(&mut cache, "live", 0, 100, 10);
    admit(&mut cache, "new", 0, 100, 20);
    assert_eq!(cache.len(), 202 - FEDERATION_REPLAY_CLEANUP_BATCH);
    check_indexes(&cache);
}

#[test]
fn cloned_transaction_and_zero_budget_do_not_drop_live_fences() {
    let mut cache = ReplayCacheV1::with_limits(8, 4).expect("cache");
    admit(&mut cache, "peer", 0, 20, 10);
    let mut staged = cache.clone();
    assert_eq!(staged.purge_expired_bounded(20, 0).expect("zero budget"), 0);
    assert_eq!(staged.purge_expired_bounded(20, 1).expect("one record"), 1);
    assert_eq!(cache.len(), 1);
    assert_eq!(cache.last_observed_unix_ms(), 10);
    assert!(matches!(
        staged.purge_expired_bounded(19, 1),
        Err(ReplayError::ClockRegression)
    ));
    check_indexes(&cache);
    check_indexes(&staged);
}

#[test]
fn architecture_capacity_keeps_all_unexpired_nonces() {
    let mut cache = ReplayCacheV1::with_limits(
        MAX_FEDERATION_REPLAY_ENTRIES,
        MAX_FEDERATION_REPLAY_ENTRIES_PER_CREDENTIAL,
    )
    .expect("architecture limits");
    for peer in 0..16 {
        for slot in 0..1_024 {
            admit(&mut cache, &format!("peer-{peer}"), slot, 100, 10);
        }
    }
    assert_eq!(cache.len(), MAX_FEDERATION_REPLAY_ENTRIES);
    let nonce = [9; 32];
    assert!(matches!(
        cache.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("extra"),
                receiver_peer_id: &id("local"),
                key_id: &id("key"),
                generation: 1,
                nonce: &nonce,
            },
            100,
            10
        ),
        Err(ReplayError::CapacityExhausted)
    ));
    assert_eq!(
        cache
            .purge_expired_bounded(99, usize::MAX)
            .expect("no expired records"),
        0
    );
    assert_eq!(cache.len(), MAX_FEDERATION_REPLAY_ENTRIES);
    check_indexes(&cache);
}
