//! Cache concurrency regressions. Synthetic clocks control ordering only;
//! the last test uses actual BOOTTIME. No retry or product deadline is changed.
use super::START;
use super::cache;
use super::value;
use crate::root_observation_cache::boottime_ns;
use pretty_assertions::assert_eq;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;
use std::sync::Barrier;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

const WATCHDOG: Duration = Duration::from_secs(2);

#[test]
fn an_earlier_sample_may_finish_after_a_later_reader_without_false_rollback() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let later = START + 1_000_001;
    let (older, newer) = std::thread::scope(|scope| {
        let cache = &cache;
        let old = scope.spawn(move || {
            cache.current_with_clock(|| {
                let sampled = START + 1;
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WATCHDOG).unwrap();
                Ok(sampled)
            })
        });
        entered_rx.recv_timeout(WATCHDOG).unwrap();
        let newer = cache.current_at(later);
        release_tx.send(()).unwrap();
        (old.join().unwrap(), newer)
    });
    assert_eq!(older.unwrap().1, 2_001);
    assert_eq!(newer.unwrap().1, 2_002);
    assert_eq!(cache.high_water.load(Ordering::Acquire), later);
    // A subsequent completed call really goes backwards by one nanosecond.
    assert!(cache.current_at(later - 1).is_err());
    assert!(cache.current_at(later + 1).is_err());
}

#[test]
fn an_unchanged_head_publisher_does_not_block_an_authority_reader() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let (published, observed) = std::thread::scope(|scope| {
        let cache = &cache;
        let publisher = scope.spawn(move || {
            cache.accept_with_clock(value(0), START, START, || {
                // Hold the publisher after its sample, while a reader advances.
                let sampled = START + 10;
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WATCHDOG).unwrap();
                Ok(sampled)
            })
        });
        entered_rx.recv_timeout(WATCHDOG).unwrap();
        let observed = cache.current_at(START + 20);
        release_tx.send(()).unwrap();
        (publisher.join().unwrap(), observed)
    });
    published.unwrap();
    observed.unwrap();
    assert_eq!(cache.high_water.load(Ordering::Acquire), START + 20);
    assert!(cache.current_at(START + 21).is_ok());
}

#[test]
fn a_reader_of_the_previous_snapshot_keeps_the_global_clock_high_water() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let (observed, published) = std::thread::scope(|scope| {
        let cache = &cache;
        let reader = scope.spawn(move || {
            cache.current_with_clock(|| {
                // Snapshot and baseline were acquired before publication.
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WATCHDOG).unwrap();
                Ok(START + 30)
            })
        });
        entered_rx.recv_timeout(WATCHDOG).unwrap();
        let published = cache.accept_at(value(0), START, START, START + 20);
        release_tx.send(()).unwrap();
        (reader.join().unwrap(), published)
    });
    observed.unwrap();
    published.unwrap();
    assert_eq!(cache.high_water.load(Ordering::Acquire), START + 30);
    assert!(cache.current_at(START + 29).is_err());
    assert!(cache.current_at(START + 31).is_err());
}

#[test]
fn a_whole_revocation_barrier_refuses_the_old_read_without_poisoning_the_new_head() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let mut next = value(100);
    next.revocations.revision += 1;
    next.revocations.revoked_grant_ids.insert("revoked".into());
    let updated = START + 100_000_000;
    let (old_read, published) = std::thread::scope(|scope| {
        let cache = &cache;
        let reader = scope.spawn(move || {
            cache.current_with_clock(|| {
                let sampled = START + 1;
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WATCHDOG).unwrap();
                Ok(sampled)
            })
        });
        entered_rx.recv_timeout(WATCHDOG).unwrap();
        cache.begin_update();
        let published = cache.accept_at(next.clone(), updated, updated, updated);
        cache.end_update();
        release_tx.send(()).unwrap();
        (reader.join().unwrap(), published)
    });
    published.unwrap();
    assert!(old_read.is_err());
    assert_eq!(*cache.current_at(updated).unwrap().0, next);
    assert_eq!(cache.update_generation.load(Ordering::Acquire), 2);
}

