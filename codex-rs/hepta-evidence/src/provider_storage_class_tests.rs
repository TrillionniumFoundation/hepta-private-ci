use codex_state::SqliteConfig;
use tempfile::TempDir;

use super::completed;
use super::ephemeral_intent;
use super::intent;
use super::sqlite_config;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;

// Exercise the ordinary durable reader with the original schema, triggers and
// canonical payload still present. A fixture-only connection temporarily
// suspends CHECK enforcement to create corrupt integer storage classes too.
// Restore the original constraints and trigger before the ordinary reader runs.
async fn corrupt_provider_storage_class(
    store: &HeptaEvidenceStore,
    sqlite: &SqliteConfig,
    table: &str,
    column: &str,
) {
    assert!(matches!(
        table,
        "provider_invocation_intents" | "provider_invocation_terminals"
    ));
    assert!(matches!(
        column,
        "payload_json"
            | "payload_sha256"
            | "thread_id"
            | "generate"
            | "schema_version"
            | "ephemeral_input_sha256"
    ));
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    let trigger_name = format!("{table}_no_update");
    let trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
    )
    .bind(&trigger_name)
    .fetch_one(&raw)
    .await
    .expect("original immutable trigger");
    let mut transaction = raw.begin().await.expect("corruption transaction");
    let original_schema: Vec<(String, String, Option<String>)> =
        sqlx::query_as("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
            .fetch_all(&mut *transaction)
            .await
            .expect("original complete schema");
    let checks_ignored: i64 = sqlx::query_scalar("PRAGMA ignore_check_constraints")
        .fetch_one(&mut *transaction)
        .await
        .expect("original CHECK enforcement");
    assert_eq!(checks_ignored, 0);
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(&mut *transaction)
        .await
        .expect("allow deliberate storage corruption on this fixture connection");
    let suspended: i64 = sqlx::query_scalar("PRAGMA ignore_check_constraints")
        .fetch_one(&mut *transaction)
        .await
        .expect("fixture CHECK suspension");
    assert_eq!(suspended, 1);
    sqlx::query(sqlx::AssertSqlSafe(format!("DROP TRIGGER {trigger_name}")))
        .execute(&mut *transaction)
        .await
        .expect("temporarily remove original trigger in fixture transaction");
    let update = format!("UPDATE {table} SET {column} = CAST({column} AS BLOB)");
    let changed = sqlx::query(sqlx::AssertSqlSafe(update))
        .execute(&mut *transaction)
        .await
        .expect("change only the SQLite storage class");
    assert_eq!(changed.rows_affected(), 1);
    let storage_type: String = sqlx::query_scalar(sqlx::AssertSqlSafe(format!(
        "SELECT typeof({column}) FROM {table}"
    )))
    .fetch_one(&mut *transaction)
    .await
    .expect("actual stored type");
    assert_eq!(storage_type, "blob");
    sqlx::query(sqlx::AssertSqlSafe(trigger.clone()))
        .execute(&mut *transaction)
        .await
        .expect("restore the exact original trigger");
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(&mut *transaction)
        .await
        .expect("restore CHECK enforcement before the ordinary read");
    let restored_checks: i64 = sqlx::query_scalar("PRAGMA ignore_check_constraints")
        .fetch_one(&mut *transaction)
        .await
        .expect("restored CHECK enforcement");
    assert_eq!(restored_checks, checks_ignored);
    let restored_schema: Vec<(String, String, Option<String>)> =
        sqlx::query_as("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
            .fetch_all(&mut *transaction)
            .await
            .expect("restored complete schema");
    assert_eq!(restored_schema, original_schema);
    transaction.commit().await.expect("commit restored-schema corruption");
    let restored: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
    )
    .bind(&trigger_name)
    .fetch_one(&raw)
    .await
    .expect("restored trigger");
    assert_eq!(restored, trigger);
    raw.close().await;
}

#[tokio::test]
async fn ordinary_provider_intent_storage_class_corruption_returns_corrupt_without_panic() {
    for column in [
        "payload_json",
        "payload_sha256",
        "thread_id",
        "generate",
        "schema_version",
        "ephemeral_input_sha256",
    ] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let intent = ephemeral_intent(/*nonce*/ 111, "storage-class-intent");
        store.append_provider_intent(&intent).await.expect("intent");
        assert!(store
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect("valid ordinary read before corruption")
            .is_some());
        corrupt_provider_storage_class(&store, &sqlite, "provider_invocation_intents", column)
            .await;
        let error = store
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect_err("ordinary provider intent reader must return corruption");
        assert!(matches!(error, EvidenceError::Corrupt(ref detail)
            if detail.contains(&format!("invalid provider {column} column"))));
    }
}

#[tokio::test]
async fn ordinary_provider_terminal_storage_class_corruption_returns_corrupt_without_panic() {
    for column in ["payload_json", "payload_sha256", "thread_id", "schema_version"] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let intent = intent(112);
        store.append_provider_intent(&intent).await.expect("intent");
        let receipt = completed(intent.clone(), b"storage-class-result");
        store
            .append_provider_receipt(&receipt)
            .await
            .expect("terminal");
        assert!(store
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect("valid ordinary read before corruption")
            .is_some());
        corrupt_provider_storage_class(&store, &sqlite, "provider_invocation_terminals", column)
            .await;
        let error = store
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect_err("ordinary provider terminal reader must return corruption");
        assert!(matches!(error, EvidenceError::Corrupt(ref detail)
            if detail.contains(&format!("invalid provider {column} column"))));
    }
}
