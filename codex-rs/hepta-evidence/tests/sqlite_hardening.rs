//! Real SQLite/SQLx regression tests. Abrupt process exit is not a hardware
//! power-loss test; max_page_count exercises SQLITE_FULL, not a host disk quota.
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

fn config(home: &Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(home.to_path_buf()).unwrap())
}

async fn database(home: &Path) -> PathBuf {
    let store = HeptaEvidenceStore::open(&config(home)).await.unwrap();
    let path = store.path().to_path_buf();
    store.close().await;
    path
}

#[tokio::test]
async fn every_pooled_connection_and_reopen_keep_durability_guards() {
    let home = TempDir::new().unwrap();
    let path = database(home.path()).await;
    for _ in 0..2 {
        let pool = config(home.path()).open_durable_evidence_pool(&path).await.unwrap();
        let mut held = Vec::new();
        for _ in 0..5 {
            let mut connection = pool.acquire().await.unwrap();
            for (pragma, expected) in [
                ("PRAGMA recursive_triggers", 1_i64),
                ("PRAGMA foreign_keys", 1),
                ("PRAGMA synchronous", 2),
            ] {
                let actual: i64 = sqlx::query_scalar(pragma)
                    .fetch_one(&mut *connection).await.unwrap();
                assert_eq!(actual, expected, "{pragma}");
            }
            held.push(connection);
        }
        drop(held);
        pool.close().await;
    }
}

#[tokio::test]
async fn replace_update_and_delete_cannot_change_the_enrolled_store_identity() {
    let home = TempDir::new().unwrap();
    let path = database(home.path()).await;
    let pool = config(home.path()).open_durable_evidence_pool(&path).await.unwrap();
    sqlx::query("INSERT INTO evidence_recovery_identity VALUES (1, 'store:original')")
        .execute(&pool).await.unwrap();
    for statement in [
        "INSERT OR REPLACE INTO evidence_recovery_identity VALUES (1, 'store:substituted')",
        "UPDATE evidence_recovery_identity SET store_id = 'store:substituted'",
        "DELETE FROM evidence_recovery_identity",
    ] {
        assert!(sqlx::query(statement).execute(&pool).await.is_err(), "{statement}");
        let actual: String = sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity")
            .fetch_one(&pool).await.unwrap();
        assert_eq!(actual, "store:original");
    }
    let duplicate = sqlx::query(
        "INSERT INTO evidence_recovery_identity VALUES (1, 'store:original') ON CONFLICT DO NOTHING",
    ).execute(&pool).await.unwrap();
    assert_eq!(duplicate.rows_affected(), 0);
    pool.close().await;
    let store = HeptaEvidenceStore::open(&config(home.path())).await.unwrap();
    assert_eq!(store.recovery_store_id().await.unwrap().as_deref(), Some("store:original"));
    store.close().await;
}

#[tokio::test]
async fn sqlite_full_does_not_commit_a_partial_transaction() {
    let home = TempDir::new().unwrap();
    let path = home.path().join("full-fixture.sqlite");
    let pool = config(home.path()).open_durable_evidence_pool(&path).await.unwrap();
    let mut connection = pool.acquire().await.unwrap();
    sqlx::query("CREATE TABLE fixture (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
        .execute(&mut *connection).await.unwrap();
    let pages: i64 = sqlx::query_scalar("PRAGMA page_count")
        .fetch_one(&mut *connection).await.unwrap();
    let cap = format!("PRAGMA max_page_count = {pages}");
    sqlx::query(&cap).execute(&mut *connection).await.unwrap();
    sqlx::query("BEGIN IMMEDIATE").execute(&mut *connection).await.unwrap();
    sqlx::query("INSERT INTO fixture VALUES (1, X'01')")
        .execute(&mut *connection).await.unwrap();
    let error = sqlx::query("INSERT INTO fixture VALUES (2, zeroblob(1048576))")
        .execute(&mut *connection).await.unwrap_err();
    assert!(matches!(&error, sqlx::Error::Database(error) if error.code().as_deref() == Some("13")));
    // SQLITE_FULL can roll the transaction back automatically. An explicit
    // rollback is best effort; it must never be followed by a success receipt.
    let _ = sqlx::query("ROLLBACK").execute(&mut *connection).await;
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM fixture")
        .fetch_one(&mut *connection).await.unwrap();
    assert_eq!(rows, 0);
    drop(connection);
    pool.close().await;
}

#[tokio::test]
async fn corrupt_database_header_is_not_silently_rebuilt() {
    let home = TempDir::new().unwrap();
    let path = database(home.path()).await;
    {
        let mut file = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
        file.write_all(b"not-a-sqlite-db!!").unwrap();
        file.sync_all().unwrap();
    }
    let corrupt = std::fs::read(&path).unwrap();
    assert!(HeptaEvidenceStore::open(&config(home.path())).await.is_err());
    assert_eq!(std::fs::read(&path).unwrap(), corrupt);
}

#[tokio::test]
#[ignore = "subprocess crash fixture; executed by abrupt_exit_preserves_commit_boundary"]
async fn abrupt_exit_child() {
    let home = PathBuf::from(std::env::var_os("HEPTA_EVIDENCE_CRASH_HOME").unwrap());
    let store = HeptaEvidenceStore::open(&config(&home)).await.unwrap();
    let pool = config(&home).open_durable_evidence_pool(store.path()).await.unwrap();
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    sqlx::query("INSERT INTO evidence_recovery_identity VALUES (1, 'store:crash')")
        .execute(&mut *transaction).await.unwrap();
    if std::env::var("HEPTA_EVIDENCE_CRASH_COMMIT").unwrap() == "true" {
        transaction.commit().await.unwrap();
    }
    std::process::exit(73); // Intentionally bypass destructors and pool shutdown.
}

#[tokio::test]
async fn abrupt_exit_preserves_commit_boundary() {
    for committed in [false, true] {
        let home = TempDir::new().unwrap();
        database(home.path()).await;
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "abrupt_exit_child", "--ignored", "--nocapture"])
            .env("HEPTA_EVIDENCE_CRASH_HOME", home.path())
            .env("HEPTA_EVIDENCE_CRASH_COMMIT", committed.to_string())
            .status().unwrap();
        assert_eq!(result.code(), Some(73));
        let store = HeptaEvidenceStore::open(&config(home.path())).await.unwrap();
        assert_eq!(
            store.recovery_store_id().await.unwrap().as_deref(),
            if committed { Some("store:crash") } else { None },
        );
        store.close().await;
    }
}
