//! Public non-test Evidence library qualifications. A local high-water marker
//! is a continuity fence, never a signed CellSplit effect or authority grant.

#[cfg(unix)]
mod unix {
    use codex_hepta_evidence::metrics_group_commit::MetricPhaseV1;
    use codex_hepta_evidence::metrics_group_commit::MetricSampleV1;
    use codex_hepta_evidence::metrics_group_commit::MetricsGroupCommitV1;
    use codex_hepta_evidence::metrics_group_commit::MetricsJournalErrorV1;
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;
    use codex_hepta_types::PhaseMetricSinkV1;
    use std::fs::OpenOptions;
    use std::fs::{self};
    use std::io::Write;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    fn original_private_root() -> tempfile::TempDir {
        let root = tempfile::tempdir().expect("isolated Evidence owner root");
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
            .expect("Evidence root must be private");
        assert_eq!(
            fs::symlink_metadata(root.path())
                .expect("original directory")
                .permissions()
                .mode()
                & 0o077,
            0
        );
        root
    }

    fn sample() -> MetricSampleV1 {
        MetricSampleV1 {
            scope_digest: Digest32::of_bytes(b"exact-scope"),
            operation_digest: Digest32::of_bytes(b"exact-effect"),
            phase: MetricPhaseV1::Cas,
            latency_micros: 14,
            succeeded: true,
        }
    }

    #[test]
    fn non_test_cold_reopen_rejects_valid_older_wal_prefix() {
        let root = original_private_root();
        let wal = root.path().join("original-evidence.wal");
        let old_prefix;
        {
            let mut owner = MetricsGroupCommitV1::open(&wal).expect("first original owner");
            owner.stage(sample()).expect("first sample");
            owner.flush().expect("fsynced first WAL and marker");
            old_prefix = fs::read(&wal).expect("first valid hash-chain prefix");

            owner.stage(sample()).expect("second sample");
            owner.flush().expect("fsynced second WAL and marker");
            assert_eq!(owner.committed_rows(), 2);
            assert_eq!(owner.committed_groups(), 2);
        }
        let original_inode = fs::metadata(&wal).expect("original WAL inode").ino();
        let original = OpenOptions::new()
            .write(true)
            .open(&wal)
            .expect("same original WAL inode");
        original
            .set_len(old_prefix.len() as u64)
            .expect("rollback to still-valid first WAL group");
        original.sync_all().expect("durable attacker truncation");
        assert_eq!(
            fs::metadata(&wal).expect("same inode").ino(),
            original_inode
        );
        assert_eq!(fs::read(&wal).expect("older valid WAL prefix"), old_prefix);
        assert!(matches!(
            MetricsGroupCommitV1::open(&wal),
            Err(MetricsJournalErrorV1::Corrupt)
        ));
    }

    /// The public Evidence actor reads the original committed frontier from
    /// its existing writer lane. A queued sample is NOT fsynced by Observe,
    /// and no external signed authorization or effect is issued.
    #[test]
    fn non_test_actor_observer_does_not_commit_queued_metric() {
        let root = original_private_root();
        let wal = root.path().join("actor-frontier.wal");
        let marker = root.path().join("actor-frontier.wal.owner-lock");
        let sink = DurablePhaseMetricSinkV1::open(&wal, 8, 8, 60_000)
            .expect("bounded original Evidence actor");
        sink.record(PhaseMetricEventV1 {
            scope_digest: Digest32::of_bytes(b"observed-scope"),
            operation_digest: Digest32::of_bytes(b"observed-effect"),
            phase: PhaseMetricKindV1::NduRead,
            latency_micros: 15,
            succeeded: true,
        })
        .expect("queued but not yet committed");
        let original_wal = fs::read(&wal).expect("original WAL bytes");
        let original_marker = fs::read(&marker).expect("original marker bytes");
        let staged = sink
            .read_local_frontier()
            .expect("read-only original frontier");
        assert_eq!(staged.sequence, 0);
        assert_eq!(staged.committed_rows, 0);
        assert_eq!(staged.journal_bytes, 0);
        assert_eq!(fs::read(&wal).expect("no Observer writes"), original_wal);
        assert_eq!(
            fs::read(&marker).expect("no marker mutation"),
            original_marker
        );

        sink.flush().expect("separately requested original fsync");
        let committed = sink.read_local_frontier().expect("committed-only frontier");
        assert_eq!(committed.sequence, 1);
        assert_eq!(committed.committed_rows, 1);
        assert!(!committed.head_digest.is_zero());
        drop(sink);
        let reopened = MetricsGroupCommitV1::open(&wal).expect("released original locks");
        assert_eq!(reopened.committed_rows(), 1);
    }

