//! Controlled protected-store and clock endpoints. These ordinary unit cases
//! exercise the real observation algorithm; they do not claim root/fsync or
//! native runtime qualification. The original root-only slow-I/O suite remains.
use super::*;
use pretty_assertions::assert_eq;
use std::collections::VecDeque;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

const OWNER: &str = "controlled-observation-clock";
const MINIMUM_NS: u64 = 500_000_000;

struct Store {
    record: Mutex<ClockRecord>,
    loads: AtomicUsize,
    writes: AtomicUsize,
    load_error: Mutex<Option<AuthorityTrustError>>,
    write_error: Mutex<Option<AuthorityTrustError>>,
    load_delay_ns: AtomicU64,
    cas_delay_ns: AtomicU64,
}
impl AuthorityFrontierStore<ClockRecord> for Store {
    fn load(&self, owner: &str) -> Result<ClockRecord, AuthorityTrustError> {
        assert_eq!(owner, OWNER);
        self.loads.fetch_add(1, Ordering::SeqCst);
        if let Some(error) = self.load_error.lock().unwrap().take() {
            return Err(error);
        }
        let record = self.record.lock().unwrap().clone();
        std::thread::sleep(Duration::from_nanos(
            self.load_delay_ns.load(Ordering::SeqCst),
        ));
        Ok(record)
    }
    fn compare_and_set(
        &self,
        owner: &str,
        expected: &ClockRecord,
        next: &ClockRecord,
    ) -> Result<(), AuthorityTrustError> {
        assert_eq!(owner, OWNER);
        self.writes.fetch_add(1, Ordering::SeqCst);
        if let Some(error) = self.write_error.lock().unwrap().take() {
            return Err(error);
        }
        let mut record = self.record.lock().unwrap();
        if *record != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *record = next.clone();
        drop(record);
        std::thread::sleep(Duration::from_nanos(
            self.cas_delay_ns.load(Ordering::SeqCst),
        ));
        Ok(())
    }
}
fn record() -> ClockRecord {
    ClockRecord {
        boot_id: "controlled-same-boot".into(),
        boottime_ns: 10_000_000,
        unix_ns: 10_000_000_000,
        wall_ns: 10_000_000_000,
        ceiling_ns: 11_000_000_000,
    }
}
fn fixture(initial: ClockRecord) -> (HostAuthorityClock, Arc<Store>) {
    let store = Arc::new(Store {
        record: Mutex::new(initial),
        loads: AtomicUsize::new(0),
        writes: AtomicUsize::new(0),
        load_error: Mutex::new(None),
        write_error: Mutex::new(None),
        load_delay_ns: AtomicU64::new(0),
        cas_delay_ns: AtomicU64::new(0),
    });
    let clock = HostAuthorityClock {
        store: store.clone(),
        owner_id: OWNER.into(),
        serial: Mutex::new(()),
    };
    (clock, store)
}
fn sample_at(record: &ClockRecord, elapsed: u64) -> ClockSample {
    ClockSample {
        boot_id: record.boot_id.clone(),
        before_ns: record.boottime_ns + elapsed,
        after_ns: record.boottime_ns + elapsed,
        realtime_ns: record.unix_ns + elapsed,
    }
}
fn observe(
    clock: &HostAuthorityClock,
    minimum_ns: u64,
    samples: Vec<Result<ClockSample, AuthorityTrustError>>,
) -> Result<HostAuthorityClockObservation, AuthorityTrustError> {
    let mut samples: VecDeque<_> = samples.into();
    let result = clock.observe_projection_with_clock(minimum_ns, || {
        samples.pop_front().expect("unexpected extra clock read")
    });
    assert!(samples.is_empty(), "unused expected clock read");
    result
}

#[test]
fn repeated_valid_windows_reload_the_record_and_publish_its_actual_post_io_time_without_cas() {
    let initial = record();
    let (clock, store) = fixture(initial.clone());
    for elapsed in [100_000_000, 300_000_000, 500_000_000] {
        let expected = observe_after_io(&initial, sample_at(&initial, elapsed)).unwrap();
        assert_eq!(
            observe(&clock, MINIMUM_NS, vec![Ok(sample_at(&initial, elapsed))]),
            Ok(expected)
        );
    }
    assert_eq!(store.loads.load(Ordering::SeqCst), 3);
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
    assert_eq!(*store.record.lock().unwrap(), initial);
}

