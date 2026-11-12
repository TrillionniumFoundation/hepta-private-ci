use super::*;
use crate::root_writer_proof::tests::fixture;
use crate::root_writer_proof::tests::observation;
use pretty_assertions::assert_eq;
const START: u64 = 1_000_000_000;
fn value(elapsed_ms: u64) -> HostAuthorityObservationResponseV2 {
    let (_, proof) = fixture();
    let mut sample = observation(&proof);
    sample.clock.anchor_boottime_ns = START + elapsed_ms * 1_000_000;
    sample.clock.anchor_unix_ms = 2_000 + elapsed_ms;
    sample.clock.ceiling_unix_ms = 3_000 + elapsed_ms;
    sample.observed_unix_ms = 2_000 + elapsed_ms;
    sample
}
fn cache() -> RootObservationCache {
    RootObservationCache::new("fixture-boot".into())
}
#[test]
fn request_start_bounds_age_and_ceiling_projection_rounds_conservatively() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    assert_eq!(cache.current_at(START + 1).unwrap().1, 2_001);
    assert_eq!(cache.current_at(START + MAX_AGE_NS).unwrap().1, 2_500);
    assert!(cache.current_at(START + MAX_AGE_NS + 1).is_err());
    assert!(
        cache
            .accept_at(
                value(501),
                START + 501_000_000,
                START + 501_000_000,
                START + 501_000_000
            )
            .is_err()
    );
    let cache = super::tests::cache();
    assert!(
        cache
            .accept_at(
                value(0),
                START,
                START + MAX_AGE_NS + 1,
                START + MAX_AGE_NS + 1
            )
            .is_err()
    );
}
#[test]
fn fresh_unrelated_registry_updates_do_not_fence_fixed_lease() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let mut next = value(100);
    next.writer.store_revision += 10;
    cache
        .accept_at(
            next.clone(),
            START + 100_000_000,
            START + 100_000_000,
            START + 100_000_000,
        )
        .unwrap();
    assert_eq!(*cache.current_at(START + 100_000_000).unwrap().0, next);
    next.writer.authority_lease.binding.payload_sha256 = [9; 32];
    assert!(
        cache
            .accept_at(
                next,
                START + 100_000_000,
                START + 100_000_000,
                START + 100_000_000
            )
            .is_err()
    );
    assert!(cache.current_at(START + 100_000_000).is_err());
}
#[test]
fn rollback_same_revision_equivocation_wrong_boot_and_late_clock_permanently_fence() {
    for case in 0..9 {
        let cache = cache();
        let initial = value(0);
        cache.accept_at(initial, START, START, START).unwrap();
        let mut next = value(100);
        match case {
            0 => next.writer.store_revision -= 1,
            1 => {
                next.revocations.revoked_grant_ids.insert("revoked".into());
            }
            2 => next.clock.boot_id = "other".into(),
            3 => next.clock.anchor_boottime_ns = START + 200_000_000,
            4 => next.clock.ceiling_unix_ms = next.clock.anchor_unix_ms - 1,
            5 => next.observed_unix_ms = 1_999,
            6 => next.clock.anchor_unix_ms = 1_999,
            7 => next.authority_epoch += 1,
            8 => next.writer.local_lease_generation += 1,
            _ => unreachable!(),
        }
        assert!(
            cache
                .accept_at(
                    next,
                    START + 100_000_000,
                    START + 100_000_000,
                    START + 100_000_000
                )
                .is_err(),
            "case {case}"
        );
        assert!(cache.current_at(START + 100_000_000).is_err());
        assert!(
            cache
                .accept_at(
                    value(100),
                    START + 100_000_000,
                    START + 100_000_000,
                    START + 100_000_000
                )
                .is_err()
        );
    }
}
#[test]
fn revocations_only_accumulate_and_update_barrier_does_not_publish_early() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    cache.begin_update();
    let mut next = value(100);
    next.revocations.revision += 1;
    next.revocations.revoked_grant_ids.insert("revoked".into());
    cache
        .accept_at(
            next.clone(),
            START + 100_000_000,
            START + 100_000_000,
            START + 100_000_000,
        )
        .unwrap();
    assert!(cache.current_at(START + 100_000_000).is_err());
    cache.end_update();
    assert_eq!(*cache.current_at(START + 100_000_000).unwrap().0, next);
    next.revocations.revision += 1;
    next.revocations.revoked_grant_ids.clear();
    assert!(
        cache
            .accept_at(
                next,
                START + 100_000_000,
                START + 100_000_000,
                START + 100_000_000
            )
            .is_err()
    );
}

fn actual_sample(origin: u64, observed: u64) -> HostAuthorityObservationResponseV2 {
    let mut sample = value(0);
    sample.clock.anchor_boottime_ns = origin;
    sample.clock.ceiling_unix_ms = 4_000;
    sample.observed_unix_ms = 2_000 + (observed - origin).div_ceil(1_000_000);
    sample
}

fn actual_cache() -> (Arc<RootObservationCache>, u64) {
    let origin = boottime_ns().unwrap();
    let cache = Arc::new(cache());
    cache.accept(actual_sample(origin, origin), origin, origin).unwrap();
    (cache, origin)
}

