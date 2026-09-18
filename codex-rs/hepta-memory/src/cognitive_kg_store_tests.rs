use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::derive_incremental_delta;
use codex_hepta_kg::query_relations;
use codex_hepta_kg::relation_kind_from_name;
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
use crate::RetrievalChannel;
use crate::RetrievalRequest;
use crate::cognitive_kg_store::kernel_query_id;
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

#[tokio::test]
async fn sqlite_projection_is_kernel_canonical_across_query_restart_correction_and_tombstone() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(14);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace_sha256 = workspace("kernel-oracle");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(owner.clone(), workspace_sha256);
    let projection_scope = scope.projection_key();

    let content = "Ada collaborated with Charles.";
    let first = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "kernel-oracle-first", content),
            &MemoryDraft {
                stable_key: "kernel-oracle".to_string(),
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
                    key: "collaboration".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "charles".to_string(),
                    relation: "collaborated_with".to_string(),
                }],
            },
        )
        .await
        .expect("initial KG generation");

    let mut transaction = store.pool.begin().await.expect("query transaction");
    let first_projection = store
        .load_kernel_projection_tx(&mut transaction, &projection_scope, 1)
        .await
        .expect("first canonical projection");
    let ada_canonical = first_projection
        .nodes
        .iter()
        .find(|node| node.label == "Ada Lovelace")
        .map(|node| node.canonical_entity_id.clone())
        .expect("Ada canonical entity");
    let seed_node_ids = first_projection
        .seed_node_ids_by_canonical
        .get(&ada_canonical)
        .cloned()
        .expect("Ada occurrence seed");
    let queried = query_relations(
        &first_projection.generation,
        KnowledgeRelationQueryV2 {
            query_id: kernel_query_id(&projection_scope, 1, &ada_canonical)
                .expect("query identity"),
            generation_digest: first_projection.generation.generation_digest,
            seed_node_ids,
            relation_kinds: vec![relation_kind_from_name("collaborated_with")],
            maximum_edges: 8,
        },
    )
    .expect("direct kernel query");
    assert_eq!(queried.edges.len(), 1);
    assert_eq!(
        queried.edges[0].identity.relation,
        relation_kind_from_name("collaborated_with")
    );
    assert_eq!(
        first.projection.kernel_generation_sha256.as_str(),
        first_projection.generation.generation_digest.to_string()
    );
    let first_generation = first_projection.generation.clone();
    transaction.commit().await.expect("query commit");

    let product_query = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Ada", 200))
        .await
        .expect("kernel-backed product query");
    assert!(
        product_query
            .candidates
            .iter()
            .any(|candidate| candidate.channels.contains(&RetrievalChannel::GraphOneHop)),
        "product retrieval did not consume the canonical KG query path"
    );

    let corrected_content = "Ada documented the analytical engine.";
    let second = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source(
                scope.clone(),
                "kernel-oracle-correction",
                corrected_content,
            ),
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
        .expect("corrected KG generation");

    let mut transaction = store.pool.begin().await.expect("second transaction");
    let second_projection = store
        .load_kernel_projection_tx(&mut transaction, &projection_scope, 2)
        .await
        .expect("second canonical projection");
    let second_generation = second_projection.generation.clone();
    transaction.commit().await.expect("second query commit");
    assert_eq!(
        second.projection.kernel_generation_sha256.as_str(),
        second_generation.generation_digest.to_string()
    );
    let delta = derive_incremental_delta(&first_generation, &second_generation)
        .expect("derive correction delta");
    let replayed = apply_incremental_delta(
        &first_generation,
        second_generation.generation,
        delta,
    )
    .expect("replay correction delta");
    assert_eq!(replayed, second_generation);

    drop(store);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen with canonical digest verification");
    let mut transaction = reopened.pool.begin().await.expect("reopen transaction");
    let reopened_projection = reopened
        .load_kernel_projection_tx(&mut transaction, &projection_scope, 2)
        .await
        .expect("reopened canonical projection");
    assert_eq!(reopened_projection.generation, second_generation);
    transaction.commit().await.expect("reopen query commit");

    let reason = "Withdraw the collaboration memory.";
    let third = reopened
        .forget_with_kg(
            &access,
            &first.memory.id.memory_id,
            2,
            &source(scope.clone(), "kernel-oracle-forget", reason),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: reason.to_string(),
                valid_from_unix_seconds: 100,
                citations: Vec::new(),
            },
        )
        .await
        .expect("tombstone KG generation");
    let mut transaction = reopened.pool.begin().await.expect("third transaction");
    let third_projection = reopened
        .load_kernel_projection_tx(&mut transaction, &projection_scope, 3)
        .await
        .expect("third canonical projection");
    transaction.commit().await.expect("third query commit");
    assert!(third_projection.generation.nodes.is_empty());
    assert!(third_projection.generation.edges.is_empty());
    assert_eq!(
        third.projection.kernel_generation_sha256.as_str(),
        third_projection.generation.generation_digest.to_string()
    );
    let delta = derive_incremental_delta(&second_generation, &third_projection.generation)
        .expect("derive tombstone delta");
    let replayed = apply_incremental_delta(
        &second_generation,
        third_projection.generation.generation,
        delta,
    )
    .expect("replay tombstone delta");
    assert_eq!(replayed, third_projection.generation);
}

