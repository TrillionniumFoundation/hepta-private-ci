use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CompactionInputRecordV2;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_compact_engine::QualifiedCompactionCandidateV2;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::DurableCognitiveLineageObservation;
use super::MAX_LANE_C_LINEAGE_REVISIONS;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

fn candidate(
    observation: DurableCognitiveLineageObservation,
    protected_record_ids: Vec<StableId>,
) -> QualifiedCompactionCandidateV2 {
    let digest = Digest32::of_bytes(b"lineage test frozen host context");
    let frontiers = observation.frontiers();
    let vector = LaneCGenerationVectorV1 {
        scope_id: observation.scope_id().clone(),
        purpose_id: StableId::new("compact-lineage-test").unwrap(),
        memory_ledger_frontier: frontiers.memory,
        source_ledger_frontier: frontiers.source,
        tombstone_frontier: frontiers.tombstone,
        knowledge_fact_frontier: frontiers.knowledge_facts,
        knowledge_graph_generation: frontiers.knowledge_graph,
        compact_checkpoint_generation: Generation::new(/*value*/ 1).unwrap(),
        prompt_registry_revision: Revision::new(/*value*/ 1).unwrap(),
        retrieval_profile_digest: digest,
        encoder_preprocessor_digest: digest,
        authority_epoch: 1,
        model_digest: digest,
        tokenizer_digest: digest,
        template_digest: digest,
        tool_schema_digest: digest,
    };
    let acquired = u64::try_from(observation.observed_at_unix_seconds()).unwrap() * 1000;
    let key = observation
        .owner_cut()
        .bind_context(vector, acquired, acquired + 1000)
        .unwrap()
        .snapshot_key()
        .clone();
    let policy = CompactionPolicyV2 {
        policy_id: StableId::new("sqlite-lineage-policy").unwrap(),
        algorithm_digest: digest,
        compatibility_digest: digest,
        maximum_retained_records: 1,
        protected_record_ids,
    };
    let inputs = observation
        .into_records()
        .into_iter()
        .map(|record| CompactionInputRecordV2 {
            record,
            retention_priority: 1,
            retention_reason_digest: digest,
        })
        .collect();
    build_qualified_candidate(
        key,
        Generation::new(/*value*/ 1).unwrap(),
        /*predecessor_checkpoint_digest*/ None,
        &policy,
        inputs,
    )
    .unwrap()
}

fn support_digest(heads: &[MemoryRecord]) -> Digest32 {
    let mut digests = heads
        .iter()
        .map(MemoryRecord::record_digest)
        .collect::<Vec<_>>();
    digests.sort();
    let mut bytes = b"hepta.compaction-support-manifest.v3".to_vec();
    bytes.extend_from_slice(&(digests.len() as u64).to_be_bytes());
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[tokio::test]
async fn sqlite_complete_original_revision_chains_reach_native_compaction_without_resurrection() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 111);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "lineage", "evidence"))
        .await
        .unwrap();
    let live = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "corrected".to_string(),
                revision: memory_revision(scope.clone(), "old fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    store
        .correct_memory(
            &access,
            &live.id.memory_id,
            live.id.revision,
            &memory_revision(scope.clone(), "current fact", citation.clone()),
        )
        .await
        .unwrap();
    let deleted = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "deleted".to_string(),
                revision: memory_revision(scope.clone(), "withdrawn fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    store
        .forget_memory(
            &access,
            &deleted.id.memory_id,
            deleted.id.revision,
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: "withdraw".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout).await.unwrap();
    let observation = reopened
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
        .await
        .unwrap();
    assert_eq!(
        (
            observation.records().len(),
            observation.source_head_count(),
            observation.excluded_head_count()
        ),
        (4, 2, 0)
    );
    assert_eq!(
        (
            observation.frontiers().memory,
            observation.frontiers().tombstone
        ),
        (4, 1)
    );
    for chain in observation.records().chunks_exact(2) {
        assert_eq!((chain[0].revision.get(), chain[1].revision.get()), (1, 2));
        assert_eq!(chain[1].predecessor_digest, Some(chain[0].record_digest()));
        assert_eq!(chain[0].record_id, chain[1].record_id);
    }
    let heads = observation.current_heads().to_vec();
    let live_head = heads
        .iter()
        .find(|head| head.state == RecordState::Live)
        .unwrap()
        .clone();
    let deleted_head = heads
        .iter()
        .find(|head| head.state == RecordState::Tombstone)
        .unwrap()
        .clone();
    let built = candidate(
        observation,
        heads.iter().map(|head| head.record_id.clone()).collect(),
    );
    assert_eq!(built.retained_records, vec![live_head]);
    assert_eq!(
        built.deleted_record_digests,
        vec![deleted_head.record_digest()]
    );
    assert_eq!(
        built.checkpoint.support_manifest_digest,
        support_digest(&heads)
    );
    assert_eq!(
        (
            built.loss_report.source_current_heads,
            built.loss_report.deleted_records,
            built.loss_report.protected_deleted_records
        ),
        (2, 1, 1)
    );
    assert_eq!(built.authority, AuthorityPosture::DENY_ALL);
}

#[tokio::test]
async fn expired_future_and_provisional_heads_exclude_entire_chains_but_bind_physical_coverage() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 112);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "eligibility", "evidence"))
        .await
        .unwrap();
    let expired = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "expired".to_string(),
                revision: memory_revision(scope.clone(), "previous eligible", citation.clone()),
            },
        )
        .await
        .unwrap();
    let mut expired_head = memory_revision(scope.clone(), "now expired", citation.clone());
    expired_head.valid_to_unix_seconds = Some(200);
    store
        .correct_memory(
            &access,
            &expired.id.memory_id,
            expired.id.revision,
            &expired_head,
        )
        .await
        .unwrap();
    for (key, verification, valid_from) in [
        ("provisional", MemoryVerification::Provisional, 100),
        ("future", MemoryVerification::Verified, 400),
        ("eligible", MemoryVerification::Verified, 100),
    ] {
        let mut revision = memory_revision(scope.clone(), key, citation.clone());
        revision.verification = verification;
        revision.valid_from_unix_seconds = valid_from;
        store
            .create_memory(
                &access,
                &MemoryDraft {
                    stable_key: key.to_string(),
                    revision,
                },
            )
            .await
            .unwrap();
    }
    let observation = store
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
        .await
        .unwrap();
    assert_eq!(
        (
            observation.source_head_count(),
            observation.excluded_head_count(),
            observation.frontiers().memory
        ),
        (4, 3, 5)
    );
    assert_eq!(observation.records(), observation.current_heads());
    assert_eq!(observation.records().len(), 1);
    assert_ne!(observation.source_head_manifest_digest(), Digest32::ZERO);
    let eligible_heads = observation.current_heads().to_vec();
    let built = candidate(observation, Vec::new());
    assert_eq!(built.retained_records, eligible_heads);
    assert_eq!(
        built.checkpoint.support_manifest_digest,
        support_digest(&eligible_heads)
    );
    assert_eq!(built.loss_report.source_current_heads, 1);
}

