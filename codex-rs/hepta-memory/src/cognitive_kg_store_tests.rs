use sqlx::Row;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

fn revision(scope: CognitiveScope, content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test]
async fn product_projection_is_scoped_cited_append_only_and_fts_backed() {
    let temp = TempDir::new().expect("temp dir");
    let agent_id = agent_id(4);
    let store_layout = layout(&temp, &agent_id);
    let store = CognitiveStore::open(&store_layout)
        .await
        .expect("store");
    let workspace_sha256 = workspace("research");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(agent_id.clone(), workspace_sha256);
    let content = "Ada collaborated with Charles.";
    let first = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "kg-source", content),
            &MemoryDraft {
                stable_key: "ada-collaboration".to_string(),
                revision: revision(scope.clone(), content),
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada Lovelace".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "charles".to_string(),
                        entity_type: "person".to_string(),
                        label: "Charles Babbage".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "collaborated".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "charles".to_string(),
                    relation: "collaborated_with".to_string(),
                }],
            },
        )
        .await
        .expect("first projection");
    assert_eq!(first.projection.generation.get(), 1);
    let first_v2 = sqlx::query(
        "SELECT generation_digest, predecessor_generation,
                predecessor_generation_digest, publication_digest
         FROM kg_projection_v2_generation_receipts
         WHERE projection_scope = ? AND generation = 1",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("first V2 projection receipt");
    assert!(
        first_v2
            .try_get::<String, _>("generation_digest")
            .expect("generation digest")
            .len()
            == 64
    );
    assert_eq!(
        first_v2
            .try_get::<Option<i64>, _>("predecessor_generation")
            .expect("first predecessor"),
        None
    );
    assert_eq!(
        first_v2
            .try_get::<Option<String>, _>("predecessor_generation_digest")
            .expect("first predecessor digest"),
        None
    );
    assert!(
        first_v2
            .try_get::<String, _>("publication_digest")
            .expect("publication digest")
            .len()
            == 64
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_entity_fts WHERE kg_entity_fts MATCH 'Ada'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("FTS5 query"),
        1
    );

    let corrected_content = "Ada documented the engine.";
    let second = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source(scope.clone(), "kg-correction", corrected_content),
            &revision(scope.clone(), corrected_content),
            &KgFactSetDraft {
                entities: vec![KgEntityFactDraft {
                    key: "ada".to_string(),
                    entity_type: "person".to_string(),
                    label: "Ada Lovelace".to_string(),
                }],
                relations: Vec::new(),
            },
        )
        .await
        .expect("replacement projection");
    assert_eq!(second.projection.generation.get(), 2);
    assert_eq!(second.projection.edge_count, 0);
    let second_v2 = sqlx::query(
        "SELECT predecessor_generation, predecessor_generation_digest
         FROM kg_projection_v2_generation_receipts
         WHERE projection_scope = ? AND generation = 2",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("second V2 projection receipt");
    assert_eq!(
        second_v2
            .try_get::<Option<i64>, _>("predecessor_generation")
            .expect("second predecessor"),
        Some(1)
    );
    assert_eq!(
        second_v2
            .try_get::<Option<String>, _>("predecessor_generation_digest")
            .expect("second predecessor digest")
            .as_deref()
            .map(str::len),
        Some(64)
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_edges")
            .fetch_one(&store.pool)
            .await
            .expect("historical edge count"),
        1
    );
    let immutable = sqlx::query("DELETE FROM kg_nodes")
        .execute(&store.pool)
        .await
        .expect_err("projection nodes are append-only");
    assert!(
        immutable
            .to_string()
            .contains("projection nodes are immutable")
    );

    let sources_before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM source_ledger")
        .fetch_one(&store.pool)
        .await
        .expect("source count");
    let bad_content = "A dangling relation.";
    let error = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "dangling", bad_content),
            &MemoryDraft {
                stable_key: "dangling".to_string(),
                revision: revision(scope.clone(), bad_content),
            },
            &KgFactSetDraft {
                entities: Vec::new(),
                relations: vec![KgRelationFactDraft {
                    key: "bad".to_string(),
                    from_entity_key: "missing".to_string(),
                    to_entity_key: "missing".to_string(),
                    relation: "references".to_string(),
                }],
            },
        )
        .await
        .expect_err("dangling relation must roll back");
    assert!(matches!(error, CognitiveStoreError::Invalid(_)));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("rolled-back source count"),
        sources_before
    );

    drop(store);
    let reopened = CognitiveStore::open(&store_layout)
        .await
        .expect("reopen after correction");
    let after_restart = reopened
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Ada Lovelace", 200))
        .await
        .expect("query corrected projection after restart");
    assert!(
        after_restart
            .candidates
            .iter()
            .any(|candidate| candidate.memory.id.memory_id == first.memory.id.memory_id),
        "corrected KG support must remain visible through the product query consumer after restart"
    );

    let reason = "withdraw corrected Ada memory";
    let forgotten = reopened
        .forget_with_kg(
            &access,
            &first.memory.id.memory_id,
            2,
            &source(scope.clone(), "kg-forget", reason),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: reason.to_string(),
                valid_from_unix_seconds: 300,
            },
        )
        .await
        .expect("tombstone projection");
    assert_eq!(forgotten.projection.generation.get(), 3);
    assert_eq!(forgotten.projection.node_count, 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_projection_v2_generation_receipts
             WHERE projection_scope = ?",
        )
        .bind(scope.projection_key())
        .fetch_one(&reopened.pool)
        .await
        .expect("V2 receipt count"),
        3
    );
    assert_eq!(forgotten.projection.edge_count, 0);

    let after_forget = reopened
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Ada Lovelace", 400))
        .await
        .expect("query after tombstone");
    assert!(
        after_forget
            .candidates
            .iter()
            .all(|candidate| candidate.memory.id.memory_id != first.memory.id.memory_id),
        "tombstoned support must disappear from visible query semantics"
    );

    drop(reopened);
    let reopened_again = CognitiveStore::open(&store_layout)
        .await
        .expect("reopen after tombstone");
    let after_second_restart = reopened_again
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Ada Lovelace", 400))
        .await
        .expect("query tombstoned projection after restart");
    assert!(
        after_second_restart
            .candidates
            .iter()
            .all(|candidate| candidate.memory.id.memory_id != first.memory.id.memory_id),
        "tombstone visibility must survive restart"
    );
}
