use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;

use super::CognitiveContextError;
use super::read;
use super::read_with_revalidation_hook;

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
    let context = read(&store, &owner, 1, 1, "lemon", 4, None).await.unwrap();
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
    assert!(read(&store, &other, 1, 1, "lemon", 4, None).await.is_err());
}


#[tokio::test]
async fn production_composition_fails_closed_on_midflight_owner_frontier_changes() {
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
                event_key: "authoritative-e2e-seed".to_string(),
                content: b"verified cobalt orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "authoritative-e2e".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified cobalt orchard".to_string(),
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

    // Advance only the source frontier after the authoritative read has been
    // computed. The admitted memory bytes themselves are unchanged, so this
    // specifically proves the broader owner-frontier fence is enforced.
    let source_drift = read_with_revalidation_hook(
        &store,
        &owner,
        1,
        1,
        "cobalt",
        4,
        None,
        || async {
            store
                .append_source(
                    &access,
                    &SourceDraft {
                        scope: scope.clone(),
                        kind: LedgerSourceKind::ExplicitMemoryDirective,
                        event_key: "authoritative-e2e-midflight-source".to_string(),
                        content: b"new evidence while read is in flight".to_vec(),
                        observed_at_unix_seconds: 101,
                    },
                )
                .await?;
            Ok(())
        },
    )
    .await;
    assert!(matches!(
        source_drift,
        Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(_)))
    ));

    // Reacquire from the new source frontier, then revoke the admitted memory
    // in the same deterministic window. Final context consumption must fail
    // closed rather than returning the already-computed content.
    let tombstone_drift = read_with_revalidation_hook(
        &store,
        &owner,
        1,
        1,
        "cobalt",
        4,
        None,
        || async {
            store
                .forget_memory(
                    &access,
                    &memory.id.memory_id,
                    1,
                    &ForgetMemoryDraft {
                        scope: scope.clone(),
                        reason: "midflight authoritative revocation".to_string(),
                        valid_from_unix_seconds: 102,
                        citations: vec![citation.clone()],
                    },
                )
                .await?;
            Ok(())
        },
    )
    .await;
    assert!(matches!(
        tombstone_drift,
        Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(_)))
    ));
}
