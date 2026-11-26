use pretty_assertions::assert_eq;

use super::*;
use std::os::unix::fs::PermissionsExt;

#[tokio::test]
async fn fresh_sqlite_wal_and_shm_inherit_private_main_mode() {
    let directory = canonical_database_test_directory();
    let path = directory.path().join(COGNITIVE_DB_FILENAME);
    create_private_initial_database(&path).expect("create private main before SQLite");
    assert_eq!(
        fs::metadata(&path).expect("main file").permissions().mode() & 0o7777,
        0o600
    );

    let sqlite_home =
        AbsolutePathBuf::try_from(directory.path().to_path_buf()).expect("absolute home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&path)
        .await
        .expect("open real SQLite WAL pool");
    sqlx::query("CREATE TABLE wal_mode_probe (value INTEGER NOT NULL)")
        .execute(&pool)
        .await
        .expect("write schema to WAL");
    sqlx::query("INSERT INTO wal_mode_probe (value) VALUES (1)")
        .execute(&pool)
        .await
        .expect("write row to WAL");

    for suffix in ["-wal", "-shm"] {
        let mut sidecar_name = path.as_os_str().to_os_string();
        sidecar_name.push(suffix);
        let sidecar = PathBuf::from(sidecar_name);
        assert_eq!(
            fs::metadata(&sidecar)
                .expect("live SQLite sidecar")
                .permissions()
                .mode()
                & 0o7777,
            0o600,
            "SQLite {suffix} sidecar must remain private"
        );
    }
    pool.close().await;
}

#[test]
fn existing_main_is_not_rewritten_by_initial_creation() {
    let directory = canonical_database_test_directory();
    let path = directory.path().join(COGNITIVE_DB_FILENAME);
    fs::write(&path, b"existing crash evidence").expect("existing file");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o640))
        .expect("mark existing permission");
    assert!(create_private_initial_database(&path).is_err());
    assert_eq!(
        fs::read(&path).expect("existing bytes").as_slice(),
        b"existing crash evidence"
    );
    assert_eq!(
        fs::metadata(&path)
            .expect("existing metadata")
            .permissions()
            .mode()
            & 0o7777,
        0o640
    );
}
