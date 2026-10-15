use super::*;
use codex_hepta_types::Digest32;

fn sample(phase: PhaseMetricKindV1) -> PhaseMetricEventV1 {
    PhaseMetricEventV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase,
        latency_micros: 15,
        succeeded: true,
    }
}

#[test]
fn producer_records_and_worker_durably_commits_group() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("group.log");
    {
        let sink = DurablePhaseMetricSinkV1::open(&path, 64, 3, 1000).unwrap();
        sink.record(sample(PhaseMetricKindV1::Cas)).unwrap();
        sink.record(sample(PhaseMetricKindV1::Signature)).unwrap();
        sink.record(sample(PhaseMetricKindV1::Cns)).unwrap();
        sink.flush().unwrap();
        let state = sink.status();
        assert!(state.healthy);
        assert_eq!(state.persisted_rows, 3);
        assert_eq!(state.dropped, 0);
    }
    let reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.pending(), 0);
}

#[test]
fn refuses_missing_identity_and_stale_writer_lock() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics.log");
    let first = DurablePhaseMetricSinkV1::open(&path, 2, 2, 25).unwrap();
    assert!(DurablePhaseMetricSinkV1::open(&path, 2, 2, 25).is_err());
    let mut invalid = sample(PhaseMetricKindV1::NeuronFeature);
    invalid.operation_digest = Digest32::ZERO;
    assert_eq!(
        first.record(invalid),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    drop(first);
    let reopened = DurablePhaseMetricSinkV1::open(&path, 2, 2, 25).unwrap();
    assert!(reopened.healthy());
}

#[test]
fn metrics_flush_barrier_and_restart_preserve_exact_committed_sample_counts() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics.log");
    {
        let sink = DurablePhaseMetricSinkV1::open(&path, 8, 3, 60_000).unwrap();
        sink.record(sample(PhaseMetricKindV1::Admission)).unwrap();
        sink.record(sample(PhaseMetricKindV1::Microbatch)).unwrap();
        sink.flush().unwrap();
        assert_eq!(sink.status().persisted_rows, 2);
        assert_eq!(sink.status().persisted_batches, 1);
    }
    {
        let sink = DurablePhaseMetricSinkV1::open(&path, 8, 3, 60_000).unwrap();
        sink.record(sample(PhaseMetricKindV1::NeuronFeature))
            .unwrap();
        sink.flush().unwrap();
        assert_eq!(sink.status().persisted_rows, 1);
    }
    let reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.committed_rows(), 3);
    assert_eq!(reopened.committed_groups(), 2);
}

#[test]
fn metrics_abrupt_exit_fixture() {
    // The child is intentionally isolated in another process: process::exit
    // skips Drop and simulates losing unflushed, in-memory telemetry.
    let Some(path) = std::env::var_os("HEPTA_METRICS_ABORT_PATH") else {
        return;
    };
    let mut writer = MetricsGroupCommitV1::open(path).unwrap();
    writer
        .stage(MetricSampleV1 {
            scope_digest: Digest32::of_bytes(b"scope"),
            operation_digest: Digest32::of_bytes(b"committed"),
            phase: MetricPhaseV1::Admission,
            latency_micros: 1,
            succeeded: true,
        })
        .unwrap();
    writer.flush().unwrap();
    writer
        .stage(MetricSampleV1 {
            scope_digest: Digest32::of_bytes(b"scope"),
            operation_digest: Digest32::of_bytes(b"not-committed"),
            phase: MetricPhaseV1::Microbatch,
            latency_micros: 2,
            succeeded: true,
        })
        .unwrap();
    std::process::exit(91);
}

#[test]
fn metrics_abrupt_process_exit_recovers_committed_prefix_and_exposes_loss_window() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics.log");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("metrics_sink::tests::metrics_abrupt_exit_fixture")
        .arg("--nocapture")
        .env("HEPTA_METRICS_ABORT_PATH", &path)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(91));
    let reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.committed_rows(), 1);
    assert_eq!(reopened.committed_groups(), 1);
    assert_eq!(reopened.pending(), 0);
}

