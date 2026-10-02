use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::TaskFlowError;
use crate::taskflow_diagnostics::unavailable;

async fn pool(path: &std::path::Path) -> sqlx::SqlitePool {
    let home = AbsolutePathBuf::try_from(path.parent().expect("database parent").to_path_buf())
        .expect("absolute database home");
    SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(path)
        .await
        .expect("open real durable WAL pool")
}

#[tokio::test]
async fn deferred_read_then_write_retains_busy_snapshot_diagnostic() {
    let temp = tempfile::tempdir().expect("temporary database");
    let pool = pool(&temp.path().join("store.sqlite3")).await;
    sqlx::query("CREATE TABLE evidence (revision INTEGER NOT NULL)")
        .execute(&pool)
        .await
        .expect("create evidence");
    sqlx::query("INSERT INTO evidence VALUES (1)")
        .execute(&pool)
        .await
        .expect("initial revision");
    let mut reader = pool.begin().await.expect("deferred transaction");
    let revision: i64 = sqlx::query_scalar("SELECT revision FROM evidence")
        .fetch_one(&mut *reader)
        .await
        .expect("snapshot read");
    assert_eq!(revision, 1);
    sqlx::query("UPDATE evidence SET revision = 2")
        .execute(&pool)
        .await
        .expect("concurrent durable writer");
    let error = sqlx::query("UPDATE evidence SET revision = 3")
        .execute(&mut *reader)
        .await
        .expect_err("stale snapshot cannot upgrade");
    assert_eq!(
        error
            .as_database_error()
            .and_then(sqlx::error::DatabaseError::code)
            .as_deref(),
        Some("517")
    );
    assert_eq!(
        unavailable(&error, std::panic::Location::caller()),
        TaskFlowError::Unavailable
    );
    reader.rollback().await.expect("release failed snapshot");
    let revision: i64 = sqlx::query_scalar("SELECT revision FROM evidence")
        .fetch_one(&pool)
        .await
        .expect("retained revision");
    assert_eq!(revision, 2);
    pool.close().await;
}

#[tokio::test]
async fn immediate_transaction_serializes_writer_before_snapshot() {
    let temp = tempfile::tempdir().expect("temporary database");
    let pool = pool(&temp.path().join("store.sqlite3")).await;
    sqlx::query("CREATE TABLE evidence (revision INTEGER NOT NULL)")
        .execute(&pool)
        .await
        .expect("create evidence");
    sqlx::query("INSERT INTO evidence VALUES (1)")
        .execute(&pool)
        .await
        .expect("initial revision");
    let mut writer = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer transaction");
    let revision: i64 = sqlx::query_scalar("SELECT revision FROM evidence")
        .fetch_one(&mut *writer)
        .await
        .expect("writer snapshot");
    assert_eq!(revision, 1);
    let mut competitor = pool.acquire().await.expect("competing connection");
    sqlx::query("PRAGMA busy_timeout = 20")
        .execute(&mut *competitor)
        .await
        .expect("bounded diagnostic contention wait");
    let error = sqlx::query("UPDATE evidence SET revision = 2")
        .execute(&mut *competitor)
        .await
        .expect_err("other writer waits instead of invalidating snapshot");
    assert_eq!(
        error
            .as_database_error()
            .and_then(sqlx::error::DatabaseError::code)
            .as_deref(),
        Some("5")
    );
    sqlx::query("UPDATE evidence SET revision = 3")
        .execute(&mut *writer)
        .await
        .expect("original writer completes");
    writer.commit().await.expect("commit original writer");
    drop(competitor);
    let revision: i64 = sqlx::query_scalar("SELECT revision FROM evidence")
        .fetch_one(&pool)
        .await
        .expect("committed revision");
    assert_eq!(revision, 3);
    pool.close().await;
}
