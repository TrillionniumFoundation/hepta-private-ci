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
    let context = read(&store, &owner, 1, "lemon", 4).await.unwrap();
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
    let withdrawn = read(&store, &owner, 1, "lemon", 4).await.unwrap();
    assert!(withdrawn.items.is_empty());
    assert!(!withdrawn.plan.as_ref().unwrap().read_allowed);
    assert_ne!(withdrawn.snapshot_digest, context.snapshot_digest);
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(read(&store, &other, 1, "lemon", 4).await.is_err());
}
