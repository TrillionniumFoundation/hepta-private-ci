use sqlx::Row;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

async fn plan(store: &CognitiveStore, sql: &str) -> Vec<String> {
    sqlx::query(sql)
        .bind("agent-id-not-used-by-planner")
        .bind("agent_private")
        .bind(Option::<String>::None)
        .bind("memory:v1:excluded")
        .bind(10_001_i64)
        .fetch_all(&store.pool)
        .await
        .expect("explain query plan")
        .into_iter()
        .map(|row| row.try_get::<String, _>("detail").expect("plan detail"))
        .collect()
}

fn assert_searches(
    label: &str,
    details: &[String],
    required_search_aliases: &[&str],
    forbidden_scan_aliases: &[&str],
) {
    let rendered = details.join("\n");
    for alias in required_search_aliases {
        assert!(
            details
                .iter()
                .any(|detail| detail.contains(&format!("SEARCH {alias}"))),
            "{label} must use an indexed lookup for {alias}:\n{rendered}"
        );
    }
    for alias in forbidden_scan_aliases {
        assert!(
            !details
                .iter()
                .any(|detail| detail.contains(&format!("SCAN {alias}"))),
            "{label} must not full-scan {alias}:\n{rendered}"
        );
    }
}

#[tokio::test]
async fn prepared_projection_queries_keep_indexed_join_boundaries() {
    let temp = TempDir::new().expect("temporary directory");
    let owner = agent_id(92);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("open cognitive store");

    let heads = plan(
        &store,
        "EXPLAIN QUERY PLAN
         SELECT r.memory_id, r.revision, r.content_sha256,
                r.verification, r.lifecycle, s.fact_set_sha256,
                s.entity_count, s.relation_count
         FROM memory_heads h
         JOIN memory_revisions r
           ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_fact_sets s
           ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ?
           AND r.workspace_sha256 IS ? AND r.memory_id != ?
         ORDER BY r.memory_id LIMIT ?",
    )
    .await;
    assert_searches("current-head cut", &heads, &["r", "s"], &["r", "s"]);

    let entities = plan(
        &store,
        "EXPLAIN QUERY PLAN
         SELECT e.memory_id, e.memory_revision, e.entity_key,
                e.canonical_entity_id, e.entity_type, e.label,
                e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                e.source_id, e.source_revision
         FROM memory_heads h
         JOIN memory_revisions r
           ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_entities e
           ON e.memory_id = r.memory_id AND e.memory_revision = r.revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ?
           AND r.workspace_sha256 IS ? AND r.memory_id != ?
           AND r.verification = 'verified' AND r.lifecycle = 'active'
         ORDER BY e.memory_id, e.memory_revision, e.entity_key LIMIT ?",
    )
    .await;
    assert_searches(
        "current entity cut",
        &entities,
        &["r", "e"],
        &["r", "e"],
    );

    let relations = plan(
        &store,
        "EXPLAIN QUERY PLAN
         SELECT q.memory_id, q.memory_revision, q.relation_key,
                q.canonical_relation_id, q.from_entity_key, q.to_entity_key,
                q.from_canonical_entity_id, q.to_canonical_entity_id,
                q.relation, q.valid_from_unix_seconds,
                q.valid_to_unix_seconds, q.source_id, q.source_revision
         FROM memory_heads h
         JOIN memory_revisions r
           ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_relations q
           ON q.memory_id = r.memory_id AND q.memory_revision = r.revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ?
           AND r.workspace_sha256 IS ? AND r.memory_id != ?
           AND r.verification = 'verified' AND r.lifecycle = 'active'
         ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
    )
    .await;
    assert_searches(
        "current relation cut",
        &relations,
        &["r", "q"],
        &["r", "q"],
    );
}

#[tokio::test]
async fn generation_receipt_lookup_uses_the_composite_primary_key() {
    let temp = TempDir::new().expect("temporary directory");
    let owner = agent_id(93);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("open cognitive store");
    let rows = sqlx::query(
        "EXPLAIN QUERY PLAN
         SELECT source_snapshot_sha256, generation_vector_sha256,
                graph_profile_sha256, generation_sha256, publication_sha256
         FROM kg_projection_generation_semantics
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind("agent_private")
    .bind(1_i64)
    .fetch_all(&store.pool)
    .await
    .expect("semantic receipt query plan");
    let details = rows
        .into_iter()
        .map(|row| row.try_get::<String, _>("detail").expect("plan detail"))
        .collect::<Vec<_>>();
    let rendered = details.join("\n");
    assert!(
        details.iter().any(|detail| {
            detail.contains("SEARCH kg_projection_generation_semantics")
                && detail.contains("projection_scope")
                && detail.contains("generation")
        }),
        "semantic receipt lookup must use the composite key:\n{rendered}"
    );
    assert!(
        !details
            .iter()
            .any(|detail| detail.contains("SCAN kg_projection_generation_semantics")),
        "semantic receipt lookup must not full-scan:\n{rendered}"
    );
}
