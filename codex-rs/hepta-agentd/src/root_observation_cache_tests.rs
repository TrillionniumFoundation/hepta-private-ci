use super::*;
use crate::root_writer_proof::tests::fixture;
use crate::root_writer_proof::tests::observation;
use pretty_assertions::assert_eq;
const START: u64 = 1_000_000_000;
impl RootObservationCache {
    fn accept_at(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
        now: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        self.accept_with_clock(observation, started, ended, || Ok(now))
    }
    fn current_at(
        &self,
        now: u64,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), ObservationReadError> {
        self.current_with_clock(|| Ok(now))
    }
}
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

#[test]
fn both_clock_samples_are_serialized_with_retained_state() {
    let cache = cache();
    let sample = |now| {
        // Checking the actual held lock makes this deterministic: moving either
        // clock sample before lock acquisition fails, without scheduler timing.
        assert!(matches!(
            cache.retained.try_lock(),
            Err(TryLockError::WouldBlock)
        ));
        Ok(now)
    };
    cache
        .accept_with_clock(value(0), START, START, || sample(START))
        .unwrap();
    assert_eq!(
        cache.current_with_clock(|| sample(START + 1)).unwrap().1,
        2_001
    );
    cache
        .accept_with_clock(value(100), START + 100_000_000, START + 100_000_000, || {
            sample(START + 100_000_001)
        })
        .unwrap();
    assert_eq!(
        cache
            .current_with_clock(|| sample(START + 100_000_002))
            .unwrap()
            .1,
        2_101
    );
}

#[test]
fn contention_and_update_barrier_never_sample_or_supply_authority() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let never_sample = || -> Result<u64, AgentdRootAuthorityError> {
        panic!("unavailable readers must not sample before acquiring the lock")
    };
    let held = cache.retained.lock().unwrap();
    assert_eq!(
        cache.current_with_clock(never_sample).unwrap_err(),
        ObservationReadError::Busy
    );
    assert!(!cache.fenced.load(Ordering::Acquire));
    drop(held);
    cache.begin_update();
    assert_eq!(
        cache.current_with_clock(never_sample).unwrap_err(),
        ObservationReadError::Updating
    );
    cache.end_update();
    assert_eq!(cache.current_at(START + 1).unwrap().1, 2_001);
    cache.fence();
    let _held = cache.retained.lock().unwrap();
    assert_eq!(
        cache.current_with_clock(never_sample).unwrap_err(),
        ObservationReadError::Unavailable
    );
}

#[test]
fn actual_backward_clock_and_clock_failure_remain_permanently_fenced() {
    for acceptance in [false, true] {
        let cache = cache();
        cache.accept_at(value(0), START, START, START).unwrap();
        cache.current_at(START + 100).unwrap();
        if acceptance {
            assert!(cache.accept_at(value(0), START, START, START + 99).is_err());
        } else {
            assert_eq!(
                cache.current_at(START + 99).unwrap_err(),
                ObservationReadError::Unavailable
            );
        }
        assert!(cache.current_at(START + 101).is_err());
        assert!(
            cache
                .accept_at(value(0), START, START, START + 101)
                .is_err()
        );
    }
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    assert_eq!(
        cache
            .current_with_clock(|| Err(AgentdRootAuthorityError::Unavailable))
            .unwrap_err(),
        ObservationReadError::Unavailable
    );
    assert!(cache.current_at(START + 1).is_err());
}

#[test]
fn poisoned_cache_is_not_classified_as_harmless_contention() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let poisoned = std::panic::catch_unwind(|| {
        let _held = cache.retained.lock().unwrap();
        panic!("controlled cache lock poison");
    });
    assert!(poisoned.is_err());
    assert_eq!(
        cache.current_at(START + 1).unwrap_err(),
        ObservationReadError::Unavailable
    );
    assert!(cache.fenced.load(Ordering::Acquire));
}

#[test]
fn stale_sample_preserves_exact_first_failure_through_cleanup_and_reaccept() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    assert_eq!(cache.current_at(START + MAX_AGE_NS).unwrap().1, 2_500);
    let now = START + MAX_AGE_NS + 1;
    assert_eq!(
        cache.current_at(now).unwrap_err(),
        ObservationReadError::Unavailable
    );
    let expected = ObservationFailure {
        stage: "cache_current_age_or_rollback",
        now_ns: Some(now),
        previous_started_ns: Some(START),
        previous_checked_ns: Some(START + MAX_AGE_NS),
        ceiling_unix_ms: Some(3_000),
        anchor_boottime_ns: Some(START),
        anchor_unix_ms: Some(2_000),
        observed_unix_ms: Some(2_000),
        ..Default::default()
    };
    assert_eq!(cache.diagnostics.first(), Some(expected));
    cache.fence_at(ObservationFailure {
        stage: "session_drop",
        ..Default::default()
    });
    assert!(cache.accept_at(value(501), now, now, now).is_err());
    assert_eq!(cache.diagnostics.first(), Some(expected));
}

#[test]
fn new_sample_cannot_hide_expired_previous_sample_and_reports_both_times() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let now = START + 501_000_000;
    assert!(cache.accept_at(value(501), now, now, now).is_err());
    assert_eq!(
        cache.diagnostics.first(),
        Some(ObservationFailure {
            stage: "cache_accept_previous",
            now_ns: Some(now),
            started_ns: Some(now),
            ended_ns: Some(now),
            previous_started_ns: Some(START),
            previous_checked_ns: Some(START),
            projected_unix_ms: Some(2_501),
            ceiling_unix_ms: Some(3_501),
            anchor_boottime_ns: Some(now),
            anchor_unix_ms: Some(2_501),
            observed_unix_ms: Some(2_501),
            ..Default::default()
        })
    );
    assert!(cache.current_at(now).is_err());
}

#[test]
fn busy_and_updating_samples_never_claim_a_first_fatal_failure() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let held = cache.retained.lock().unwrap();
    assert_eq!(
        cache.current_at(START).unwrap_err(),
        ObservationReadError::Busy
    );
    assert_eq!(cache.diagnostics.first(), None);
    drop(held);
    cache.begin_update();
    assert_eq!(
        cache.current_at(START).unwrap_err(),
        ObservationReadError::Updating
    );
    assert_eq!(cache.diagnostics.first(), None);
    cache.end_update();
    assert!(cache.current_at(START).is_ok());
}
