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
            std::fs::set_permissions(&journals, std::fs::Permissions::from_mode(0o700)).unwrap();
            std::fs::set_permissions(local.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
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
    fn archived_acknowledgement_is_recoverable_after_reopen() {
        let fixture = Fixture::new();
        let expected =
            evidence_recovery_frontier_v2_sha256(&frontier(2, fixture.identity_sha256.clone()))
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
            .read_segment_metadata(
                index.latest_segment.as_ref().unwrap(),
                "store:segmented-test",
            )
            .unwrap();
        let segment =
            std::fs::read(backend.legacy.journals.join(metadata.segment_file_name)).unwrap();
        let active = std::fs::read(&paths.active).unwrap();
        let mut duplicate = segment;
        duplicate.extend_from_slice(&active);
        std::fs::write(&paths.active, duplicate).unwrap();
        std::fs::set_permissions(&paths.active, std::fs::Permissions::from_mode(0o600)).unwrap();

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
    fn repeated_rollovers_reopen_with_exact_history_and_archived_acknowledgements() {
        let fixture = Fixture::new();
        for generation in 1_u64..=13 {
            let mut backend = fixture.open();
            let proposed = frontier(generation, fixture.identity_sha256.clone());
            backend
                .compare_and_swap(
                    "store:segmented-test",
                    generation.checked_sub(1).filter(|value| *value > 0),
                    &proposed,
                )
                .unwrap();
            drop(backend);
            let mut reopened = fixture.open();
            let history = reopened
                .get_history(
                    "store:segmented-test",
                    EvidenceFrontierHistoryRangeV1::new(1, generation).unwrap(),
                )
                .unwrap();
            assert_eq!(
                history.iter().map(|entry| entry.frontier_generation).collect::<Vec<_>>(),
                (1..=generation).collect::<Vec<_>>()
            );
            for acknowledged in 1..=generation {
                let digest = evidence_recovery_frontier_v2_sha256(&frontier(
                    acknowledged,
                    fixture.identity_sha256.clone(),
                ))
                .unwrap();
                let acknowledgement = reopened
                    .recover_durable_acknowledgement("store:segmented-test", acknowledged, &digest)
                    .unwrap()
                    .unwrap();
                assert_eq!(acknowledgement.audit_sequence, acknowledged);
                assert_eq!(acknowledgement.frontier_sha256, digest);
            }
        }
    }

    #[test]
    fn later_duplicate_prefix_is_anchored_and_allows_subsequent_publication() {
        let fixture = Fixture::new();
        let mut backend = fixture.open();
        for generation in 1_u64..=10 {
            backend
                .compare_and_swap(
                    "store:segmented-test",
                    generation.checked_sub(1).filter(|value| *value > 0),
                    &frontier(generation, fixture.identity_sha256.clone()),
                )
                .unwrap();
        }
        let paths = backend.paths("store:segmented-test").unwrap();
        let index = backend.read_index(&paths, "store:segmented-test").unwrap().unwrap();
        let metadata = backend
            .read_segment_metadata(index.latest_segment.as_ref().unwrap(), "store:segmented-test")
            .unwrap();
        assert_eq!(metadata.first_generation, 5);
        let segment = std::fs::read(backend.legacy.journals.join(metadata.segment_file_name)).unwrap();
        let mut duplicate = segment.clone();
        duplicate.extend_from_slice(&std::fs::read(&paths.active).unwrap());
        std::fs::write(&paths.active, &duplicate).unwrap();
        drop(backend);
        let mut reopened = fixture.open();
        let history = reopened
            .get_history("store:segmented-test", EvidenceFrontierHistoryRangeV1::new(1, 10).unwrap())
            .unwrap();
        assert_eq!(history.len(), 10);

        // A partial duplicate cannot choose its own starting chain anchor.
        let first_end = segment.iter().position(|byte| *byte == b'\n').unwrap() + 1;
        std::fs::write(&paths.active, &duplicate[first_end..]).unwrap();
        assert!(reopened.get_history(
            "store:segmented-test",
            EvidenceFrontierHistoryRangeV1::new(1, 10).unwrap(),
        ).is_err());
        std::fs::write(&paths.active, &duplicate).unwrap();
        for generation in 11_u64..=13 {
            reopened
                .compare_and_swap(
                    "store:segmented-test",
                    Some(generation - 1),
                    &frontier(generation, fixture.identity_sha256.clone()),
                )
                .unwrap();
        }
        let history = reopened
            .get_history("store:segmented-test", EvidenceFrontierHistoryRangeV1::new(1, 13).unwrap())
            .unwrap();
        assert_eq!(history.iter().map(|entry| entry.frontier_generation).collect::<Vec<_>>(),
            (1..=13).collect::<Vec<_>>());
    }

}
