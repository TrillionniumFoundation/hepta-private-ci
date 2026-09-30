//! Lightweight SQLite connection primitives owned by the existing state shim.
//! No domain schema, migrations, authority records or runtime are owned here.
#![expect(
    clippy::disallowed_methods,
    reason = "centralized state SQLite connection shim"
)]
use log::LevelFilter;
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous};
use sqlx::{ConnectOptions, Error, SqlitePool};
use std::path::Path;
use std::time::Duration;

/// Shared connection primitive for independently owned authoritative stores.
/// This configures WAL/FULL and foreign keys, but owns no domain facts or migrations.
pub async fn open_durable_authority_pool(path: &Path) -> Result<SqlitePool, Error> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await
}

/// A one-connection, process-local schema oracle. No authority data is copied here.
pub async fn open_schema_reference_pool() -> Result<SqlitePool, Error> {
    let options = SqliteConnectOptions::new()
        .in_memory(true)
        .foreign_keys(true)
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn authoritative_pool_retains_wal_full_and_foreign_keys() {
        let root = tempfile::tempdir().unwrap();
        let pool = open_durable_authority_pool(&root.path().join("authority.sqlite"))
            .await
            .unwrap();
        let mode: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&pool)
            .await
            .unwrap();
        let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&pool)
            .await
            .unwrap();
        let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(mode, "wal");
        assert_eq!(synchronous, 2);
        assert_eq!(foreign_keys, 1);
        let tables: i64 =
            sqlx::query_scalar("SELECT count(*) FROM sqlite_schema WHERE type='table'")
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(tables, 0); // Creating a pool creates no domain owner or schema.
        pool.close().await;
    }
    #[tokio::test]
    async fn transient_schema_oracles_are_isolated_and_retain_one_connection() {
        let first = open_schema_reference_pool().await.unwrap();
        let second = open_schema_reference_pool().await.unwrap();
        sqlx::query("CREATE TABLE oracle_only (value INTEGER NOT NULL)")
            .execute(&first)
            .await
            .unwrap();
        sqlx::query("INSERT INTO oracle_only VALUES(7)")
            .execute(&first)
            .await
            .unwrap();
        let value: i64 = sqlx::query_scalar("SELECT value FROM oracle_only")
            .fetch_one(&first)
            .await
            .unwrap();
        let other: i64 =
            sqlx::query_scalar("SELECT count(*) FROM sqlite_schema WHERE name='oracle_only'")
                .fetch_one(&second)
                .await
                .unwrap();
        assert_eq!(value, 7);
        assert_eq!(other, 0);
        first.close().await;
        second.close().await;
    }
}
