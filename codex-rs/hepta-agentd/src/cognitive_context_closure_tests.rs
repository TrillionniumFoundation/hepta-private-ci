use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;

use super::read;
use super::revalidate;
use super::revalidate_with_retrieval_context;

#[tokio::test]
async fn real_owner_rejects_plan_receipt_substitution_and_generation_replay() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000181").unwrap();
    let layout = HeptaFleetRoot::parse(std::fs::canonicalize(fleet).unwrap())
        .unwrap()
        .layout()
        .agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "plan-closure-source".to_string(),
                content: b"verified receipt closure".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "plan-closure-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope,
                    content: "verified receipt closure".to_string(),
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
    let context = read(&store, &owner, /*body_generation*/ 1, "receipt closure", /*limit*/ 4, /*ranker*/ None)
        .await
        .unwrap();
    assert_eq!(context.items.len(), 1);
    revalidate(
        &store,
        &owner,
        &context.snapshot_digest,
        &context.read_digest,
        context.omitted_records,
        &context.items,
        context.plan.as_ref(),
        /*ranker*/ None,
    )
    .await
    .unwrap();
    let mut substituted = context.plan.clone().unwrap();
    substituted.plan_receipt_digest = Digest32::of_bytes(b"different-plan-receipt").to_string();
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            Some(&substituted),
            /*ranker*/ None,
        )
        .await
        .is_err()
    );
    assert!(
        revalidate_with_retrieval_context(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            context.plan.as_ref(),
            /*ranker*/ None,
            /*body_generation*/ 2,
            /*current_retrieval*/ None,
        )
        .await
        .is_err()
    );
    let mut oversize = context.items.clone();
    oversize[0].content = "x".repeat(crate::MAX_COGNITIVE_CONTEXT_BYTES + 1);
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &oversize,
            context.plan.as_ref(),
            /*ranker*/ None,
        )
        .await
        .is_err()
    );
}
