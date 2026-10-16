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
        owner
            .stage(sample(MetricPhaseV1::Cas))
            .expect("first group");
        owner
            .flush()
            .expect("first durable row")
            .expect("first group ACK");
        let original = fs::read(&path).expect("durable WAL");
        let original_inode = fs::metadata(&path).expect("original file").ino();
        match fault {
            "truncate" => {
                let file = OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .expect("open original inode");
                file.set_len(0).expect("truncate SAME inode");
                file.sync_all().expect("persist corruption");
            }
            "equal_length_rewrite" => {
                let mut corrupt = original.clone();
                let pos = corrupt.len() - 2;
                corrupt[pos] = if corrupt[pos] == b'0' { b'1' } else { b'0' };
                let mut file = OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .expect("same inode");
                file.write_all(&corrupt).expect("rewrite identical length");
                file.sync_all().expect("persist changed tail");
                assert_eq!(
                    fs::metadata(&path).expect("same size").len(),
                    original.len() as u64
                );
            }
            _ => unreachable!("fixed faults"),
        }
        assert_eq!(
            fs::metadata(&path).expect("same inode").ino(),
            original_inode
        );
        owner
            .stage(sample(MetricPhaseV1::Cns))
            .expect("stage a second group");
        assert!(matches!(owner.flush(), Err(MetricsJournalErrorV1::Corrupt)));
        assert!(matches!(
            owner.flush(),
            Err(MetricsJournalErrorV1::Poisoned)
        ));
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
    owner
        .stage(sample(MetricPhaseV1::Wal))
        .expect("stage first group");
    owner.flush().expect("original fsynced group");
    let original = fs::read(&path).expect("old bytes");
    let inode = fs::metadata(&path).expect("old inode").ino();

    fs::rename(&path, &removed).expect("displace while original FD lives");
    fs::write(&path, &original).expect("replacement with identical bytes");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private replacement");
    assert_ne!(fs::metadata(&path).expect("replacement").ino(), inode);
    assert_eq!(fs::read(&path).expect("replacement bytes"), original);
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
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
    owner
        .stage(sample(MetricPhaseV1::Admission))
        .expect("stage group");
    owner.flush().expect("durable first group");
    let parked = root.path().join("parked-original");
    fs::rename(&parent, &parked).expect("move directory without changing file inode");
    symlink(&parked, &parent).expect("replace original parent with a symlink");
    // The named journal still refers to the exact same file inode, so a
    // file-only identity check would falsely return an empty flush ACK.
    assert_eq!(
        fs::read(&path).expect("same original file"),
        fs::read(parked.join("journal")).expect("original parked file")
    );
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn moved_same_evidence_wal_into_new_private_parent_cannot_earn_flush_ack() {
    use std::os::unix::fs::MetadataExt as _;

    let root = tempfile::tempdir().expect("private Evidence root");
    let parent = root.path().join("live");
    fs::create_dir(&parent).expect("original parent");
    let path = parent.join("journal");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    owner.stage(sample(MetricPhaseV1::Cas)).expect("stage");
    owner.flush().expect("durable original group");
    let original_inode = fs::metadata(&path).expect("original WAL").ino();

    let moved = root.path().join("original-parent-moved");
    fs::rename(&parent, &moved).expect("move original directory");
    fs::create_dir(&parent).expect("inject new private directory");
    fs::rename(moved.join("journal"), &path).expect("preserve original WAL inode");
    assert_eq!(
        fs::metadata(&path).expect("same original WAL inode").ino(),
        original_inode
    );
    // The file-only identity, byte length and final-group hash all still
    // match. The original parent OWNER identity alone must deny this ACK.
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn lost_evidence_wal_with_persistent_marker_never_bootstraps_new_history() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let missing = dir.path().join("displaced-original-journal");
    {
        let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
        owner
            .stage(sample(MetricPhaseV1::Cas))
            .expect("original group");
        owner.flush().expect("durable original group");
    }
    let marker = dir.path().join("journal.owner-lock");
    assert!(marker.is_file(), "durable original marker exists");
    fs::rename(&path, &missing).expect("remove original WAL path");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(!path.exists(), "never recreate a healthy empty WAL");
    assert!(marker.exists(), "retain original marker for recovery");
}

