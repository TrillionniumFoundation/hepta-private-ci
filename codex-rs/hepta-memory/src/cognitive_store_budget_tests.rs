use sqlx::Connection;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

fn assert_budget_error(result: Result<(), CognitiveStoreError>) {
    assert!(
        matches!(result, Err(CognitiveStoreError::Invalid(message)) if message.contains("startup row/byte bounds")),
        "oversized logical state must be rejected before materialization"
    );
}

#[tokio::test]
async fn admission_accumulates_rows_and_bytes_across_tables() {
    let mut connection = SqliteConnection::connect("sqlite::memory:")
        .await
        .expect("connection");
    // Small aggregate fixtures isolate admission without allocating the
    // production byte budget. Names remain from the compiled table inventory.
    sqlx::query(
        "CREATE TABLE cognitive_local_events(payload BLOB);
         CREATE TABLE cognitive_local_outbox(payload BLOB);
         INSERT INTO cognitive_local_events VALUES (zeroblob(100));
         INSERT INTO cognitive_local_outbox VALUES (zeroblob(100));",
    )
    .execute(&mut connection)
    .await
    .expect("seed tables");
    let tables = ["cognitive_local_events", "cognitive_local_outbox"];
    assert_budget_error(
        verify_tables(
            &mut connection,
            &tables,
            Budget {
                remaining_rows: 1,
                remaining_bytes: 4096,
            },
        )
        .await,
    );
    assert_budget_error(
        verify_tables(
            &mut connection,
            &tables,
            Budget {
                remaining_rows: 4,
                remaining_bytes: 200,
            },
        )
        .await,
    );
    verify_tables(
        &mut connection,
        &tables,
        Budget {
            remaining_rows: 2,
            remaining_bytes: 4096,
        },
    )
    .await
    .expect("exact row budget must remain usable");
}

#[tokio::test]
async fn admission_rejects_production_row_limit_before_fetching_history() {
    let mut connection = SqliteConnection::connect("sqlite::memory:")
        .await
        .expect("connection");
    sqlx::query(
        "CREATE TABLE cognitive_local_events(payload BLOB);
         WITH RECURSIVE rows(n) AS (
             SELECT 1 UNION ALL SELECT n + 1 FROM rows WHERE n < 262145
         ) INSERT INTO cognitive_local_events SELECT NULL FROM rows;",
    )
    .execute(&mut connection)
    .await
    .expect("seed oversized row count");
    assert_budget_error(
        verify_tables(
            &mut connection,
            &["cognitive_local_events"],
            Budget::default(),
        )
        .await,
    );
}

#[tokio::test]
async fn admission_rejects_single_oversized_row_before_fetching_payload() {
    let mut connection = SqliteConnection::connect("sqlite::memory:")
        .await
        .expect("connection");
    sqlx::query("CREATE TABLE cognitive_local_events(payload BLOB)")
        .execute(&mut connection)
        .await
        .expect("table");
    sqlx::query("INSERT INTO cognitive_local_events VALUES (zeroblob(?))")
        .bind(MAX_ROW_BYTES)
        .execute(&mut connection)
        .await
        .expect("seed oversized framed row");
    assert_budget_error(
        verify_tables(
            &mut connection,
            &["cognitive_local_events"],
            Budget::default(),
        )
        .await,
    );
}

#[tokio::test]
async fn ordinary_open_admits_budget_before_integrity_and_content_materialization() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(88);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    store
        .append_source(
            &CognitiveAccess::agent_private(owner.clone()),
            &source(CognitiveScope::AgentPrivate, "budget", "evidence"),
        )
        .await
        .expect("source");
    // Save the exact guard from an admitted compiled schema before tampering.
    let guard: String =
        sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = 'source_ledger_no_update'")
            .fetch_one(&store.pool)
            .await
            .expect("compiled guard");
    let mut transaction = store.pool.begin().await.expect("tamper transaction");
    sqlx::query(
        "DROP TRIGGER source_ledger_no_update;
         PRAGMA ignore_check_constraints = ON;
         UPDATE source_ledger SET content = zeroblob(2097152);
         PRAGMA ignore_check_constraints = OFF;",
    )
    .execute(&mut *transaction)
    .await
    .expect("oversized owner row");
    sqlx::query(sqlx::AssertSqlSafe(guard.as_str()))
        .execute(&mut *transaction)
        .await
        .expect("restore exact admitted immutable guard");
    transaction.commit().await.expect("commit tamper");
    store.pool.close().await;
    drop(store);
    match CognitiveStore::open(&layout(&temp, &owner)).await {
        Err(error) => assert_budget_error(Err(error)),
        Ok(_) => panic!("oversized owner state must not reopen"),
    }
}

#[tokio::test]
async fn each_journal_validator_admits_its_own_snapshot_before_loading_chains() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(89);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(&mut *connection)
        .await
        .expect("allow oversized adversarial payload");
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES ('budget-lease', 1, 'budget-event', 'budget-occurrence', ?,
            1, 'budget-fence', 'admitted', CAST(zeroblob(2097152) AS TEXT), ?, ?, ?, 0)",
    )
    .bind(owner.as_str())
    .bind("0".repeat(64))
    .bind("0".repeat(64))
    .bind("0".repeat(64))
    .execute(&mut *connection)
    .await
    .expect("oversized event in exact compiled schema");
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(&mut *connection)
        .await
        .expect("restore check policy");
    drop(connection);
    assert_budget_error(
        crate::local_lease_outbox::verify_local_lease_outbox(&store.pool, &owner).await,
    );
    assert_budget_error(
        crate::logical_turn_registry::verify_logical_turn_registry(&store.pool, &owner).await,
    );
    assert_budget_error(
        crate::local_compact_executor::verify_local_compact_events(&store.pool, &owner).await,
    );
    store.pool.close().await;
}
