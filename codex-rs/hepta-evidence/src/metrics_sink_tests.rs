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


#[test]
fn live_durable_evidence_sink_refuses_replaced_wal_before_positive_flush_ack() {
    let root = tempfile::tempdir().expect("private Evidence directory");
    let path = root.path().join("original-evidence.log");
    let former = root.path().join("renamed-original-evidence.log");
    let sink = DurablePhaseMetricSinkV1::open(&path, 8, 8, 60_000)
        .expect("real background fsync worker");
    sink.record(sample(PhaseMetricKindV1::Cas))
        .expect("original CAS phase");
    sink.flush().expect("first durable fsync");

    // The same valid bytes under a NEW inode must not let the still-running
    // original async writer mint a metrics-ack continuation after corruption.
    std::fs::rename(&path, &former).expect("remove original pathname");
    std::fs::copy(&former, &path).expect("copy apparently intact Evidence WAL");
    assert_eq!(sink.flush(), Err(PhaseMetricSinkErrorV1::Unavailable));
    assert!(!sink.healthy(), "old writer must latch a terminal failure");
    assert_eq!(
        sink.record(sample(PhaseMetricKindV1::Cns)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    // This does NOT authorize opening a new trusted writer from the copied
    // journal: true restart continuity requires independent storage custody.
}
