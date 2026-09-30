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
    sqlx::query("DELETE FROM memory_fts_docsize")
        .execute(&store.pool)
        .await
        .expect("remove FTS index metadata without changing content rows");
    store.pool.close().await;
    drop(store);
    let result = CognitiveStore::open(&layout(&temp, &agent_id(86))).await;
    assert!(
        matches!(result, Err(CognitiveStoreError::Corrupt(message)) if message.contains("memory FTS index integrity"))
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
        let original_trigger: String =
            sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                .bind(trigger)
                .fetch_one(&store.pool)
                .await
                .expect("exact original trigger");
        sqlx::query(drop_trigger)
            .execute(&store.pool)
            .await
            .expect("drop guard for attack");
        sqlx::query(mutation)
            .execute(&store.pool)
            .await
            .expect("tamper ledger bytes");
        sqlx::query(&original_trigger)
            .execute(&store.pool)
            .await
            .expect("restore exact guard");
        store.pool.close().await;
        drop(store);
        let result = CognitiveStore::open(&layout(&temp, &agent_id(86))).await;
        assert!(
            matches!(result, Err(CognitiveStoreError::Corrupt(message)) if message.contains(expected)),
            "mutation must fail closed: {mutation}"
        );
    }
}
