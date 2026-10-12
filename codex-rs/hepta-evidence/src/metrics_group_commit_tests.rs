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
fn wal_metric_phase_survives_group_commit_and_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("wal-metrics");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        writer.stage(sample(MetricPhaseV1::Wal)).unwrap();
        assert_eq!(writer.flush().unwrap().unwrap().rows, 1);
    }
    let reopened = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(reopened.pending(), 0);
}

#[cfg(unix)]
#[test]
fn existing_insecure_metrics_file_and_symlink_are_denied() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let dir = tempfile::tempdir().expect("private dir");
    let path = dir.path().join("metrics");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).expect("owner writer");
        writer.stage(sample(MetricPhaseV1::Cas)).expect("stage");
        writer.flush().expect("durable group");
    }
    let before = fs::read(&path).expect("original group");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("relax permissions");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("restore");
    let alias = dir.path().join("metrics-alias");
    symlink(&path, &alias).expect("make alias");
    assert!(matches!(
        MetricsGroupCommitV1::open(&alias),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert_eq!(fs::read(&path).expect("journal unchanged"), before);
}

#[cfg(unix)]
#[test]
fn writable_metrics_directory_is_not_accepted_as_production_writer() {
    use std::os::unix::fs::PermissionsExt;

    let dir = tempfile::tempdir().expect("private root");
    let exposed = dir.path().join("exposed");
    fs::create_dir(&exposed).expect("directory");
    fs::set_permissions(&exposed, fs::Permissions::from_mode(0o777))
        .expect("expose directory");
    assert!(matches!(
        MetricsGroupCommitV1::open(exposed.join("metrics")),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
}
