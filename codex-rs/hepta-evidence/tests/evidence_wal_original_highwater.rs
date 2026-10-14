//! Public non-test Evidence library qualifications. A local high-water marker
//! is a continuity fence, never a signed CellSplit effect or authority grant.

#[cfg(unix)]
mod unix {
    use codex_hepta_evidence::metrics_group_commit::{
        MetricPhaseV1, MetricSampleV1, MetricsGroupCommitV1, MetricsJournalErrorV1,
    };
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::{Digest32, PhaseMetricEventV1, PhaseMetricKindV1, PhaseMetricSinkV1};
    use std::fs::{self, OpenOptions};
    use std::os::unix::fs::{MetadataExt, PermissionsExt};

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
}
