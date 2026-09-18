use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::ProductionCognitiveStore;

fn layout(temp: &TempDir, owner: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root).expect("create fleet root");
    HeptaFleetRoot::parse(root)
        .expect("fleet root")
        .layout()
        .agent(owner)
}

#[tokio::test]
async fn owner_facade_reopens_the_same_durable_sqlite_cut() {
    let temp = TempDir::new().expect("temp dir");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000c01").expect("owner");
    let layout = layout(&temp, &owner);

    let store = ProductionCognitiveStore::open(&layout)
        .await
        .expect("open authoritative store");
    let database_path = store.path().to_path_buf();
    let access = CognitiveAccess::agent_private(owner.clone());
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "cognitive-store-durable-reopen".to_string(),
        content: b"durable owner facade".to_vec(),
        observed_at_unix_seconds: 100,
    };
    store
        .backend_for_test()
        .append_source(&access, &source)
        .await
        .expect("append durable source");
    let before = store
        .recovery_anchor()
        .await
        .expect("capture pre-reopen cut");
    drop(store);

    let reopened = ProductionCognitiveStore::open(&layout)
        .await
        .expect("reopen authoritative store");
    let after = reopened
        .recovery_anchor()
        .await
        .expect("capture post-reopen cut");

    assert_eq!(reopened.path(), database_path.as_path());
    assert_eq!(before, after);
}
