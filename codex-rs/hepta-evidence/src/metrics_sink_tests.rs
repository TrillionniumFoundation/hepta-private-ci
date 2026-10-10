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
    assert_eq!(first.record(invalid), Err(PhaseMetricSinkErrorV1::Unavailable));
    drop(first);
    let reopened = DurablePhaseMetricSinkV1::open(&path, 2, 2, 25).unwrap();
    assert!(reopened.healthy());
}
