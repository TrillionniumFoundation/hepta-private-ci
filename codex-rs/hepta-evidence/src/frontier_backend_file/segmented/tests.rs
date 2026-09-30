#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::PermissionsExt;

    use tempfile::TempDir;

    use super::*;
    use crate::EVIDENCE_DATABASE_LINEAGE;
    use crate::EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME;
    use crate::EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY;
    use crate::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
    use crate::EvidenceRecoveryFrontierSignatureV2;
    use crate::EvidenceRecoverySnapshotV1;
    use crate::evidence_recovery_ledger_root_v2;
    use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION;
    use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS;

    struct Fixture {
        _external: TempDir,
        _local: TempDir,
        backend_root: PathBuf,
        local_root: PathBuf,
        identity_sha256: Sha256Digest,
    }

    impl Fixture {
        fn new() -> Self {
            let external = tempfile::tempdir().unwrap();
            let local = tempfile::tempdir().unwrap();
            let backend_root = external.path().join("backend");
            let journals = backend_root.join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
            std::fs::create_dir(&backend_root).unwrap();
            std::fs::create_dir(&journals).unwrap();
            std::fs::set_permissions(&backend_root, std::fs::Permissions::from_mode(0o700))
                .unwrap();
            std::fs::set_permissions(&journals, std::fs::Permissions::from_mode(0o700))
                .unwrap();
            std::fs::set_permissions(local.path(), std::fs::Permissions::from_mode(0o700))
                .unwrap();
            let identity = EvidenceFrontierBackendIdentityV1 {
                schema_version: EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION,
                backend_id: "backend:segmented-test".to_string(),
                authority_id: "authority:segmented-test".to_string(),
                authority_generation: 1,
                storage_class: EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS.to_string(),
            };
            let identity_bytes = serde_json::to_vec(&identity).unwrap();
            let identity_path = backend_root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
            std::fs::write(&identity_path, &identity_bytes).unwrap();
            std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600))
                .unwrap();
            let local_root = local.path().canonicalize().unwrap();
            Self {
                _external: external,
                _local: local,
                backend_root: backend_root.canonicalize().unwrap(),
                local_root,
                identity_sha256: Sha256Digest::for_bytes(&identity_bytes),
            }
        }

        fn open(&self) -> SegmentedFileEvidenceFrontierBackend {
            SegmentedFileEvidenceFrontierBackend::open_same_filesystem_for_testing(
                &self.backend_root,
                self.identity_sha256.clone(),
                &self.local_root,
            )
            .unwrap()
        }
    }

    fn frontier(generation: u64, backend: Sha256Digest) -> EvidenceRecoveryFrontierV2 {
        let snapshot = EvidenceRecoverySnapshotV1 {
            schema_version: 1,
            database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
            migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
            qualification_max_seq: generation,
            qualification_frontier_sha256: Sha256Digest::for_bytes(
                format!("qualification-{generation}").as_bytes(),
            ),
            authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
        };
        EvidenceRecoveryFrontierV2 {
            schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
            store_id: "store:segmented-test".to_string(),
            frontier_generation: generation,
            ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
            snapshot,
            issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer"),
            frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signers"),
            backend_identity_sha256: backend,
            build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
            qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification"),
            backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            created_at_unix_ms: 1_900_000_000_000 + generation,
            signer_policy_generation: 1,
            signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
                signer_principal_id: "signer:test".to_string(),
                signer_key_epoch: 1,
                signature_hex: "11".repeat(64),
            }],
        }
    }

    #[test]
    fn automatic_rollover_preserves_latest_history_and_capacity() {
        let fixture = Fixture::new();
        let mut backend = fixture.open();
        for generation in 1_u64..=6 {
            backend
                .compare_and_swap(
                    "store:segmented-test",
                    generation.checked_sub(1).filter(|value| *value > 0),
                    &frontier(generation, fixture.identity_sha256.clone()),
                )
                .unwrap();
        }
        assert_eq!(
            backend
                .get_latest("store:segmented-test")
                .unwrap()
                .unwrap()
                .frontier_generation,
            6
        );
        let history = backend
            .get_history(
                "store:segmented-test",
                EvidenceFrontierHistoryRangeV1::new(1, 6).unwrap(),
            )
            .unwrap();
        assert_eq!(
            history
                .iter()
                .map(|frontier| frontier.frontier_generation)
                .collect::<Vec<_>>(),
            vec![1, 2, 3, 4, 5, 6]
        );
        let capacity = backend.capacity_status("store:segmented-test").unwrap();
        assert_eq!(capacity.segment_count, 1);
        assert_eq!(capacity.archived_records, 4);
        assert_eq!(capacity.active_records, 2);
    }

    #[test]
    fn exact_duplicate_retry_returns_original_ack_without_a_second_commit() {
        let fixture = Fixture::new();
        let mut backend = fixture.open();
        let proposed = frontier(1, fixture.identity_sha256.clone());
        let original = backend
            .compare_and_swap("store:segmented-test", None, &proposed)
            .unwrap();
        let before = backend.capacity_status("store:segmented-test").unwrap();

        let repeated = backend
            .compare_and_swap("store:segmented-test", None, &proposed)
            .unwrap();
        let after = backend.capacity_status("store:segmented-test").unwrap();
        let history = backend
            .get_history(
                "store:segmented-test",
                EvidenceFrontierHistoryRangeV1::new(1, 1).unwrap(),
            )
            .unwrap();

        assert_eq!(repeated, original);
        assert_eq!(repeated.audit_sequence, 1);
        assert_eq!(history, vec![proposed]);
        assert_eq!(after.segment_count, before.segment_count);
        assert_eq!(after.archived_records, before.archived_records);
        assert_eq!(after.active_records, before.active_records);
        assert_eq!(after.active_bytes, before.active_bytes);
    }

    #[test]
    fn archived_acknowledgement_is_recoverable_after_reopen() {
        let fixture = Fixture::new();
        let expected = evidence_recovery_frontier_v2_sha256(&frontier(
            2,
            fixture.identity_sha256.clone(),
        ))
        .unwrap();
        {
            let mut backend = fixture.open();
            for generation in 1_u64..=5 {
                backend
                    .compare_and_swap(
                        "store:segmented-test",
                        generation.checked_sub(1).filter(|value| *value > 0),
                        &frontier(generation, fixture.identity_sha256.clone()),
                    )
                    .unwrap();
            }
        }
        let mut reopened = fixture.open();
        let acknowledgement = reopened
            .recover_durable_acknowledgement("store:segmented-test", 2, &expected)
            .unwrap()
            .unwrap();
        assert_eq!(acknowledgement.frontier_generation, 2);
        assert_eq!(acknowledgement.audit_sequence, 2);
    }

    #[test]
    fn duplicate_active_prefix_after_archive_crash_is_deduplicated() {
        let fixture = Fixture::new();
        let mut backend = fixture.open();
        for generation in 1_u64..=6 {
            backend
                .compare_and_swap(
                    "store:segmented-test",
                    generation.checked_sub(1).filter(|value| *value > 0),
                    &frontier(generation, fixture.identity_sha256.clone()),
                )
                .unwrap();
        }
        let paths = backend.paths("store:segmented-test").unwrap();
        let index = backend
            .read_index(&paths, "store:segmented-test")
            .unwrap()
            .unwrap();
        let metadata = backend
            .read_segment_metadata(index.latest_segment.as_ref().unwrap(), "store:segmented-test")
            .unwrap();
        let segment =
            std::fs::read(backend.legacy.journals.join(metadata.segment_file_name)).unwrap();
        let active = std::fs::read(&paths.active).unwrap();
        let mut duplicate = segment;
        duplicate.extend_from_slice(&active);
        std::fs::write(&paths.active, duplicate).unwrap();
        std::fs::set_permissions(&paths.active, std::fs::Permissions::from_mode(0o600))
            .unwrap();

        let history = backend
            .get_history(
                "store:segmented-test",
                EvidenceFrontierHistoryRangeV1::new(1, 6).unwrap(),
            )
            .unwrap();
        assert_eq!(history.len(), 6);
        assert_eq!(history.last().unwrap().frontier_generation, 6);
    }

    #[test]
    fn rehashed_archive_to_active_repair_transition_fails_reopen() {
        let fixture = Fixture::new();
        let mut backend = fixture.open();
        for generation in 1_u64..=5 {
            backend
                .compare_and_swap(
                    "store:segmented-test",
                    generation.checked_sub(1).filter(|value| *value > 0),
                    &frontier(generation, fixture.identity_sha256.clone()),
                )
                .unwrap();
        }
        let paths = backend.paths("store:segmented-test").unwrap();
        let active = std::fs::read(&paths.active).unwrap();
        let mut record: EvidenceFrontierAuditRecordV1 =
            serde_json::from_slice(active.strip_suffix(b"\n").unwrap()).unwrap();
        record.frontier.source_commit = "c".repeat(40);
        record.frontier_sha256 =
            evidence_recovery_frontier_v2_sha256(&record.frontier).unwrap();
        record.record_sha256 = audit_record_sha256(&record).unwrap();
        let active = encode_record(&record).unwrap();
        std::fs::write(&paths.active, &active).unwrap();
        std::fs::set_permissions(&paths.active, std::fs::Permissions::from_mode(0o600))
            .unwrap();

        let mut index = backend
            .read_index(&paths, "store:segmented-test")
            .unwrap()
            .unwrap();
        index.active_journal_bytes = u64::try_from(active.len()).unwrap();
        index.active_journal_sha256 = Sha256Digest::for_bytes(&active);
        index.frontier_generation = record.frontier.frontier_generation;
        index.frontier = record.frontier.clone();
        index.frontier_sha256 = record.frontier_sha256.clone();
        index.record_sha256 = record.record_sha256.clone();
        index.index_sha256 = latest_index_sha256(&index).unwrap();
        std::fs::write(&paths.index, serde_json::to_vec(&index).unwrap()).unwrap();
        std::fs::set_permissions(&paths.index, std::fs::Permissions::from_mode(0o600))
            .unwrap();

        let mut reopened = fixture.open();
        assert!(matches!(
            reopened.get_latest("store:segmented-test"),
            Err(EvidenceFrontierBackendError::Corrupt(message))
                if message.contains("non-automatic transition")
                    && message.contains("RepairRequired")
        ));
    }
}
