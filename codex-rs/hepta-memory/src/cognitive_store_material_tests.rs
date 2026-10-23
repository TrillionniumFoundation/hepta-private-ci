use super::*;
use codex_state::RootSqliteMaterialSource;
use std::ffi::OsStr;

#[tokio::test]
async fn private_material_rejects_unregistered_schema_before_check_expressions() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(173);
    let candidate_layout = layout(&temp, &owner);
    let (store, _, _) = seeded(&temp, &owner).await;
    let cut = store.recovery_anchor().await.unwrap();
    sqlx::query("CREATE TABLE unregistered_material (value TEXT CHECK(value = 'allowed'))")
        .execute(store.observation_pool())
        .await
        .unwrap();
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(store.observation_pool())
        .await
        .unwrap();
    sqlx::query("INSERT INTO unregistered_material VALUES ('rejected')")
        .execute(store.observation_pool())
        .await
        .unwrap();
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(store.observation_pool())
        .await
        .unwrap();
    store.observation_pool().close().await;
    drop(store);
    let config = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(candidate_layout.cognitive_root().to_path_buf()).unwrap(),
    );
    let result = super::super::material::validate_private_candidate(
        &config,
        &candidate_layout
            .cognitive_root()
            .join("cognitive_1.sqlite3"),
        &owner,
        &cut,
        candidate_layout.cognitive_root(),
        &CognitiveCommitGate::default(),
    )
    .await;
    let error = result.unwrap_err().to_string();
    assert!(
        error.contains("table"),
        "original schema admission: {error}"
    );
    assert!(
        !error.contains("quick_check"),
        "premature CHECK evaluation: {error}"
    );
}

fn protected_temp() -> TempDir {
    let root = std::env::var_os("HEPTA_TEST_ROOT_MATERIAL_DESTINATION")
        .expect("actual Root fixture must provide a protected destination");
    tempfile::tempdir_in(root).expect("Root-private material fixture")
}

fn root_source_layout(source_layout: &HeptaAgentLayout) {
    for name in [
        "cognitive_1.sqlite3",
        "cognitive_1.sqlite3-wal",
        "cognitive_1.sqlite3-shm",
        "cognitive_1.sqlite3-journal",
    ] {
        let path = source_layout.cognitive_root().join(name);
        if path.exists() {
            std::os::unix::fs::chown(path, Some(60001), /*gid*/ None).unwrap();
        }
    }
    std::os::unix::fs::chown(
        source_layout.cognitive_root(),
        Some(60001),
        /*gid*/ None,
    )
    .unwrap();
}

fn capture_copy(
    source_layout: &HeptaAgentLayout,
    destination_layout: &HeptaAgentLayout,
) -> Result<PathBuf, CognitiveRecoveryError> {
    std::fs::create_dir_all(destination_layout.cognitive_root())
        .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
    std::fs::set_permissions(
        destination_layout.cognitive_root(),
        std::fs::Permissions::from_mode(0o700),
    )
    .map_err(|error| CognitiveRecoveryError::Unavailable(error.to_string()))?;
    let source_config = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(source_layout.cognitive_root().to_path_buf()).unwrap(),
    );
    let destination_config = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(destination_layout.cognitive_root().to_path_buf()).unwrap(),
    );
    RootSqliteMaterialSource::bind_registered(
        &source_config,
        &source_layout.cognitive_root().join("cognitive_1.sqlite3"),
        /*registered_uid*/ 60001,
        &destination_config,
    )
    .and_then(|source| source.materialize_private_candidate(OsStr::new("cognitive_1.sqlite3")))
    .map_err(recovery_error)
}

#[tokio::test]
#[ignore = "requires actual Root0, a protected destination and private /data TMP"]
async fn root_material_validates_live_wal_copy_without_owner_lock_or_activation() {
    let source_temp = TempDir::new().unwrap();
    let owner = agent_id(171);
    let source_layout = layout(&source_temp, &owner);
    let (store, _, _) = seeded(&source_temp, &owner).await;
    let wal = source_layout
        .cognitive_root()
        .join("cognitive_1.sqlite3-wal");
    assert!(std::fs::metadata(&wal).unwrap().len() > 0);
    root_source_layout(&source_layout);
    let mut transaction = store
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    let cut = capture(&mut transaction, &owner).await.unwrap();
    let pointer_before = std::fs::read(
        source_layout
            .cognitive_root()
            .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER),
    )
    .ok();
    let destination_temp = protected_temp();
    let destination_layout = layout(&destination_temp, &owner);
    let path = capture_copy(&source_layout, &destination_layout).unwrap();
    let verified = CognitiveStore::verify_root_material_candidate(&destination_layout, &cut)
        .await
        .unwrap();
    assert_eq!(verified.path(), path);
    assert_eq!(verified.anchor(), &cut);
    assert_eq!(capture(&mut transaction, &owner).await.unwrap(), cut);
    assert_eq!(
        std::fs::read(
            source_layout
                .cognitive_root()
                .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER)
        )
        .ok(),
        pointer_before
    );
    assert!(
        !destination_layout
            .cognitive_root()
            .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER)
            .exists()
    );
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!PathBuf::from(format!("{}{suffix}", path.display())).exists());
    }
    transaction.rollback().await.unwrap();
}

#[tokio::test]
#[ignore = "requires actual Root0, a protected destination and private /data TMP"]
async fn root_material_mismatched_full_cut_does_not_return_evidence_or_activate() {
    let source_temp = TempDir::new().unwrap();
    let owner = agent_id(172);
    let source_layout = layout(&source_temp, &owner);
    let (store, _, _) = seeded(&source_temp, &owner).await;
    let mut cut = store.recovery_anchor().await.unwrap();
    cut.state_digest = Sha256Digest::for_bytes(b"another prospective cut");
    root_source_layout(&source_layout);
    let mut transaction = store
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    let destination_temp = protected_temp();
    let destination_layout = layout(&destination_temp, &owner);
    capture_copy(&source_layout, &destination_layout).unwrap();
    assert!(matches!(
        CognitiveStore::verify_root_material_candidate(&destination_layout, &cut).await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert!(
        !destination_layout
            .cognitive_root()
            .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER)
            .exists()
    );
    transaction.rollback().await.unwrap();
}
