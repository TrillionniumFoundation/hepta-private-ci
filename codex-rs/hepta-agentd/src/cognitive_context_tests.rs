use codex_hepta_cognitive_read::AuthoritativeReadRequestV1;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_authoritative;
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
use codex_hepta_types::StableId;

use super::authoritative_provider;
use super::context_purpose_id;
use super::read;

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
    let context = read(&store, &owner, 1, 2, "lemon", 4, None).await.unwrap();
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
    let withdrawn = read(&store, &owner, 1, 2, "lemon", 4, None).await.unwrap();
    assert!(withdrawn.items.is_empty());
    assert!(!withdrawn.plan.as_ref().unwrap().read_allowed);
    assert_ne!(withdrawn.snapshot_digest, context.snapshot_digest);
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(read(&store, &other, 1, 2, "lemon", 4, None).await.is_err());
}

fn must<T, E: std::fmt::Display>(result: Result<T, E>, context: &str) -> T {
    result.unwrap_or_else(|error| panic!("{context}: {error}"))
}

#[tokio::test]
async fn authoritative_final_use_fail_closes_on_frontier_epoch_and_lease_drift() {
    let temp = must(tempfile::tempdir(), "tempdir");
    let fleet = temp.path().join("fleet");
    must(std::fs::create_dir_all(&fleet), "create fleet");
    let owner = must(
        AgentId::parse("00000000-0000-4000-8000-000000000121"),
        "owner id",
    );
    let fleet_root = must(HeptaFleetRoot::parse(fleet), "fleet root");
    let layout = fleet_root.layout().agent(&owner);
    let store = must(CognitiveStore::open(&layout).await, "open store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = must(
        store
            .append_source(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "authoritative-context-test".to_string(),
                    content: b"authoritative evidence".to_vec(),
                    observed_at_unix_seconds: 100,
                },
            )
            .await,
        "append source",
    );
    let memory = must(
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: "authoritative-record".to_string(),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: "authoritative lemon fact".to_string(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation.clone()],
                    },
                },
            )
            .await,
        "remember memory",
    );

    let initial_ms = 150_000;
    let initial_cut = must(
        store.lane_c_snapshot(&access, &scope, 150).await,
        "initial lane C cut",
    );
    let initial_provider = must(
        authoritative_provider(&initial_cut, 2, None, initial_ms),
        "initial provider",
    );
    let initial_request = SnapshotAcquisitionRequestV1 {
        request_id: must(
            StableId::new("context-adversarial-initial"),
            "initial request id",
        ),
        scope_id: initial_cut.scope_id().clone(),
        purpose_id: must(context_purpose_id(), "context purpose"),
        minimum_memory_frontier: initial_cut.frontiers().memory,
        minimum_tombstone_frontier: initial_cut.frontiers().tombstone,
        authority_epoch: 2,
        deadline_unix_ms: 152_000,
    };
    let guard = must(
        read_authoritative(
            &initial_provider,
            initial_ms,
            initial_request,
            AuthoritativeReadRequestV1 {
                allowed_kinds: Vec::new(),
                maximum_results: 16,
                include_tombstones: false,
                maximum_encoded_bytes: 8192,
            },
        ),
        "initial authoritative read",
    );

    must(
        store
            .correct_memory(
                &access,
                &memory.id.memory_id,
                1,
                &MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "corrected authoritative lemon fact".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            )
            .await,
        "correct memory",
    );
    let advanced_cut = must(
        store.lane_c_snapshot(&access, &scope, 150).await,
        "advanced lane C cut",
    );
    let advanced_provider = must(
        authoritative_provider(&advanced_cut, 2, None, 150_100),
        "advanced provider",
    );
    assert_eq!(
        guard.revalidate(&advanced_provider, 150_100),
        Err(SnapshotProviderError::GenerationGone)
    );

    let epoch_request = SnapshotAcquisitionRequestV1 {
        request_id: must(
            StableId::new("context-adversarial-epoch"),
            "epoch request id",
        ),
        scope_id: advanced_cut.scope_id().clone(),
        purpose_id: must(context_purpose_id(), "epoch purpose"),
        minimum_memory_frontier: advanced_cut.frontiers().memory,
        minimum_tombstone_frontier: advanced_cut.frontiers().tombstone,
        authority_epoch: 2,
        deadline_unix_ms: 152_500,
    };
    let epoch_provider = must(
        authoritative_provider(&advanced_cut, 2, None, 150_200),
        "epoch provider",
    );
    let epoch_guard = must(
        read_authoritative(
            &epoch_provider,
            150_200,
            epoch_request,
            AuthoritativeReadRequestV1 {
                allowed_kinds: Vec::new(),
                maximum_results: 16,
                include_tombstones: false,
                maximum_encoded_bytes: 8192,
            },
        ),
        "epoch authoritative read",
    );
    let revoked_provider = must(
        authoritative_provider(&advanced_cut, 3, None, 150_300),
        "revoked provider",
    );
    assert_eq!(
        epoch_guard.revalidate(&revoked_provider, 150_300),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );

    let lease_request = SnapshotAcquisitionRequestV1 {
        request_id: must(
            StableId::new("context-adversarial-lease"),
            "lease request id",
        ),
        scope_id: advanced_cut.scope_id().clone(),
        purpose_id: must(context_purpose_id(), "lease purpose"),
        minimum_memory_frontier: advanced_cut.frontiers().memory,
        minimum_tombstone_frontier: advanced_cut.frontiers().tombstone,
        authority_epoch: 2,
        deadline_unix_ms: 153_000,
    };
    let lease_provider = must(
        authoritative_provider(&advanced_cut, 2, None, 150_400),
        "lease provider",
    );
    let lease_guard = must(
        read_authoritative(
            &lease_provider,
            150_400,
            lease_request,
            AuthoritativeReadRequestV1 {
                allowed_kinds: Vec::new(),
                maximum_results: 16,
                include_tombstones: false,
                maximum_encoded_bytes: 8192,
            },
        ),
        "lease authoritative read",
    );
    assert_eq!(
        lease_guard.revalidate(&lease_provider, 151_400),
        Err(SnapshotProviderError::LeaseExpired)
    );
}
