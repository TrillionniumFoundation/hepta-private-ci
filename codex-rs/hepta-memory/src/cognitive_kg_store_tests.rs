use pretty_assertions::assert_eq;
use tempfile::TempDir;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::cognitive_kg_store::ProjectionNode;
use crate::cognitive_kg_store::canonical_generation_from_projection;
use crate::cognitive_kg_store::load_canonical_generation_tx;
use crate::cognitive_kg_store::load_generation_query_cut_tx;
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

#[test]
fn repeated_shapes_match_independent_single_occurrence_generations() {
    let snapshot = Sha256Digest::for_bytes(b"shared source cut");
    let vector = Digest32::of_bytes(b"shared generation vector");
    let first = ProjectionNode {
        node_id: "occurrence:first".to_string(),
        canonical_entity_id: "entity:shared".to_string(),
        entity_type: "concept".to_string(),
        label: "Shared shape".to_string(),
        valid_from: 100,
        valid_to: None,
        memory_id: "memory:first".to_string(),
        memory_revision: 1,
        source_id: "source:first".to_string(),
        source_revision: 1,
    };
    let second = ProjectionNode {
        node_id: "occurrence:second".to_string(),
        memory_id: "memory:second".to_string(),
        source_id: "source:second".to_string(),
        valid_from: 200,
        ..first.clone()
    };
    let other = ProjectionNode {
        node_id: "occurrence:other".to_string(),
        canonical_entity_id: "entity:other".to_string(),
        label: "Distinct shape".to_string(),
        ..first.clone()
    };
    let singles = [&first, &second, &other]
        .into_iter()
        .map(|node| {
            canonical_generation_from_projection(
                /*generation*/ 1,
                &snapshot,
                vector,
                std::slice::from_ref(node),
                &[],
            )
            .expect("single-occurrence reference")
        })
        .collect::<Vec<_>>();
    let mut shared = singles[0].nodes[0].clone();
    shared.supports.extend(singles[1].nodes[0].supports.clone());
    let expected = build_complete_generation(
        Generation::new(/*value*/ 1).expect("generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: singles[0].source_snapshot_digest,
            generation_vector_digest: vector,
            graph_profile_digest: singles[0].graph_profile_digest,
            complete_source_cut: true,
            nodes: vec![shared, singles[2].nodes[0].clone()],
            edges: Vec::new(),
        },
    )
    .expect("independent kernel merge");
    let actual = canonical_generation_from_projection(
        /*generation*/ 1,
        &snapshot,
        vector,
        &[first, second, other],
        &[],
    )
    .expect("memoized source cut");
    assert_eq!(actual, expected);
}

#[tokio::test]
async fn product_projection_is_scoped_cited_append_only_and_fts_backed() {
    let temp = TempDir::new().expect("temp dir");
    let agent_id = agent_id(4);
    let store = CognitiveStore::open(&layout(&temp, &agent_id))
        .await
        .expect("store");
    let workspace_sha256 = workspace("research");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(agent_id, workspace_sha256);
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
    let mut transaction = store.pool.begin().await.expect("query-cut transaction");
    let original_generation = load_canonical_generation_tx(&mut transaction, &scope.projection_key(), 1)
        .await
        .expect("generation-only reference");
    let (query_generation, query_supports) =
        load_generation_query_cut_tx(&mut transaction, &scope.projection_key(), 1)
            .await
            .expect("generation and support index from the same physical edge rows");
    assert_eq!(query_generation, original_generation);
    assert_eq!(
        query_supports,
        Some(std::collections::BTreeMap::from([(
            original_generation.edges[0].supports[0].source_id.to_string(),
            (first.memory.id.memory_id.as_str().to_string(), 1),
        )]))
    );
    transaction.commit().await.expect("finish query-cut transaction");
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_revision_entity_fts WHERE kg_revision_entity_fts MATCH 'Ada'",
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
    let mut transaction = store.pool.begin().await.expect("historical query-cut transaction");
    let (historical_generation, historical_supports) =
        load_generation_query_cut_tx(&mut transaction, &scope.projection_key(), 1)
            .await
            .expect("historical support index remains bound to generation one");
    assert_eq!(historical_generation, original_generation);
    assert_eq!(
        historical_supports,
        Some(std::collections::BTreeMap::from([(
            original_generation.edges[0].supports[0].source_id.to_string(),
            (first.memory.id.memory_id.as_str().to_string(), 1),
        )]))
    );
    let (_, current_supports) =
        load_generation_query_cut_tx(&mut transaction, &scope.projection_key(), 2)
            .await
            .expect("current query cut excludes the corrected historical relation");
    assert_eq!(current_supports, Some(std::collections::BTreeMap::new()));
    transaction.commit().await.expect("finish historical query-cut transaction");
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_relations")
            .fetch_one(&store.pool)
            .await
            .expect("historical edge count"),
        1
    );
    let immutable = sqlx::query("DELETE FROM kg_revision_entities")
        .execute(&store.pool)
        .await
        .expect_err("projection nodes are append-only");
    assert!(
        immutable
            .to_string()
            .contains("KG revision entities are immutable")
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
                revision: revision(scope, bad_content),
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
}
