use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;

use super::read;
use super::read_with_after_product_rank;

#[path = "cognitive_context_budget_tests.rs"]
mod budget;

#[tokio::test]
async fn context_reads_real_owner_content_and_removes_committed_tombstones() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "context-test".to_string(),
                content: b"verified lemon orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "orchard".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified lemon orchard".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();
    let context = read(&store, &owner, 1, "lemon", 4, None).await.unwrap();
    assert_eq!(context.items.len(), 1);
    assert!(context.plan.as_ref().unwrap().read_allowed);
    assert_eq!(context.items[0].memory_id, memory.id.memory_id.as_str());
    assert_eq!(context.items[0].content, "verified lemon orchard");
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdrawn".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    let withdrawn = read(&store, &owner, 1, "lemon", 4, None).await.unwrap();
    assert!(withdrawn.items.is_empty());
    assert!(!withdrawn.plan.as_ref().unwrap().read_allowed);
    assert_ne!(withdrawn.snapshot_digest, context.snapshot_digest);
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(read(&store, &other, 1, "lemon", 4, None).await.is_err());
}

#[tokio::test]
async fn post_rank_withdrawal_cannot_attach_stale_memory() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000121").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "post-rank-withdrawal".to_string(),
                content: b"ranked apricot memory".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "apricot".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "ranked apricot memory".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();

    let hook_store = store.clone();
    let hook_access = access.clone();
    let hook_scope = scope.clone();
    let hook_memory_id = memory.id.memory_id.clone();
    let hook_citation = citation.clone();
    let result = read_with_after_product_rank(
        &store,
        &owner,
        1,
        "apricot",
        4,
        None,
        move || async move {
            hook_store
                .forget_memory(
                    &hook_access,
                    &hook_memory_id,
                    1,
                    &ForgetMemoryDraft {
                        scope: hook_scope,
                        reason: "withdrawn after ranking".to_string(),
                        valid_from_unix_seconds: 200,
                        citations: vec![hook_citation],
                    },
                )
                .await
                .unwrap();
        },
    )
    .await;

    // The ranked candidate belonged to the old owner cut. The batch binding
    // revalidation observes the tombstone and the final cut revalidation makes
    // the whole request fail closed rather than returning the stale text.
    assert!(result.is_err());

    let after = read(&store, &owner, 1, "apricot", 4, None).await.unwrap();
    assert!(after.items.is_empty());
    assert!(!after.plan.as_ref().unwrap().read_allowed);
}
