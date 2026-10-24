//! Original durable-store and actual-time observation-window qualifications.
use super::*;
use pretty_assertions::assert_eq;

fn phased_record() -> ClockRecord {
    ClockRecord {
        boot_id: "same-boot".into(),
        boottime_ns: 10_000_000_000,
        unix_ns: 20_000_999_999,
        wall_ns: 20_000_999_999,
        ceiling_ns: 21_000_999_999,
    }
}

fn sample_at(after_ns: u64) -> ClockSample {
    ClockSample {
        boot_id: "same-boot".into(),
        before_ns: after_ns,
        after_ns,
        realtime_ns: phased_record().wall_ns,
    }
}

#[test]
fn observation_reserve_matches_client_ceil_at_the_exact_nanosecond_boundary() {
    let record = phased_record();
    // The client's projection is 20_000 ms + ceil((boot - 9_999_000_001) / 1ms),
    // with a 21_000 ms ceiling. Exactly 500 ms remain at this BOOTTIME value.
    let last_sample_with_reserve = 10_499_000_001;
    let observation =
        observe_projection_after_io(&record, sample_at(last_sample_with_reserve)).unwrap();
    assert_eq!(observation.projection.anchor_boottime_ns, 9_999_000_001);
    assert_eq!(observation.projection.anchor_unix_ms, 20_000);
    assert_eq!(observation.projection.ceiling_unix_ms, 21_000);
    assert_eq!(observation.observed_unix_ms, 20_500);
    assert_eq!(
        observe_projection_after_io(&record, sample_at(last_sample_with_reserve + 1)),
        Err(AuthorityTrustError::Unavailable),
    );
    // The original clock itself is still valid. A difference of floored
    // milliseconds says 500 here and would incorrectly admit one extra ns.
    let old = observe_after_io(&record, sample_at(last_sample_with_reserve + 1)).unwrap();
    assert_eq!(old.projection.ceiling_unix_ms - old.observed_unix_ms, 500);
}

#[test]
fn observation_reserve_preserves_original_invalid_and_boot_refusals() {
    let record = phased_record();
    let mut rollback = sample_at(record.boottime_ns);
    rollback.realtime_ns = record.wall_ns - 1;
    assert_eq!(
        observe_projection_after_io(&record, rollback),
        Err(AuthorityTrustError::Invalid)
    );
    let mut wide_sample = sample_at(record.boottime_ns + 10_000_001);
    wide_sample.before_ns = record.boottime_ns;
    assert_eq!(
        observe_projection_after_io(&record, wide_sample),
        Err(AuthorityTrustError::Invalid)
    );
    let mut another_boot = sample_at(record.boottime_ns);
    another_boot.boot_id = "another-boot".into();
    assert_eq!(
        observe_projection_after_io(&record, another_boot),
        Err(AuthorityTrustError::Unavailable)
    );
}

fn wait_for_boottime(boottime_ns: u64) {
    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    while sample_os_clock().unwrap().after_ns < boottime_ns {
        assert!(
            std::time::Instant::now() < deadline,
            "actual BOOTTIME failed to reach the controlled boundary"
        );
        std::thread::sleep(Duration::from_millis(2));
    }
}

#[test]
#[ignore = "explicit root-only complete-record reuse and corruption refusal"]
fn root_observation_reuses_a_durable_window_but_reads_the_full_record_each_time() {
    let fixture = Fixture::new();
    let retained = fixture.store.load("slow-clock").unwrap();
    let files: Vec<_> = std::fs::read_dir(fixture._directory.path())
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
        })
        .collect();
    assert_eq!(files.len(), 1);
    let bytes = std::fs::read(&files[0]).unwrap();
    let mut observations = Vec::new();
    for _ in 0..4 {
        observations.push(fixture.clock.observe_current_or_renew().unwrap());
        std::thread::sleep(Duration::from_millis(2));
    }
    assert!(
        observations
            .windows(2)
            .all(|pair| pair[0].observed_unix_ms <= pair[1].observed_unix_ms)
    );
    assert!(
        observations
            .windows(2)
            .all(|pair| pair[0].projection == pair[1].projection)
    );
    assert_eq!(fixture.store.cas_calls.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.store.load("slow-clock").unwrap(), retained);
    assert_eq!(std::fs::read(&files[0]).unwrap(), bytes);
    let corrupt = b"{\"schema\":1,\"owner_id\":\"slow-clock\",\"frontier\":null}";
    std::fs::write(&files[0], corrupt).unwrap();
    assert_eq!(
        fixture.clock.observe_current_or_renew(),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(fixture.store.cas_calls.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&files[0]).unwrap(), corrupt);
}

#[test]
#[ignore = "explicit root-only post-load reserve loss with one real durable renewal"]
fn root_observation_losing_its_reserve_during_load_renews_once() {
    let fixture = Fixture::new();
    let (arrived_tx, arrived_rx) = mpsc::sync_channel(1);
    let (resume_tx, resume_rx) = mpsc::channel();
    *fixture.store.load_pause.lock().unwrap() = Some((arrived_tx, resume_rx));
    let clock = fixture.clock.clone();
    let worker = std::thread::spawn(move || clock.observe_current_or_renew());
    let previous = arrived_rx.recv_timeout(Duration::from_secs(15)).unwrap();
    wait_for_boottime(previous.boottime_ns + 600_000_000);
    // It is still an original valid clock reading, but not a window capable
    // of supporting the client's complete 500 ms cache age.
    assert!(observe_after_io(&previous, sample_os_clock().unwrap()).is_ok());
    resume_tx.send(()).unwrap();
    let observed = worker.join().unwrap().unwrap();
    assert_eq!(fixture.store.cas_calls.load(Ordering::SeqCst), 1);
    let renewed = fixture.store.load("slow-clock").unwrap();
    assert_ne!(renewed, previous);
    assert!(observed.observed_unix_ms * 1_000_000 >= previous.unix_ns + 500_000_000);
    assert!(observed.observed_unix_ms <= observed.projection.ceiling_unix_ms);
}

#[test]
#[ignore = "explicit root-only late actual publication acknowledgement without retry"]
fn root_observation_renewal_losing_its_reserve_is_refused_without_another_cas() {
    let fixture = Fixture::new();
    let old = fixture.store.load("slow-clock").unwrap();
    wait_for_boottime(old.boottime_ns + HORIZON_NS + 10_000_000);
    let (arrived, resume) = fixture.pause();
    let clock = fixture.clock.clone();
    let worker = std::thread::spawn(move || clock.observe_current_or_renew());
    let durable = arrived.recv_timeout(Duration::from_secs(15)).unwrap();
    wait_for_boottime(durable.boottime_ns + 600_000_000);
    resume.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap(),
        Err(AuthorityTrustError::Unavailable)
    );
    // The actual original record remains valid now, proving the rejection
    // was the 500 ms remaining-window gate rather than one-second expiry.
    assert!(observe_after_io(&durable, sample_os_clock().unwrap()).is_ok());
    assert_eq!(fixture.store.cas_calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.store.load("slow-clock"), Ok(durable));
}
