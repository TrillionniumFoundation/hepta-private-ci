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

#[cfg(unix)]
#[test]
fn live_evidence_wal_rejects_same_inode_truncate_and_equal_length_tail_rewrite() {
    use std::os::unix::fs::MetadataExt as _;

    for fault in ["truncate", "equal_length_rewrite"] {
        let dir = tempfile::tempdir().expect("private Evidence directory");
        let path = dir.path().join("journal");
        let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
        owner.stage(sample(MetricPhaseV1::Cas)).expect("first group");
        owner.flush().expect("first durable row").expect("first group ACK");
        let original = fs::read(&path).expect("durable WAL");
        let original_inode = fs::metadata(&path).expect("original file").ino();
        match fault {
            "truncate" => {
                let file = OpenOptions::new().write(true).open(&path).expect("open original inode");
                file.set_len(0).expect("truncate SAME inode");
                file.sync_all().expect("persist corruption");
            }
            "equal_length_rewrite" => {
                let mut corrupt = original.clone();
                let pos = corrupt.len() - 2;
                corrupt[pos] = if corrupt[pos] == b'0' { b'1' } else { b'0' };
                let mut file = OpenOptions::new().write(true).open(&path).expect("same inode");
                file.write_all(&corrupt).expect("rewrite identical length");
                file.sync_all().expect("persist changed tail");
                assert_eq!(fs::metadata(&path).expect("same size").len(), original.len() as u64);
            }
            _ => unreachable!("fixed faults"),
        }
        assert_eq!(fs::metadata(&path).expect("same inode").ino(), original_inode);
        owner.stage(sample(MetricPhaseV1::Cns)).expect("stage a second group");
        assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::Corrupt)));
        assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::Poisoned)));
    }
}

#[cfg(unix)]
#[test]
fn original_evidence_wal_replacement_invalidates_even_empty_flush_barrier() {
    use std::os::unix::fs::MetadataExt as _;
    use std::os::unix::fs::PermissionsExt as _;

    let dir = tempfile::tempdir().expect("private Evidence directory");
    let path = dir.path().join("journal");
    let removed = dir.path().join("displaced-original-journal");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
    owner.stage(sample(MetricPhaseV1::Wal)).expect("stage first group");
    owner.flush().expect("original fsynced group");
    let original = fs::read(&path).expect("old bytes");
    let inode = fs::metadata(&path).expect("old inode").ino();

    fs::rename(&path, &removed).expect("displace while original FD lives");
    fs::write(&path, &original).expect("replacement with identical bytes");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private replacement");
    assert_ne!(fs::metadata(&path).expect("replacement").ino(), inode);
    assert_eq!(fs::read(&path).expect("replacement bytes"), original);
    assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::UnsafePath)));
    assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::Poisoned)));
    assert_eq!(fs::read(&path).expect("no orphan ACK writes"), original);
}

#[cfg(unix)]
#[test]
fn evidence_wal_rejects_symlink_parent_replacement_with_unchanged_file_inode() {
    use std::os::unix::fs::symlink;

    let root = tempfile::tempdir().expect("private root");
    let parent = root.path().join("live");
    fs::create_dir(&parent).expect("private live parent");
    let path = parent.join("journal");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
    owner.stage(sample(MetricPhaseV1::Admission)).expect("stage group");
    owner.flush().expect("durable first group");
    let parked = root.path().join("parked-original");
    fs::rename(&parent, &parked).expect("move directory without changing file inode");
    symlink(&parked, &parent).expect("replace original parent with a symlink");
    // The named journal still refers to the exact same file inode, so a
    // file-only identity check would falsely return an empty flush ACK.
    assert_eq!(fs::read(&path).expect("same original file"), fs::read(parked.join("journal")).unwrap());
    assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::UnsafePath)));
    assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::Poisoned)));
}
