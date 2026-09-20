use std::collections::BTreeMap;

use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::query_relations;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use sqlx::Row;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryRevisionId;
use crate::MemoryVerification;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_kg_store::load_canonical_generation_tx;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

fn active_revision(scope: CognitiveScope, content: &str, valid_from: i64) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: valid_from,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

async fn load_generation(
    store: &CognitiveStore,
    scope: &CognitiveScope,
    generation: u64,
) -> KnowledgeGenerationV2 {
    let mut transaction = store.pool.begin().await.expect("oracle read transaction");
    let generation = load_canonical_generation_tx(
        &mut transaction,
        &scope.projection_key(),
        i64::try_from(generation).expect("bounded generation"),
    )
    .await
    .expect("canonical generation");
    transaction.commit().await.expect("oracle read commit");
    generation
}

fn delta_to(
    predecessor: &KnowledgeGenerationV2,
    target: &KnowledgeGenerationV2,
) -> KnowledgeProjectionDeltaV2 {
    let predecessor_nodes = predecessor
        .nodes
        .iter()
        .cloned()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let target_nodes = target
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
    let target_edges = target
        .edges
        .iter()
        .cloned()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();

    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: target.source_snapshot_digest,
        generation_vector_digest: target.generation_vector_digest,
        graph_profile_digest: target.graph_profile_digest,
        remove_node_ids: predecessor_nodes
            .keys()
            .filter(|id| !target_nodes.contains_key(*id))
            .cloned()
            .collect(),
        upsert_nodes: target_nodes
            .iter()
            .filter(|(id, node)| predecessor_nodes.get(*id) != Some(*node))
            .map(|(_, node)| node.clone())
            .collect(),
        remove_edge_identities: predecessor_edges
            .keys()
            .filter(|identity| !target_edges.contains_key(*identity))
            .cloned()
            .collect(),
        upsert_edges: target_edges
            .iter()
            .filter(|(identity, edge)| predecessor_edges.get(*identity) != Some(*edge))
            .map(|(_, edge)| edge.clone())
            .collect(),
    }
}

async fn assert_persisted_semantics(
    store: &CognitiveStore,
    scope: &CognitiveScope,
    generation: &KnowledgeGenerationV2,
    expected_generation_sha256: &str,
) {
    let row = sqlx::query(
        "SELECT source_snapshot_sha256, generation_vector_sha256,
                graph_profile_sha256, generation_sha256, publication_sha256
         FROM kg_projection_generation_semantics
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(scope.projection_key())
    .bind(i64::try_from(generation.generation.get()).expect("bounded generation"))
    .fetch_one(&store.pool)
    .await
    .expect("persisted canonical semantics");
    assert_eq!(
        row.try_get::<String, _>("source_snapshot_sha256")
            .expect("source snapshot"),
        generation.source_snapshot_digest.to_string()
    );
    assert_eq!(
        row.try_get::<String, _>("generation_vector_sha256")
            .expect("generation vector"),
        generation.generation_vector_digest.to_string()
    );
    assert_eq!(
        row.try_get::<String, _>("graph_profile_sha256")
            .expect("graph profile"),
        generation.graph_profile_digest.to_string()
    );
    assert_eq!(
        row.try_get::<String, _>("generation_sha256")
            .expect("generation digest"),
        generation.generation_digest.to_string()
    );
    assert_eq!(
        expected_generation_sha256,
        generation.generation_digest.to_string()
    );
    assert_eq!(
        row.try_get::<String, _>("publication_sha256")
            .expect("publication digest")
            .len(),
        64
    );
}

fn node<'a>(generation: &'a KnowledgeGenerationV2, node_id: &str) -> &'a KnowledgeNodeV2 {
    generation
        .nodes
        .iter()
        .find(|node| node.node_id.as_str() == node_id)
        .expect("canonical node")
}

fn edges_by_identity(
    generation: &KnowledgeGenerationV2,
) -> BTreeMap<KnowledgeEdgeIdentityV2, KnowledgeEdgeV2> {
    generation
        .edges
        .iter()
        .cloned()
        .map(|edge| (edge.identity.clone(), edge))
        .collect()
}

