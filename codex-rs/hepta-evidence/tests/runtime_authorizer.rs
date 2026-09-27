//! These are native SQLx tests, not tests of a Python authorization model.

use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Cases {
    setup_sql: String,
    denied_sql: Vec<String>,
    allowed_sql: Vec<String>,
}

fn cases() -> Cases {
    serde_json::from_str(include_str!(
        "../../../qualification/kernel-evidence/SQLITE_RUNTIME_CASES.json"
    ))
    .expect("authorizer fixture")
}

fn config(home: &tempfile::TempDir) -> SqliteConfig {
    SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::from_absolute_path(home.path()).expect("absolute fixture directory"),
    )
}

#[tokio::test]
async fn all_runtime_connections_and_reopened_pools_reject_privilege_changes() {
    let home = tempfile::tempdir().expect("temporary directory");
    let config = config(&home);
    let path = home.path().join("authorizer-contract.sqlite");
    let cases = cases();
    let migration = config
        .open_durable_evidence_pool(&path)
        .await
        .expect("controlled migration pool");
    sqlx::raw_sql(&cases.setup_sql)
        .execute(&migration)
        .await
        .expect("fixture migration");
    migration.close().await;

    for _ in 0..2 {
        let runtime = config
            .open_durable_evidence_runtime_pool(&path)
            .await
            .expect("restricted runtime pool");
        // Hold every lease so this actually tests five different connections.
        let mut connections = Vec::new();
        for _ in 0..5 {
            connections.push(runtime.acquire().await.expect("pool connection"));
        }
        for connection in &mut connections {
            for sql in &cases.denied_sql {
                let error = sqlx::raw_sql(sql)
                    .execute(&mut **connection)
                    .await
                    .expect_err("forbidden SQL must fail");
                let code = error.as_database_error()
                    .and_then(|error| error.code())
                    .and_then(|code| code.parse::<i32>().ok())
                    .expect("SQLite error code");
                assert!(
                    matches!(code & 0xff, 23 | 19),
                    "{sql:?} failed for an unrelated reason: {error}"
                );
            }
            for sql in &cases.allowed_sql {
                sqlx::raw_sql(sql)
                    .execute(&mut **connection)
                    .await
                    .unwrap_or_else(|error| panic!("allowed SQL {sql:?} failed: {error}"));
            }
            for (pragma, expected) in [
                ("PRAGMA recursive_triggers", 1_i64),
                ("PRAGMA foreign_keys", 1_i64),
                ("PRAGMA synchronous", 2_i64),
            ] {
                let actual: i64 = sqlx::query_scalar(pragma)
                    .fetch_one(&mut **connection)
                    .await
                    .expect("read enforced pragma");
                assert_eq!(actual, expected);
            }
        }
        drop(connections);
        runtime.close().await;
    }

    // Runtime denial must not prevent an explicit, separately opened migration.
    let migration = config
        .open_durable_evidence_pool(&path)
        .await
        .expect("controlled next migration pool");
    sqlx::query("CREATE TABLE next_migration (id INTEGER PRIMARY KEY)")
        .execute(&migration)
        .await
        .expect("administrative DDL is separate from runtime authority");
    migration.close().await;
}

#[tokio::test]
async fn runtime_allows_autoincrement_transactions_and_idempotent_insert() {
    let home = tempfile::tempdir().expect("temporary directory");
    let config = config(&home);
    let path = home.path().join("authorizer-transaction.sqlite");
    let migration = config.open_durable_evidence_pool(&path).await.expect("migration");
    sqlx::raw_sql(&cases().setup_sql).execute(&migration).await.expect("fixture");
    migration.close().await;
    let runtime = config.open_durable_evidence_runtime_pool(&path).await.expect("runtime");
    let mut transaction = runtime.begin().await.expect("begin");
    for id in ["evidence:new", "evidence:new"] {
        sqlx::query("INSERT INTO qualification_evidence(evidence_id) VALUES (?) ON CONFLICT DO NOTHING")
            .bind(id)
            .execute(&mut *transaction)
            .await
            .expect("append without direct sqlite_sequence authority");
    }
    transaction.commit().await.expect("commit");
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
        .fetch_one(&runtime).await.expect("count");
    assert_eq!(count, 2);
    runtime.close().await;
}

#[tokio::test]
async fn product_runtime_revalidates_real_migrations_and_recovers_its_identity() {
    let home = tempfile::tempdir().expect("temporary directory");
    let config = config(&home);
    let store = HeptaEvidenceStore::open_runtime(&config).await.expect("real runtime schema");
    store.bind_recovery_store_id("store:runtime-authorizer").await.expect("bind identity");
    let before = store.recovery_snapshot().await.expect("runtime snapshot");
    store.close().await;
    let reopened = HeptaEvidenceStore::open_runtime(&config).await.expect("reopened runtime");
    assert_eq!(reopened.recovery_store_id().await.expect("identity"), Some("store:runtime-authorizer".to_string()));
    assert_eq!(reopened.recovery_snapshot().await.expect("snapshot"), before);
    reopened.close().await;
}

#[tokio::test]
async fn runtime_opener_does_not_create_a_missing_database() {
    let home = tempfile::tempdir().expect("temporary directory");
    let path = home.path().join("must-not-be-created.sqlite");
    assert!(config(&home).open_durable_evidence_runtime_pool(&path).await.is_err());
    assert!(!path.exists());
}
