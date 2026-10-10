use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn cold_reopen_reads_canonical_snapshot_without_mutating_source() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(94);
    let (store, access, _) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("independently retained cut");
    let expected = store
        .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200)
        .await
        .expect("canonical snapshot");
    let root = store.path().parent().expect("root").to_path_buf();
    store.pool.close().await;
    let before = capture_recovery_tree(&root);
    for _ in 0..2 {
        let recovered = CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await
        .expect("admit cold image");
        assert_eq!(recovered.anchor(), &anchor);
        assert_eq!(
            recovered
                .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200)
                .await
                .expect("recovered canonical snapshot"),
            expected
        );
        let stranger = CognitiveAccess::agent_private(agent_id(99));
        assert!(matches!(
            recovered
                .lane_c_snapshot(&stranger, &CognitiveScope::AgentPrivate, 200)
                .await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
        assert_eq!(capture_recovery_tree(&root), before);
    }
}

#[tokio::test]
async fn cold_recovery_rejects_revision_change_and_forgetting_rollback() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(95);
    let (store, access, memory) = seeded(&temp, &owner).await;
    let old = store.recovery_anchor().await.expect("retained old cut");
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&store.pool)
        .await
        .expect("checkpoint");
    let backup = std::fs::read(store.path()).expect("old cold bytes");
    store
        .forget_with_kg(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &source(
                CognitiveScope::AgentPrivate,
                "forget-source",
                "explicit forget",
            ),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicit forget".into(),
                valid_from_unix_seconds: 200,
                citations: Vec::new(),
            },
        )
        .await
        .expect("acknowledged forget revision");
    let current = store
        .recovery_anchor()
        .await
        .expect("latest independent cut");
    assert_ne!(old, current);
    store.pool.close().await;
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&old)
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    let recovered = CognitiveStore::open_read_only_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&current),
    )
    .await
    .expect("current forgotten cut");
    assert_eq!(recovered.anchor(), &current);
    // Restoring the pre-forget bytes must never resurrect the forgotten fact
    // under the current witness. There is no 'allow older' fallback policy.
    std::fs::write(store.path(), backup).expect("simulate rolled back disk");
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&current)
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    let root = store.path().parent().expect("root");
    std::fs::remove_dir_all(root).expect("remove source");
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::Revoked
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert!(!root.exists());
}

#[tokio::test]
async fn stable_inspection_metadata_cannot_authenticate_changed_content() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(96);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("independent cut");
    store.pool.close().await;
    let metadata = std::fs::metadata(store.path()).expect("metadata");
    let mut bytes = std::fs::read(store.path()).expect("cold bytes");
    let needle = b"remembered fact";
    let mut changed = 0;
    for offset in 0..=bytes.len() - needle.len() {
        if &bytes[offset..offset + needle.len()] == needle {
            bytes[offset] = b'R';
            changed += 1;
        }
    }
    assert!(changed > 0);
    let file = std::fs::OpenOptions::new()
        .write(true)
        .open(store.path())
        .expect("same inode");
    std::os::unix::fs::FileExt::write_all_at(&file, &bytes, 0).expect("inplace same-size mutation");
    file.set_times(std::fs::FileTimes::new().set_modified(metadata.modified().expect("mtime")))
        .expect("restore mtime");
    let after = std::fs::metadata(store.path()).expect("metadata");
    assert_eq!(
        (
            metadata.ino(),
            metadata.len(),
            metadata.modified().expect("mtime")
        ),
        (after.ino(), after.len(), after.modified().expect("mtime"))
    );
    // The guard is acquired AFTER tampering, so even ctime is stable throughout
    // inspection. The independent full logical hash must catch the mutation.
    let before = capture_recovery_tree(store.path().parent().expect("root"));
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor)
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(
        capture_recovery_tree(store.path().parent().expect("root")),
        before
    );
}

#[tokio::test]
async fn crash_reopen_refuses_pending_wal() {
    const CHILD_ROOT: &str = "HEPTA_COLD_RECOVERY_CRASH_FIXTURE";
    let owner = agent_id(97);
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let layout = codex_hepta_paths::HeptaFleetRoot::parse(PathBuf::from(root))
            .expect("child fleet")
            .layout()
            .agent(&owner);
        let store = CognitiveStore::open(&layout)
            .await
            .expect("child canonical owner");
        // Exit without destructors/checkpoint, exactly while a canonical owner
        // connection has live WAL/SHM. The parent must not replay those files.
        let _cut = store
            .recovery_anchor()
            .await
            .expect("child read transaction");
        std::process::exit(73);
    }
    let temp = TempDir::new().expect("temp");
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("independent witness");
    store.pool.close().await;
    let status = std::process::Command::new(std::env::current_exe().expect("test binary"))
        .args([
            "--exact",
            "cognitive_store::recovery::tests::cold_read_only::crash_reopen_refuses_pending_wal",
            "--nocapture",
        ])
        .env(CHILD_ROOT, temp.path().join("fleet"))
        .status()
        .expect("child process");
    assert_eq!(status.code(), Some(73));
    let root = store.path().parent().expect("root");
    assert!(std::fs::read_dir(root).expect("entries").any(|entry| {
        entry
            .expect("entry")
            .file_name()
            .to_string_lossy()
            .ends_with("-wal")
    }));
    let before = capture_recovery_tree(root);
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor)
        )
        .await,
        Err(CognitiveRecoveryError::Indeterminate(_))
    ));
    assert_eq!(capture_recovery_tree(root), before);
}
