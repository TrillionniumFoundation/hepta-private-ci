//! The oracle must accept the exact compiled migration schema and still reject
//! missing or behaviorally changed definitions when reopening existing state.

use super::*;
use tempfile::TempDir;

async fn fixture() -> (TempDir, HeptaAgentLayout, CognitiveStore) {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("fleet");
    std::fs::create_dir(&root).unwrap();
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(root).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c060").unwrap();
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    (temp, layout, store)
}

#[tokio::test]
async fn compiled_schema_matches_complete_required_oracle_on_reopen() {
    assert_eq!(REQUIRED_SCHEMA_OBJECTS.len(), 132);
    let (_temp, layout, store) = fixture().await;
    sqlx::query("INSERT INTO cognitive_operation_destination_terminal VALUES ('destination', 'operation', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'applied', 'proof', 1)")
        .execute(&store.pool).await.unwrap();
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&layout).await.unwrap();
    let evidence: String = sqlx::query_scalar("SELECT evidence FROM cognitive_operation_destination_terminal WHERE destination_id = 'destination' AND operation_id = 'operation'")
        .fetch_one(&reopened.pool).await.unwrap();
    assert_eq!(evidence, "proof");
}

#[tokio::test]
async fn each_required_terminal_object_is_rejected_when_missing_on_reopen() {
    for (statement, object_name) in [
        (
            "DROP TABLE cognitive_operation_destination_terminal",
            "cognitive_operation_destination_terminal",
        ),
        (
            "DROP INDEX cognitive_operation_destination_terminal_disposition_lookup",
            "cognitive_operation_destination_terminal_disposition_lookup",
        ),
        (
            "DROP TRIGGER cognitive_operation_destination_terminal_no_update",
            "cognitive_operation_destination_terminal_no_update",
        ),
        (
            "DROP TRIGGER cognitive_operation_destination_terminal_no_delete",
            "cognitive_operation_destination_terminal_no_delete",
        ),
    ] {
        let (_temp, layout, store) = fixture().await;
        sqlx::query(statement).execute(&store.pool).await.unwrap();
        let remaining: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_schema WHERE name = ?")
                .bind(object_name)
                .fetch_one(&store.pool)
                .await
                .unwrap();
        assert_eq!(remaining, 0, "tamper precondition for {object_name}");
        store.pool.close().await;
        drop(store);
        let error = CognitiveStore::open(&layout)
            .await
            .err()
            .expect("missing required object must reject reopen");
        assert!(matches!(error, CognitiveStoreError::Corrupt(_)), "{error}");
    }
}

#[tokio::test]
async fn same_name_weakened_terminal_trigger_is_rejected_on_reopen() {
    let (_temp, layout, store) = fixture().await;
    let mut transaction = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    sqlx::query("DROP TRIGGER cognitive_operation_destination_terminal_no_delete")
        .execute(&mut *transaction)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER cognitive_operation_destination_terminal_no_delete BEFORE DELETE ON cognitive_operation_destination_terminal BEGIN SELECT 1; END")
        .execute(&mut *transaction).await.unwrap();
    transaction.commit().await.unwrap();
    let definition: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = 'cognitive_operation_destination_terminal_no_delete'")
        .fetch_one(&store.pool).await.unwrap();
    assert_eq!(
        definition,
        "CREATE TRIGGER cognitive_operation_destination_terminal_no_delete BEFORE DELETE ON cognitive_operation_destination_terminal BEGIN SELECT 1; END"
    );
    store.pool.close().await;
    drop(store);
    let error = CognitiveStore::open(&layout)
        .await
        .err()
        .expect("weakened trigger must reject reopen");
    assert!(matches!(error, CognitiveStoreError::Corrupt(_)), "{error}");
    assert!(
        error
            .to_string()
            .contains("schema definition oracle mismatch")
    );
}