fn require_actual_read_wait(cache: &RootObservationCache) {
    let end = std::time::Instant::now() + std::time::Duration::from_secs(2);
    while cache.admission_waits.load(Ordering::Acquire) == 0 {
        assert!(std::time::Instant::now() < end, "the original read never entered contention");
        std::thread::yield_now();
    }
}

#[test]
fn contended_current_samples_after_the_original_guard_without_losing_the_feed() {
    let (cache, _) = actual_cache();
    let mut held = cache.retained.lock().unwrap();
    let reader = Arc::clone(&cache);
    let waiting = std::thread::spawn(move || reader.current());
    require_actual_read_wait(&cache);
    // Advance the real watermark AFTER the reader has already contended.
    // Its production sample must occur after acquiring this same guard.
    let now = boottime_ns().unwrap();
    let earlier = cache.current_locked(
        &mut held,
        now,
        cache.update_generation.load(Ordering::Acquire),
    ).unwrap();
    drop(held);
    let observed = waiting.join().unwrap().unwrap();
    assert_eq!(*observed.0, *earlier.0);
    assert!(observed.1 >= earlier.1);
    assert!(!cache.fenced.load(Ordering::Acquire));
}

#[test]
fn later_accept_cannot_renew_an_already_waiting_reads_original_budget() {
    let (cache, origin) = actual_cache();
    let first_deadline = cache.read_deadline_ns.load(Ordering::Acquire);
    let mut held = cache.retained.lock().unwrap();
    let reader = Arc::clone(&cache);
    let waiting = std::thread::spawn(move || reader.current());
    require_actual_read_wait(&cache);
    // A real newer accepted response has a later deadline, but the waiting
    // call must retain its first deadline. The guard stays held until it fails.
    std::thread::sleep(std::time::Duration::from_millis(200));
    let accepted = boottime_ns().unwrap();
    cache.accept_locked(
        &mut held,
        actual_sample(origin, accepted),
        accepted,
        accepted,
        accepted,
    ).unwrap();
    let second_deadline = cache.read_deadline_ns.load(Ordering::Acquire);
    assert!(second_deadline > first_deadline);
    let result = waiting.join().unwrap();
    assert!(matches!(result, Err(AgentdRootAuthorityError::Unavailable)));
    assert_eq!(
        cache.expired_admission_deadline.load(Ordering::Acquire),
        first_deadline,
    );
    let refused_at = cache.expired_admission_sample.load(Ordering::Acquire);
    assert!(refused_at > first_deadline);
    // OS scheduling may delay the failure past either deadline. The captured
    // expiry above must still be the original deadline, never the newer one.
    // No second current/authority/effect call follows the returned failure.
    assert_eq!(held.as_ref().unwrap().request_started_ns, accepted);
    drop(held);
}

#[test]
fn absent_budget_and_poison_cannot_turn_contention_into_authority() {
    let empty = cache();
    let held = empty.retained.lock().unwrap();
    assert!(matches!(empty.current(), Err(AgentdRootAuthorityError::Unavailable)));
    assert_eq!(empty.admission_waits.load(Ordering::Acquire), 0);
    drop(held);

    let (cache, _) = actual_cache();
    let poison = Arc::clone(&cache);
    assert!(std::thread::spawn(move || {
        let _held = poison.retained.lock().unwrap();
        panic!("poison the actual original retained mutex");
    }).join().is_err());
    assert!(matches!(cache.current(), Err(AgentdRootAuthorityError::Unavailable)));
    assert!(cache.retained.is_poisoned());
}

#[test]
fn waiting_read_refuses_a_real_fence_or_active_consumer_barrier() {
    for fence in [false, true] {
        let (cache, _) = actual_cache();
        let held = cache.retained.lock().unwrap();
        let reader = Arc::clone(&cache);
        let waiting = std::thread::spawn(move || reader.current());
        require_actual_read_wait(&cache);
        if fence {
            cache.fence();
        } else {
            cache.begin_update();
        }
        assert!(matches!(
            waiting.join().unwrap(),
            Err(AgentdRootAuthorityError::Unavailable)
        ));
        drop(held);
        if !fence {
            cache.end_update();
        }
    }
}

#[test]
fn completed_consumer_barrier_and_generation_overflow_reject_old_admission() {
    let (cache, _) = actual_cache();
    let admission = cache.capture_read_admission().unwrap();
    cache.begin_update();
    cache.end_update();
    // Both boolean endpoints would be stable. The actual completed generation
    // still rejects the same earlier admission before it can read evidence.
    assert!(matches!(
        cache.acquire_retained_read(admission),
        Err(AgentdRootAuthorityError::Unavailable)
    ));

    let (cache, _) = actual_cache();
    cache.update_generation.store(u64::MAX - 1, Ordering::Release);
    cache.begin_update();
    cache.end_update();
    assert_eq!(cache.update_generation.load(Ordering::Acquire), u64::MAX);
    assert!(matches!(cache.current(), Err(AgentdRootAuthorityError::Unavailable)));
}

pub(crate) fn component_with_original_retained_lock(
    cache: &RootObservationCache,
    body: impl FnOnce(),
) {
    let _held = cache.retained.lock().unwrap();
    body();
}

pub(crate) fn component_wait_for_original_read_admission(cache: &RootObservationCache) {
    require_actual_read_wait(cache);
}

pub(crate) fn component_last_validated_read(cache: &RootObservationCache) -> u64 {
    cache.retained.lock().unwrap().as_ref().unwrap().last_checked_ns
}
