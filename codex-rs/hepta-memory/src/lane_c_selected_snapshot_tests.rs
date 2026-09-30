use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;

#[tokio::test]
async fn exact_selection_preserves_missing_ids_subsets_and_request_bounds() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(181);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "selection", "evidence"))
        .await
        .unwrap();
    let record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "selected".to_string(),
                revision: memory_revision(scope.clone(), "selected fact", citation),
            },
        )
        .await
        .unwrap();
    let id = StableId::new(record.id.memory_id.as_str()).unwrap();
    let missing = StableId::new("memory:explicitly-missing").unwrap();
    let cut = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 300,
            &[id.clone(), missing.clone()],
        )
        .await
        .unwrap();
    assert_eq!(cut.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(cut.snapshot().records.len(), 1);
    let read = cut
        .owner_snapshot()
        .read_ids(ReadIdsRequestV1 {
            snapshot_digest: cut.snapshot().snapshot_digest,
            record_ids: vec![id.clone(), missing.clone()],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 8192,
        })
        .unwrap();
    assert_eq!(read.missing_ids(), &[missing]);
    let selected = cut.select_ids(std::slice::from_ref(&id)).unwrap();
    assert_ne!(selected.cut_digest(), cut.cut_digest());
    let reacquired = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 301,
            std::slice::from_ref(&id),
        )
        .await
        .unwrap();
    assert_eq!(selected.cut_digest(), reacquired.cut_digest());
    assert!(
        cut.select_ids(&[StableId::new("memory:not-requested").unwrap()])
            .is_err()
    );
    assert!(
        store
            .lane_c_snapshot_ids(
                &access,
                &scope,
                /*now_unix_seconds*/ 300,
                &[id.clone(), id.clone()]
            )
            .await
            .is_err()
    );
    let excessive = (0..513)
        .map(|index| StableId::new(format!("memory:limit-{index}")).unwrap())
        .collect::<Vec<_>>();
    assert!(
        store
            .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &excessive)
            .await
            .is_err()
    );
    assert!(
        store
            .lane_c_snapshot_ids(
                &CognitiveAccess::agent_private(agent_id(182)),
                &scope,
                /*now_unix_seconds*/ 300,
                &[id]
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn selected_cut_rejects_unselected_expiry_source_drift_and_clock_regression() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(183);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "expiry", "evidence"))
        .await
        .unwrap();
    let record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "retained".to_string(),
                revision: memory_revision(scope.clone(), "retained fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    let mut expires = memory_revision(scope.clone(), "unselected expiring fact", citation);
    expires.valid_to_unix_seconds = Some(350);
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "unselected-expiry".to_string(),
                revision: expires,
            },
        )
        .await
        .unwrap();
    let ids = [StableId::new(record.id.memory_id.as_str()).unwrap()];
    let cut = store
        .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &ids)
        .await
        .unwrap();
    store
        .revalidate_lane_c_selection(&access, &scope, &cut, /*now_unix_seconds*/ 301)
        .await
        .unwrap();
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &cut, /*now_unix_seconds*/ 350)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &cut, /*now_unix_seconds*/ 299)
            .await,
        Err(CognitiveStoreError::Invalid(_))
    ));
    store
        .append_source(
            &access,
            &source(scope.clone(), "new-source", "changed source frontier"),
        )
        .await
        .unwrap();
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &cut, /*now_unix_seconds*/ 301)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
}

#[tokio::test]
async fn selected_cut_rejects_correction_tombstone_and_head_pointer_rollback() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(184);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "correction", "evidence"))
        .await
        .unwrap();
    let record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "corrected".to_string(),
                revision: memory_revision(scope.clone(), "first fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    let ids = [StableId::new(record.id.memory_id.as_str()).unwrap()];
    let initial = store
        .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &ids)
        .await
        .unwrap();
    let corrected = store
        .correct_memory(
            &access,
            &record.id.memory_id,
            record.id.revision,
            &memory_revision(scope.clone(), "second fact", citation.clone()),
        )
        .await
        .unwrap();
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &initial, /*now_unix_seconds*/ 300)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let current = store
        .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &ids)
        .await
        .unwrap();
    assert_eq!(current.snapshot().records[0].revision.get(), 2);
    // Corrupt only the owner head pointer; the shared ancestry validator must
    // not hide newer committed revisions behind an older, still-valid row.
    sqlx::query("UPDATE memory_heads SET revision = 1 WHERE memory_id = ?")
        .bind(record.id.memory_id.as_str())
        .execute(&store.pool)
        .await
        .unwrap();
    assert!(matches!(
        store
            .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &ids)
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    sqlx::query("UPDATE memory_heads SET revision = 2 WHERE memory_id = ?")
        .bind(record.id.memory_id.as_str())
        .execute(&store.pool)
        .await
        .unwrap();
    store
        .forget_memory(
            &access,
            &corrected.id.memory_id,
            corrected.id.revision,
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: "selection deletion".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &current, /*now_unix_seconds*/ 300)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
}