    /// Preserve the last correct marker row but corrupt an EARLIER row.
    /// The normal-library actor's explicit Observer must reject the entire
    /// original history and make future metrics unavailable.
    #[test]
    fn non_test_actor_observer_poisoned_by_old_marker_corruption() {
        let root = original_private_root();
        let wal = root.path().join("actor-corrupt.wal");
        let marker = root.path().join("actor-corrupt.wal.owner-lock");
        let sink =
            DurablePhaseMetricSinkV1::open(&wal, 8, 1, 60_000).expect("original Evidence writer");
        for _ in 0..3 {
            sink.record(PhaseMetricEventV1 {
                scope_digest: Digest32::of_bytes(b"observed-scope"),
                operation_digest: Digest32::of_bytes(b"observed-effect"),
                phase: PhaseMetricKindV1::Cas,
                latency_micros: 4,
                succeeded: true,
            })
            .expect("real metric");
        }
        sink.flush().expect("three real durable groups");
        let mut marker_bytes = fs::read(&marker).expect("original high-water rows");
        let first = marker_bytes
            .windows(3)
            .position(|window| window == b"F1|")
            .expect("first actual F1 high-water row");
        let digit = first + 3;
        assert!(marker_bytes[digit].is_ascii_digit());
        marker_bytes[digit] = if marker_bytes[digit] == b'9' {
            b'8'
        } else {
            b'9'
        };
        let mut same_inode = OpenOptions::new()
            .write(true)
            .open(&marker)
            .expect("same original marker inode");
        same_inode
            .write_all(&marker_bytes)
            .expect("in-place prior marker corruption");
        same_inode.sync_all().expect("persist corruption");
        assert!(sink.read_local_frontier().is_err());
        assert!(
            !sink.healthy(),
            "a failed original Observer poisons the writer"
        );
        assert!(
            sink.record(PhaseMetricEventV1 {
                scope_digest: Digest32::of_bytes(b"observed-scope"),
                operation_digest: Digest32::of_bytes(b"forbidden-effect"),
                phase: PhaseMetricKindV1::FinalUse,
                latency_micros: 1,
                succeeded: false,
            })
            .is_err()
        );
    }

    #[test]
    fn non_test_stop_ack_releases_wal_and_marker_before_next_owner() {
        let root = original_private_root();
        let wal = root.path().join("bounded-stop.wal");
        let marker = root.path().join("bounded-stop.wal.owner-lock");
        for round in 0..8_u64 {
            let sink = DurablePhaseMetricSinkV1::open(&wal, 8, 8, 60_000)
                .expect("one live Evidence owner");
            sink.record(PhaseMetricEventV1 {
                scope_digest: Digest32::of_bytes(b"exact-scope"),
                operation_digest: Digest32::of_bytes(b"exact-effect"),
                phase: PhaseMetricKindV1::Wal,
                latency_micros: 20,
                succeeded: true,
            })
            .expect("bounded queued evidence sample");

            // Stop itself must flush the queued group and release both
            // original OS locks BEFORE the public sink is fully dropped.
            drop(sink);
            assert!(marker.is_file(), "durable original marker must remain");
            let reopened = MetricsGroupCommitV1::open(&wal)
                .expect("Stop ACK must follow WAL and marker lock release");
            assert_eq!(reopened.committed_rows(), round + 1);
            assert_eq!(reopened.committed_groups(), round + 1);
        }
    }

