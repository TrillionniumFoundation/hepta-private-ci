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

// A held receiver stands in for an Evidence writer blocked in an I/O call.
// No fake successful fsync receipt or external effect is produced.
fn unresponsive_writer_fixture(
    capacity: usize,
) -> (DurablePhaseMetricSinkV1, Receiver<WriterCommandV1>) {
    let (channel, receiver) = sync_channel(capacity);
    let health = Arc::new(WriterHealthV1 {
        healthy: AtomicBool::new(true),
        dropped: AtomicU64::new(0),
        persisted_batches: AtomicU64::new(0),
        persisted_rows: AtomicU64::new(0),
    });
    (
        DurablePhaseMetricSinkV1 {
            channel,
            health,
            worker: Mutex::new(None),
        },
        receiver,
    )
}

#[test]
fn saturated_writer_rejects_flush_and_drop_without_waiting_for_queue_space() {
    let (sink, held_receiver) = unresponsive_writer_fixture(1);
    let admitted = sink
        .channel
        .try_send(WriterCommandV1::Record(MetricSampleV1 {
            scope_digest: Digest32::of_bytes(b"scope"),
            operation_digest: Digest32::of_bytes(b"operation"),
            phase: MetricPhaseV1::Cas,
            latency_micros: 1,
            succeeded: true,
        }));
    assert!(admitted.is_ok());
    assert_eq!(
        sink.flush_with_timeout(Duration::from_millis(5)),
        Err(PhaseMetricSinkErrorV1::Backpressure)
    );
    assert!(!sink.healthy());
    assert_eq!(sink.status().persisted_rows, 0);
    drop(sink);
    drop(held_receiver);
}

#[test]
fn missing_fsync_ack_poison_writer_and_never_invents_commit() {
    let (sink, receiver) = unresponsive_writer_fixture(1);
    assert_eq!(
        sink.flush_with_timeout(Duration::from_millis(5)),
        Err(PhaseMetricSinkErrorV1::Unavailable)
    );
    assert!(!sink.healthy());
    assert_eq!(sink.status().persisted_batches, 0);
    assert!(matches!(receiver.try_recv(), Ok(WriterCommandV1::Flush(_))));
    drop(receiver);
    drop(sink);
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
/// An acknowledged Stop is a writer-lock handoff, not merely a report
/// that flush() has returned. The next owner must be able to reopen the same
/// fsynced journal immediately, without sleeps, polling or a second writer.
#[test]
fn acknowledged_stop_releases_original_metrics_lock_before_reopen() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("stop-handoff.log");
    for round in 0..32_u64 {
        let sink = DurablePhaseMetricSinkV1::open(&path, 8, 2, 60_000)
            .expect("one current Evidence writer");
        sink.record(sample(PhaseMetricKindV1::Wal))
            .expect("bounded phase sample");
        sink.flush().expect("real durable flush before Stop");
        drop(sink);

        // The public writer Drop already received its Stop ACK. Reopen
        // immediately to prove ACK cannot race the original OS lock release.
        let recovered = MetricsGroupCommitV1::open(&path)
            .expect("Stop ACK must follow writer lock release");
        assert_eq!(recovered.committed_rows(), round + 1);
        assert_eq!(recovered.committed_groups(), round + 1);
    }
}

/// Stop itself must fsync queued samples before releasing the original
/// writer lock and acknowledging a clean shutdown. No explicit flush,
/// sleeps or fabricated journal counters are permitted in this regression.
#[test]
fn graceful_stop_commits_queued_samples_before_lock_handoff() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("stop-commits.log");
    for round in 0..16_u64 {
        let sink = DurablePhaseMetricSinkV1::open(&path, 8, 8, 60_000)
            .expect("one original Evidence writer");
        sink.record(sample(PhaseMetricKindV1::NduRead))
            .expect("queued sample");
        drop(sink);

        let committed = MetricsGroupCommitV1::open(&path)
            .expect("Stop must fsync and release the original lock before ACK");
        assert_eq!(committed.committed_rows(), round + 1);
        assert_eq!(committed.committed_groups(), round + 1);
    }
}

