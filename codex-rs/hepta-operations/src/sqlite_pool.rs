//! Adapt operation-owner files to the repository's durable SQLite pool policy.

use std::path::Path;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

use crate::DurableOperationError;

pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, DurableOperationError> {
    let absolute = std::path::absolute(path)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let parent = absolute.parent().ok_or_else(|| {
        DurableOperationError::Unavailable("operation database has no parent".to_string())
    })?;
    let home = AbsolutePathBuf::from_absolute_path(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&absolute)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::open_durable_pool;

    #[tokio::test]
    async fn shared_pool_keeps_full_sync_foreign_keys_and_persisted_owner_rows()
    -> Result<(), Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("operations.sqlite");
        let pool = open_durable_pool(&path).await?;
        let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&pool)
            .await?;
        let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&pool)
            .await?;
        let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&pool)
            .await?;
        assert_eq!(
            (synchronous, foreign_keys, journal_mode.as_str()),
            (2, 1, "wal")
        );
        sqlx::query("CREATE TABLE owner_record (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            .execute(&pool)
            .await?;
        sqlx::query("INSERT INTO owner_record VALUES (1, 'persisted')")
            .execute(&pool)
            .await?;
        pool.close().await;
        let pool = open_durable_pool(&path).await?;
        let value: String = sqlx::query_scalar("SELECT value FROM owner_record WHERE id = 1")
            .fetch_one(&pool)
            .await?;
        assert_eq!(value, "persisted");
        pool.close().await;
        Ok(())
    }
}
