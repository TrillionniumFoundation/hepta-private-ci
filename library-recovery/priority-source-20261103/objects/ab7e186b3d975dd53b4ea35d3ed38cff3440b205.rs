use super::*;
type ProofRow = (i64, String, String, String, String, String, i64);

#[tokio::test]
async fn immutable_proof_rejects_logical_and_rowid_replace_with_recursive_triggers_off() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("PRAGMA recursive_triggers = OFF").execute(&mut *connection).await.expect("off");
    let mode: i64 = sqlx::query_scalar("PRAGMA recursive_triggers").fetch_one(&mut *connection).await.expect("mode");
    assert_eq!(mode, 0);
    sqlx::query("INSERT INTO cognitive_operation_destination_terminal VALUES ('dest','op',?, 'applied','proof',1)")
        .bind("a".repeat(64)).execute(&mut *connection).await.expect("first insert");
    let before: Vec<ProofRow> = sqlx::query_as("SELECT rowid,* FROM cognitive_operation_destination_terminal ORDER BY rowid")
        .fetch_all(&mut *connection).await.expect("before");
    for (operation, disposition, evidence, rowid) in [
        ("op", "applied", "proof", before[0].0),
        ("op", "not_applied", "contradictory", before[0].0),
        ("different-logical-identity", "not_applied", "rowid bypass", before[0].0),
    ] {
        let result = sqlx::query("INSERT OR REPLACE INTO cognitive_operation_destination_terminal(rowid,destination_id,operation_id,semantic_sha256,disposition,evidence,recorded_at_unix_ms) VALUES (?,'dest',?,?,?,?,1)")
            .bind(rowid).bind(operation).bind("a".repeat(64)).bind(disposition).bind(evidence)
            .execute(&mut *connection).await;
        assert!(result.is_err(), "replacement must be refused");
        let after: Vec<ProofRow> = sqlx::query_as("SELECT rowid,* FROM cognitive_operation_destination_terminal ORDER BY rowid")
            .fetch_all(&mut *connection).await.expect("after");
        assert_eq!(after, before);
    }
    sqlx::query("INSERT INTO cognitive_operation_destination_terminal VALUES ('dest','new',?,'applied','new proof',2)")
        .bind("b".repeat(64)).execute(&mut *connection).await.expect("normal subsequent insert");
}

#[tokio::test]
async fn missing_or_modified_proof_insert_guard_is_rejected_on_reopen() {
    for modified in [false, true] {
        let temp = TempDir::new().expect("temp");
        let opened = store(&temp).await;
        sqlx::query("DROP TRIGGER cognitive_operation_destination_terminal_no_replace")
            .execute(&opened.pool).await.expect("remove guard fixture");
        if modified {
            sqlx::query("CREATE TRIGGER cognitive_operation_destination_terminal_no_replace BEFORE INSERT ON cognitive_operation_destination_terminal BEGIN SELECT 1; END")
                .execute(&opened.pool).await.expect("weaken guard fixture");
        }
        opened.pool.close().await;
        drop(opened);
        let root = temp.path().join("fleet-real-target");
        let fleet = HeptaFleetRoot::parse(root.canonicalize().expect("canonical root")).expect("fleet");
        let reopened = CognitiveStore::open(&fleet.layout().agent(&agent())).await;
        assert!(matches!(reopened, Err(crate::CognitiveStoreError::Corrupt(_))));
    }
}