#[test]
fn exact_remaining_window_boundaries_choose_only_one_original_renewal_when_required() {
    for remaining in [0, 499_999_999, 500_000_000, 500_000_001] {
        let initial = record();
        let elapsed = HORIZON_NS - remaining;
        let (clock, store) = fixture(initial.clone());
        let mut stamps = vec![Ok(sample_at(&initial, elapsed))];
        if remaining < MINIMUM_NS {
            stamps.extend([
                Ok(sample_at(&initial, elapsed + 1)),
                Ok(sample_at(&initial, elapsed + 2)),
            ]);
        }
        let observed = observe(&clock, MINIMUM_NS, stamps).unwrap();
        let durable = store.record.lock().unwrap().clone();
        let final_elapsed = if remaining < MINIMUM_NS {
            elapsed + 2
        } else {
            elapsed
        };
        assert_eq!(
            observed,
            observe_after_io(&durable, sample_at(&initial, final_elapsed)).unwrap()
        );
        assert_eq!(store.loads.load(Ordering::SeqCst), 1);
        assert_eq!(
            store.writes.load(Ordering::SeqCst),
            usize::from(remaining < MINIMUM_NS)
        );
    }
}

#[test]
fn zero_minimum_retains_actual_floor_time_in_the_fractional_ceiling_tail() {
    let mut initial = record();
    initial.unix_ns += 1;
    initial.ceiling_ns += 1;
    let (clock, store) = fixture(initial.clone());
    assert_eq!(
        observe(
            &clock,
            /*minimum_ns*/ 0,
            vec![Ok(sample_at(&initial, HORIZON_NS))]
        ),
        observe_after_io(&initial, sample_at(&initial, HORIZON_NS))
    );
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
}

#[test]
fn submillisecond_ceiling_phase_cannot_overstate_the_receivers_projectable_window() {
    for (remaining, renew) in [(500_000_000, true), (500_000_001, false)] {
        let mut initial = record();
        initial.unix_ns += 1;
        initial.ceiling_ns += 1;
        let elapsed = HORIZON_NS - remaining;
        let (clock, store) = fixture(initial.clone());
        let mut stamps = vec![Ok(sample_at(&initial, elapsed))];
        if renew {
            stamps.extend([
                Ok(sample_at(&initial, elapsed + 1)),
                Ok(sample_at(&initial, elapsed + 2)),
            ]);
        }
        let observed = observe(&clock, MINIMUM_NS, stamps).unwrap();
        assert_eq!(store.writes.load(Ordering::SeqCst), usize::from(renew));
        let last = initial.boottime_ns + elapsed + if renew { 2 } else { 0 };
        let projectable_end = observed.projection.anchor_boottime_ns
            + (observed.projection.ceiling_unix_ms - observed.projection.anchor_unix_ms)
                * 1_000_000;
        assert!(projectable_end - last >= MINIMUM_NS);
    }
}

#[test]
fn expired_during_load_renews_once_and_does_not_return_the_pre_load_timestamp() {
    let initial = record();
    let (clock, store) = fixture(initial.clone());
    let elapsed = HORIZON_NS + 1;
    let result = observe(
        &clock,
        MINIMUM_NS,
        vec![
            Ok(sample_at(&initial, elapsed)),
            Ok(sample_at(&initial, elapsed + 1)),
            Ok(sample_at(&initial, elapsed + 2)),
        ],
    )
    .unwrap();
    assert!(result.observed_unix_ms * 1_000_000 >= initial.ceiling_ns);
    assert_eq!(store.writes.load(Ordering::SeqCst), 1);
}

#[test]
fn slow_cas_consuming_the_required_horizon_is_refused_without_a_second_renewal() {
    for cas_elapsed in [500_000_000, 500_000_001, HORIZON_NS + 1] {
        let initial = record();
        let (clock, store) = fixture(initial.clone());
        let begin = HORIZON_NS;
        let result = observe(
            &clock,
            MINIMUM_NS,
            vec![
                Ok(sample_at(&initial, begin)),
                Ok(sample_at(&initial, begin)),
                Ok(sample_at(&initial, begin + cas_elapsed)),
            ],
        );
        if cas_elapsed == 500_000_000 {
            assert!(result.is_ok());
        } else {
            assert_eq!(result, Err(AuthorityTrustError::Unavailable));
        }
        assert_eq!(store.writes.load(Ordering::SeqCst), 1);
        assert_eq!(
            *store.record.lock().unwrap(),
            project(&initial, sample_at(&initial, begin)).unwrap()
        );
    }
}