#[cfg(unix)]
#[test]
fn missing_owner_marker_revokes_live_empty_flush_and_denies_reopen() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    owner
        .stage(sample(MetricPhaseV1::Cns))
        .expect("first sample");
    owner.flush().expect("original durable record");
    fs::remove_file(&marker).expect("lose persistent marker");
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Io(_)) | Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
    drop(owner);
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(!marker.exists(), "do not synthesize an identity");
}

#[cfg(unix)]
#[test]
fn replacement_owner_marker_inode_with_same_bytes_revokes_live_writer() {
    use std::os::unix::fs::PermissionsExt as _;

    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let removed = dir.path().join("previous-owner-marker");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    owner
        .stage(sample(MetricPhaseV1::Admission))
        .expect("first sample");
    owner.flush().expect("original durable record");
    let bytes = fs::read(&marker).expect("original marker bytes");
    fs::rename(&marker, &removed).expect("move original marker inode");
    fs::write(&marker, bytes).expect("replace with matching bytes");
    fs::set_permissions(&marker, fs::Permissions::from_mode(0o600))
        .expect("private replacement marker");
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn same_inode_marker_content_corruption_denies_live_and_recovered_owner() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    owner
        .stage(sample(MetricPhaseV1::Signature))
        .expect("first sample");
    owner.flush().expect("original durable record");
    let mut bytes = fs::read(&marker).expect("original identity");
    // The original HEMW1 header, not the separately tested F1 high-water
    // tail, is the subject of this identity corruption regression.
    let last_digit = owner.owner_marker_bytes.len() - 2;
    bytes[last_digit] = if bytes[last_digit] == b'0' {
        b'1'
    } else {
        b'0'
    };
    let mut opened = OpenOptions::new()
        .write(true)
        .open(&marker)
        .expect("original inode");
    opened
        .write_all(&bytes)
        .expect("overwrite marker with same size");
    opened.sync_all().expect("persist marker corruption");
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
    drop(owner);
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::UnsafePath)
    ));
}

#[cfg(unix)]
#[test]
fn partial_or_legacy_evidence_owner_cannot_be_adopted_as_new_genesis() {
    use std::os::unix::fs::PermissionsExt as _;

    for state in ["marker_only", "wal_only"] {
        let dir = tempfile::tempdir().expect("private Evidence root");
        let path = dir.path().join("journal");
        let marker = dir.path().join("journal.owner-lock");
        let missing = match state {
            "marker_only" => {
                fs::write(&marker, b"incomplete").expect("partial bootstrap marker");
                &path
            }
            "wal_only" => {
                fs::write(&path, b"historical records without original marker")
                    .expect("legacy WAL");
                &marker
            }
            _ => unreachable!("known storage cases"),
        };
        if state == "marker_only" {
            fs::set_permissions(&marker, fs::Permissions::from_mode(0o600))
                .expect("private marker");
        } else {
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private old WAL");
        }
        assert!(matches!(
            MetricsGroupCommitV1::open(&path),
            Err(MetricsJournalErrorV1::UnsafePath)
        ));
        assert!(!missing.exists(), "missing half must not be created");
    }
}

