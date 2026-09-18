use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::query_relations;
use codex_hepta_types::StableId;
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


async fn current_kernel_generation(
    store: &CognitiveStore,
    scope: &CognitiveScope,
) -> KnowledgeGenerationV2 {
    let mut transaction = store.pool.begin().await.expect("kernel read transaction");
    let projection_scope = scope.projection_key();
    let generation: i64 =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(&projection_scope)
            .fetch_one(&mut *transaction)
            .await
            .expect("current projection generation");
    let value = crate::cognitive_kg_kernel::load_kernel_generation_tx(
        &mut transaction,
        &projection_scope,
        generation,
    )
    .await
    .expect("load kernel generation")
    .expect("current generation exists");
    transaction.commit().await.expect("commit kernel read");
    value
}

fn delta_between(
    predecessor: &KnowledgeGenerationV2,
    candidate: &KnowledgeGenerationV2,
) -> KnowledgeProjectionDeltaV2 {
    let remove_node_ids = predecessor
        .nodes
        .iter()
        .filter(|node| {
            !candidate
                .nodes
                .iter()
                .any(|candidate_node| candidate_node.node_id == node.node_id)
        })
        .map(|node| node.node_id.clone())
        .collect();
    let upsert_nodes = candidate
        .nodes
        .iter()
        .filter(|node| {
            predecessor
                .nodes
                .iter()
                .find(|predecessor_node| predecessor_node.node_id == node.node_id)
                != Some(*node)
        })
        .cloned()
        .collect();
    let remove_edge_identities = predecessor
        .edges
        .iter()
        .filter(|edge| {
            !candidate
                .edges
                .iter()
                .any(|candidate_edge| candidate_edge.identity == edge.identity)
        })
        .map(|edge| edge.identity.clone())
        .collect();
    let upsert_edges = candidate
        .edges
        .iter()
        .filter(|edge| {
            predecessor
                .edges
                .iter()
                .find(|predecessor_edge| predecessor_edge.identity == edge.identity)
                != Some(*edge)
        })
        .cloned()
        .collect();
    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: candidate.source_snapshot_digest,
        generation_vector_digest: candidate.generation_vector_digest,
        graph_profile_digest: candidate.graph_profile_digest,
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}

#[tokio::test]
async fn hepta_kg_and_sqlite_share_one_generation_oracle_across_reopen_and_tombstone() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(44);
    let workspace_sha256 = workspace("kernel-oracle");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(owner.clone(), workspace_sha256);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout).await.expect("store");

    let content = "Ada collaborated with Charles.";
    let first = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "oracle-source", content),
            &MemoryDraft {
                stable_key: "oracle-memory".to_string(),
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
        .expect("first oracle generation");
    assert_eq!(first.projection.generation.get(), 1);

    let generation_one = current_kernel_generation(&store, &scope).await;
    let persisted_one: String = sqlx::query_scalar(
        "SELECT generation_sha256 FROM kg_projection_kernel_receipts
         WHERE projection_scope = ? AND generation = 1",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("persisted first kernel digest");
    assert_eq!(persisted_one, generation_one.generation_digest.to_string());

    let query = query_relations(
        &generation_one,
        KnowledgeRelationQueryV2 {
            query_id: StableId::new("oracle:sqlite-visible").expect("query id"),
            generation_digest: generation_one.generation_digest,
            seed_node_ids: generation_one
                .nodes
                .iter()
                .map(|node| node.node_id.clone())
                .collect(),
            relation_kinds: Vec::new(),
            maximum_edges: 32,
        },
    )
    .expect("V2 relation query");
    let sqlite_edge_ids = sqlx::query_scalar::<_, String>(
        "SELECT edge_id FROM kg_edges
         WHERE projection_scope = ? AND generation = 1
         ORDER BY edge_id",
    )
    .bind(scope.projection_key())
    .fetch_all(&store.pool)
    .await
    .expect("sqlite edge identities");
    assert_eq!(
        query
            .edges
            .iter()
            .map(|edge| edge.identity.relation_id.to_string())
            .collect::<Vec<_>>(),
        sqlite_edge_ids
    );

    let ada_identity: String = sqlx::query_scalar(
        "SELECT i.canonical_entity_id
         FROM kg_projection_node_entities i
         JOIN kg_nodes n
           ON n.projection_scope = i.projection_scope
          AND n.generation = i.generation AND n.node_id = i.node_id
         WHERE i.projection_scope = ? AND i.generation = 1
           AND n.label = 'Ada Lovelace'
         LIMIT 1",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("Ada canonical identity");
    let graph_visible = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                first.projection.generation,
                ada_identity,
                first.memory.id.clone(),
            )],
            150,
        )
        .await
        .expect("digest-bound product graph query");
    assert!(!graph_visible.is_empty());

    drop(store);
    let store = CognitiveStore::open(&agent_layout)
        .await
        .expect("reopen validates and backfills the V2 publication chain");
    assert_eq!(
        current_kernel_generation(&store, &scope)
            .await
            .generation_digest,
        generation_one.generation_digest
    );

    let corrected_content = "Ada documented the engine.";
    let second = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source(scope.clone(), "oracle-correction", corrected_content),
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
        .expect("corrected oracle generation");
    let generation_two = current_kernel_generation(&store, &scope).await;
    let incremental_two = apply_incremental_delta(
        &generation_one,
        generation_two.generation,
        delta_between(&generation_one, &generation_two),
    )
    .expect("incremental correction generation");
    assert_eq!(incremental_two, generation_two);
    assert!(generation_two.edges.is_empty());

    let corrected_ada_identity: String = sqlx::query_scalar(
        "SELECT i.canonical_entity_id
         FROM kg_projection_node_entities i
         JOIN kg_nodes n
           ON n.projection_scope = i.projection_scope
          AND n.generation = i.generation AND n.node_id = i.node_id
         WHERE i.projection_scope = ? AND i.generation = 2
           AND n.label = 'Ada Lovelace'
         LIMIT 1",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("corrected Ada canonical identity");
    assert!(
        store
            .graph_channel_for_test(
                &[(
                    scope.clone(),
                    second.projection.generation,
                    corrected_ada_identity,
                    second.memory.id.clone(),
                )],
                250,
            )
            .await
            .expect("corrected graph query")
            .is_empty()
    );

    let reason = "explicitly withdraw oracle memory";
    let third = store
        .forget_with_kg(
            &access,
            &second.memory.id.memory_id,
            2,
            &source(scope.clone(), "oracle-forget", reason),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: reason.to_string(),
                valid_from_unix_seconds: 300,
                citations: Vec::new(),
            },
        )
        .await
        .expect("tombstone oracle generation");
    assert_eq!(third.projection.generation.get(), 3);
    let generation_three = current_kernel_generation(&store, &scope).await;
    let incremental_three = apply_incremental_delta(
        &generation_two,
        generation_three.generation,
        delta_between(&generation_two, &generation_three),
    )
    .expect("incremental tombstone generation");
    assert_eq!(incremental_three, generation_three);
    assert!(generation_three.nodes.is_empty());
    assert!(generation_three.edges.is_empty());
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection_kernel_receipts")
            .fetch_one(&store.pool)
            .await
            .expect("kernel receipt count"),
        3
    );

    drop(store);
    let reopened = CognitiveStore::open(&agent_layout)
        .await
        .expect("reopen after tombstone");
    let reopened_generation = current_kernel_generation(&reopened, &scope).await;
    assert_eq!(reopened_generation, generation_three);
}
