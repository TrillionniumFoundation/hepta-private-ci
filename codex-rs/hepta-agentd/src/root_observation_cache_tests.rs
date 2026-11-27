use super::*;
use crate::root_writer_proof::tests::fixture;
use crate::root_writer_proof::tests::observation;
use pretty_assertions::assert_eq;
use std::sync::Barrier;

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
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        self.current_with_clock(|| Ok(now))
    }
}

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

#[test]
fn refresh_and_parallel_readers_do_not_contend_on_retained_state() {
    let cache = cache();
    let original = value(0);
    cache
        .accept_at(original.clone(), START, START, START)
        .unwrap();
    let refreshing = Barrier::new(2);
    let publish = Barrier::new(2);
    let readers = Barrier::new(4);
    let mut next = original.clone();
    next.writer.store_revision += 1;
    std::thread::scope(|scope| {
        let refresh = scope.spawn(|| {
            cache.accept_with_clock(next.clone(), START, START, || {
                refreshing.wait();
                publish.wait();
                Ok(START)
            })
        });
        refreshing.wait();
        let reads: Vec<_> = (0..4)
            .map(|_| {
                scope.spawn(|| {
                    cache.current_with_clock(|| {
                        readers.wait();
                        Ok(START + 1)
                    })
                })
            })
            .collect();
        let results: Vec<_> = reads.into_iter().map(|read| read.join().unwrap()).collect();
        publish.wait();
        refresh.join().unwrap().unwrap();
        for result in results {
            let (observed, projected) = result.unwrap();
            assert_eq!(*observed, original);
            assert_eq!(projected, 2_001);
        }
    });
    assert_eq!(*cache.current_at(START + 1).unwrap().0, next);
    // Refresh cannot replace the newer watermark established by a reader.
    assert!(cache.current_at(START).is_err());
}

#[test]
fn overlapping_clock_samples_keep_the_maximum_without_false_rollback() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let sampled = Barrier::new(2);
    let finish = Barrier::new(2);
    std::thread::scope(|scope| {
        let earlier = scope.spawn(|| {
            cache.current_with_clock(|| {
                sampled.wait();
                finish.wait();
                Ok(START + 1)
            })
        });
        sampled.wait();
        let later = cache.current_at(START + 2);
        finish.wait();
        assert_eq!(earlier.join().unwrap().unwrap().1, 2_001);
        assert_eq!(later.unwrap().1, 2_001);
    });
    // A subsequent, non-overlapping rollback still permanently fences.
    assert!(cache.current_at(START + 1).is_err());
    assert!(cache.current_at(START + 2).is_err());
    assert!(cache.accept_at(value(0), START, START, START + 2).is_err());
}

#[test]
fn a_complete_revocation_update_during_a_read_cannot_publish_the_old_head() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let mut next = value(100);
    next.revocations.revision += 1;
    next.revocations.revoked_grant_ids.insert("revoked".into());
    let now = START + 100_000_000;
    let crossing = cache.current_with_clock(|| {
        cache.begin_update();
        cache.accept_at(next.clone(), now, now, now).unwrap();
        cache.end_update();
        Ok(now)
    });
    assert!(crossing.is_err());
    assert_eq!(*cache.current_at(now).unwrap().0, next);
}
