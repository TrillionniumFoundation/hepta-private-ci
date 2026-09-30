//! Startup and periodic checks of the authoritative cleanup schema and data.

use super::*;

impl NativeCleanupStore {
    pub(crate) async fn probe_schema(&self) -> Result<i64, NativeCleanupStoreError> {
        let mut tx = self.pool.begin().await.map_err(cleanup_sqlx)?;
        if cleanup_store_revision(&mut tx, &self.owner_id, self.owner_generation).await? == 0 {
            return Err(NativeCleanupStoreError::Corrupt(
                "cleanup store revision is zero".to_string(),
            ));
        }
        let cookie: i64 = sqlx::query_scalar("PRAGMA schema_version")
            .fetch_one(&mut *tx)
            .await
            .map_err(cleanup_sqlx)?;
        tx.commit().await.map_err(cleanup_sqlx)?;
        Ok(cookie)
    }

    pub(crate) async fn verify_integrity(&self) -> Result<(), NativeCleanupStoreError> {
        let rows: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check")
            .fetch_all(&self.pool)
            .await
            .map_err(cleanup_sqlx)?;
        if rows.as_slice() != ["ok"] {
            return Err(NativeCleanupStoreError::Corrupt(
                "cleanup integrity_check failed".to_string(),
            ));
        }
        if !sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&self.pool)
            .await
            .map_err(cleanup_sqlx)?
            .is_empty()
        {
            return Err(NativeCleanupStoreError::Corrupt(
                "cleanup foreign keys invalid".to_string(),
            ));
        }
        let schemas = sqlx::query("SELECT sql FROM sqlite_schema WHERE name IN ('runtime_codex_cleanup_meta', 'runtime_codex_cleanup_obligations', 'runtime_codex_cleanup_ready_idx', 'runtime_codex_cleanup_lease_idx')")
            .fetch_all(&self.pool).await.map_err(cleanup_sqlx)?;
        let normalize = |value: &str| {
            value
                .chars()
                .filter(|character| !character.is_ascii_whitespace())
                .flat_map(char::to_lowercase)
                .collect::<String>()
                .replace("ifnotexists", "")
        };
        let observed = schemas
            .iter()
            .map(|row| {
                row.try_get::<String, _>("sql")
                    .map(|value| normalize(&value))
                    .map_err(cleanup_sqlx)
            })
            .collect::<Result<std::collections::BTreeSet<_>, _>>()?;
        let expected = CLEANUP_SCHEMA_STATEMENTS
            .into_iter()
            .map(normalize)
            .collect::<std::collections::BTreeSet<_>>();
        if observed != expected {
            return Err(NativeCleanupStoreError::Corrupt(
                "cleanup constraint/index schema changed".to_string(),
            ));
        }
        self.probe_schema().await?;
        Ok(())
    }

    pub(crate) async fn close(&self) {
        self.pool.close().await;
    }
}