#[test]
fn durable_sink_records_wal_and_reopens_without_corrupting_journal() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("wal-metrics.log");
    {
        let sink = DurablePhaseMetricSinkV1::open(&path, 64, 2, 1000).unwrap();
        sink.record(sample(PhaseMetricKindV1::Wal)).unwrap();
        sink.record(sample(PhaseMetricKindV1::Wal)).unwrap();
        sink.flush().unwrap();
        assert_eq!(sink.status().persisted_rows, 2);
    }
    assert!(MetricsGroupCommitV1::open(&path).is_ok());
}

#[test]
fn signed_neuron_phase_writer_round_trips_actual_group_commit() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("neuron-phase-metrics.log");
    {
        let sink = DurablePhaseMetricSinkV1::open(&path, 16, 2, 1000).unwrap();
        sink.record(sample(PhaseMetricKindV1::NduRead)).unwrap();
        sink.record(sample(PhaseMetricKindV1::FinalUse)).unwrap();
        sink.flush().unwrap();
        assert_eq!(sink.status().persisted_rows, 2);
        assert!(sink.status().healthy);
    }
    let reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.pending(), 0);
}

#[test]
fn metrics_flush_timeout_poisoned_when_queue_is_full_without_writer_progress() {
    // A stalled Evidence owner must not block the Split coordinator forever
    // while it waits to enqueue its commit barrier.
    let (tx, rx) = sync_channel(1);
    let sink = DurablePhaseMetricSinkV1 {
        channel: tx,
        health: Arc::new(WriterHealthV1 {
            healthy: AtomicBool::new(true),
            dropped: AtomicU64::new(0),
            persisted_batches: AtomicU64::new(0),
            persisted_rows: AtomicU64::new(0),
        }),
        worker: Mutex::new(None),
    };
    sink.record(sample(PhaseMetricKindV1::Cas)).unwrap();
    let start = std::time::Instant::now();
    assert_eq!(
        sink.flush_with_timeout(Duration::from_millis(20)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    assert!(start.elapsed() < Duration::from_secs(2));
    assert!(!sink.healthy());
    assert_eq!(
        sink.record(sample(PhaseMetricKindV1::Cns)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    // The timed-out sink can detach without making a false flush claim.
    drop(rx);
    drop(sink);
}

#[test]
fn metrics_flush_timeout_poisoned_when_writer_accepts_but_never_acks() {
    // This simulates fsync stalled *after* the flush command was queued.
    let (tx, rx) = sync_channel(1);
    let sink = DurablePhaseMetricSinkV1 {
        channel: tx,
        health: Arc::new(WriterHealthV1 {
            healthy: AtomicBool::new(true),
            dropped: AtomicU64::new(0),
            persisted_batches: AtomicU64::new(0),
            persisted_rows: AtomicU64::new(0),
        }),
        worker: Mutex::new(None),
    };
    assert_eq!(
        sink.flush_with_timeout(Duration::from_millis(20)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    assert!(!sink.healthy());
    assert_eq!(
        sink.flush_with_timeout(Duration::from_millis(20)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    drop(rx);
    drop(sink);
}

#[test]
fn metrics_sink_drop_never_waits_on_saturated_unserved_channel() {
    // No writer thread is scheduled: a blocking Stop send would never return.
    let (tx, rx) = sync_channel(1);
    let sink = DurablePhaseMetricSinkV1 {
        channel: tx,
        health: Arc::new(WriterHealthV1 {
            healthy: AtomicBool::new(true),
            dropped: AtomicU64::new(0),
            persisted_batches: AtomicU64::new(0),
            persisted_rows: AtomicU64::new(0),
        }),
        worker: Mutex::new(None),
    };
    sink.record(sample(PhaseMetricKindV1::Cas)).unwrap();
    let started = std::time::Instant::now();
    let mut sink = sink;
    sink.stop_with_timeout(Duration::from_millis(20));
    assert!(started.elapsed() < Duration::from_secs(2));
    assert!(!sink.healthy());
    drop(sink);
    drop(rx);
}

#[cfg(unix)]
#[test]
fn evidence_writer_flush_refuses_ack_after_original_wal_inode_replacement() {
    use std::fs;
    use std::os::unix::fs::PermissionsExt as _;

    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let removed = dir.path().join("old-journal");
    let sink = DurablePhaseMetricSinkV1::open(&path, 8, 2, 60_000).expect("live writer");
    sink.record(sample(PhaseMetricKindV1::Cas)).expect("sample");
    sink.flush().expect("original durable ACK");
    let original = fs::read(&path).expect("original group");
    fs::rename(&path, &removed).expect("replace while original owner is alive");
    fs::write(&path, &original).expect("inject same-looking WAL");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private replacement");

    // No new samples are staged: the flush would previously have returned
    // Ok(None), letting a downstream Split mark telemetry as safely durable.
    assert_eq!(sink.flush(), Err(PhaseMetricSinkErrorV1::Unavailable));
    assert!(!sink.healthy());
    assert_eq!(
        sink.record(sample(PhaseMetricKindV1::Cns)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
}

#[cfg(unix)]
#[test]
fn restarted_evidence_sink_cannot_claim_a_new_history_after_wal_loss() {
    use std::fs;

    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("metrics.log");
    let retired = dir.path().join("retired-metrics.log");
    {
        let sink =
            DurablePhaseMetricSinkV1::open(&path, 8, 2, 25).expect("original durable writer");
        sink.record(sample(PhaseMetricKindV1::Cas)).expect("sample");
        sink.flush().expect("original group fsync ACK");
    }
    let marker = dir.path().join("metrics.log.owner-lock");
    assert!(marker.exists(), "independent persistent identity");
    fs::rename(&path, &retired).expect("original journal is gone");
    assert!(
        DurablePhaseMetricSinkV1::open(&path, 8, 2, 25).is_err(),
        "a new process must not mint a fresh healthy Evidence owner"
    );
    assert!(!path.exists(), "no replacement empty journal");
}

#[test]
fn evidence_stop_ack_hands_off_original_wal_and_marker_lock_before_reopen() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("stop-handoff.log");
    for round in 0..24_u64 {
        let sink =
            DurablePhaseMetricSinkV1::open(&path, 8, 2, 60_000).expect("one original writer");
        sink.record(sample(PhaseMetricKindV1::Wal))
            .expect("accepted metric");
        sink.flush().expect("durably fsynced group and highwater");
        drop(sink);

        // This is an immediate original-owner reopen, not a sleep/poll test.
        // A successful Stop ACK must follow release of both file locks.
        let recovered = MetricsGroupCommitV1::open(&path).expect("no previous writer lock remains");
        assert_eq!(recovered.committed_rows(), round + 1);
        assert_eq!(recovered.committed_groups(), round + 1);
    }
}

#[test]
fn graceful_evidence_stop_persists_pending_sample_before_owner_lock_release() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("stop-unflushed.log");
    for round in 0..12_u64 {
        let sink =
            DurablePhaseMetricSinkV1::open(&path, 8, 8, 60_000).expect("one original writer");
        sink.record(sample(PhaseMetricKindV1::NduRead))
            .expect("accepted pending metric");
        drop(sink);

        let reopened =
            MetricsGroupCommitV1::open(&path).expect("Stop ACK follows original owner drop");
        assert_eq!(reopened.committed_rows(), round + 1);
        assert_eq!(reopened.committed_groups(), round + 1);
    }
}

#[cfg(unix)]
#[test]
fn evidence_actor_returns_read_only_original_frontier_without_flushing_pending() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("observer.log");
    let marker = dir.path().join("observer.log.owner-lock");
    let sink =
        DurablePhaseMetricSinkV1::open(&path, 16, 8, 60_000).expect("original Evidence writer");
    sink.record(sample(PhaseMetricKindV1::Cas))
        .expect("committed");
    sink.flush().expect("original durable group");
    let first = sink.read_local_frontier().expect("read original Evidence");
    assert_eq!(first.sequence, 1);
    assert_eq!(first.committed_rows, 1);
    assert_eq!(first.journal_bytes, std::fs::metadata(&path).unwrap().len());

    sink.record(sample(PhaseMetricKindV1::Cns))
        .expect("staged only");
    let before_wal = std::fs::read(&path).expect("original WAL bytes");
    let before_marker = std::fs::read(&marker).expect("original frontier rows");
    let second = sink.read_local_frontier().expect("local observer read");
    assert_eq!(
        second, first,
        "read-only query cannot commit staged metrics"
    );
    assert_eq!(std::fs::read(&path).expect("WAL unchanged"), before_wal);
    assert_eq!(
        std::fs::read(&marker).expect("marker unchanged"),
        before_marker
    );
}

#[cfg(unix)]
#[test]
fn actor_observer_rejects_corrupt_prior_marker_with_intact_last_row() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("observer.log");
    let marker = dir.path().join("observer.log.owner-lock");
    let sink =
        DurablePhaseMetricSinkV1::open(&path, 16, 1, 60_000).expect("original Evidence writer");
    for phase in [
        PhaseMetricKindV1::Cas,
        PhaseMetricKindV1::Signature,
        PhaseMetricKindV1::Cns,
    ] {
        sink.record(sample(phase)).expect("original metric");
    }
    sink.flush().expect("three committed groups");
    assert_eq!(sink.read_local_frontier().unwrap().sequence, 3);
    let mut bytes = std::fs::read(&marker).expect("three frontier rows");
    let original_last = bytes[bytes.len() - 102..].to_vec();
    let first_row = bytes
        .windows(3)
        .position(|segment| segment == b"F1|")
        .expect("marker highwater format");
    bytes[first_row + 3] = b'f';
    assert_eq!(&bytes[bytes.len() - 102..], original_last.as_slice());
    std::fs::write(&marker, bytes).expect("same-inode earlier marker tamper");
    assert_eq!(
        sink.read_local_frontier(),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    assert!(!sink.healthy());
    assert_eq!(sink.flush(), Err(PhaseMetricSinkErrorV1::Unavailable));
}

#[test]
fn bounded_observer_timeout_poisoned_when_writer_never_replies() {
    let (tx, rx) = sync_channel(1);
    let sink = DurablePhaseMetricSinkV1 {
        channel: tx,
        health: Arc::new(WriterHealthV1 {
            healthy: AtomicBool::new(true),
            dropped: AtomicU64::new(0),
            persisted_batches: AtomicU64::new(0),
            persisted_rows: AtomicU64::new(0),
        }),
        worker: Mutex::new(None),
    };
    assert_eq!(
        sink.read_local_frontier_with_timeout(Duration::from_millis(20)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    assert!(!sink.healthy());
    drop(rx);
    drop(sink);
}

#[test]
fn poisoned_evidence_writer_drops_prequeued_events_without_flush_ack() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("queued-after-observer-timeout.log");
    let writer = MetricsGroupCommitV1::open(&path).expect("original writer");
    let (tx, rx) = sync_channel(2);
    let (reply, acknowledged) = sync_channel(1);
    tx.send(WriterCommandV1::Record(MetricSampleV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase: MetricPhaseV1::Cas,
        latency_micros: 1,
        succeeded: true,
    }))
    .expect("one record queued before timeout");
    tx.send(WriterCommandV1::Flush(reply))
        .expect("one old barrier queued before timeout");
    let health = Arc::new(WriterHealthV1 {
        healthy: AtomicBool::new(false),
        dropped: AtomicU64::new(0),
        persisted_batches: AtomicU64::new(0),
        persisted_rows: AtomicU64::new(0),
    });
    // The single original writer starts running only after its caller has
    // timed out and poisoned it. Never consume the queued success path.
    writer_loop(
        writer,
        rx,
        Arc::clone(&health),
        2,
        Duration::from_millis(25),
    );
    assert!(
        acknowledged
            .recv_timeout(Duration::from_millis(25))
            .is_err(),
        "timeout must not yield a late positive durable ACK"
    );
    assert!(!health.healthy.load(Ordering::Acquire));
    assert_eq!(health.persisted_rows.load(Ordering::Acquire), 0);
    drop(tx);
    let recovered = MetricsGroupCommitV1::open(&path).expect("original WAL replay");
    assert_eq!(recovered.committed_rows(), 0);
    assert_eq!(recovered.committed_groups(), 0);
}
