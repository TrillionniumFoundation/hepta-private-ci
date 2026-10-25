//! Independently derive the schema from compiled migrations, never owner bytes.
use super::*;

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected() {
    let directory = tempfile::tempdir().expect("reference SQLite directory");
    let sqlite_home =
        AbsolutePathBuf::try_from(directory.path().to_path_buf()).expect("absolute SQLite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&directory.path().join("schema.sqlite3"))
        .await
        .expect("reference SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migration chain");
    // Recovery and startup share one canonical schema inventory. A migration
    // adding a logical table must bind its contents, not silently ignore it.
    let actual: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list WHERE schema = 'main' AND type IN ('table', 'virtual') AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetch_all(&pool).await.expect("canonical table inventory");
    let mut expected: Vec<String> = REQUIRED_SCHEMA_OBJECTS
        .iter()
        .filter(|&(_, kind)| *kind == "table")
        .map(|(name, _)| (*name).to_owned())
        .collect();
    expected.push("_sqlx_migrations".to_owned());
    expected.sort();
    assert_eq!(actual, expected);
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, ?, ?)",
    )
    .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
    .bind(owner.as_str())
    .execute(&pool)
    .await
    .expect("owner metadata");
    verify_store(&pool, &owner)
        .await
        .expect("compiled schema must open");
    sqlx::raw_sql("DROP TRIGGER source_ledger_no_update; CREATE TRIGGER source_ledger_no_update BEFORE UPDATE ON source_ledger WHEN 0 BEGIN SELECT RAISE(ABORT, 'disabled guard'); END;")
        .execute(&pool).await.expect("tamper reference trigger");
    assert!(
        matches!(verify_store(&pool, &owner).await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("schema definition oracle mismatch"))
    );
    pool.close().await;
}

#[cfg(unix)]
#[tokio::test]
async fn first_generation_wal_uses_private_file_permissions() {
    use std::os::unix::fs::MetadataExt;

    let directory = tempfile::tempdir().expect("private SQLite directory");
    let path = directory.path().join(COGNITIVE_DB_FILENAME);
    create_private_initial_database(&path).expect("atomically create private initial database");
    let sqlite_home = AbsolutePathBuf::try_from(directory.path().to_path_buf())
        .expect("absolute SQLite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&path)
        .await
        .expect("open the real WAL/FULL SQLite pool");
    sqlx::query("CREATE TABLE private_wal_probe (value INTEGER NOT NULL)")
        .execute(&pool)
        .await
        .expect("create test table through WAL");
    sqlx::query("INSERT INTO private_wal_probe (value) VALUES (1)")
        .execute(&pool)
        .await
        .expect("append through WAL");

    let mut wal_name = path.as_os_str().to_os_string();
    wal_name.push("-wal");
    let wal = PathBuf::from(wal_name);
    assert!(wal.exists(), "a live WAL must exist during the test");
    for file in [&path, &wal] {
        let metadata = fs::symlink_metadata(file).expect("private SQLite file");
        assert!(metadata.file_type().is_file(), "no symlink or special file");
        assert_eq!(metadata.nlink(), 1, "no hard-linked SQLite file");
        assert_eq!(metadata.mode() & 0o7777, 0o600, "private SQLite mode");
    }
    let mut shm_name = path.as_os_str().to_os_string();
    shm_name.push("-shm");
    let shm = PathBuf::from(shm_name);
    if shm.exists() {
        let metadata = fs::symlink_metadata(&shm).expect("shared-memory sidecar");
        assert_eq!(metadata.mode() & 0o7777, 0o600, "private SHM mode");
        assert_eq!(metadata.nlink(), 1, "no hard-linked SHM");
    }
    pool.close().await;
}

#[cfg(unix)]
#[test]
fn private_initialization_never_replaces_existing_database() {
    let directory = tempfile::tempdir().expect("private SQLite directory");
    let path = directory.path().join(COGNITIVE_DB_FILENAME);
    fs::write(&path, b"retained-existing-bytes").expect("existing data");
    let before = fs::metadata(&path).expect("original metadata");
    create_private_initial_database(&path).expect("preserve existing database");
    let after = fs::metadata(&path).expect("retained metadata");
    use std::os::unix::fs::MetadataExt;
    assert_eq!(before.ino(), after.ino(), "existing inode is not replaced");
    assert_eq!(
        fs::read(&path).expect("original contents"),
        b"retained-existing-bytes"
    );
}
