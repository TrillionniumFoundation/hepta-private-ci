use super::*;
use sqlx::migrate::Migrate;

#[derive(Clone, Copy)]
enum HistoricalProfile {
    Circuit,
    ProviderRecovery,
}

#[derive(Clone, Copy)]
enum RestartCut {
    BeforeRelabel,
    AfterRelabel,
}

type MigrationRecord = (i64, String, String, bool, Vec<u8>, i64);

async fn migration_records(pool: &SqlitePool) -> Vec<MigrationRecord> {
    sqlx::query_as(
        "SELECT version, description, installed_on, success, checksum, execution_time
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .expect("complete migration identities")
}

async fn historical_recovery_pool(profile: HistoricalProfile) -> (tempfile::TempDir, SqlitePool) {
    let directory = tempfile::tempdir().expect("private history root");
    let root = directory.path().canonicalize().expect("canonical root");
    let pool = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(root.clone()).expect("absolute fixture root"),
    )
    .open_durable_evidence_pool(&root.join("historical.sqlite3"))
    .await
    .expect("historical owner database");
    let mut connection = pool.acquire().await.expect("owner connection");
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await
        .expect("original migration journal");
    for version in 1..=19 {
        let migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == version)
            .expect("shared original migration");
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("apply exact original SQL");
        if version == 3 {
            sqlx::query(
                "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
            )
            .execute(&mut *connection)
            .await
            .expect("historical owner identity");
        }
    }
    let versions: &[i64] = match profile {
        HistoricalProfile::Circuit => &[20, 21, 22],
        HistoricalProfile::ProviderRecovery => &[23],
    };
    for version in versions {
        let mut migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == *version)
            .expect("historical branch SQL")
            .clone();
        if matches!(profile, HistoricalProfile::ProviderRecovery) {
            migration.version = 20;
        }
        connection
            .apply("_sqlx_migrations", &migration)
            .await
            .expect("original independently numbered branch migration");
    }
    drop(connection);
    (directory, pool)
}

async fn reopen_recovery_history(profile: HistoricalProfile, cut: RestartCut) {
    let (directory, pool) = historical_recovery_pool(profile).await;
    let original = migration_records(&pool).await;
    if matches!(cut, RestartCut::AfterRelabel) {
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("commit identity-only reconciliation");
    }
    let retained = tempfile::tempdir().expect("retained owner root");
    let root = retained.path().canonicalize().expect("canonical owner");
    sqlx::query("VACUUM INTO ?")
        .bind(root.join(AUTOMATION_DB_FILENAME).to_str().expect("path"))
        .execute(&pool)
        .await
        .expect("persist the exact restart cut");
    pool.close().await;
    drop(directory);
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    let store = AutomationStore::open_root(root.clone(), owner.clone())
        .await
        .expect("real owner reopen applies both histories once");
    let after = migration_records(&store.pool).await;
    for mut record in original {
        if matches!(profile, HistoricalProfile::ProviderRecovery) && record.0 == 20 {
            record.0 = 23;
        }
        assert!(
            after.contains(&record),
            "original migration identity was changed"
        );
    }
    assert_eq!(after.len(), MIGRATOR.iter().count());
    let schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
        .fetch_one(&store.pool)
        .await
        .expect("composed owner schema");
    assert_eq!(schema, i64::from(AUTOMATION_SCHEMA_VERSION));
    for column in ["provider_effect_key", "wire_payload"] {
        let count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM pragma_table_info('taskflow_effect_dispatch_attempts') WHERE name = ?",
        )
        .bind(column)
        .fetch_one(&store.pool)
        .await
        .expect("exact recovery columns");
        assert_eq!(count, 1);
    }
    for table in [
        "circuit_v2_definitions",
        "circuit_v2_runs",
        "circuit_v2_events",
        "circuit_learning_outbox_v1",
    ] {
        let count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
        )
        .bind(table)
        .fetch_one(&store.pool)
        .await
        .expect("retained Circuit schema");
        assert_eq!(count, 1);
    }
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner)
        .await
        .expect("idempotent second cold restart");
    assert_eq!(migration_records(&reopened.pool).await, after);
    reopened.close().await;
}

#[tokio::test]
async fn circuit_history_before_relabel_reopens_with_recovery_material() {
    reopen_recovery_history(HistoricalProfile::Circuit, RestartCut::BeforeRelabel).await;
}

#[tokio::test]
async fn circuit_history_after_relabel_reopens_with_recovery_material() {
    reopen_recovery_history(HistoricalProfile::Circuit, RestartCut::AfterRelabel).await;
}

#[tokio::test]
async fn recovery_history_before_relabel_retains_original_checksum_and_circuit() {
    reopen_recovery_history(
        HistoricalProfile::ProviderRecovery,
        RestartCut::BeforeRelabel,
    )
    .await;
}

#[tokio::test]
async fn recovery_history_after_relabel_retains_original_checksum_and_circuit() {
    reopen_recovery_history(
        HistoricalProfile::ProviderRecovery,
        RestartCut::AfterRelabel,
    )
    .await;
}

#[tokio::test]
async fn unknown_dirty_or_occupied_provider_history_is_never_relabelled() {
    for mutation in [
        "UPDATE _sqlx_migrations SET checksum = x'00' WHERE version = 20",
        "UPDATE _sqlx_migrations SET success = 0 WHERE version = 20",
        "INSERT INTO _sqlx_migrations(version, description, installed_on, success, checksum, execution_time) SELECT 23, description, installed_on, success, checksum, execution_time FROM _sqlx_migrations WHERE version = 20",
    ] {
        let (_directory, pool) =
            historical_recovery_pool(HistoricalProfile::ProviderRecovery).await;
        sqlx::query(mutation)
            .execute(&pool)
            .await
            .expect("explicit corrupt-history injection");
        let before = migration_records(&pool).await;
        assert!(reconcile_legacy_migration_ids(&pool).await.is_err());
        assert_eq!(migration_records(&pool).await, before);
        pool.close().await;
    }
}