    /// Readback cannot implicitly fsync or include a staged future sample.
    /// The local frontier is a diagnostic; the original committed high-water
    /// must remain unchanged until the explicit metrics group commit.
    #[test]
    fn non_test_frontier_observer_never_flushes_pending_metrics() {
        let root = original_private_root();
        let wal = root.path().join("frontier.wal");
        let marker = root.path().join("frontier.wal.owner-lock");
        let mut owner = MetricsGroupCommitV1::open(&wal).expect("original Evidence owner");
        owner
            .stage(sample())
            .expect("staged but uncommitted metric");
        let before_wal = fs::read(&wal).expect("WAL before readback");
        let before_marker = fs::read(&marker).expect("marker before readback");

        let frontier = owner
            .read_local_frontier()
            .expect("original local observer");
        assert_eq!(frontier.sequence, 0);
        assert_eq!(frontier.committed_rows, 0);
        assert_eq!(frontier.journal_bytes, 0);
        assert_eq!(owner.pending(), 1);
        assert_eq!(fs::read(&wal).expect("WAL after readback"), before_wal);
        assert_eq!(
            fs::read(&marker).expect("marker after readback"),
            before_marker
        );

        owner.flush().expect("explicit original owner fsync");
        let committed = owner.read_local_frontier().expect("committed frontier");
        assert_eq!(committed.sequence, 1);
        assert_eq!(committed.committed_rows, 1);
        assert_eq!(committed.head_digest, owner.committed_head());
        assert_eq!(committed.journal_bytes, fs::metadata(&wal).unwrap().len());
        assert_ne!(committed.wal_inode, 0);
        assert_ne!(committed.marker_inode, 0);
    }

    /// A correct latest WAL/marker row must never mask a modified EARLIER
    /// independently persisted high-water row during cold recovery.
    #[test]
    fn non_test_reopen_denies_old_marker_corruption_with_valid_latest_row() {
        let root = original_private_root();
        let wal = root.path().join("all-rows.wal");
        let marker = root.path().join("all-rows.wal.owner-lock");
        {
            let mut owner = MetricsGroupCommitV1::open(&wal).expect("original Evidence owner");
            for _ in 0..3 {
                owner.stage(sample()).expect("real group sample");
                owner.flush().expect("WAL and marker fsync");
            }
            assert_eq!(owner.committed_groups(), 3);
        }
        let original_inode = fs::metadata(&marker).expect("original marker").ino();
        let mut bytes = fs::read(&marker).expect("persisted full marker history");
        let row_start = bytes
            .windows(3)
            .position(|window| window == b"F1|")
            .expect("at least one original high-water row");
        let first_sequence_digit = row_start + 3;
        assert!(
            bytes[first_sequence_digit].is_ascii_digit(),
            "original F1 sequence must be a decimal value"
        );
        bytes[first_sequence_digit] = if bytes[first_sequence_digit] == b'9' {
            b'8'
        } else {
            b'9'
        };
        let mut original = OpenOptions::new()
            .write(true)
            .open(&marker)
            .expect("same owner-marker inode");
        original
            .write_all(&bytes)
            .expect("corrupt only the original first marker row");
        original
            .sync_all()
            .expect("persisted same-inode marker corruption");
        assert_eq!(
            fs::metadata(&marker).expect("same marker inode").ino(),
            original_inode
        );
        assert_eq!(
            fs::metadata(&marker).expect("unchanged marker size").len(),
            bytes.len() as u64
        );
        assert!(matches!(
            MetricsGroupCommitV1::open(&wal),
            Err(MetricsJournalErrorV1::Corrupt)
        ));
    }
}
