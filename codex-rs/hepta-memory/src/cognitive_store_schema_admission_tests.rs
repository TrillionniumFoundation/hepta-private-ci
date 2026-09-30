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
