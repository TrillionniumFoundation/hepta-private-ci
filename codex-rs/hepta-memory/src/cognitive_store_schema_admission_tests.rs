use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::super::super::CognitiveStore;
use super::super::super::CognitiveStoreError;
use super::super::super::MIGRATOR;
use super::super::super::open_v2_test_pool;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[tokio::test]
async fn admitted_compiled_historical_prefixes_upgrade_forward() {
    for version in [2, 13, 14] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(91);
        let owner_layout = layout(&temp, &owner);
        let pool = open_v2_test_pool(&owner_layout)
            .await
            .expect("compiled v2 prefix");
        MIGRATOR
            .run_to(version, &pool)
            .await
            .expect("clean historical prefix");
        pool.close().await;
        drop(pool);
        let store = CognitiveStore::open(&owner_layout)
            .await
            .expect("clean historical schema must remain upgradeable");
        let versions: Vec<i64> =
            sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&store.pool)
                .await
                .expect("upgraded migration lineage");
        assert_eq!(
            versions,
            MIGRATOR
                .iter()
                .map(|migration| migration.version)
                .collect::<Vec<_>>()
        );
        store
            .recovery_anchor()
            .await
            .expect("upgraded owner integrity");
        store.pool.close().await;
    }
}

#[tokio::test]
async fn historical_trigger_tampering_is_rejected_before_pending_migration_executes_it() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(92);
    let owner_layout = layout(&temp, &owner);
    let pool = open_v2_test_pool(&owner_layout)
        .await
        .expect("compiled historical prefix");
    sqlx::query(
        "INSERT INTO kg_projection (projection_scope, generation) VALUES ('agent_private', 7)",
    )
    .execute(&pool)
    .await
    .expect("legacy projection targeted by migration 0003 DELETE");
    // Reuse a compiled trigger name but change its table/event and body. If
    // migration 0003 runs first, its DELETE evaluates this lazy oversized BLOB.
    sqlx::raw_sql(
        "DROP TRIGGER source_ledger_no_update;
         CREATE TRIGGER source_ledger_no_update BEFORE DELETE ON kg_projection
         BEGIN SELECT length(zeroblob(9223372036854775807)); END;",
    )
    .execute(&pool)
    .await
    .expect("fixed poisoned historical trigger");
    let path = owner_layout.cognitive_root().join("cognitive_1.sqlite3");
    pool.close().await;
    drop(pool);
    let before = std::fs::read(&path).expect("historical source bytes");
    assert!(matches!(CognitiveStore::open(&owner_layout).await,
        Err(CognitiveStoreError::Corrupt(message)) if message.contains("compiled cognitive schema definition oracle mismatch")));
    assert_eq!(
        std::fs::read(&path).expect("original source unchanged"),
        before
    );
}

#[tokio::test]
async fn migration_row_bounds_types_and_contiguous_prefix_precede_sqlx_materialization() {
    for (mutation, expected) in [
        (
            "UPDATE _sqlx_migrations SET checksum = zeroblob(1048576) WHERE version = 1",
            "exceeds bounds",
        ),
        (
            "UPDATE _sqlx_migrations SET description = CAST(zeroblob(1025) AS TEXT) WHERE version = 1",
            "exceeds bounds",
        ),
        (
            "UPDATE _sqlx_migrations SET checksum = 'wrong storage type' WHERE version = 1",
            "invalid storage types",
        ),
        (
            "DELETE FROM _sqlx_migrations WHERE version = 1",
            "continuous compiled prefix",
        ),
        (
            "INSERT INTO _sqlx_migrations (version, description, success, checksum, execution_time) VALUES (99, 'unknown migration', 1, zeroblob(48), 0)",
            "continuous compiled prefix",
        ),
        (
            "WITH RECURSIVE n(v) AS (VALUES(3) UNION ALL SELECT v + 1 FROM n WHERE v < 66) INSERT INTO _sqlx_migrations (version, description, success, checksum, execution_time) SELECT v, 'excess migration', 1, zeroblob(48), 0 FROM n",
            "unknown entries",
        ),
    ] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(93);
        let owner_layout = layout(&temp, &owner);
        let pool = open_v2_test_pool(&owner_layout)
            .await
            .expect("compiled historical prefix");
        sqlx::query(mutation)
            .execute(&pool)
            .await
            .expect("fixed poisoned ledger row");
        pool.close().await;
        drop(pool);
        let result = CognitiveStore::open(&owner_layout).await;
        let error = match result {
            Err(error) => error,
            Ok(_) => panic!("poisoned migration rows must never reach SQLx: {mutation}"),
        };
        let expected_class = match &error {
            CognitiveStoreError::Invalid(_) => expected == "exceeds bounds",
            CognitiveStoreError::Corrupt(_) => expected != "exceeds bounds",
            CognitiveStoreError::Unavailable(_)
            | CognitiveStoreError::AccessDenied(_)
            | CognitiveStoreError::Conflict(_) => false,
        };
        assert!(
            expected_class && error.to_string().contains(expected),
            "unexpected rejection: {error}"
        );
    }
}

