use super::*;

fn sample(phase: MetricPhaseV1) -> MetricSampleV1 {
    MetricSampleV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase,
        latency_micros: 42,
        succeeded: true,
    }
}
#[test]
fn one_fsync_for_group_replay_and_next_sequence() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics");
    let previous;
    {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        writer.stage(sample(MetricPhaseV1::Cas)).unwrap();
        writer.stage(sample(MetricPhaseV1::Signature)).unwrap();
        writer.stage(sample(MetricPhaseV1::Cns)).unwrap();
        let receipt = writer.flush().unwrap().unwrap();
        assert_eq!(receipt.rows, 3);
        previous = receipt.head_digest;
    }
    let mut reopened = MetricsGroupCommitV1::open(&path).unwrap();
    let receipt = {
        reopened.stage(sample(MetricPhaseV1::Admission)).unwrap();
        reopened.flush().unwrap().unwrap()
    };
    assert_eq!(receipt.sequence, 2);
    assert_ne!(receipt.head_digest, previous);
}

#[test]
fn tampered_group_is_rejected_and_phase_times_failures() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        writer.stage(sample(MetricPhaseV1::Cas)).unwrap();
        writer.flush().unwrap();
    }
    let (result, metric) = measure_phase_v1(
        Digest32::of_bytes(b"s"),
        Digest32::of_bytes(b"o"),
        MetricPhaseV1::Cas,
        || Err::<(), _>("conflict"),
    );
    assert!(result.is_err());
    assert!(!metric.succeeded);
    std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"truncated")
        .unwrap();
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}


#[test]
fn replay_exposes_exact_committed_count_without_counting_unsynced_staging() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics");
    let first_head;
    {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        assert_eq!(writer.committed_rows(), 0);
        assert_eq!(writer.committed_groups(), 0);
        writer.stage(sample(MetricPhaseV1::Admission)).unwrap();
        writer.stage(sample(MetricPhaseV1::Microbatch)).unwrap();
        let receipt = writer.flush().unwrap().unwrap();
        first_head = receipt.head_digest;
        assert_eq!(writer.committed_rows(), 2);
        assert_eq!(writer.committed_groups(), 1);
        writer.stage(sample(MetricPhaseV1::NeuronFeature)).unwrap();
        assert_eq!(writer.pending(), 1);
        assert_eq!(writer.committed_rows(), 2);
        // A process crash here would discard this staged row, not certify it.
    }
    let mut reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.committed_rows(), 2);
    assert_eq!(reopened.committed_groups(), 1);
    assert_eq!(reopened.committed_head(), first_head);
    assert_eq!(reopened.pending(), 0);
    assert!(reopened.flush().unwrap().is_none());
    reopened.stage(sample(MetricPhaseV1::NeuronFeature)).unwrap();
    assert_eq!(reopened.flush().unwrap().unwrap().sequence, 2);
    drop(reopened);
    let final_view = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(final_view.committed_rows(), 3);
    assert_eq!(final_view.committed_groups(), 2);
}

#[test]
fn replay_rejects_modified_committed_payload_without_skipping_corruption() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("metrics");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        writer.stage(sample(MetricPhaseV1::Signature)).unwrap();
        writer.flush().unwrap().unwrap();
    }
    let original = std::fs::read_to_string(&path).unwrap();
    assert!(original.contains(":42:1"));
    std::fs::write(&path, original.replace(":42:1", ":43:1")).unwrap();
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}
