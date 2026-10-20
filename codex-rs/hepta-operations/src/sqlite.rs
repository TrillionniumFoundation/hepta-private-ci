use std::path::Path;

use codex_state::SqliteConfig;
use sqlx::SqlitePool;

use crate::DurableOperationError;

pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, DurableOperationError> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let canonical_parent = std::fs::canonicalize(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let file_name = path
        .file_name()
        .ok_or(DurableOperationError::Invalid("database file name"))?;
    let absolute_path = canonical_parent.join(file_name);
    SqliteConfig::open_operation_owner_pool(&absolute_path)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}

#[cfg(test)]
pub(crate) mod tests {
    use super::open_durable_pool;

    pub(crate) async fn assert_operation_policy(
        pool: &sqlx::SqlitePool,
    ) -> Result<(), sqlx::Error> {
        assert_eq!(pool.options().get_max_connections(), 4);
        let mut connections = Vec::new();
        for _ in 0..4 {
            let mut connection = pool.acquire().await?;
            let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
                .fetch_one(&mut *connection)
                .await?;
            let sync: i64 = sqlx::query_scalar("PRAGMA synchronous")
                .fetch_one(&mut *connection)
                .await?;
            let foreign: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
                .fetch_one(&mut *connection)
                .await?;
            let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
                .fetch_one(&mut *connection)
                .await?;
            assert_eq!((journal.as_str(), sync, foreign, busy), ("wal", 2, 1, 5000));
            connections.push(connection);
        }
        assert!(
            pool.try_acquire().is_none(),
            "fifth connection must not escape owner bound"
        );
        Ok(())
    }

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