#[tokio::test]
async fn wrong_owner_historical_database_is_denied_before_any_durable_upgrade() {
    const LEDGER_SQL: &str =
        "SELECT version, description, installed_on, success, checksum, execution_time
         FROM _sqlx_migrations ORDER BY version";
    const SCHEMA_SQL: &str = "SELECT name, type, tbl_name, sql FROM sqlite_schema ORDER BY name";
    const KG_SQL: &str =
        "SELECT projection_scope, generation FROM kg_projection ORDER BY projection_scope";
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(94);
    let owner_layout = layout(&temp, &owner);
    let pool = open_v2_test_pool(&owner_layout)
        .await
        .expect("owner A compiled historical database");
    sqlx::query(
        "INSERT INTO kg_projection (projection_scope, generation) VALUES ('agent_private', 7)",
    )
    .execute(&pool)
    .await
    .expect("legacy projection that migration 0003 would delete");
    let ledger_before: Vec<(i64, String, String, i64, Vec<u8>, i64)> = sqlx::query_as(LEDGER_SQL)
        .fetch_all(&pool)
        .await
        .expect("complete historical migration ledger");
    assert_eq!(
        ledger_before.iter().map(|row| row.0).collect::<Vec<_>>(),
        vec![1, 2]
    );
    let schema_before: Vec<(String, String, String, Option<String>)> = sqlx::query_as(SCHEMA_SQL)
        .fetch_all(&pool)
        .await
        .expect("complete historical schema");
    let kg_before: Vec<(String, i64)> = sqlx::query_as(KG_SQL)
        .fetch_all(&pool)
        .await
        .expect("historical KG projection");
    assert_eq!(kg_before, vec![("agent_private".to_string(), 7)]);
    pool.close().await;
    drop(pool);

    let other_layout = layout(&temp, &agent_id(95));
    super::super::super::create_private_directory(other_layout.cognitive_root())
        .expect("owner B regular private root");
    let copied = other_layout.cognitive_root().join("cognitive_1.sqlite3");
    std::fs::copy(
        owner_layout.cognitive_root().join("cognitive_1.sqlite3"),
        &copied,
    )
    .expect("copy owner A cold historical database into owner B path");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&copied, std::fs::Permissions::from_mode(0o600))
            .expect("retain the required private database mode");
    }
    let bytes_before = std::fs::read(&copied).expect("copied historical source bytes");
    assert!(matches!(CognitiveStore::open(&other_layout).await,
        Err(CognitiveStoreError::AccessDenied(message)) if message == "cognitive database belongs to a different agent"));
    assert_eq!(
        std::fs::read(&copied).expect("source unchanged after denial"),
        bytes_before
    );

    // Inspect through the private SQLite shim without running migrations or
    // rebinding an owner. Compare complete records, not just migration counts.
    let home = codex_utils_absolute_path::AbsolutePathBuf::try_from(
        other_layout.cognitive_root().to_path_buf(),
    )
    .expect("regular private inspection home");
    let inspection = codex_state::SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&copied)
        .await
        .expect("inspect unchanged historical database");
    let ledger_after: Vec<(i64, String, String, i64, Vec<u8>, i64)> = sqlx::query_as(LEDGER_SQL)
        .fetch_all(&inspection)
        .await
        .expect("retained complete ledger");
    let schema_after: Vec<(String, String, String, Option<String>)> = sqlx::query_as(SCHEMA_SQL)
        .fetch_all(&inspection)
        .await
        .expect("retained complete schema");
    let kg_after: Vec<(String, i64)> = sqlx::query_as(KG_SQL)
        .fetch_all(&inspection)
        .await
        .expect("retained legacy KG projection");
    assert_eq!(
        (ledger_after, schema_after, kg_after),
        (ledger_before, schema_before, kg_before)
    );
    inspection.close().await;
}
