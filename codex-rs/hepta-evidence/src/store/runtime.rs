use super::*;

impl HeptaEvidenceStore {
    /// Open an already migrated evidence lineage through the restricted runtime
    /// connection profile.
    ///
    /// Production callers must perform a read-only preflight first. This method
    /// deliberately does not create the database or run the migrator; it verifies
    /// the current ledger and schema again after every pooled connection has been
    /// fenced by the SQLite authorizer.
    pub async fn open_existing_runtime(sqlite: &SqliteConfig) -> Result<Self, EvidenceError> {
        let path = sqlite.home().join(EVIDENCE_DATABASE_LINEAGE);
        let pool = sqlite
            .open_existing_durable_evidence_runtime_pool(&path)
            .await
            .map_err(classify_sqlx_error)?;
        if let Err(error) = verify_quick_check(&pool).await {
            pool.close().await;
            return Err(error);
        }
        if let Err(error) = verify_existing_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self {
            pool,
            path,
            provider_effect_boundary_lock: Arc::new(tokio::sync::Mutex::new(())),
        })
    }
}

#[cfg(test)]
mod tests {
    use codex_utils_absolute_path::AbsolutePathBuf;
    use tempfile::TempDir;

    use super::*;

    fn sqlite_config(temp: &TempDir) -> SqliteConfig {
        SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
        )
    }

    async fn assert_rejected(store: &HeptaEvidenceStore, statement: &str) {
        let result = sqlx::query(statement).execute(&store.pool).await;
        assert!(
            result.is_err(),
            "restricted evidence runtime unexpectedly accepted: {statement}"
        );
    }

    #[tokio::test]
    async fn restricted_runtime_allows_authoritative_appends_but_denies_control_plane_sql() {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let bootstrap = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("bootstrap migrated evidence store");
        bootstrap.close().await;

        let runtime = HeptaEvidenceStore::open_existing_runtime(&sqlite)
            .await
            .expect("open restricted evidence runtime");
        runtime
            .bind_recovery_store_id("store:runtime-authorizer-test")
            .await
            .expect("authoritative runtime insert remains available");
        assert_eq!(
            runtime
                .recovery_store_id()
                .await
                .expect("read recovery identity")
                .as_deref(),
            Some("store:runtime-authorizer-test")
        );
        runtime
            .recovery_snapshot()
            .await
            .expect("bounded runtime integrity reads remain available");

        assert_rejected(&runtime, "CREATE TABLE runtime_escape(value INTEGER)").await;
        assert_rejected(
            &runtime,
            "DROP TRIGGER qualification_evidence_no_update",
        )
        .await;
        assert_rejected(&runtime, "UPDATE _sqlx_migrations SET success = 0").await;
        assert_rejected(&runtime, "PRAGMA foreign_keys = OFF").await;
        assert_rejected(&runtime, "ATTACH DATABASE ':memory:' AS escaped").await;

        let trigger_result = sqlx::query(
            "UPDATE evidence_recovery_identity SET store_id = 'store:replacement' WHERE singleton = 1",
        )
        .execute(&runtime.pool)
        .await;
        assert!(
            trigger_result.is_err(),
            "immutable evidence triggers must remain active under the runtime authorizer"
        );
        runtime.close().await;
    }
}
