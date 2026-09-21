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
use super::revalidate;

#[path = "cognitive_context_budget_tests.rs"]
mod budget;

#[tokio::test]
async fn context_reads_real_owner_content_and_removes_committed_tombstones() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let fleet = std::fs::canonicalize(&fleet).unwrap();
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
    let current = revalidate(
        &store,
        &owner,
        &context.snapshot_digest,
        &context.read_digest,
        context.omitted_records,
        &context.items,
        context.plan.as_ref(),
        None,
    )
    .await
    .unwrap();
    assert_eq!(current.snapshot_digest, context.snapshot_digest);
    assert_eq!(current.read_digest, context.read_digest);
    assert_eq!(
        usize::from(current.verified_item_count),
        context.items.len()
    );
    let mut tampered_plan = context.plan.clone().unwrap();
    tampered_plan.evaluated_context_digest = "22".repeat(32);
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            Some(&tampered_plan),
            None,
        )
        .await
        .is_err(),
        "a substituted ordered-context digest must fail final-use validation"
    );
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &"11".repeat(32),
            context.omitted_records,
            &context.items,
            context.plan.as_ref(),
            None,
        )
        .await
        .is_err(),
        "a forged read receipt must fail final-use validation"
    );
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
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            context.plan.as_ref(),
            None,
        )
        .await
        .is_err(),
        "a committed tombstone must invalidate the historical read receipt"
    );
    let withdrawn = read(&store, &owner, 1, "lemon", 4, None).await.unwrap();
    assert!(withdrawn.items.is_empty());
    assert!(!withdrawn.plan.as_ref().unwrap().read_allowed);
    assert_ne!(withdrawn.snapshot_digest, context.snapshot_digest);
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(read(&store, &other, 1, "lemon", 4, None).await.is_err());
}

#[tokio::test]
async fn final_use_binds_complete_owner_cut_not_only_memory_snapshot() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let fleet = std::fs::canonicalize(&fleet).unwrap();
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
                event_key: "cut-binding-memory-source".to_string(),
                content: b"verified owner cut binding marker".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "cut-binding-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified owner cut binding marker".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();

    let context = read(&store, &owner, 1, "binding marker", 4, None)
        .await
        .unwrap();
    assert_eq!(context.items.len(), 1);
    let before = store
        .lane_c_snapshot(&access, &scope, 200)
        .await
        .unwrap();
    assert_eq!(
        before.snapshot().snapshot_digest.to_string(),
        context.snapshot_digest
    );

    // Advance an owner frontier without changing any memory head. A final-use
    // binding that only compared CognitiveSnapshot.snapshot_digest would miss
    // this drift even though the declared coherent owner cut changed.
    store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "cut-binding-unrelated-source".to_string(),
                content: b"unrelated source frontier advance".to_vec(),
                observed_at_unix_seconds: 150,
            },
        )
        .await
        .unwrap();
    let after = store
        .lane_c_snapshot(&access, &scope, 200)
        .await
        .unwrap();
    assert_eq!(
        after.snapshot().snapshot_digest,
        before.snapshot().snapshot_digest,
        "memory snapshot must remain identical so the regression isolates owner-cut drift"
    );
    assert_ne!(after.cut_digest(), before.cut_digest());

    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            context.plan.as_ref(),
            None,
        )
        .await
        .is_err(),
        "source/KG/tombstone frontier drift must stale the final-use packet even when memory heads are unchanged"
    );
}
