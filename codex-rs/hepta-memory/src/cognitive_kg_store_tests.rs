use pretty_assertions::assert_eq;
use sqlx::Row;
use tempfile::TempDir;

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
            "SELECT COUNT(*) FROM kg_revision_entity_fts WHERE kg_revision_entity_fts MATCH 'Ada'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("FTS5 query"),
        1
    );

    let first_transition = sqlx::query(
        "SELECT predecessor_generation, predecessor_generation_sha256,
                generation_sha256, transition_kind, verification_mode,
                previous_trigger_revision, trigger_memory_revision,
                previous_entity_support_count, next_entity_support_count,
                previous_relation_support_count, next_relation_support_count,
                touched_canonical_entity_count,
                touched_canonical_relation_count,
                trigger_payload_bytes, full_oracle_verified
         FROM kg_projection_generation_transitions
         WHERE projection_scope = ? AND generation = 1",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("first transition receipt");
    assert_eq!(
        first_transition
            .try_get::<Option<i64>, _>("predecessor_generation")
            .expect("predecessor generation"),
        None
    );
    assert_eq!(
        first_transition
            .try_get::<Option<String>, _>("predecessor_generation_sha256")
            .expect("predecessor digest"),
        None
    );
    assert_eq!(
        first_transition
            .try_get::<String, _>("generation_sha256")
            .expect("generation digest"),
        first.projection.generation_sha256.as_str()
    );
    assert_eq!(
        first_transition
            .try_get::<String, _>("transition_kind")
            .expect("transition kind"),
        "baseline_full_oracle"
    );
    assert_eq!(
        first_transition
            .try_get::<String, _>("verification_mode")
            .expect("verification mode"),
        "full_candidate_oracle_v1"
    );
    assert_eq!(
        first_transition
            .try_get::<Option<i64>, _>("previous_trigger_revision")
            .expect("previous trigger revision"),
        None
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("trigger_memory_revision")
            .expect("trigger revision"),
        1
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("previous_entity_support_count")
            .expect("previous entities"),
        0
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("next_entity_support_count")
            .expect("next entities"),
        2
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("previous_relation_support_count")
            .expect("previous relations"),
        0
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("next_relation_support_count")
            .expect("next relations"),
        1
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("touched_canonical_entity_count")
            .expect("touched entities"),
        2
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("touched_canonical_relation_count")
            .expect("touched relations"),
        1
    );
    assert!(
        first_transition
            .try_get::<i64, _>("trigger_payload_bytes")
            .expect("trigger bytes")
            > 0
    );
    assert_eq!(
        first_transition
            .try_get::<i64, _>("full_oracle_verified")
            .expect("oracle verification"),
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

    let second_transition = sqlx::query(
        "SELECT predecessor_generation, predecessor_generation_sha256,
                generation_sha256, transition_kind, verification_mode,
                previous_trigger_revision, trigger_memory_revision,
                previous_entity_support_count, next_entity_support_count,
                previous_relation_support_count, next_relation_support_count,
                touched_canonical_entity_count,
                touched_canonical_relation_count,
                trigger_payload_bytes, full_oracle_verified
         FROM kg_projection_generation_transitions
         WHERE projection_scope = ? AND generation = 2",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("second transition receipt");
    assert_eq!(
        second_transition
            .try_get::<Option<i64>, _>("predecessor_generation")
            .expect("predecessor generation"),
        Some(1)
    );
    assert_eq!(
        second_transition
            .try_get::<Option<String>, _>("predecessor_generation_sha256")
            .expect("predecessor digest")
            .as_deref(),
        Some(first.projection.generation_sha256.as_str())
    );
    assert_eq!(
        second_transition
            .try_get::<String, _>("generation_sha256")
            .expect("generation digest"),
        second.projection.generation_sha256.as_str()
    );
    assert_eq!(
        second_transition
            .try_get::<String, _>("transition_kind")
            .expect("transition kind"),
        "delta_full_oracle"
    );
    assert_eq!(
        second_transition
            .try_get::<String, _>("verification_mode")
            .expect("verification mode"),
        "full_candidate_oracle_v1"
    );
    assert_eq!(
        second_transition
            .try_get::<Option<i64>, _>("previous_trigger_revision")
            .expect("previous trigger revision"),
        Some(1)
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("trigger_memory_revision")
            .expect("trigger revision"),
        2
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("previous_entity_support_count")
            .expect("previous entities"),
        2
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("next_entity_support_count")
            .expect("next entities"),
        1
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("previous_relation_support_count")
            .expect("previous relations"),
        1
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("next_relation_support_count")
            .expect("next relations"),
        0
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("touched_canonical_entity_count")
            .expect("touched entities"),
        2
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("touched_canonical_relation_count")
            .expect("touched relations"),
        1
    );
    assert!(
        second_transition
            .try_get::<i64, _>("trigger_payload_bytes")
            .expect("trigger bytes")
            > 0
    );
    assert_eq!(
        second_transition
            .try_get::<i64, _>("full_oracle_verified")
            .expect("oracle verification"),
        1
    );

    let transition_immutable = sqlx::query(
        "UPDATE kg_projection_generation_transitions
         SET full_oracle_verified = 1
         WHERE projection_scope = ? AND generation = 2",
    )
    .bind(scope.projection_key())
    .execute(&store.pool)
    .await
    .expect_err("transition receipts are append-only");
    assert!(
        transition_immutable
            .to_string()
            .contains("KG generation transition receipts are immutable")
    );

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