#[test]
fn publisher_panic_poisons_both_current_entry_and_current_exit() {
    for overlap in [false, true] {
        let cache = cache();
        cache.accept_at(value(0), START, START, START).unwrap();
        let panic_while_publishing = || {
            assert!(
                catch_unwind(AssertUnwindSafe(|| {
                    let _ = cache.accept_with_clock(value(0), START, START, || {
                        panic!("test publisher panic while holding its real mutex")
                    });
                }))
                .is_err()
            );
        };
        if overlap {
            assert!(
                cache
                    .current_with_clock(|| {
                        panic_while_publishing();
                        Ok(START + 1)
                    })
                    .is_err()
            );
        } else {
            panic_while_publishing();
            assert!(cache.current_at(START + 1).is_err());
        }
        assert!(cache.writer.is_poisoned());
        assert!(!cache.revocations_match(&value(0).revocations));
        assert!(cache.accept_at(value(0), START, START, START + 2).is_err());
        assert!(cache.current_at(START + 2).is_err());
    }
}

#[test]
fn a_revocation_generation_overflow_is_sticky_and_cannot_reset() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    cache
        .update_generation
        .store(u64::MAX - 1, Ordering::Release);
    cache.begin_update();
    assert_eq!(cache.update_generation.load(Ordering::Acquire), u64::MAX);
    cache.end_update();
    assert!(cache.current_at(START + 1).is_err());
    cache.end_update();
    assert_eq!(cache.update_generation.load(Ordering::Acquire), u64::MAX);
    assert!(cache.accept_at(value(0), START, START, START + 1).is_err());
}

#[test]
fn a_fence_during_a_publisher_clock_sample_prevents_publication() {
    let cache = cache();
    let original = value(0);
    cache
        .accept_at(original.clone(), START, START, START)
        .unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let published = std::thread::scope(|scope| {
        let cache = &cache;
        let publisher = scope.spawn(move || {
            cache.accept_with_clock(value(100), START + 100_000_000, START + 100_000_000, || {
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WATCHDOG).unwrap();
                Ok(START + 100_000_000)
            })
        });
        entered_rx.recv_timeout(WATCHDOG).unwrap();
        cache.fence();
        release_tx.send(()).unwrap();
        publisher.join().unwrap()
    });
    assert!(published.is_err());
    assert_eq!(*cache.retained.load_full().unwrap().observation, original);
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

#[test]
fn a_fence_after_current_entry_prevents_returning_the_loaded_snapshot() {
    let cache = cache();
    cache.accept_at(value(0), START, START, START).unwrap();
    let observed = cache.current_with_clock(|| {
        let sampled = START + 1;
        cache.fence();
        Ok(sampled)
    });
    assert!(observed.is_err());
    assert!(cache.current_at(START + 2).is_err());
    assert!(cache.accept_at(value(0), START, START, START + 2).is_err());
}

#[test]
fn concurrent_authority_readers_use_actual_boottime_without_false_fences() {
    let cache = cache();
    let mut sample = value(0);
    let started = boottime_ns().unwrap();
    sample.clock.anchor_boottime_ns = started;
    cache
        .accept(sample, started, boottime_ns().unwrap())
        .unwrap();
    let ready = Barrier::new(3);
    let results = std::thread::scope(|scope| {
        let first = scope.spawn(|| {
            ready.wait();
            (0..32).try_for_each(|_| cache.current().map(|_| ()))
        });
        let second = scope.spawn(|| {
            ready.wait();
            (0..32).try_for_each(|_| cache.current().map(|_| ()))
        });
        ready.wait();
        (first.join().unwrap(), second.join().unwrap())
    });
    results.0.unwrap();
    results.1.unwrap();
    assert!(cache.current().is_ok());
}