#[test]
fn corrupt_rollback_and_illegal_boot_samples_are_not_republished() {
    let mut corrupt = record();
    corrupt.ceiling_ns += 1;
    let (clock, store) = fixture(corrupt.clone());
    assert_eq!(
        observe(&clock, MINIMUM_NS, vec![Ok(sample_at(&corrupt, 1))]),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
    let initial = record();
    let mut old_wall = sample_at(&initial, 1);
    old_wall.realtime_ns = initial.wall_ns - 1;
    let mut backward_boot = sample_at(&initial, 1);
    backward_boot.before_ns = initial.boottime_ns - 1;
    let mut uncertain_span = sample_at(&initial, 1);
    uncertain_span.after_ns += MAX_SAMPLE_SPAN_NS + 1;
    for bad in [old_wall, backward_boot, uncertain_span] {
        let (clock, store) = fixture(initial.clone());
        assert_eq!(
            observe(&clock, MINIMUM_NS, vec![Ok(bad)]),
            Err(AuthorityTrustError::Invalid)
        );
        assert_eq!(store.writes.load(Ordering::SeqCst), 0);
    }
    let (clock, store) = fixture(initial.clone());
    let reboot = || ClockSample {
        boot_id: "different-boot".into(),
        before_ns: 1,
        after_ns: 2,
        realtime_ns: initial.ceiling_ns - 1,
    };
    assert_eq!(
        observe(&clock, MINIMUM_NS, vec![Ok(reboot()), Ok(reboot())]),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
}

#[test]
fn load_sample_and_cas_errors_never_trigger_an_error_retry() {
    for error in [
        AuthorityTrustError::Unavailable,
        AuthorityTrustError::Invalid,
        AuthorityTrustError::Conflict,
    ] {
        let initial = record();
        let (clock, store) = fixture(initial.clone());
        *store.load_error.lock().unwrap() = Some(error);
        assert_eq!(observe(&clock, MINIMUM_NS, vec![]), Err(error));
        assert_eq!(store.writes.load(Ordering::SeqCst), 0);
        assert_eq!(observe(&clock, MINIMUM_NS, vec![Err(error)]), Err(error));
        assert_eq!(store.writes.load(Ordering::SeqCst), 0);
        *store.write_error.lock().unwrap() = Some(error);
        assert_eq!(
            observe(
                &clock,
                MINIMUM_NS,
                vec![
                    Ok(sample_at(&initial, HORIZON_NS)),
                    Ok(sample_at(&initial, HORIZON_NS))
                ]
            ),
            Err(error)
        );
        assert_eq!(store.writes.load(Ordering::SeqCst), 1);
        assert_eq!(*store.record.lock().unwrap(), initial);
    }
}

#[test]
fn failed_post_cas_sample_does_not_reuse_old_time_or_repeat_the_cas() {
    let initial = record();
    let (clock, store) = fixture(initial.clone());
    assert_eq!(
        observe(
            &clock,
            MINIMUM_NS,
            vec![
                Ok(sample_at(&initial, HORIZON_NS)),
                Ok(sample_at(&initial, HORIZON_NS)),
                Err(AuthorityTrustError::Unavailable)
            ]
        ),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(store.writes.load(Ordering::SeqCst), 1);
}

#[test]
fn impossible_minimum_is_rejected_before_any_store_or_clock_read() {
    let (clock, store) = fixture(record());
    assert_eq!(
        observe(&clock, HORIZON_NS + 1, vec![]),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(
        clock.observe_projection(Duration::MAX),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(store.loads.load(Ordering::SeqCst), 0);
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
}

#[test]
fn forced_refresh_keeps_its_real_os_sample_and_always_performs_one_cas() {
    let initial = initial_record(sample_os_clock().unwrap()).unwrap();
    let (clock, store) = fixture(initial);
    for calls in 1..=2 {
        let observation = clock.refresh_projection().unwrap();
        assert!(observation.observed_unix_ms <= observation.projection.ceiling_unix_ms);
        assert_eq!(store.writes.load(Ordering::SeqCst), calls);
        let retained = store.record.lock().unwrap().clone();
        assert_eq!(observation.projection.boot_id, retained.boot_id);
        assert_eq!(
            observation.projection.anchor_unix_ms,
            retained.unix_ns / 1_000_000
        );
    }
}

fn past_real_record(age_ns: u64) -> ClockRecord {
    let mut record = initial_record(sample_os_clock().unwrap()).unwrap();
    record.boottime_ns = record.boottime_ns.checked_sub(age_ns).unwrap();
    record.unix_ns = record.unix_ns.checked_sub(age_ns).unwrap();
    record.wall_ns = record.wall_ns.checked_sub(age_ns).unwrap();
    record.ceiling_ns = record.ceiling_ns.checked_sub(age_ns).unwrap();
    record
}

#[test]
fn current_time_reuses_a_valid_short_window_while_explicit_refresh_still_persists() {
    let initial = past_real_record(/*age_ns*/ 600_000_000);
    let (clock, store) = fixture(initial.clone());
    let now = clock.now_unix_ms().unwrap();
    assert_eq!(store.writes.load(Ordering::SeqCst), 0);
    assert_eq!(*store.record.lock().unwrap(), initial);
    assert!(now <= initial.ceiling_ns / 1_000_000);
    assert!(initial.ceiling_ns / 1_000_000 - now < 500);

    let refreshed = clock.refresh_projection().unwrap();
    assert!(refreshed.observed_unix_ms >= now);
    assert_eq!(store.loads.load(Ordering::SeqCst), 2);
    assert_eq!(store.writes.load(Ordering::SeqCst), 1);
    assert!(store.record.lock().unwrap().ceiling_ns > initial.ceiling_ns);
}

#[test]
fn current_time_samples_after_slow_load_and_renews_once_instead_of_returning_old_time() {
    let initial = past_real_record(/*age_ns*/ 0);
    let (clock, store) = fixture(initial.clone());
    store.load_delay_ns.store(1_100_000_000, Ordering::SeqCst);
    let now = clock.now_unix_ms().unwrap();
    assert!(now * 1_000_000 > initial.ceiling_ns);
    assert_eq!(store.loads.load(Ordering::SeqCst), 1);
    assert_eq!(store.writes.load(Ordering::SeqCst), 1);
    let retained = store.record.lock().unwrap().clone();
    assert!(now <= retained.ceiling_ns / 1_000_000);
}

#[test]
fn current_time_and_forced_refresh_reject_slow_cas_without_a_second_renewal() {
    for read in [
        HostAuthorityClock::now_unix_ms,
        |clock: &HostAuthorityClock| {
            clock
                .refresh_projection()
                .map(|observation| observation.observed_unix_ms)
        },
    ] {
        let initial = past_real_record(/*age_ns*/ 1_100_000_000);
        let (clock, store) = fixture(initial);
        store.cas_delay_ns.store(1_100_000_000, Ordering::SeqCst);
        assert_eq!(read(&clock), Err(AuthorityTrustError::Unavailable));
        assert_eq!(store.loads.load(Ordering::SeqCst), 1);
        assert_eq!(store.writes.load(Ordering::SeqCst), 1);
    }
}

#[test]
fn current_time_and_forced_refresh_preserve_rollback_and_store_error_refusals() {
    for read in [
        HostAuthorityClock::now_unix_ms,
        |clock: &HostAuthorityClock| {
            clock
                .refresh_projection()
                .map(|observation| observation.observed_unix_ms)
        },
    ] {
        let mut future = past_real_record(/*age_ns*/ 0);
        future.unix_ns += 3_600_000_000_000;
        future.wall_ns += 3_600_000_000_000;
        future.ceiling_ns += 3_600_000_000_000;
        let (clock, store) = fixture(future);
        assert_eq!(read(&clock), Err(AuthorityTrustError::Invalid));
        assert_eq!(store.writes.load(Ordering::SeqCst), 0);
        for error in [
            AuthorityTrustError::Invalid,
            AuthorityTrustError::Unavailable,
            AuthorityTrustError::Conflict,
        ] {
            let (clock, store) = fixture(past_real_record(/*age_ns*/ 0));
            *store.load_error.lock().unwrap() = Some(error);
            assert_eq!(read(&clock), Err(error));
            assert_eq!(store.loads.load(Ordering::SeqCst), 1);
            assert_eq!(store.writes.load(Ordering::SeqCst), 0);

            let initial = past_real_record(/*age_ns*/ 1_100_000_000);
            let (clock, store) = fixture(initial.clone());
            *store.write_error.lock().unwrap() = Some(error);
            assert_eq!(read(&clock), Err(error));
            assert_eq!(store.loads.load(Ordering::SeqCst), 1);
            assert_eq!(store.writes.load(Ordering::SeqCst), 1);
            assert_eq!(*store.record.lock().unwrap(), initial);
        }
    }
}

#[test]
fn legal_new_boot_uses_one_original_durable_renewal_before_publishing_that_boot() {
    let initial = record();
    let (clock, store) = fixture(initial.clone());
    let stamp = |elapsed| ClockSample {
        boot_id: "legal-new-boot".into(),
        before_ns: 1_000_000 + elapsed,
        after_ns: 1_000_000 + elapsed,
        realtime_ns: initial.ceiling_ns + elapsed,
    };
    let observed = observe(
        &clock,
        MINIMUM_NS,
        vec![Ok(stamp(0)), Ok(stamp(1)), Ok(stamp(2))],
    )
    .unwrap();
    assert_eq!(observed.projection.boot_id, "legal-new-boot");
    assert_eq!(store.writes.load(Ordering::SeqCst), 1);
    assert_eq!(
        *store.record.lock().unwrap(),
        project(&initial, stamp(1)).unwrap()
    );
}