#[cfg(unix)]
#[test]
fn evidence_wal_highwater_survives_cold_reopen_and_original_owner_append() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    {
        let mut first = MetricsGroupCommitV1::open(&path).expect("original writer");
        first.stage(sample(MetricPhaseV1::Cas)).expect("first");
        assert_eq!(
            first
                .flush()
                .expect("first durable group")
                .unwrap()
                .sequence,
            1
        );
        first.stage(sample(MetricPhaseV1::Cns)).expect("second");
        assert_eq!(
            first
                .flush()
                .expect("second durable group")
                .unwrap()
                .sequence,
            2
        );
    }
    {
        let mut recovered = MetricsGroupCommitV1::open(&path).expect("recover two groups");
        assert_eq!(recovered.committed_groups(), 2);
        assert_eq!(recovered.committed_rows(), 2);
        recovered
            .stage(sample(MetricPhaseV1::Signature))
            .expect("post-restart third group");
        assert_eq!(
            recovered
                .flush()
                .expect("third durable group")
                .unwrap()
                .sequence,
            3
        );
    }
    let final_view = MetricsGroupCommitV1::open(&path).expect("recover all three groups");
    assert_eq!(final_view.committed_groups(), 3);
    assert_eq!(final_view.committed_rows(), 3);
    assert_eq!(
        fs::metadata(&marker)
            .expect("separate high-water file")
            .len(),
        final_view.owner_marker_bytes.len() as u64 + 3 * OWNER_FRONTIER_ROW_BYTES as u64
    );
}

