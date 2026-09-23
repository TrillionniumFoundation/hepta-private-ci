use sqlx::migrate::Migrate;
use sqlx::sqlite::SqlitePoolOptions;

use super::*;

async fn historical_pool(displaced: bool) -> SqlitePool {
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .expect("SQLite owner");
    let mut connection = pool.acquire().await.expect("owner connection");
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await
        .expect("migration journal");
    for version in 1..=3 {
        let migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == version)
            .expect("base migration");
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("base schema");
    }
    sqlx::query(
        "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    )
    .execute(&mut *connection)
    .await
    .expect("historical owner");
    for (version, source) in [
        (4, if displaced { 17 } else { 4 }),
        (5, if displaced { 18 } else { 5 }),
    ] {
        let mut migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == source)
            .expect("original SQL")
            .clone();
        migration.version = version;
        connection
            .apply("_sqlx_migrations", &migration)
            .await
            .expect("historical branch migration");
    }
    drop(connection);
    pool
}

#[tokio::test]
async fn both_historical_branches_converge_without_rewriting_checksums() {
    for displaced in [false, true] {
        let pool = historical_pool(displaced).await;
        let before: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("original identities");
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("explicit remapping");
        // A crash at this cut leaves a complete, re-runnable identity transaction.
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("idempotent reopen");
        MIGRATOR
            .run(&pool)
            .await
            .expect("complete canonical schema");
        let after: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("retained checksums");
        assert!(before.iter().all(|checksum| after.contains(checksum)));
        assert_eq!(after.len(), MIGRATOR.iter().count());
        let schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
            .fetch_one(&pool)
            .await
            .expect("schema");
        assert_eq!(schema, i64::from(AUTOMATION_SCHEMA_VERSION));
        for table in [
            "automation_schedule_metadata",
            "automation_occurrence_lifecycle",
            "destination_operation_dedupe",
            "automation_timer_lifecycle",
        ] {
            let count: i64 = sqlx::query_scalar(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
            )
            .bind(table)
            .fetch_one(&pool)
            .await
            .expect("schema inventory");
            assert_eq!(count, 1, "missing {table}");
        }
        pool.close().await;
    }
}

#[tokio::test]
async fn unknown_or_dirty_history_is_not_relabelled() {
    for mutation in [
        "UPDATE _sqlx_migrations SET checksum = x'00' WHERE version=4",
        "UPDATE _sqlx_migrations SET success=0 WHERE version=5",
    ] {
        let pool = historical_pool(true).await;
        sqlx::query(mutation)
            .execute(&pool)
            .await
            .expect("fault injection");
        assert!(matches!(
            reconcile_legacy_migration_ids(&pool).await,
            Err(AutomationError::Corrupt)
        ));
        let versions: Vec<i64> =
            sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("unchanged identities");
        assert_eq!(versions, vec![1, 2, 3, 4, 5]);
        pool.close().await;
    }
}
