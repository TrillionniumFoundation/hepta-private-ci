use codex_hepta_cognitive_store::CognitiveRecoveryError;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::open_authoritative;
use codex_hepta_cognitive_store::open_authoritative_read_only_recovery;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000971").expect("owner id")
}

#[tokio::test]
async fn canonical_facade_reopens_same_durable_sqlite_cut() {
    let temp = TempDir::new().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet"))
        .expect("fleet");
    let owner = owner();
    let layout = fleet.layout().agent(&owner);

    let first = open_authoritative(&layout).await.expect("first open");
    assert_eq!(first.owner_agent_id(), &owner);
    let database_path = first.path().to_path_buf();
    assert!(database_path.is_file(), "authoritative SQLite file must exist");
    let first_anchor = first.recovery_anchor().await.expect("first anchor");
    drop(first);

    let reopened = open_authoritative(&layout).await.expect("reopen");
    assert_eq!(reopened.path(), database_path.as_path());
    assert_eq!(
        reopened.recovery_anchor().await.expect("reopened anchor"),
        first_anchor,
        "reopen must preserve the exact durable owner cut"
    );
}

#[tokio::test]
async fn revoked_recovery_never_falls_back_to_normal_open() {
    let temp = TempDir::new().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet"))
        .expect("fleet");
    let owner = owner();
    let layout = fleet.layout().agent(&owner);
    let store = open_authoritative(&layout).await.expect("seed store");
    drop(store);

    let result = open_authoritative_read_only_recovery(
        &layout,
        CognitiveRecoveryRequirement::Revoked,
    )
    .await;
    assert!(matches!(result, Err(CognitiveRecoveryError::AccessDenied(_))));
}
