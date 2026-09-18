use std::collections::BTreeMap;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_types::Generation;
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
use crate::MemoryRevisionId;
use crate::MemoryVerification;
use crate::ProjectionGeneration;
use crate::cognitive_kg_store::v2;
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

async fn load_v2_generation(
    store: &CognitiveStore,
    scope: &CognitiveScope,
    generation: u64,
) -> KnowledgeGenerationV2 {
    let mut transaction = store.pool.begin().await.expect("V2 load transaction");
    let loaded = v2::load_generation_tx(
        &mut transaction,
        &scope.projection_key(),
        i64::try_from(generation).expect("generation fits i64"),
    )
    .await
    .expect("stored projection must load through canonical V2");
    transaction.commit().await.expect("V2 load commit");
    loaded.generation
}

fn incremental_delta(
    predecessor: &KnowledgeGenerationV2,
    successor: &KnowledgeGenerationV2,
) -> KnowledgeProjectionDeltaV2 {
    let predecessor_nodes = predecessor
        .nodes
        .iter()
        .cloned()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let successor_nodes = successor
        .nodes
        .iter()
        .cloned()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let predecessor_edges = predecessor
        .edges
        .iter()
        .cloned()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();
    let successor_edges = successor
        .edges
        .iter()
        .cloned()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();

    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: successor.source_snapshot_digest,
        generation_vector_digest: successor.generation_vector_digest,
        graph_profile_digest: successor.graph_profile_digest,
        remove_node_ids: predecessor_nodes
            .keys()
            .filter(|node_id| !successor_nodes.contains_key(*node_id))
            .cloned()
            .collect(),
        upsert_nodes: successor_nodes
            .iter()
            .filter(|(node_id, node)| predecessor_nodes.get(*node_id) != Some(*node))
            .map(|(_, node)| node.clone())
            .collect(),
        remove_edge_identities: predecessor_edges
            .keys()
            .filter(|identity| !successor_edges.contains_key(*identity))
            .cloned()
            .collect(),
        upsert_edges: successor_edges
            .iter()
            .filter(|(identity, edge)| predecessor_edges.get(*identity) != Some(*edge))
            .map(|(_, edge)| edge.clone())
            .collect(),
    }
}

fn assert_incremental_matches_full(
    predecessor: &KnowledgeGenerationV2,
    successor: &KnowledgeGenerationV2,
) {
    let rebuilt = apply_incremental_delta(
        predecessor,
        Generation::new(successor.generation.get()).expect("valid successor generation"),
        incremental_delta(predecessor, successor),
    )
    .expect("incremental rebuild must match durable full rebuild");
    assert_eq!(&rebuilt, successor);
}

#[tokio::test]
async fn product_projection_is_scoped_cited_append_only_and_fts_backed() {
    let temp = TempDir::new().expect("temp dir");
    let agent_id = agent_id(4);
    let test_layout = layout(&temp, &agent_id);
    let store = CognitiveStore::open(&test_layout).await.expect("store");
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
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_entity_fts WHERE kg_entity_fts MATCH 'Ada'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("FTS5 query"),
        1
    );

    let first_v2 = load_v2_generation(&store, &scope, 1).await;
    assert_eq!(
        first.projection.output_sha256.as_str(),
        first_v2.generation_digest.to_string()
    );
    assert_eq!(first_v2.nodes.len(), 2);
    assert_eq!(first_v2.edges.len(), 1);
    assert_eq!(first_v2.edges[0].supports.len(), 1);
    assert_ne!(
        first_v2.nodes[0].supports[0].source_fact_digest,
        first_v2.nodes[1].supports[0].source_fact_digest
    );
    assert_ne!(
        first_v2.nodes[0].supports[0].source_fact_digest,
        first_v2.edges[0].supports[0].source_fact_digest
    );
    assert_eq!(
        first_v2.edges[0].supports[0].source_id.as_str(),
        first.source.source_id.as_str()
    );
    assert_eq!(
        first_v2.edges[0].supports[0].source_revision.get(),
        first.source.revision
    );

    let ada_canonical: String = sqlx::query_scalar(
        "SELECT canonical_entity_id FROM kg_revision_entities
         WHERE memory_id = ? AND memory_revision = 1 AND entity_key = 'ada'",
    )
    .bind(first.memory.id.memory_id.as_str())
    .fetch_one(&store.pool)
    .await
    .expect("Ada canonical identity");
    let first_graph = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                ProjectionGeneration(1),
                ada_canonical.clone(),
                first.memory.id.clone(),
            )],
            150,
        )
        .await
        .expect("V2 product graph query");
    assert_eq!(first_graph, vec![first.memory.id.clone()]);

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
    let second_v2 = load_v2_generation(&store, &scope, 2).await;
    assert_eq!(
        second.projection.output_sha256.as_str(),
        second_v2.generation_digest.to_string()
    );
    assert_incremental_matches_full(&first_v2, &second_v2);
    assert_eq!(second_v2.edges.len(), 0);
    let corrected_graph = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                ProjectionGeneration(2),
                ada_canonical.clone(),
                second.memory.id.clone(),
            )],
            150,
        )
        .await
        .expect("corrected V2 product graph query");
    assert!(corrected_graph.is_empty());

    let reopened = CognitiveStore::open(&test_layout)
        .await
        .expect("V2 generation must survive reopen verification");
    assert_eq!(
        load_v2_generation(&reopened, &scope, 2).await,
        second_v2
    );
    let reopened_graph = reopened
        .graph_channel_for_test(
            &[(
                scope.clone(),
                ProjectionGeneration(2),
                ada_canonical.clone(),
                second.memory.id.clone(),
            )],
            150,
        )
        .await
        .expect("reopened V2 product graph query");
    assert!(reopened_graph.is_empty());
    drop(reopened);

    let forget_reason = "withdraw collaboration memory";
    let forgotten = store
        .forget_with_kg(
            &access,
            &second.memory.id.memory_id,
            2,
            &source(scope.clone(), "kg-forget", forget_reason),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: forget_reason.to_string(),
                valid_from_unix_seconds: 200,
            },
        )
        .await
        .expect("tombstone projection");
    assert_eq!(forgotten.projection.generation.get(), 3);
    let third_v2 = load_v2_generation(&store, &scope, 3).await;
    assert_incremental_matches_full(&second_v2, &third_v2);
    assert!(third_v2.nodes.is_empty());
    assert!(third_v2.edges.is_empty());
    assert_eq!(
        forgotten.projection.output_sha256.as_str(),
        third_v2.generation_digest.to_string()
    );
    let tombstoned_graph = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                ProjectionGeneration(3),
                ada_canonical,
                MemoryRevisionId {
                    memory_id: forgotten.memory.id.memory_id.clone(),
                    revision: 3,
                },
            )],
            250,
        )
        .await
        .expect("tombstoned V2 product graph query");
    assert!(tombstoned_graph.is_empty());

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