#[tokio::test]
async fn canonical_v2_sqlite_restart_query_correction_and_tombstone_are_one_chain() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(94);
    let owner_layout = layout(&temp, &owner);
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let store = CognitiveStore::open(&owner_layout).await.expect("store");

    let first_content = "Ada collaborated with Charles.";
    let first = store
        .remember_with_kg(
            &access,
            &source(scope.clone(), "kg-oracle-first", first_content),
            &MemoryDraft {
                stable_key: "kg-oracle-memory".to_string(),
                revision: active_revision(scope.clone(), first_content, 100),
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
        .expect("first canonical write");
    let full_one = load_generation(&store, &scope, first.projection.generation.get()).await;
    assert_persisted_semantics(
        &store,
        &scope,
        &full_one,
        first.projection.generation_sha256.as_str(),
    )
    .await;
    assert_eq!(full_one.nodes.len(), 2);
    assert_eq!(full_one.edges.len(), 1);

    let ada_id = canonical_entity_id(&owner, &scope, "ada");
    let ada_stable = StableId::new(ada_id.clone()).expect("canonical Ada id");
    let query_one = query_relations(
        &full_one,
        KnowledgeRelationQueryV2 {
            query_id: StableId::new("kg-oracle:query:1").expect("query id"),
            generation_digest: full_one.generation_digest,
            seed_node_ids: vec![ada_stable.clone()],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: Some(150),
            maximum_edges: 8,
        },
    )
    .expect("V2 query one");
    assert_eq!(query_one.edges.len(), 1);
    let sql_one = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                first.projection.generation,
                ada_id.clone(),
                first.memory.id.clone(),
            )],
            150,
        )
        .await
        .expect("SQLite graph query one");
    assert_eq!(sql_one, vec![first.memory.id.clone()]);

    let second_content = "Ada documented the Analytical Engine.";
    let second = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source(scope.clone(), "kg-oracle-correction", second_content),
            &active_revision(scope.clone(), second_content, 200),
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada Lovelace".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "engine".to_string(),
                        entity_type: "machine".to_string(),
                        label: "Analytical Engine".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "documented".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "engine".to_string(),
                    relation: "documented".to_string(),
                }],
            },
        )
        .await
        .expect("canonical correction");
    let full_two = load_generation(&store, &scope, second.projection.generation.get()).await;
    assert_persisted_semantics(
        &store,
        &scope,
        &full_two,
        second.projection.generation_sha256.as_str(),
    )
    .await;
    let incremental_two = apply_incremental_delta(
        &full_one,
        full_two.generation,
        delta_to(&full_one, &full_two),
    )
    .expect("incremental correction");
    assert_eq!(incremental_two, full_two);
    assert_eq!(
        node(&full_one, &ada_id).node_id,
        node(&full_two, &ada_id).node_id
    );
    assert_ne!(
        node(&full_one, &ada_id).supports,
        node(&full_two, &ada_id).supports
    );
    assert_ne!(edges_by_identity(&full_one), edges_by_identity(&full_two));

    let query_two = query_relations(
        &full_two,
        KnowledgeRelationQueryV2 {
            query_id: StableId::new("kg-oracle:query:2").expect("query id"),
            generation_digest: full_two.generation_digest,
            seed_node_ids: vec![ada_stable.clone()],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: Some(250),
            maximum_edges: 8,
        },
    )
    .expect("V2 query two");
    assert_eq!(query_two.edges.len(), 1);
    let sql_two = store
        .graph_channel_for_test(
            &[(
                scope.clone(),
                second.projection.generation,
                ada_id.clone(),
                second.memory.id.clone(),
            )],
            250,
        )
        .await
        .expect("SQLite graph query two");
    assert_eq!(sql_two, vec![second.memory.id.clone()]);

    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("reopen verifies physical and canonical generations");
    let reopened_two = load_generation(&reopened, &scope, second.projection.generation.get()).await;
    assert_eq!(reopened_two, full_two);
    let explanation = reopened
        .explain_memory_head(&access, &second.memory.id.memory_id)
        .await
        .expect("digest-bound explanation after restart");
    assert_eq!(
        explanation.kg_projection_generation_sha256,
        Some(second.projection.generation_sha256.clone())
    );

    let forgotten = reopened
        .forget_with_kg(
            &access,
            &second.memory.id.memory_id,
            2,
            &source(
                scope.clone(),
                "kg-oracle-forget",
                "withdraw canonical oracle memory",
            ),
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: "withdraw canonical oracle memory".to_string(),
                valid_from_unix_seconds: 300,
                citations: Vec::new(),
            },
        )
        .await
        .expect("canonical tombstone");
    let full_three =
        load_generation(&reopened, &scope, forgotten.projection.generation.get()).await;
    assert_persisted_semantics(
        &reopened,
        &scope,
        &full_three,
        forgotten.projection.generation_sha256.as_str(),
    )
    .await;
    let incremental_three = apply_incremental_delta(
        &full_two,
        full_three.generation,
        delta_to(&full_two, &full_three),
    )
    .expect("incremental tombstone");
    assert_eq!(incremental_three, full_three);
    assert!(full_three.nodes.is_empty());
    assert!(full_three.edges.is_empty());

    let query_three = query_relations(
        &full_three,
        KnowledgeRelationQueryV2 {
            query_id: StableId::new("kg-oracle:query:3").expect("query id"),
            generation_digest: full_three.generation_digest,
            seed_node_ids: vec![ada_stable],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: Some(350),
            maximum_edges: 8,
        },
    )
    .expect("V2 query after tombstone");
    assert!(query_three.edges.is_empty());
    let sql_three = reopened
        .graph_channel_for_test(
            &[(
                scope,
                forgotten.projection.generation,
                ada_id,
                MemoryRevisionId {
                    memory_id: forgotten.memory.id.memory_id.clone(),
                    revision: forgotten.memory.id.revision,
                },
            )],
            350,
        )
        .await
        .expect("SQLite graph query after tombstone");
    assert!(sql_three.is_empty());
}
