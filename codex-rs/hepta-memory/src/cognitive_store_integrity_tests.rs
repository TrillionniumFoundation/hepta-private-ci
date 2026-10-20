use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;

async fn seeded(temp: &TempDir) -> CognitiveStore {
    let owner = agent_id(86);
    let store = CognitiveStore::open(&layout(temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let citation = store
        .append_source(
            &access,
            &source(CognitiveScope::AgentPrivate, "integrity", "alpha evidence"),
        )
        .await
        .expect("source");
    store
        .create_memory(
            &access,
            &MemoryDraft {
                stable_key: "integrity".to_string(),
                revision: memory_revision(CognitiveScope::AgentPrivate, "alpha evidence", citation),
            },
        )
        .await
        .expect("memory");
    store
}

#[tokio::test]
async fn reopening_rejects_memory_fts_content_and_cardinality_tampering() {
    for mutation in [
        "UPDATE memory_fts SET content = 'injected retrieval terms'",
        "DELETE FROM memory_fts",
        "INSERT INTO memory_fts(memory_id, revision, content) SELECT memory_id, revision, content FROM memory_fts",
        "UPDATE memory_fts SET memory_id = 'unregistered memory identity'",
    ] {
        let temp = TempDir::new().expect("temp dir");
        let store = seeded(&temp).await;
        sqlx::query(mutation)
            .execute(&store.pool)
            .await
            .expect("tamper search index");
        store.pool.close().await;
        drop(store);
        let result = CognitiveStore::open(&layout(&temp, &agent_id(86))).await;
        assert!(
            matches!(result, Err(CognitiveStoreError::Corrupt(message)) if message.contains("memory FTS rows")),
            "mutation must fail closed: {mutation}"
        );
    }
}

#[tokio::test]
async fn reopening_rejects_fts_inverted_index_corruption_with_unchanged_content_rows() {
    let temp = TempDir::new().expect("temp dir");
    let store = seeded(&temp).await;
    let before: Vec<(String, i64, String)> =
        sqlx::query_as("SELECT memory_id, revision, content FROM memory_fts ORDER BY rowid")
            .fetch_all(&store.pool)
            .await
            .expect("original FTS content rows");
    sqlx::query("DELETE FROM memory_fts_docsize")
        .execute(&store.pool)
        .await
        .expect("remove FTS index metadata without changing content rows");
    let after: Vec<(String, i64, String)> =
        sqlx::query_as("SELECT memory_id, revision, content FROM memory_fts ORDER BY rowid")
            .fetch_all(&store.pool)
            .await
            .expect("retained FTS content rows");
    assert_eq!(after, before);
    // The pinned SQLite invokes FTS5 xIntegrity from quick_check as well.
    // A current owner skips initialization and is rejected by the independently
    // admitted reopen quick-check before its separate FTS verification phase.
    // Historical admission still checks FTS before pending migrations execute.
    let physical: Vec<String> = sqlx::query_scalar("PRAGMA quick_check(1)")
        .fetch_all(&store.pool)
        .await
        .expect("physical quick-check result");
    assert_eq!(
        physical,
        vec!["malformed inverted index for FTS5 table main.memory_fts"]
    );
    store.pool.close().await;
    drop(store);
    let error = match CognitiveStore::open(&layout(&temp, &agent_id(86))).await {
        Err(error) => error,
        Ok(_) => panic!("corrupted physical FTS metadata must never reopen"),
    };
    assert!(
        matches!(&error, CognitiveStoreError::Corrupt(message) if message == "SQLite quick_check rejected the cognitive store"),
        "unexpected corruption gate: {error}"
    );
}

#[tokio::test]
async fn reopening_rejects_ledger_digest_tampering_and_oversized_rows() {
    for (trigger, drop_trigger, mutation, expected) in [
        (
            "source_ledger_no_update",
            "DROP TRIGGER source_ledger_no_update",
            "UPDATE source_ledger SET content = CAST('tampered evidence' AS BLOB)",
            "source_ledger content digest",
        ),
        (
            "memory_revisions_no_update",
            "DROP TRIGGER memory_revisions_no_update",
            "UPDATE memory_revisions SET content = 'tampered memory'",
            "memory_revisions content digest",
        ),
        (
            "source_ledger_no_update",
            "DROP TRIGGER source_ledger_no_update",
            "UPDATE source_ledger SET content = zeroblob(1048577)",
            "source_ledger content exceeds",
        ),
        (
            "memory_revisions_no_update",
            "DROP TRIGGER memory_revisions_no_update",
            "UPDATE memory_revisions SET content = CAST(zeroblob(65537) AS TEXT)",
            "memory_revisions content exceeds",
        ),
    ] {
        let temp = TempDir::new().expect("temp dir");
        let store = seeded(&temp).await;
        let mut fault = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("fixture fault transaction");
        // Save trusted seeded migration SQL before tampering, never owner input.
        // Retain one connection for DROP and restore, so schema caches on other
        // pool connections cannot confuse this deliberately transient fixture.
        let original_trigger: String =
            sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                .bind(trigger)
                .fetch_one(&mut *fault)
                .await
                .expect("exact original trigger");
        sqlx::query(drop_trigger)
            .execute(&mut *fault)
            .await
            .expect("drop guard for attack");
        sqlx::query(mutation)
            .execute(&mut *fault)
            .await
            .expect("tamper ledger bytes");
        sqlx::query(sqlx::AssertSqlSafe(original_trigger.as_str()))
            .execute(&mut *fault)
            .await
            .expect("restore exact guard");
        fault.commit().await.expect("commit exact restored fixture");
        store.pool.close().await;
        drop(store);
        let result = CognitiveStore::open(&layout(&temp, &agent_id(86))).await;
        assert!(
            matches!(result, Err(CognitiveStoreError::Corrupt(message)) if message.contains(expected)),
            "mutation must fail closed: {mutation}"
        );
    }
}