#[tokio::test]
async fn exact_owner_read_survives_large_unselected_history_but_bounds_selected_ancestry() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(185);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "capacity", "evidence"))
        .await
        .unwrap();
    let selected = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "small-selected".to_string(),
                revision: memory_revision(scope.clone(), "selected fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    let unrelated = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "large-unselected".to_string(),
                revision: memory_revision(scope.clone(), "unrelated history", citation),
            },
        )
        .await
        .unwrap();
    // Efficient fixture seeding in the SAME physical owner's schema, retaining
    // its immutable rows, contiguous ancestry, citations and foreign keys.
    // The operation under test is the normal owner method, not a test executor.
    let history_depth = 17_000_i64;
    let mut tx = store.pool.begin().await.unwrap();
    sqlx::query(
        "WITH RECURSIVE seq(n) AS (SELECT 2 UNION ALL SELECT n + 1 FROM seq WHERE n < ?)
         INSERT INTO memory_revisions
           (memory_id, revision, owner_agent_id, scope_kind, workspace_sha256, content,
            content_sha256, verification, lifecycle, tombstone_reason, valid_from_unix_seconds,
            valid_to_unix_seconds, supersedes_revision, recorded_at_unix_seconds)
         SELECT r.memory_id, seq.n, r.owner_agent_id, r.scope_kind, r.workspace_sha256, r.content,
                r.content_sha256, r.verification, r.lifecycle, r.tombstone_reason,
                r.valid_from_unix_seconds, r.valid_to_unix_seconds, seq.n - 1, r.recorded_at_unix_seconds
         FROM seq CROSS JOIN memory_revisions r WHERE r.memory_id = ? AND r.revision = 1"
    ).bind(history_depth).bind(unrelated.id.memory_id.as_str()).execute(&mut *tx).await.unwrap();
    sqlx::query(
        "INSERT INTO memory_citations (memory_id, memory_revision, ordinal, source_id, source_revision)
         SELECT r.memory_id, r.revision, c.ordinal, c.source_id, c.source_revision
         FROM memory_revisions r JOIN memory_citations c ON c.memory_id = r.memory_id AND c.memory_revision = 1
         WHERE r.memory_id = ? AND r.revision > 1"
    ).bind(unrelated.id.memory_id.as_str()).execute(&mut *tx).await.unwrap();
    sqlx::query("UPDATE memory_heads SET revision = ? WHERE memory_id = ?")
        .bind(history_depth)
        .bind(unrelated.id.memory_id.as_str())
        .execute(&mut *tx)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    assert!(matches!(
        store
            .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
            .await,
        Err(CognitiveStoreError::Unavailable(_))
    ));
    let selected_ids = [StableId::new(selected.id.memory_id.as_str()).unwrap()];
    let cut = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 300,
            &selected_ids,
        )
        .await
        .unwrap();
    assert_eq!(cut.frontiers().memory, 17_001);
    assert_eq!(cut.snapshot().records.len(), 1);
    store
        .revalidate_lane_c_selection(&access, &scope, &cut, /*now_unix_seconds*/ 301)
        .await
        .unwrap();
    let deep_ids = [StableId::new(unrelated.id.memory_id.as_str()).unwrap()];
    assert!(matches!(
        store
            .lane_c_snapshot_ids(&access, &scope, /*now_unix_seconds*/ 300, &deep_ids)
            .await,
        Err(CognitiveStoreError::Unavailable(_))
    ));
}