#[tokio::test]
async fn revalidation_returns_current_cut_and_rejects_time_only_eligibility_flip_or_clock_regression()
 {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 113);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "clock", "evidence"))
        .await
        .unwrap();
    for (key, valid_from, valid_to) in [("expires", 100, Some(200)), ("becomes-valid", 200, None)] {
        let mut revision = memory_revision(scope.clone(), key, citation.clone());
        revision.valid_from_unix_seconds = valid_from;
        revision.valid_to_unix_seconds = valid_to;
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: key.to_string(),
                    revision,
                },
            )
            .await
            .unwrap();
    }
    let before = store
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 100)
        .await
        .unwrap();
    let current = store
        .revalidate_lane_c_lineage(&access, &scope, &before, /*now_unix_seconds*/ 150)
        .await
        .unwrap();
    assert_eq!(
        current.source_binding_digest(),
        before.source_binding_digest()
    );
    assert_eq!(current.observed_at_unix_seconds(), 150);
    assert_ne!(current.observation_digest(), before.observation_digest());
    let flipped = store
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 201)
        .await
        .unwrap();
    assert_eq!(
        (flipped.source_head_count(), flipped.excluded_head_count()),
        (before.source_head_count(), before.excluded_head_count())
    );
    assert_ne!(flipped.current_heads(), before.current_heads());
    assert!(matches!(
        store
            .revalidate_lane_c_lineage(&access, &scope, &before, /*now_unix_seconds*/ 201)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    assert!(matches!(
        store
            .revalidate_lane_c_lineage(&access, &scope, &before, /*now_unix_seconds*/ 99)
            .await,
        Err(CognitiveStoreError::Invalid(_))
    ));
}

#[tokio::test]
async fn lineage_requires_matching_agent_and_workspace_access() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 114);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let digest = workspace("lineage-private");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: digest.clone(),
    };
    let access = CognitiveAccess::workspace_private(owner.clone(), digest);
    let citation = store
        .append_source(
            &access,
            &source(scope.clone(), "private", "private evidence"),
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "private".to_string(),
                revision: memory_revision(scope.clone(), "private fact", citation),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        store
            .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
            .await
            .unwrap()
            .records()
            .len(),
        1
    );
    for denied in [
        CognitiveAccess::agent_private(owner.clone()),
        CognitiveAccess::workspace_private(owner.clone(), workspace("wrong")),
        CognitiveAccess::workspace_private(agent_id(/*suffix*/ 115), workspace("lineage-private")),
    ] {
        assert!(matches!(
            store
                .lane_c_lineage(&denied, &scope, /*now_unix_seconds*/ 300)
                .await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
    }
    let agent_access = CognitiveAccess::agent_private(owner);
    assert!(
        store
            .lane_c_lineage(
                &agent_access,
                &CognitiveScope::AgentPrivate,
                /*now_unix_seconds*/ 300
            )
            .await
            .unwrap()
            .records()
            .is_empty()
    );
}

#[tokio::test]
async fn owner_read_rejects_foreign_scope_citation_inserted_around_admission() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 116);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "local", "local evidence"))
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "local".to_string(),
                revision: memory_revision(scope.clone(), "local fact", citation),
            },
        )
        .await
        .unwrap();
    let workspace_digest = workspace("foreign-scope");
    let foreign_access = CognitiveAccess::workspace_private(owner, workspace_digest.clone());
    let foreign_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_digest,
    };
    let foreign = store
        .append_source(
            &foreign_access,
            &source(foreign_scope, "foreign", "foreign evidence"),
        )
        .await
        .unwrap();
    sqlx::query("INSERT INTO memory_citations (memory_id, memory_revision, ordinal, source_id, source_revision) VALUES (?, 1, 1, ?, 1)")
        .bind(memory.id.memory_id.as_str()).bind(foreign.source_id.as_str()).execute(&store.pool).await.unwrap();
    assert!(matches!(
        store
            .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    assert!(matches!(
        store
            .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    assert!(matches!(
        store
            .lane_c_snapshot_page(
                &access, &scope, /*now_unix_seconds*/ 300, /*maximum_heads*/ 1,
                /*after*/ None
            )
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn sqlite_terminal_tombstone_cannot_be_replayed_as_live_ancestry() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 117);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "terminal", "evidence"))
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "terminal".to_string(),
                revision: memory_revision(scope.clone(), "old live", citation.clone()),
            },
        )
        .await
        .unwrap();
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &ForgetMemoryDraft {
                scope: scope.clone(),
                reason: "terminal".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    sqlx::query("INSERT INTO memory_revisions SELECT memory_id, 3, owner_agent_id, scope_kind, workspace_sha256, content, content_sha256, verification, 'active', NULL, valid_from_unix_seconds, valid_to_unix_seconds, 2, recorded_at_unix_seconds FROM memory_revisions WHERE memory_id = ? AND revision = 2")
        .bind(memory.id.memory_id.as_str()).execute(&store.pool).await.unwrap();
    sqlx::query("INSERT INTO memory_citations SELECT memory_id, 3, ordinal, source_id, source_revision FROM memory_citations WHERE memory_id = ? AND memory_revision = 2")
        .bind(memory.id.memory_id.as_str()).execute(&store.pool).await.unwrap();
    sqlx::query("UPDATE memory_heads SET revision = 3 WHERE memory_id = ?")
        .bind(memory.id.memory_id.as_str())
        .execute(&store.pool)
        .await
        .unwrap();
    assert!(matches!(
        store.lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300).await,
        Err(CognitiveStoreError::Corrupt(reason)) if reason.contains("resurrection")
    ));
}

