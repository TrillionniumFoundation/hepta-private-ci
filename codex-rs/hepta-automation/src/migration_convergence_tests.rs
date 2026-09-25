use codex_state::open_in_memory_sqlite_pool;
use sqlx::migrate::Migrate;

use super::*;

async fn historical_pool(displaced: bool) -> SqlitePool {
    let pool = open_in_memory_sqlite_pool(1).await.expect("SQLite owner");
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

async fn reopen_persisted_history(displaced: bool, after_rebind: bool) {
    let temp = tempfile::tempdir().expect("private owner root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical owner root")
        .join("owner");
    std::fs::create_dir(&root).expect("owner directory");
    let pool = historical_pool(displaced).await;
    let before: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("original history");
    if after_rebind {
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("bounded repair");
    }
    // Reopen exactly the persisted cut before or after the repair transaction,
    // before later migrations: no live connection supplies hidden state.
    sqlx::query("VACUUM INTO ?")
        .bind(root.join(AUTOMATION_DB_FILENAME).to_str().expect("path"))
        .execute(&pool)
        .await
        .expect("persist historical cut");
    pool.close().await;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner ID");
    let store = AutomationStore::open_root(root.clone(), owner.clone())
        .await
        .expect("real open");
    let after: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("retained history");
    assert!(before.iter().all(|checksum| after.contains(checksum)));
    assert_eq!(after.len(), MIGRATOR.iter().count());
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner)
        .await
        .expect("idempotent restart");
    assert!(reopened.timer_epoch() > 0);
    reopened.close().await;
}

// Independent on-disk histories retain the default per-test watchdog and all
// checksum/restart assertions; one case cannot consume another case's budget.
#[tokio::test]
async fn canonical_cut_before_rebind_reopens() {
    reopen_persisted_history(false, false).await;
}

#[tokio::test]
async fn canonical_cut_after_rebind_reopens() {
    reopen_persisted_history(false, true).await;
}

#[tokio::test]
async fn displaced_cut_before_rebind_reopens() {
    reopen_persisted_history(true, false).await;
}

#[tokio::test]
async fn displaced_cut_after_rebind_reopens() {
    reopen_persisted_history(true, true).await;
}

#[tokio::test]
async fn occupied_relocation_rolls_back_all_history_rebinding() {
    let pool = historical_pool(/*displaced*/ true).await;
    sqlx::query("INSERT INTO _sqlx_migrations(version,description,installed_on,success,checksum,execution_time) SELECT 17,description,installed_on,success,checksum,execution_time FROM _sqlx_migrations WHERE version=4")
        .execute(&pool).await.expect("inject conflicting target identity");
    let before: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("before repair");
    assert!(reconcile_legacy_migration_ids(&pool).await.is_err());
    let after: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("after rollback");
    assert_eq!(before, after);
    pool.close().await;
}