#[cfg(unix)]
#[test]
fn valid_older_wal_prefix_cannot_be_adopted_after_cold_same_inode_truncate() {
    use std::os::unix::fs::MetadataExt as _;

    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let earlier;
    {
        let mut writer = MetricsGroupCommitV1::open(&path).expect("original owner");
        writer
            .stage(sample(MetricPhaseV1::Cas))
            .expect("first sample");
        writer.flush().expect("durable first group");
        earlier = fs::read(&path).expect("valid committed prefix");
        writer
            .stage(sample(MetricPhaseV1::Cns))
            .expect("second sample");
        writer.flush().expect("durable second group");
    }
    let inode = fs::metadata(&path).expect("original inode").ino();
    let opened = OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("same inode");
    opened
        .set_len(earlier.len() as u64)
        .expect("roll back to VALID prefix");
    opened.sync_all().expect("persist truncated prefix");
    assert_eq!(fs::read(&path).expect("remaining bytes"), earlier);
    assert_eq!(fs::metadata(&path).expect("inode unchanged").ino(), inode);
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn marker_highwater_truncation_is_not_accepted_after_restart() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    {
        let mut writer = MetricsGroupCommitV1::open(&path).expect("original writer");
        writer.stage(sample(MetricPhaseV1::Cas)).expect("first");
        writer.flush().expect("first fsync");
        writer
            .stage(sample(MetricPhaseV1::Signature))
            .expect("second");
        writer.flush().expect("second fsync");
    }
    let original_len = fs::metadata(&marker).expect("two frontiers").len();
    let marker_file = OpenOptions::new()
        .write(true)
        .open(&marker)
        .expect("same high-water inode");
    marker_file
        .set_len(original_len - OWNER_FRONTIER_ROW_BYTES as u64)
        .expect("drop most recent high-water record");
    marker_file.sync_all().expect("persist marker truncation");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn valid_wal_group_fsynced_without_marker_highwater_remains_quarantined() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let old_head;
    {
        let mut first = MetricsGroupCommitV1::open(&path).expect("owner");
        first.stage(sample(MetricPhaseV1::Wal)).expect("first");
        first.flush().expect("first fully committed group");
        old_head = first.committed_head();
    }
    // Fault injection: simulate a crash between the physical WAL fsync and
    // append/fsync of its separate high-water row, using a valid WAL record.
    let payload = encode_sample(&sample(MetricPhaseV1::FinalUse));
    let head = digest_group(2, old_head, &payload);
    let second = format!("M1|{}|{}|{}|{}|{}\n", 2, old_head, head, 1, payload);
    let mut raw = OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("original WAL");
    raw.write_all(second.as_bytes())
        .expect("second group bytes");
    raw.sync_all()
        .expect("durable WAL without separate marker ACK");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn tampered_same_inode_marker_last_frontier_denies_live_empty_flush() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let mut writer = MetricsGroupCommitV1::open(&path).expect("writer");
    writer.stage(sample(MetricPhaseV1::Cas)).expect("first");
    writer.flush().expect("durable original group");
    let mut bytes = fs::read(&marker).expect("original marker highwater");
    let index = bytes.len() - 2;
    bytes[index] = if bytes[index] == b'0' { b'1' } else { b'0' };
    let mut file = OpenOptions::new()
        .write(true)
        .open(&marker)
        .expect("same marker inode");
    file.write_all(&bytes).expect("alter final head byte");
    file.sync_all().expect("persist tampering");
    assert!(matches!(
        writer.flush(),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
    assert!(matches!(
        writer.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn pre_highwater_marker_cannot_claim_old_nonempty_wal_without_migration() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let old_header_len;
    {
        let mut writer = MetricsGroupCommitV1::open(&path).expect("writer");
        old_header_len = writer.owner_marker_bytes.len() as u64;
        writer.stage(sample(MetricPhaseV1::Cas)).expect("sample");
        writer.flush().expect("fsynced WAL and marker");
    }
    let owner_file = OpenOptions::new()
        .write(true)
        .open(&marker)
        .expect("original marker inode");
    owner_file
        .set_len(old_header_len)
        .expect("drop all new frontier rows");
    owner_file.sync_all().expect("legacy marker-only layout");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn cold_replay_rejects_tampered_first_marker_row_with_valid_last_frontier() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let identity_len;
    {
        let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
        identity_len = owner.owner_marker_bytes.len();
        for phase in [
            MetricPhaseV1::Cas,
            MetricPhaseV1::Signature,
            MetricPhaseV1::Cns,
        ] {
            owner.stage(sample(phase)).expect("stage original event");
            owner.flush().expect("committed original group");
        }
    }
    let mut marker_bytes = fs::read(&marker).expect("original marker history");
    let saved_final = marker_bytes[marker_bytes.len() - OWNER_FRONTIER_ROW_BYTES..].to_vec();
    // Change the first (not the last) F1 sequence field. Length, inode,
    // final tuple and original WAL bytes are all left unchanged.
    let first_hex_digit = identity_len + 3;
    assert_eq!(marker_bytes[first_hex_digit], b'0');
    marker_bytes[first_hex_digit] = b'1';
    assert_eq!(
        &marker_bytes[marker_bytes.len() - OWNER_FRONTIER_ROW_BYTES..],
        saved_final.as_slice()
    );
    fs::write(&marker, &marker_bytes).expect("tamper SAME marker inode");
    assert!(matches!(
        MetricsGroupCommitV1::open(&path),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn live_local_observer_rechecks_entire_marker_history_and_poisons_on_drift() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
    let identity_len = owner.owner_marker_bytes.len();
    for phase in [
        MetricPhaseV1::Admission,
        MetricPhaseV1::Microbatch,
        MetricPhaseV1::Wal,
    ] {
        owner.stage(sample(phase)).expect("group");
        owner.flush().expect("durable original group");
    }
    let before = owner
        .read_local_frontier()
        .expect("verified local snapshot");
    assert_eq!(before.sequence, 3);
    assert_eq!(before.committed_rows, 3);
    assert_eq!(before.head_digest, owner.committed_head());
    assert_eq!(
        before.journal_bytes,
        fs::metadata(&path).expect("original journal").len()
    );
    let mut damaged = fs::read(&marker).expect("original marker");
    damaged[identity_len + OWNER_FRONTIER_ROW_BYTES + 3] = b'f';
    fs::write(&marker, &damaged).expect("tamper only the middle marker record");
    assert!(matches!(
        owner.read_local_frontier(),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn local_observer_frontier_is_read_only_and_never_counts_unflushed_staging() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("journal");
    let marker = dir.path().join("journal.owner-lock");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original owner");
    owner.stage(sample(MetricPhaseV1::Cas)).expect("first");
    owner.flush().expect("first group");
    owner
        .stage(sample(MetricPhaseV1::Cns))
        .expect("pending only");
    let original_wal = fs::read(&path).expect("committed group");
    let original_marker = fs::read(&marker).expect("original highwater");
    let snapshot = owner.read_local_frontier().expect("local observer read");
    assert_eq!(snapshot.sequence, 1);
    assert_eq!(snapshot.committed_rows, 1);
    assert_eq!(owner.pending(), 1);
    assert_eq!(fs::read(&path).expect("unchanged WAL"), original_wal);
    assert_eq!(
        fs::read(&marker).expect("unchanged marker"),
        original_marker
    );
}

#[cfg(unix)]
#[test]
fn observer_replay_does_not_mutate_original_writer_file_offset() {
    use std::io::Seek as _;
    use std::io::SeekFrom;

    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("offset.log");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original WAL owner");
    for phase in [MetricPhaseV1::Cas, MetricPhaseV1::Signature] {
        owner.stage(sample(phase)).expect("stage original metric");
        owner.flush().expect("durable original metric");
    }
    // Deliberately set an unrelated offset on the original owned FD. The
    // previous cloned-descriptor seek(0) changed this shared offset.
    let before = {
        let mut original = &owner.file;
        original
            .seek(SeekFrom::Start(7))
            .expect("test original fd offset");
        original.stream_position().expect("original position")
    };
    let snapshot = owner.read_local_frontier().expect("read complete history");
    assert_eq!(snapshot.sequence, 2);
    let after = {
        let mut original = &owner.file;
        original
            .stream_position()
            .expect("unchanged original offset")
    };
    assert_eq!(after, before, "Observer must use read_at, not shared seek");
    // The original O_APPEND owner must still be able to commit normally.
    owner
        .stage(sample(MetricPhaseV1::Cns))
        .expect("third metric");
    assert_eq!(
        owner
            .flush()
            .expect("third group")
            .expect("durable ACK")
            .sequence,
        3
    );
    drop(owner);
    assert_eq!(
        MetricsGroupCommitV1::open(&path)
            .expect("verified recovery")
            .committed_groups(),
        3
    );
}

#[test]
fn bound_committed_metric_query_requires_exact_scope_operation_phase_and_success() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("bound-metrics.log");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    let query = MetricsCommittedSampleQueryV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase: MetricPhaseV1::Cas,
        succeeded: true,
    };
    owner
        .stage(sample(MetricPhaseV1::Cas))
        .expect("unflushed sample");
    assert_eq!(
        owner
            .read_committed_sample(query)
            .expect("read staged-only prefix"),
        None,
        "staged rows cannot become a false Split operation acknowledgment"
    );
    let original = owner.flush().expect("durable original group").unwrap();
    let readback = owner
        .read_committed_sample(query)
        .expect("fully validated WAL")
        .expect("exact committed operation phase");
    assert_eq!(readback.query, query);
    assert_eq!(readback.matching_rows, 1);
    assert_eq!(readback.first_group_sequence, 1);
    assert_eq!(readback.last_group_sequence, 1);
    assert_eq!(readback.last_group_head, original.head_digest);
    assert_eq!(readback.frontier.sequence, 1);
    assert_eq!(readback.frontier.committed_rows, 1);

    for wrong in [
        MetricsCommittedSampleQueryV1 {
            scope_digest: Digest32::of_bytes(b"other scope"),
            ..query
        },
        MetricsCommittedSampleQueryV1 {
            operation_digest: Digest32::of_bytes(b"other operation"),
            ..query
        },
        MetricsCommittedSampleQueryV1 {
            phase: MetricPhaseV1::Cns,
            ..query
        },
        MetricsCommittedSampleQueryV1 {
            succeeded: false,
            ..query
        },
    ] {
        assert_eq!(owner.read_committed_sample(wrong).unwrap(), None);
        assert_eq!(owner.committed_groups(), 1, "query is read-only");
    }
    assert!(!owner.poisoned);
}

#[cfg(unix)]
#[test]
fn bound_metric_readback_counts_exact_repeated_durable_rows_and_ignores_staging() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("repeated-metric.log");
    let query = MetricsCommittedSampleQueryV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase: MetricPhaseV1::Signature,
        succeeded: true,
    };
    {
        let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
        owner.stage(sample(MetricPhaseV1::Signature)).unwrap();
        owner.flush().expect("first group");
        owner.stage(sample(MetricPhaseV1::Cas)).unwrap();
        owner.stage(sample(MetricPhaseV1::Signature)).unwrap();
        let last = owner.flush().expect("second group").unwrap();
        owner.stage(sample(MetricPhaseV1::Signature)).unwrap();
        let proof = owner.read_committed_sample(query).unwrap().unwrap();
        assert_eq!(proof.matching_rows, 2, "no synthetic third staged row");
        assert_eq!(proof.first_group_sequence, 1);
        assert_eq!(proof.last_group_sequence, 2);
        assert_eq!(proof.last_group_head, last.head_digest);
        assert_eq!(proof.frontier.committed_rows, 3);
        assert_eq!(owner.pending(), 1);
    }
    let mut recovery = MetricsGroupCommitV1::open(&path).expect("real cold recovery");
    let proof = recovery.read_committed_sample(query).unwrap().unwrap();
    assert_eq!(proof.matching_rows, 2);
    assert_eq!(proof.frontier.sequence, 2);
}

#[cfg(unix)]
#[test]
fn bound_metric_corrupt_old_frontier_cannot_claim_latest_matching_sample() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("tampered-metric.log");
    let marker = dir.path().join("tampered-metric.log.owner-lock");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    let header_bytes = owner.owner_marker_bytes.len();
    owner.stage(sample(MetricPhaseV1::Admission)).unwrap();
    owner.flush().unwrap();
    owner.stage(sample(MetricPhaseV1::Cas)).unwrap();
    owner.flush().unwrap();
    let query = MetricsCommittedSampleQueryV1 {
        scope_digest: Digest32::of_bytes(b"scope"),
        operation_digest: Digest32::of_bytes(b"operation"),
        phase: MetricPhaseV1::Cas,
        succeeded: true,
    };
    assert!(owner.read_committed_sample(query).unwrap().is_some());
    // Retain the final marker row intact. A local last-head-only check
    // cannot detect this earlier committed high-water corruption.
    let mut bytes = fs::read(&marker).expect("original marker");
    bytes[header_bytes + 3] = b'f';
    fs::write(&marker, bytes).expect("tamper same marker inode");
    assert!(matches!(
        owner.read_committed_sample(query),
        Err(MetricsJournalErrorV1::Corrupt)
    ));
    assert!(matches!(
        owner.flush(),
        Err(MetricsJournalErrorV1::Poisoned)
    ));
}

#[cfg(unix)]
#[test]
fn invalid_bound_sample_query_never_disables_original_evidence_owner() {
    let dir = tempfile::tempdir().expect("private Evidence root");
    let path = dir.path().join("invalid-bound-query.log");
    let mut owner = MetricsGroupCommitV1::open(&path).expect("original writer");
    assert!(matches!(
        owner.read_committed_sample(MetricsCommittedSampleQueryV1 {
            scope_digest: Digest32::ZERO,
            operation_digest: Digest32::of_bytes(b"operation"),
            phase: MetricPhaseV1::Cas,
            succeeded: true,
        }),
        Err(MetricsJournalErrorV1::EmptyDigest)
    ));
    assert!(!owner.poisoned);
    owner.stage(sample(MetricPhaseV1::Cas)).unwrap();
    assert!(
        owner
            .flush()
            .expect("legitimate metric still works")
            .is_some()
    );
}



#[cfg(unix)]
#[test]
fn bounded_committed_cohort_memberships_match_individual_wal_readbacks() {
    let dir = tempfile::tempdir().expect("private original metrics WAL");
    let path = dir.path().join("ordered-cohort-readback.wal");
    let scope = Digest32::of_bytes(b"original shared Scope");
    let member_a = Digest32::of_bytes(b"original cohort member A");
    let member_b = Digest32::of_bytes(b"original cohort member B");
    let a = MetricsCommittedSampleQueryV1 {
        scope_digest: scope,
        operation_digest: member_a,
        phase: MetricPhaseV1::Admission,
        succeeded: true,
    };
    let b = MetricsCommittedSampleQueryV1 {
        operation_digest: member_b,
        ..a
    };
    let missing = MetricsCommittedSampleQueryV1 {
        operation_digest: Digest32::of_bytes(b"no original Admission"),
        ..a
    };
    let mut writer = MetricsGroupCommitV1::open(&path).expect("exclusive WAL/marker");
    for operation in [member_a, member_b] {
        writer.stage(MetricSampleV1 {
            scope_digest: scope,
            operation_digest: operation,
            phase: MetricPhaseV1::Admission,
            latency_micros: 19,
            succeeded: true,
        }).expect("original Admission staging");
    }

    // The read-only Observer MUST NOT count staged but uncommitted metrics.
    assert_eq!(
        writer.read_committed_samples(&[a, b, missing]).unwrap(),
        vec![None, None, None]
    );
    let receipt = writer.flush().unwrap().expect("fsynced original WAL");
    assert_eq!(receipt.rows, 2);

    let before = writer
        .read_committed_samples(&[a, b, missing])
        .expect("one complete verified WAL and high-water scan");
    assert_eq!(before.len(), 3);
    assert!(before[2].is_none());
    for (query, proof) in [a, b].into_iter().zip(before.iter()) {
        let proof = proof.expect("exact committed original Admission");
        assert_eq!(proof.query, query);
        assert_eq!(proof.matching_rows, 1);
        assert_eq!(proof.first_group_sequence, 1);
        assert_eq!(proof.last_group_sequence, 1);
        assert_eq!(proof.frontier, writer.read_local_frontier().unwrap());
        assert_eq!(
            Some(proof),
            writer.read_committed_sample(query).unwrap(),
            "batch readback must match the historical single-item ABI"
        );
    }

    // Invalid caller input cannot poison the original verified WAL state.
    assert!(matches!(
        writer.read_committed_samples(&[a, a]),
        Err(MetricsJournalErrorV1::Capacity)
    ));
    assert!(writer.read_committed_samples(&[a, b]).is_ok());
    assert!(matches!(
        writer.read_committed_samples(&[]),
        Err(MetricsJournalErrorV1::Capacity)
    ));

    // A duplicated SUCCESS Admission is not silently collapsed into one.
    writer.stage(MetricSampleV1 {
        scope_digest: scope,
        operation_digest: member_a,
        phase: MetricPhaseV1::Admission,
        latency_micros: 20,
        succeeded: true,
    }).unwrap();
    writer.flush().unwrap().expect("second committed original group");
    let counted = writer.read_committed_samples(&[a, b]).unwrap();
    assert_eq!(counted[0].unwrap().matching_rows, 2);
    assert_eq!(counted[1].unwrap().matching_rows, 1);
    assert_eq!(counted[0].unwrap().first_group_sequence, 1);
    assert_eq!(counted[0].unwrap().last_group_sequence, 2);
    let frozen = counted;
    drop(writer);
    let mut cold = MetricsGroupCommitV1::open(&path).expect("cold exact WAL reopen");
    assert_eq!(cold.read_committed_samples(&[a, b]).unwrap(), frozen);
}
