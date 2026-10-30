use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn altered_append_default_fails_reopen_with_triggers_and_migration_checksums_intact() {
    for table in [
        "taskflow_effect_dispatch_attempts",
        "taskflow_effect_provider_bindings",
        "taskflow_effect_dispatch_observations",
        "taskflow_effect_dispatch_reconciliations",
    ] {
        let mut original = legacy_effect(LegacyReceipt::LostAcceptedV20).await;
        original.reopen().await;
        let preserved = "SELECT name,sql FROM main.sqlite_schema WHERE type='trigger'
                         UNION ALL SELECT CAST(version AS TEXT),hex(checksum)
                         FROM main._sqlx_migrations ORDER BY 1";
        let before: Vec<(String, String)> = sqlx::query_as(preserved)
            .fetch_all(&original.store.pool)
            .await
            .expect("original guards and migration history");
        let mut connection = original
            .store
            .pool
            .acquire()
            .await
            .expect("catalog fault injection");
        sqlx::query("PRAGMA writable_schema=ON")
            .execute(&mut *connection)
            .await
            .expect("enable catalog injection");
        let changed = sqlx::query(
            "UPDATE main.sqlite_schema SET sql=replace(sql,'DEFAULT 0','DEFAULT 1')
             WHERE type='table' AND name=? AND sql LIKE '%append_profile_version INTEGER NOT NULL DEFAULT 0%'",
        ).bind(table).execute(&mut *connection).await.expect("alter one persisted column default");
        assert_eq!(changed.rows_affected(), 1);
        sqlx::query("PRAGMA writable_schema=OFF")
            .execute(&mut *connection)
            .await
            .expect("end catalog injection");
        let after: Vec<(String, String)> = sqlx::query_as(preserved)
            .fetch_all(&mut *connection)
            .await
            .expect("unchanged guards and checksums");
        assert_eq!(after, before);
        drop(connection);
        original.store.close().await;
        let result =
            AutomationStore::open_root(original.root, original.store.owner_agent_id.clone()).await;
        match result {
            Err(AutomationError::Corrupt) => {}
            Ok(reopened) => {
                reopened.close().await;
                panic!("changed append default was accepted on reopen for {table}");
            }
            Err(error) => panic!("unexpected reopen failure for {table}: {error}"),
        }
    }
}
