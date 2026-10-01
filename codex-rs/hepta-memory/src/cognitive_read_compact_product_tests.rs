use std::sync::Arc;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CognitiveReadCompactionRetentionV1;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn policy(record_id: StableId) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: StableId::new("policy:cognitive-read-compaction").unwrap(),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: 1,
        protected_record_ids: vec![record_id],
    }
}

fn vector(cut: &super::super::DurableCognitiveSelectionSnapshot) -> LaneCGenerationVectorV1 {
    LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new(COGNITIVE_READ_COMPACTION_PURPOSE_ID).unwrap(),
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-preprocessor"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    }
}

#[tokio::test]
async fn normal_owner_path_binds_full_lineage_exact_read_and_final_cut() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(211);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "compact", "evidence"))
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "compact-product".to_string(),
                revision: memory_revision(scope.clone(), "first", citation.clone()),
            },
        )
        .await
        .unwrap();
    let second = store
        .correct_memory(
            &access,
            &first.id.memory_id,
            first.id.revision,
            &memory_revision(scope.clone(), "second", citation),
        )
        .await
        .unwrap();
    let record_id = StableId::new(second.id.memory_id.as_str()).unwrap();
    let cut = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 300,
            std::slice::from_ref(&record_id),
        )
        .await
        .unwrap();
    let result = store
        .build_cognitive_read_compaction_candidate(
            &access,
            &scope,
            /*now_unix_seconds*/ 300,
            vector(&cut),
            Generation::new(1).unwrap(),
            None,
            &policy(record_id.clone()),
            vec![CognitiveReadCompactionRetentionV1 {
                record_id,
                retention_priority: 10,
                retention_reason_digest: digest("retention-reason"),
            }],
        )
        .await
        .unwrap();

    result.validate().unwrap();
    assert_eq!(result.candidate().retained_records.len(), 1);
    assert_eq!(
        result.candidate().retained_records[0].revision.get(),
        second.id.revision
    );
    assert!(!result.owner_cut_digest().is_zero());
    assert!(!result.read_receipt_digest().is_zero());
    assert_eq!(result.authority(), AuthorityPosture::DENY_ALL);
}

#[tokio::test]
async fn concurrent_correction_is_rejected_before_candidate_publication() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(212);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "race", "evidence"))
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "compact-race".to_string(),
                revision: memory_revision(scope.clone(), "first", citation.clone()),
            },
        )
        .await
        .unwrap();
    let record_id = StableId::new(first.id.memory_id.as_str()).unwrap();
    let cut = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 300,
            std::slice::from_ref(&record_id),
        )
        .await
        .unwrap();
    let generation_vector = vector(&cut);
    let hook = Arc::new(CompactionFinalRevalidationHook {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    install_compaction_final_revalidation_hook(Arc::clone(&hook));

    let task_store = store.clone();
    let task_access = access.clone();
    let task_scope = scope.clone();
    let task_record_id = record_id.clone();
    let task = tokio::spawn(async move {
        task_store
            .build_cognitive_read_compaction_candidate(
                &task_access,
                &task_scope,
                /*now_unix_seconds*/ 300,
                generation_vector,
                Generation::new(1).unwrap(),
                None,
                &policy(task_record_id.clone()),
                vec![CognitiveReadCompactionRetentionV1 {
                    record_id: task_record_id,
                    retention_priority: 10,
                    retention_reason_digest: digest("retention-reason"),
                }],
            )
            .await
    });
    hook.reached.notified().await;
    store
        .correct_memory(
            &access,
            &first.id.memory_id,
            first.id.revision,
            &memory_revision(scope, "corrected during build", citation),
        )
        .await
        .unwrap();
    hook.release.notify_one();
    assert!(matches!(
        task.await.unwrap(),
        Err(CognitiveStoreError::Conflict(_))
    ));
}
