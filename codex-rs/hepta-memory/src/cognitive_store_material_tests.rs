use super::*;
use pretty_assertions::assert_eq;

#[test]
fn active_pointer_fifo_is_rejected_without_waiting_for_a_writer() {
    let temp = TempDir::new().unwrap();
    let pointer = temp
        .path()
        .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER);
    let result = std::process::Command::new("mkfifo")
        .args(["-m", "600"])
        .arg(&pointer)
        .output()
        .expect("create actual FIFO fixture");
    assert!(result.status.success(), "{result:?}");
    let root = temp.path().to_path_buf();
    let (sender, receiver) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender.send(resolve_active_database_path(&root)).unwrap();
    });
    let result = receiver
        .recv_timeout(std::time::Duration::from_secs(1))
        .expect("active pointer open blocked on a FIFO");
    worker.join().unwrap();
    assert!(result.is_err());
}

#[tokio::test]
async fn private_material_rejects_unregistered_schema_before_check_expressions() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(173);
    let candidate_layout = layout(&temp, &owner);
    let (store, _, _) = seeded(&temp, &owner).await;
    let cut = store.recovery_anchor().await.unwrap();
    let mut corruptor = store.observation_pool().acquire().await.unwrap();
    sqlx::query("CREATE TABLE unregistered_material (value TEXT CHECK(value = 'allowed'))")
        .execute(&mut *corruptor)
        .await
        .unwrap();
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(&mut *corruptor)
        .await
        .unwrap();
    sqlx::query("INSERT INTO unregistered_material VALUES ('rejected')")
        .execute(&mut *corruptor)
        .await
        .unwrap();
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(&mut *corruptor)
        .await
        .unwrap();
    let retained: String = sqlx::query_scalar("SELECT value FROM unregistered_material")
        .fetch_one(&mut *corruptor)
        .await
        .unwrap();
    assert_eq!(retained, "rejected");
    drop(corruptor);
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
    let database = resolve_active_database_path(source_layout.cognitive_root()).unwrap();
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let mut path = database.as_os_str().to_os_string();
        path.push(suffix);
        let path = PathBuf::from(path);
        if path.exists() {
            std::os::unix::fs::chown(path, Some(60001), /*gid*/ None).unwrap();
        }
    }
    let pointer = source_layout
        .cognitive_root()
        .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER);
    if pointer.exists() {
        std::os::unix::fs::chown(pointer, Some(60001), /*gid*/ None).unwrap();
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
    super::super::RootCognitiveMaterialRegistration::bind_registered_layout(
        source_layout,
        /*registered_uid*/ 60001,
    )?
    .materialize_private_candidate(destination_layout)
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
    let transaction = store
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

#[tokio::test]
#[ignore = "requires actual Root0, a protected destination and private /data TMP"]
async fn root_registration_selects_original_recovered_generation_and_rejects_pointer_replacement() {
    let source_temp = TempDir::new().unwrap();
    let owner = agent_id(174);
    let source_layout = layout(&source_temp, &owner);
    let (store, _, _) = seeded(&source_temp, &owner).await;
    let cut = store.recovery_anchor().await.unwrap();
    store.observation_pool().close().await;
    drop(store);
    let recovered = CognitiveStore::open_with_recovery(
        &source_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &recovery_authority(&owner),
        &RecoveryVerifier,
    )
    .await
    .unwrap();
    assert_ne!(
        recovered.path(),
        source_layout.cognitive_root().join("cognitive_1.sqlite3")
    );
    root_source_layout(&source_layout);
    let registered = super::super::RootCognitiveMaterialRegistration::bind_registered_layout(
        &source_layout,
        /*registered_uid*/ 60001,
    )
    .unwrap();
    assert_eq!(registered.identity().database_path(), recovered.path());
    let destination_temp = protected_temp();
    let destination_layout = layout(&destination_temp, &owner);
    std::fs::create_dir_all(destination_layout.cognitive_root()).unwrap();
    std::fs::set_permissions(
        destination_layout.cognitive_root(),
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let transaction = recovered
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    registered
        .materialize_private_candidate(&destination_layout)
        .unwrap();
    CognitiveStore::verify_root_material_candidate(&destination_layout, &cut)
        .await
        .unwrap();
    let pointer = source_layout
        .cognitive_root()
        .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER);
    let bytes = std::fs::read(&pointer).unwrap();
    std::fs::rename(&pointer, pointer.with_extension("old")).unwrap();
    std::fs::write(&pointer, &bytes).unwrap();
    std::fs::set_permissions(&pointer, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::os::unix::fs::chown(&pointer, Some(60001), /*gid*/ None).unwrap();
    assert_eq!(
        resolve_active_database_path(source_layout.cognitive_root()).unwrap(),
        recovered.path()
    );
    assert!(
        registered.verify_registered().is_err(),
        "same basename cannot replace the registered pointer inode"
    );
    transaction.rollback().await.unwrap();

    let fresh_temp = TempDir::new().unwrap();
    let fresh_owner = agent_id(175);
    let fresh_layout = layout(&fresh_temp, &fresh_owner);
    let (fresh, _, _) = seeded(&fresh_temp, &fresh_owner).await;
    root_source_layout(&fresh_layout);
    let registered = super::super::RootCognitiveMaterialRegistration::bind_registered_layout(
        &fresh_layout,
        /*registered_uid*/ 60001,
    )
    .unwrap();
    std::fs::write(
        fresh_layout
            .cognitive_root()
            .join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER),
        b"unexpected pointer",
    )
    .unwrap();
    assert!(
        registered.verify_registered().is_err(),
        "absent pointer cannot become present"
    );
    drop(fresh);
}
