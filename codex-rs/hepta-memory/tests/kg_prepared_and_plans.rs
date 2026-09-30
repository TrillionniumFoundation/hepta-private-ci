//! Public equivalence and SQLite-plan contracts for the prepared KG writer.

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::KgEntityFactDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::KgRelationFactDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use tempfile::TempDir;

fn owner(suffix: u8) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012x}"))
        .expect("valid owner")
}

fn layout(temporary: &TempDir, owner: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let fleet = temporary.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("create fleet root");
    HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(owner)
}

fn source(event_key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

fn first_memory(stable_key: &str, content: &str) -> MemoryDraft {
    MemoryDraft {
        stable_key: stable_key.to_string(),
        revision: correction(content),
    }
}

fn correction(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

fn facts(label_suffix: &str, relation: &str) -> KgFactSetDraft {
    KgFactSetDraft {
        entities: vec![
            KgEntityFactDraft {
                key: "alpha".to_string(),
                entity_type: "concept".to_string(),
                label: format!("Alpha {label_suffix}"),
            },
            KgEntityFactDraft {
                key: "beta".to_string(),
                entity_type: "concept".to_string(),
                label: format!("Beta {label_suffix}"),
            },
        ],
        relations: vec![KgRelationFactDraft {
            key: "alpha-beta".to_string(),
            from_entity_key: "alpha".to_string(),
            to_entity_key: "beta".to_string(),
            relation: relation.to_string(),
        }],
    }
}

async fn read_only_pool(store: &CognitiveStore) -> SqlitePool {
    let options = SqliteConnectOptions::new()
        .filename(store.path())
        .read_only(true)
        .create_if_missing(false);
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
        .expect("open read-only query-plan pool")
}

async fn five_bind_plan(pool: &SqlitePool, sql: &str) -> Vec<String> {
    sqlx::query(sql)
        .bind("agent-id-not-used-by-planner")
        .bind("agent_private")
        .bind(Option::<String>::None)
        .bind("memory:v1:excluded")
        .bind(10_001_i64)
        .fetch_all(pool)
        .await
        .expect("explain query plan")
        .into_iter()
        .map(|row| row.try_get::<String, _>("detail").expect("plan detail"))
        .collect()
}

fn assert_indexed_join_boundary(
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
async fn prepared_writer_matches_the_existing_v2_oracle_across_lifecycle() {
    let legacy_temp = TempDir::new().expect("legacy temporary directory");
    let prepared_temp = TempDir::new().expect("prepared temporary directory");
    let owner = owner(231);
    let legacy_layout = layout(&legacy_temp, &owner);
    let prepared_layout = layout(&prepared_temp, &owner);
    let access = CognitiveAccess::agent_private(owner);
    let legacy = CognitiveStore::open(&legacy_layout)
        .await
        .expect("open legacy writer");
    let prepared = CognitiveStore::open(&prepared_layout)
        .await
        .expect("open prepared writer");

    let initial_content = "The prepared writer retains exact V2 semantics.";
    let initial_source = source("prepared-parity-initial", initial_content);
    let initial_memory = first_memory("prepared-parity-memory", initial_content);
    let initial_facts = facts("initial", "supports");
    let legacy_initial = legacy
        .remember_with_kg(
            &access,
            &initial_source,
            &initial_memory,
            &initial_facts,
        )
        .await
        .expect("legacy initial write");
    let prepared_initial = prepared
        .remember_with_kg_prepared(
            &access,
            &initial_source,
            &initial_memory,
            &initial_facts,
        )
        .await
        .expect("prepared initial write");
    assert_eq!(prepared_initial.write, legacy_initial);
    assert_eq!(prepared_initial.metrics.cas_conflicts, 0);
    assert_eq!(prepared_initial.metrics.retry_count, 0);
    assert_eq!(prepared_initial.metrics.planned_heads, 1);
    assert_eq!(prepared_initial.metrics.planned_nodes, 2);
    assert_eq!(prepared_initial.metrics.planned_edges, 1);

    let corrected_content = "The prepared writer retains corrected V2 semantics.";
    let corrected_source = source("prepared-parity-correction", corrected_content);
    let corrected_memory = correction(corrected_content);
    let corrected_facts = facts("corrected", "contradicts");
    let legacy_corrected = legacy
        .correct_with_kg(
            &access,
            &legacy_initial.memory.id.memory_id,
            1,
            &corrected_source,
            &corrected_memory,
            &corrected_facts,
        )
        .await
        .expect("legacy correction");
    let prepared_corrected = prepared
        .correct_with_kg_prepared(
            &access,
            &prepared_initial.write.memory.id.memory_id,
            1,
            &corrected_source,
            &corrected_memory,
            &corrected_facts,
        )
        .await
        .expect("prepared correction");
    assert_eq!(prepared_corrected.write, legacy_corrected);
    assert_eq!(prepared_corrected.metrics.cas_conflicts, 0);
    assert_eq!(prepared_corrected.metrics.planned_heads, 1);
    assert_eq!(prepared_corrected.metrics.planned_nodes, 2);
    assert_eq!(prepared_corrected.metrics.planned_edges, 1);

    let reason = "The user explicitly withdrew the prepared parity memory.";
    let forget_source = source("prepared-parity-forget", reason);
    let forget = ForgetMemoryDraft {
        scope: CognitiveScope::AgentPrivate,
        reason: reason.to_string(),
        valid_from_unix_seconds: 200,
        citations: Vec::new(),
    };
    let legacy_forgotten = legacy
        .forget_with_kg(
            &access,
            &legacy_corrected.memory.id.memory_id,
            2,
            &forget_source,
            &forget,
        )
        .await
        .expect("legacy forget");
    let prepared_forgotten = prepared
        .forget_with_kg_prepared(
            &access,
            &prepared_corrected.write.memory.id.memory_id,
            2,
            &forget_source,
            &forget,
        )
        .await
        .expect("prepared forget");
    assert_eq!(prepared_forgotten.write, legacy_forgotten);
    assert_eq!(prepared_forgotten.metrics.cas_conflicts, 0);
    assert_eq!(prepared_forgotten.metrics.planned_heads, 1);
    assert_eq!(prepared_forgotten.metrics.planned_nodes, 0);
    assert_eq!(prepared_forgotten.metrics.planned_edges, 0);
}

#[tokio::test]
async fn prepared_projection_queries_keep_indexed_join_boundaries() {
    let temporary = TempDir::new().expect("temporary directory");
    let owner = owner(232);
    let owner_layout = layout(&temporary, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("open cognitive store");
    let pool = read_only_pool(&store).await;

    let heads = five_bind_plan(
        &pool,
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
    assert_indexed_join_boundary("current-head cut", &heads, &["r", "s"], &["r", "s"]);

    let entities = five_bind_plan(
        &pool,
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
    assert_indexed_join_boundary("current entity cut", &entities, &["r", "e"], &["r", "e"]);

    let relations = five_bind_plan(
        &pool,
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
    assert_indexed_join_boundary(
        "current relation cut",
        &relations,
        &["r", "q"],
        &["r", "q"],
    );
}

#[tokio::test]
async fn generation_receipt_lookup_uses_the_composite_primary_key() {
    let temporary = TempDir::new().expect("temporary directory");
    let owner = owner(233);
    let owner_layout = layout(&temporary, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("open cognitive store");
    let pool = read_only_pool(&store).await;
    let rows = sqlx::query(
        "EXPLAIN QUERY PLAN
         SELECT source_snapshot_sha256, generation_vector_sha256,
                graph_profile_sha256, generation_sha256, publication_sha256
         FROM kg_projection_generation_semantics
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind("agent_private")
    .bind(1_i64)
    .fetch_all(&pool)
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
