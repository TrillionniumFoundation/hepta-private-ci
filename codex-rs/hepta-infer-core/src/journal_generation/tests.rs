#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::*;

    struct OneShotFailpoint {
        target: JournalFailpoint,
        fired: bool,
    }

    impl JournalFailpointController for OneShotFailpoint {
        fn hit(&mut self, point: JournalFailpoint) -> Result<(), JournalGenerationError> {
            if point == self.target && !self.fired {
                self.fired = true;
                return Err(JournalGenerationError::CrashInjected(point));
            }
            Ok(())
        }
    }

    fn store(temp: &TempDir) -> JournalGenerationStore {
        JournalGenerationStore::open(temp.path(), "native-control").expect("store")
    }

    fn commit_first(store: &JournalGenerationStore) -> CommittedJournalGeneration {
        store
            .commit_generation(
                JournalGenerationInput {
                    generation: 1,
                    previous_manifest_sha256: None,
                    snapshot: b"snapshot-one",
                    predecessor_archive: b"journal-one",
                    created_at_unix_ms: 1_800_000_000_000,
                    retain_checkpoints: 3,
                },
                &mut NoJournalFailpoints,
            )
            .expect("generation one")
    }

    #[test]
    fn recovery_observes_only_a_complete_old_or_new_generation_at_every_failpoint() {
        let points = [
            JournalFailpoint::BeforeArchiveWrite,
            JournalFailpoint::AfterArchiveFsync,
            JournalFailpoint::AfterArchiveRename,
            JournalFailpoint::AfterCheckpointFsync,
            JournalFailpoint::AfterCheckpointRename,
            JournalFailpoint::BeforePointerRename,
            JournalFailpoint::AfterPointerRename,
            JournalFailpoint::AfterDirectoryFsync,
        ];
        for point in points {
            let temp = TempDir::new().expect("temp");
            let store = store(&temp);
            let first = commit_first(&store);
            let mut failpoint = OneShotFailpoint {
                target: point,
                fired: false,
            };
            let _ = store.commit_generation(
                JournalGenerationInput {
                    generation: 2,
                    previous_manifest_sha256: Some(first.manifest_sha256),
                    snapshot: b"snapshot-two",
                    predecessor_archive: b"journal-two",
                    created_at_unix_ms: 1_800_000_001_000,
                    retain_checkpoints: 3,
                },
                &mut failpoint,
            );
            let recovered = store.recover().expect("recover exact generation");
            assert!(matches!(recovered.manifest.generation, 1 | 2));
            match recovered.manifest.generation {
                1 => assert_eq!(recovered.snapshot, b"snapshot-one"),
                2 => assert_eq!(recovered.snapshot, b"snapshot-two"),
                _ => unreachable!(),
            }
        }
    }

    #[test]
    fn content_addressed_archive_is_verified_before_reuse() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp);
        let first = commit_first(&store);
        fs::write(&first.archive_path, b"tampered").expect("tamper");
        let error = store
            .commit_generation(
                JournalGenerationInput {
                    generation: 2,
                    previous_manifest_sha256: Some(first.manifest_sha256),
                    snapshot: b"snapshot-two",
                    predecessor_archive: b"journal-one",
                    created_at_unix_ms: 1_800_000_001_000,
                    retain_checkpoints: 3,
                },
                &mut NoJournalFailpoints,
            )
            .expect_err("archive mismatch");
        assert_eq!(error, JournalGenerationError::CorruptArchive);
    }

    #[test]
    fn checkpoint_soak_exceeds_the_legacy_record_capacity_without_losing_identity() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp);
        let mut snapshot = Vec::new();
        for index in 0..=16_384_u32 {
            let line = format!("request-{index:05}|released|digest-{index:05}\n");
            snapshot.extend_from_slice(line.as_bytes());
        }
        store
            .commit_generation(
                JournalGenerationInput {
                    generation: 1,
                    previous_manifest_sha256: None,
                    snapshot: &snapshot,
                    predecessor_archive: b"bounded predecessor journal",
                    created_at_unix_ms: 1_800_000_000_000,
                    retain_checkpoints: 2,
                },
                &mut NoJournalFailpoints,
            )
            .expect("soak checkpoint");
        let recovered = store.recover().expect("recover soak checkpoint");
        assert_eq!(recovered.snapshot, snapshot);
        assert_eq!(recovered.snapshot.split(|byte| *byte == b'\n').count() - 1, 16_385);
    }

    #[test]
    fn generation_chain_rejects_skips_and_wrong_predecessors() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp);
        let first = commit_first(&store);
        assert_eq!(
            store
                .commit_generation(
                    JournalGenerationInput {
                        generation: 3,
                        previous_manifest_sha256: Some(first.manifest_sha256),
                        snapshot: b"snapshot-three",
                        predecessor_archive: b"journal-three",
                        created_at_unix_ms: 1_800_000_002_000,
                        retain_checkpoints: 3,
                    },
                    &mut NoJournalFailpoints,
                )
                .expect_err("skip"),
            JournalGenerationError::PreviousGenerationMismatch
        );
    }
}
