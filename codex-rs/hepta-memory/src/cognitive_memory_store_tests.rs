use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;

#[tokio::test]
async fn memory_identity_survives_verified_revisions_and_tombstone() {
    let temp = TempDir::new().expect("temp dir");
    let agent_id = agent_id(3);
    let store = CognitiveStore::open(&layout(&temp, &agent_id))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(agent_id);
    let citation = store
        .append_source(
            &access,
            &source(CognitiveScope::AgentPrivate, "remember-1", "Name is Ada"),
        )
        .await
        .expect("source");
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "person-name".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "The user's preferred name is Ada.",
                    citation.clone(),
                ),
            },
        )
        .await
        .expect("first memory");
    assert_eq!(first.id.revision, 1);
    assert_eq!(first.supersedes_revision, None);
    assert_eq!(first.verification, MemoryVerification::Verified);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("legacy create generation"),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT extractor_contract FROM kg_revision_fact_sets
             WHERE memory_id = ? AND memory_revision = 1",
        )
        .bind(first.id.memory_id.as_str())
        .fetch_one(&store.pool)
        .await
        .expect("legacy zero-fact receipt"),
        "legacy_memory_api_zero_v1"
    );

    let mut corrected = memory_revision(
        CognitiveScope::AgentPrivate,
        "The user's preferred name is Grace.",
        citation.clone(),
    );
    corrected.valid_from_unix_seconds = 200;
    let second = store
        .correct_memory(&access, &first.id.memory_id, 1, &corrected)
        .await
        .expect("second revision");
    assert_eq!(second.id.memory_id, first.id.memory_id);
    assert_eq!(second.id.revision, 2);
    assert_eq!(second.supersedes_revision, Some(1));
    assert_eq!(second.verification, MemoryVerification::Verified);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("legacy correction generation"),
        2
    );

    let tombstone = ForgetMemoryDraft {
        scope: CognitiveScope::AgentPrivate,
        reason: "explicit_forget".to_string(),
        valid_from_unix_seconds: 300,
        citations: vec![citation],
    };
    let third = store
        .forget_memory(&access, &first.id.memory_id, 2, &tombstone)
        .await
        .expect("tombstone revision");
    assert_eq!(third.id.memory_id, first.id.memory_id);
    assert_eq!(third.id.revision, 3);
    assert_eq!(third.supersedes_revision, Some(2));
    assert_eq!(
        third.lifecycle,
        MemoryLifecycleState::Tombstoned {
            reason: tombstone.reason,
        }
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("legacy forget generation"),
        3
    );

    let stale = store
        .correct_memory(&access, &first.id.memory_id, 1, &corrected)
        .await
        .expect_err("stale revision must fail");
    assert!(matches!(stale, CognitiveStoreError::Conflict(_)));
    let update_error = sqlx::query("UPDATE memory_revisions SET content = 'tampered'")
        .execute(&store.pool)
        .await
        .expect_err("memory revisions must be immutable");
    assert!(
        update_error
            .to_string()
            .contains("memory revisions are immutable")
    );
}
