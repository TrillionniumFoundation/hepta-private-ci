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
    reopened
        .stage(sample(MetricPhaseV1::NeuronFeature))
        .unwrap();
    assert_eq!(reopened.flush().unwrap().unwrap().sequence, 2);
    drop(reopened);
    let final_view = MetricsGroupCommitV1::open(&path).unwrap();
    assert_eq!(final_view.committed_rows(), 3);
    assert_eq!(final_view.committed_groups(), 2);
}

#[test]
fn owner_releases_writer_lock_before_each_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("lock-release.log");
    for expected_groups in 1..=8_u64 {
        let mut writer = MetricsGroupCommitV1::open(&path).unwrap();
        assert!(matches!(
            MetricsGroupCommitV1::open(&path),
            Err(MetricsJournalErrorV1::WriterUnavailable)
        ));
        writer.stage(sample(MetricPhaseV1::Admission)).unwrap();
        writer.flush().unwrap().unwrap();
        drop(writer);

        // Each new owner must recover exactly the committed prefix. The
        // previous exclusive lock must not survive its writer lifetime.
        let reopened = MetricsGroupCommitV1::open(&path).unwrap();
        assert_eq!(reopened.committed_groups(), expected_groups);
        assert_eq!(reopened.committed_rows(), expected_groups);
        drop(reopened);
    }
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

#[test]
fn independently_signed_ndu_and_final_use_metrics_survive_replay() {
    let dir = tempfile::tempdir().expect("temp");
    let path = dir.path().join("neuron-metrics");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).expect("open");
        writer
            .stage(sample(MetricPhaseV1::NduRead))
            .expect("NDU read");
        writer
            .stage(sample(MetricPhaseV1::FinalUse))
            .expect("Final-use");
        let group = writer.flush().expect("flush").expect("group");
        assert_eq!(group.rows, 2);
    }
    let reopened = MetricsGroupCommitV1::open(&path).expect("verify replay");
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
    fs::set_permissions(&exposed, fs::Permissions::from_mode(0o777)).expect("expose directory");
    assert!(matches!(
        MetricsGroupCommitV1::open(exposed.join("metrics")),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
}

#[cfg(unix)]
#[test]
fn existing_hardlink_alias_cannot_become_a_second_metrics_writer() {
    let dir = tempfile::tempdir().expect("private metrics directory");
    let path = dir.path().join("metrics");
    {
        let mut first = MetricsGroupCommitV1::open(&path).expect("create journal");
        first.stage(sample(MetricPhaseV1::Wal)).expect("stage");
        first.flush().expect("durable first group");
    }
    let original = fs::read(&path).expect("original metrics");
    let alias = dir.path().join("metrics-alias");
    fs::hard_link(&path, &alias).expect("link original metrics inode");
    for unsafe_path in [&path, &alias] {
        assert!(matches!(
            MetricsGroupCommitV1::open(unsafe_path),
            Err(MetricsJournalErrorV1::UnsafePath)
        ));
    }
    assert_eq!(
        fs::read(&path).expect("no writes to unsafe inode"),
        original
    );
    fs::remove_file(&alias).expect("remove hardlink");
    assert!(MetricsGroupCommitV1::open(&path).is_ok());
}

#[test]
fn journal_open_does_not_create_an_unprovisioned_storage_directory() {
    let dir = tempfile::tempdir().expect("fixture root");
    let unknown_parent = dir.path().join("not-owned-by-metrics");
    let journal = unknown_parent.join("metrics");
    assert!(!unknown_parent.exists());
    assert!(MetricsGroupCommitV1::open(&journal).is_err());
    assert!(!unknown_parent.exists());
    assert!(!journal.exists());
}


#[test]
fn live_empty_evidence_barrier_refuses_replaced_journal_inode() {
    let root = tempfile::tempdir().expect("private Evidence directory");
    let path = root.path().join("journal.log");
    let former = root.path().join("old-journal.log");
    let mut writer = MetricsGroupCommitV1::open(&path).expect("original Evidence writer");
    writer
        .stage(sample(MetricPhaseV1::Cas))
        .expect("signed operation observation");
    writer.flush().expect("first group fsync");
    std::fs::rename(&path, &former).expect("replace original Evidence pathname");
    std::fs::copy(&former, &path).expect("copy apparently valid bytes");
    assert!(matches!(
        writer.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        writer.stage(sample(MetricPhaseV1::Cns)),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
    drop(writer);
    // A second writer cannot adopt a healthy in-memory continuation from
    // the original writer's stale descriptor. This test is not host custody.
    assert!(std::fs::read(&path).is_ok());
}

#[test]
fn evidence_same_inode_truncate_and_equal_length_tail_rewrite_poison_barrier() {
    for case in ["truncate", "tail_rewrite"] {
        let root = tempfile::tempdir().expect("private metrics directory");
        let path = root.path().join("journal.log");
        let mut writer = MetricsGroupCommitV1::open(&path).expect("original Evidence WAL");
        writer
            .stage(sample(MetricPhaseV1::Signature))
            .expect("phase sample");
        writer.flush().expect("original group committed");
        let original = std::fs::read(&path).expect("fsynced original bytes");
        match case {
            "truncate" => {
                std::fs::OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .expect("same file inode")
                    .set_len(0)
                    .expect("truncate original WAL");
            }
            "tail_rewrite" => {
                let mut bytes = original.clone();
                let pipes = bytes
                    .iter()
                    .enumerate()
                    .filter_map(|(index, byte)| (*byte == b'|').then_some(index))
                    .collect::<Vec<_>>();
                assert!(pipes.len() >= 4);
                let byte = &mut bytes[pipes[2] + 1];
                *byte = if *byte == b'0' { b'1' } else { b'0' };
                std::fs::write(&path, &bytes).expect("rewrite same original inode");
                assert_eq!(bytes.len(), original.len());
            }
            _ => unreachable!("fixed corruption cases"),
        }
        // No staged samples: the metrics ACK still must validate the original
        // WAL rather than silently treating empty flush as acknowledged.
        assert!(matches!(
            writer.flush(),
            Err(MetricsJournalErrorV1::Corrupt)
        ));
        assert!(matches!(
            writer.stage(sample(MetricPhaseV1::Cas)),
            Err(MetricsJournalErrorV1::Poisoned)
        ));
    }
}


#[cfg(unix)]
#[test]
fn live_evidence_barrier_denies_parent_directory_became_peer_writable() {
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("initial owner-private Evidence path");
    let path = root.path().join("journal.log");
    let mut writer = MetricsGroupCommitV1::open(&path).expect("safe original writer");
    writer
        .stage(sample(MetricPhaseV1::Admission))
        .expect("real phase sample");
    writer.flush().expect("first durable original group");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o777))
        .expect("external permission relaxation");
    assert!(matches!(
        writer.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        writer.stage(sample(MetricPhaseV1::Cas)),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("restore permissions only for test cleanup");
}
