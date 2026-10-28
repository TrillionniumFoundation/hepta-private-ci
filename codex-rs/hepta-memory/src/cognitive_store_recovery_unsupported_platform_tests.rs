//! Unsupported platforms retain fail-closed identity semantics.
//!
//! These tests correct the platform assumptions of the success cases. They do
//! not implement Windows writable recovery or relax its descriptor, authority,
//! permission, sidecar, or publication requirements.

use super::*;

#[tokio::test]
async fn unsupported_recovery_preserves_sources_sidecars_and_active_pointer() {
    #[derive(Clone, Copy)]
    enum SourceFixture {
        Cold,
        Sidecars,
        ActivePointerWithSidecars,
    }

    for fixture in [
        SourceFixture::Cold,
        SourceFixture::Sidecars,
        SourceFixture::ActivePointerWithSidecars,
    ] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(196);
        let agent_layout = layout(&temp, &owner);
        let (store, _, _) = seeded(&temp, &owner).await;
        let anchor = store
            .recovery_anchor()
            .await
            .expect("valid current witness");
        let database = store.path().to_path_buf();
        let root = database.parent().expect("cognitive root").to_path_buf();
        store.pool.close().await;
        drop(store);
        let authority = recovery_authority(&owner);

        // The pointer is a hostile/pre-existing fixture, not a publication by
        // the unsupported recovery implementation. Keep both generations.
        let source_path = match fixture {
            SourceFixture::ActivePointerWithSidecars => {
                let fence = authority.fencing_token_digest().expect("fence digest");
                let name = recovered_database_filename(&anchor, &fence);
                let candidate = root.join(&name);
                std::fs::copy(&database, &candidate).expect("existing generation");
                std::fs::write(
                    root.join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER),
                    format!("{name}\n"),
                )
                .expect("existing active pointer");
                candidate
            }
            SourceFixture::Cold | SourceFixture::Sidecars => database.clone(),
        };
        if !matches!(fixture, SourceFixture::Cold) {
            for (suffix, payload) in [
                ("-wal", b"untrusted WAL bytes".as_slice()),
                ("-shm", b"untrusted SHM bytes".as_slice()),
                ("-journal", b"untrusted rollback-journal bytes".as_slice()),
            ] {
                let mut sidecar = source_path.as_os_str().to_os_string();
                sidecar.push(suffix);
                std::fs::write(PathBuf::from(sidecar), payload).expect("existing sidecar");
            }
        }
        let before = capture_recovery_tree(&root);

        // Normalize both spellings identically so this exercises the explicit
        // non-Unix descriptor guard, not a path-parent spelling mismatch.
        let home = AbsolutePathBuf::try_from(root).expect("absolute source root");
        let bound_path = home
            .as_path()
            .join(source_path.file_name().expect("source name"));
        let config = SqliteConfig::from_sqlite_home(home);
        assert!(matches!(
            config.bind_existing_recovery_database(&bound_path),
            Err(SqliteRecoveryError::Indeterminate)
        ));

        let failure = recovery_failure(
            CognitiveStore::open_with_recovery(
                &agent_layout,
                CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
                &authority,
                &RecoveryVerifier,
            )
            .await,
        );
        assert!(
            matches!(failure, CognitiveRecoveryError::Indeterminate(_)),
            "unsupported identity-bound recovery must not grant a writer: {failure:?}"
        );
        assert_eq!(
            capture_recovery_tree(source_path.parent().expect("source root")),
            before,
            "unsupported recovery changed a source, sidecar, pointer, lock, or directory metadata"
        );
    }
}
