use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

fn vector(cut: &DurableCognitiveSnapshot) -> LaneCGenerationVectorV1 {
    let digest = Digest32::of_bytes(b"test frozen external profile");
    LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("read-only-context").unwrap(),
        memory_ledger_frontier: cut.frontiers().memory,
        source_ledger_frontier: cut.frontiers().source,
        tombstone_frontier: cut.frontiers().tombstone,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest,
        encoder_preprocessor_digest: digest,
        authority_epoch: 1,
        model_digest: digest,
        tokenizer_digest: digest,
        template_digest: digest,
        tool_schema_digest: digest,
    }
}

#[tokio::test]
async fn existing_sqlite_writes_are_readable_by_new_lane_c_after_reopen() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(101);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "event", "evidence"))
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "first".to_string(),
                revision: memory_revision(scope.clone(), "known fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    let before = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    assert_eq!(before.frontiers().memory, 1);
    assert_eq!(before.frontiers().source, 1);
    assert_eq!(
        before.snapshot().records[0].record_id.as_str(),
        first.id.memory_id.as_str()
    );
    let result = before
        .read(ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: before.snapshot().snapshot_digest,
                allowed_kinds: vec![MemoryKind::Fact],
                maximum_results: 10,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 8192,
        })
        .unwrap();
    assert_eq!(result.records(), before.snapshot().records);
    store.pool.close().await;
    let reopened = CognitiveStore::open(&layout).await.unwrap();
    let recovered = reopened
        .revalidate_lane_c_snapshot(&access, &scope, &before, 201)
        .await
        .unwrap();
    assert_eq!(recovered.snapshot(), before.snapshot());
    reopened
        .append_source(
            &access,
            &source(scope.clone(), "later-event", "new unassociated evidence"),
        )
        .await
        .unwrap();
    assert!(matches!(
        reopened
            .revalidate_lane_c_snapshot(&access, &scope, &recovered, 201)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let second = reopened
        .correct_memory(
            &access,
            &first.id.memory_id,
            1,
            &memory_revision(scope.clone(), "corrected fact", citation),
        )
        .await
        .unwrap();
    let corrected = reopened
        .lane_c_snapshot(&access, &scope, 202)
        .await
        .unwrap();
    assert_eq!(
        corrected.snapshot().records[0].revision.get(),
        second.id.revision
    );
    assert_eq!(
        corrected.snapshot().records[0].predecessor_digest,
        Some(before.snapshot().records[0].record_digest())
    );
    assert!(matches!(
        reopened
            .revalidate_lane_c_snapshot(&access, &scope, &before, 202)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
}

#[tokio::test]
async fn tombstone_invalidates_prior_cut_and_survives_reopen() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(102);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "event", "evidence"))
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "forget-me".to_string(),
                revision: memory_revision(scope.clone(), "withdraw this", citation.clone()),
            },
        )
        .await
        .unwrap();
    let before = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    store
        .forget_memory(
            &access,
            &first.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: "owner request".to_string(),
                valid_from_unix_seconds: 300,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    // A committed deletion is immediate, even when its validity label is future-dated.
    let deleted = store.lane_c_snapshot(&access, &scope, 201).await.unwrap();
    assert_eq!(deleted.frontiers().tombstone, 1);
    assert_eq!(deleted.snapshot().records[0].state, RecordState::Tombstone);
    assert!(matches!(
        store
            .revalidate_lane_c_snapshot(&access, &scope, &before, 201)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let result = deleted
        .read(ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: deleted.snapshot().snapshot_digest,
                allowed_kinds: vec![MemoryKind::Fact],
                maximum_results: 10,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 8192,
        })
        .unwrap();
    assert!(result.records().is_empty());
    store.pool.close().await;
    let reopened = CognitiveStore::open(&layout).await.unwrap();
    assert_eq!(
        reopened
            .lane_c_snapshot(&access, &scope, 202)
            .await
            .unwrap()
            .snapshot(),
        deleted.snapshot()
    );
}

#[tokio::test]
async fn scope_provisional_and_time_filters_do_not_leak_unadmitted_facts() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(103);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::workspace_private(owner.clone(), workspace("allowed"));
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace("allowed"),
    };
    let citation = store
        .append_source(&access, &source(scope.clone(), "event", "private evidence"))
        .await
        .unwrap();
    let mut provisional = memory_revision(scope.clone(), "unverified", citation.clone());
    provisional.verification = MemoryVerification::Provisional;
    store
        .create_memory(
            &access,
            &MemoryDraft {
                stable_key: "provisional".to_string(),
                revision: provisional,
            },
        )
        .await
        .unwrap();
    let mut expired = memory_revision(scope.clone(), "expired", citation);
    expired.valid_to_unix_seconds = Some(150);
    store
        .create_memory(
            &access,
            &MemoryDraft {
                stable_key: "expired".to_string(),
                revision: expired,
            },
        )
        .await
        .unwrap();
    let unexpired = store.lane_c_snapshot(&access, &scope, 140).await.unwrap();
    assert_eq!(unexpired.snapshot().records.len(), 1);
    let cut = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    assert!(cut.snapshot().records.is_empty());
    assert_eq!(cut.frontiers().memory, 2);
    assert_eq!(cut.frontiers(), unexpired.frontiers());
    assert!(matches!(
        store
            .revalidate_lane_c_snapshot(&access, &scope, &unexpired, 200)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    assert!(matches!(
        store
            .lane_c_snapshot(&CognitiveAccess::agent_private(owner), &scope, 200)
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    assert!(matches!(
        store
            .lane_c_snapshot(
                &CognitiveAccess::agent_private(agent_id(104)),
                &CognitiveScope::AgentPrivate,
                200
            )
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    let agent_cut = store
        .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200)
        .await
        .unwrap();
    assert_eq!(agent_cut.frontiers().memory, 0);
    assert!(agent_cut.snapshot().records.is_empty());
}

#[tokio::test]
async fn context_binding_rejects_forged_owner_frontiers_and_clock_regression() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(105);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let cut = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    let bound = cut.bind_context(vector(&cut), 200_001, 210_000).unwrap();
    assert_eq!(bound.snapshot(), cut.snapshot());
    let mut forged = vector(&cut);
    forged.tombstone_frontier += 1;
    assert_eq!(
        cut.bind_context(forged, 200_001, 210_000),
        Err(SnapshotProviderError::GenerationGone)
    );
    assert_eq!(
        cut.bind_context(vector(&cut), 201_000, 210_000),
        Err(SnapshotProviderError::InvalidLeaseWindow)
    );
    assert!(matches!(
        store
            .revalidate_lane_c_snapshot(&access, &scope, &cut, 199)
            .await,
        Err(CognitiveStoreError::Invalid(_))
    ));
}

#[tokio::test]
async fn retained_cut_detects_old_valid_backup_after_ordinary_reopen() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(106);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "event", "evidence"))
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "versioned".to_string(),
                revision: memory_revision(scope.clone(), "old", citation.clone()),
            },
        )
        .await
        .unwrap();
    let backup = temp.path().join("old.sqlite3");
    sqlx::query("VACUUM INTO ?")
        .bind(backup.to_str().unwrap())
        .execute(&store.pool)
        .await
        .unwrap();
    store
        .correct_memory(
            &access,
            &first.id.memory_id,
            1,
            &memory_revision(scope.clone(), "current", citation),
        )
        .await
        .unwrap();
    let current = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    let retained_witness = current.cut_digest().to_string();
    store.pool.close().await;
    std::fs::copy(&backup, layout.cognitive_root().join("cognitive_1.sqlite3")).unwrap();
    // Legacy open verifies internal integrity, but cannot know which backup is latest.
    let reopened = CognitiveStore::open(&layout).await.unwrap();
    assert!(matches!(
        reopened
            .revalidate_lane_c_cut(&access, &scope, retained_witness.parse().unwrap(), 201)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
}