#[tokio::test]
async fn whole_scope_lineage_rejects_revision_budget_overflow_instead_of_returning_prefix() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 118);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "budget", "evidence"))
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "budget".to_string(),
                revision: memory_revision(scope.clone(), "fact", citation),
            },
        )
        .await
        .unwrap();
    let maximum = i64::try_from(MAX_LANE_C_LINEAGE_REVISIONS).unwrap();
    sqlx::query("WITH RECURSIVE revisions(n) AS (SELECT 2 UNION ALL SELECT n + 1 FROM revisions WHERE n < ?) INSERT INTO memory_revisions SELECT r.memory_id, n, r.owner_agent_id, r.scope_kind, r.workspace_sha256, r.content, r.content_sha256, r.verification, r.lifecycle, r.tombstone_reason, r.valid_from_unix_seconds, r.valid_to_unix_seconds, n - 1, r.recorded_at_unix_seconds FROM revisions JOIN memory_revisions r ON r.memory_id = ? AND r.revision = 1")
        .bind(maximum + 1).bind(memory.id.memory_id.as_str()).execute(&store.pool).await.unwrap();
    sqlx::query("INSERT INTO memory_citations SELECT memory_id, revision, 0, ?, 1 FROM memory_revisions WHERE memory_id = ? AND revision > 1")
        .bind(memory.citations[0].source_id.as_str()).bind(memory.id.memory_id.as_str()).execute(&store.pool).await.unwrap();
    sqlx::query("UPDATE memory_heads SET revision = ? WHERE memory_id = ?")
        .bind(maximum + 1)
        .bind(memory.id.memory_id.as_str())
        .execute(&store.pool)
        .await
        .unwrap();
    assert!(
        matches!(store.lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300).await, Err(CognitiveStoreError::Unavailable(reason)) if reason.contains("revision capacity"))
    );
}
