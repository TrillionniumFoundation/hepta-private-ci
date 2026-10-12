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
