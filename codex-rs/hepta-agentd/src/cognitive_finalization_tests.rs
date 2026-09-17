use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
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
use tokio_util::sync::CancellationToken;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000129").unwrap()
}

#[tokio::test]
async fn control_socket_receipts_change_after_post_read_tombstone() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let lifecycle = FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = lifecycle
        .register(
            AgentManifest::new(
                owner(),
                WorkspaceBinding::new(workspace.clone(), &fleet_root).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    lifecycle
        .compare_and_transition(&owner(), 0, AgentLifecycle::Starting)
        .unwrap();
    let config = crate::AgentdConfig::load(
        fleet_path,
        owner(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let store = Arc::new(CognitiveStore::open(&record.layout).await.unwrap());
    let access = CognitiveAccess::agent_private(owner());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "final-use-source".to_string(),
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
                stable_key: "final-use-memory".to_string(),
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

    let (identity, registry, _writer_lock) = config.into_parts();
    let socket = identity.control_socket.clone();
    let state = Arc::new(crate::AgentdState::new(identity, registry, 16).unwrap());
    state.attach_cognitive_store(Arc::clone(&store)).unwrap();
    lifecycle
        .compare_and_transition(&owner(), 1, AgentLifecycle::Running)
        .unwrap();
    state.mark_app_server_ready().unwrap();
    let cancellation = CancellationToken::new();
    let server = crate::AgentdControlServer::bind(
        socket.clone(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await
    .unwrap();
    let task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(socket, owner(), 1).unwrap();

    let observed = client
        .cognitive_context("lemon".to_string(), 4)
        .await
        .unwrap();
    assert_eq!(observed.items.len(), 1);
    assert!(observed.plan.as_ref().unwrap().read_allowed);

    // Simulate the exact race the native worker must close: the owner returned
    // a valid historical cut, then the selected memory was withdrawn before
    // provider turn/start.
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdrawn before model dispatch".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();

    let final_use = client
        .cognitive_context("lemon".to_string(), 4)
        .await
        .unwrap();
    assert!(final_use.items.is_empty());
    assert!(!final_use.plan.as_ref().unwrap().read_allowed);
    assert_ne!(final_use.snapshot_digest, observed.snapshot_digest);
    assert_ne!(final_use.read_digest, observed.read_digest);

    cancellation.cancel();
    tokio::time::timeout(std::time::Duration::from_secs(2), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
}
