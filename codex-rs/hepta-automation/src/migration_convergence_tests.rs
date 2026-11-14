use sqlx::migrate::Migrate;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

async fn historical_pool(displaced: bool) -> TestResult<(tempfile::TempDir, SqlitePool)> {
    let directory = tempfile::tempdir()?;
    let sqlite_home = AbsolutePathBuf::try_from(directory.path().to_path_buf())?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&directory.path().join("historical.sqlite3"))
        .await?;
    let mut connection = pool.acquire().await?;
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await?;
    for version in 1..=3 {
        let migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == version)
            .ok_or("base migration")?;
        connection.apply("_sqlx_migrations", migration).await?;
    }
    sqlx::query(
        "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    )
    .execute(&mut *connection)
    .await?;
    for (version, source) in [
        (4, if displaced { 17 } else { 4 }),
        (5, if displaced { 18 } else { 5 }),
    ] {
        let mut migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == source)
            .ok_or("original SQL")?
            .clone();
        migration.version = version;
        connection.apply("_sqlx_migrations", &migration).await?;
    }
    drop(connection);
    Ok((directory, pool))
}

#[tokio::test]
async fn both_historical_branches_converge_without_rewriting_checksums() -> TestResult {
    for displaced in [false, true] {
        let (_directory, pool) = historical_pool(displaced).await?;
        let before: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await?;
        reconcile_legacy_migration_ids(&pool).await?;
        // A crash at this cut leaves a complete, re-runnable identity transaction.
        reconcile_legacy_migration_ids(&pool).await?;
        MIGRATOR.run(&pool).await?;
        let after: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await?;
        assert!(before.iter().all(|checksum| after.contains(checksum)));
        assert_eq!(after.len(), MIGRATOR.iter().count());
        let schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
            .fetch_one(&pool)
            .await?;
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
            .await?;
            assert_eq!(count, 1, "missing {table}");
        }
        pool.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn unknown_or_dirty_history_is_not_relabelled() -> TestResult {
    for mutation in [
        "UPDATE _sqlx_migrations SET checksum = x'00' WHERE version=4",
        "UPDATE _sqlx_migrations SET success=0 WHERE version=5",
    ] {
        let (_directory, pool) = historical_pool(/*displaced*/ true).await?;
        sqlx::query(mutation).execute(&pool).await?;
        assert!(matches!(
            reconcile_legacy_migration_ids(&pool).await,
            Err(AutomationError::Corrupt)
        ));
        let versions: Vec<i64> =
            sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await?;
        assert_eq!(versions, vec![1, 2, 3, 4, 5]);
        pool.close().await;
    }
    Ok(())
}

async fn reopen_persisted_history(displaced: bool, after_rebind: bool) -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("owner");
    std::fs::create_dir(&root)?;
    let (_directory, pool) = historical_pool(displaced).await?;
    let before: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await?;
    if after_rebind {
        reconcile_legacy_migration_ids(&pool).await?;
    }
    // Reopen exactly the persisted cut before or after the repair transaction,
    // before later migrations: no live connection supplies hidden state.
    sqlx::query("VACUUM INTO ?")
        .bind(root.join(AUTOMATION_DB_FILENAME).to_str().ok_or("path")?)
        .execute(&pool)
        .await?;
    pool.close().await;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let store = AutomationStore::open_root(root.clone(), owner.clone()).await?;
    let after: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await?;
    assert!(before.iter().all(|checksum| after.contains(checksum)));
    assert_eq!(after.len(), MIGRATOR.iter().count());
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner).await?;
    assert!(reopened.timer_epoch() > 0);
    reopened.close().await;
    Ok(())
}

// Independent on-disk histories retain the default per-test watchdog and all
// checksum/restart assertions; one case cannot consume another case's budget.
#[tokio::test]
async fn canonical_cut_before_rebind_reopens() -> TestResult {
    reopen_persisted_history(/*displaced*/ false, /*after_rebind*/ false).await
}

#[tokio::test]
async fn canonical_cut_after_rebind_reopens() -> TestResult {
    reopen_persisted_history(/*displaced*/ false, /*after_rebind*/ true).await
}

#[tokio::test]
async fn displaced_cut_before_rebind_reopens() -> TestResult {
    reopen_persisted_history(/*displaced*/ true, /*after_rebind*/ false).await
}

#[tokio::test]
async fn displaced_cut_after_rebind_reopens() -> TestResult {
    reopen_persisted_history(/*displaced*/ true, /*after_rebind*/ true).await
}

#[tokio::test]
async fn occupied_relocation_rolls_back_all_history_rebinding() -> TestResult {
    let (_directory, pool) = historical_pool(/*displaced*/ true).await?;
    sqlx::query("INSERT INTO _sqlx_migrations(version,description,installed_on,success,checksum,execution_time) SELECT 17,description,installed_on,success,checksum,execution_time FROM _sqlx_migrations WHERE version=4")
        .execute(&pool).await?;
    let before: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await?;
    assert!(reconcile_legacy_migration_ids(&pool).await.is_err());
    let after: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await?;
    assert_eq!(before, after);
    pool.close().await;
    Ok(())
}
