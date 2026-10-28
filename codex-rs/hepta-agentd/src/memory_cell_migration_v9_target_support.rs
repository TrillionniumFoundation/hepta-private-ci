//! A separate destination Agentd owner, reopened only from received files.
//! Fixture keys and control-only readiness are explicit qualification seams.

use std::fs::File;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::io::BufReader;
use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdMemoryCellRuntimeV1;
use crate::AgentdState;
use crate::MemoryCellMigrationStoreV9;
use super::process_support::Spec;
use super::process_support::emit;
use super::process_support::spec;
use super::super::process_release_test_support::ProcessRelease;
use super::super::test_support::GateResolver;

pub(super) fn copy_tree(source: &Path, destination: &Path) -> Vec<Value> {
    let mut pending = vec![std::path::PathBuf::new()];
    let mut inventory = Vec::new();
    while let Some(relative) = pending.pop() {
        let input = source.join(&relative);
        let output = destination.join(&relative);
        let metadata = input.symlink_metadata().expect("source file metadata");
        if metadata.is_dir() {
            if !output.exists() { std::fs::create_dir(&output).expect("target data directory"); }
            std::fs::set_permissions(&output, std::fs::Permissions::from_mode(0o700)).expect("private target data");
            for entry in std::fs::read_dir(input).expect("source inventory") {
                pending.push(relative.join(entry.expect("source entry").file_name()));
            }
        } else {
            assert!(metadata.is_file(), "only regular files can enter an image");
            let raw = std::fs::read(&input).expect("source bytes");
            let mut file = File::create_new(&output).expect("distinct new target inode");
            file.write_all(&raw).expect("target bytes");
            file.set_permissions(metadata.permissions()).expect("preserve file mode");
            file.sync_all().expect("target data fsync");
            inventory.push(json!({"path":relative,"bytes":raw.len(),"sha256":Sha256Digest::for_bytes(&raw),
                "mode":metadata.permissions().mode() & 0o777}));
        }
        File::open(output.parent().expect("parent")).and_then(|file| file.sync_all()).expect("target directory fsync");
    }
    inventory.sort_by_key(|row| row["path"].as_str().expect("path").to_string());
    inventory
}

pub(super) async fn target_child() {
    let Spec::Target { active, image_store, manifest, payload, mut checkpoint, unavailable_source } = spec()
        else { panic!("target spec") };
    for path in &unavailable_source { assert!(!path.exists(), "source root must remain unavailable"); }
    let owner = manifest.pin().owner_agent_id.clone();
    let migration = MemoryCellMigrationStoreV9::open(image_store, manifest.clone()).expect("complete committed destination");
    let image = migration.committed_image(&payload).expect("exact image vector");
    let fleet = HeptaFleetRoot::parse(active.join("fleet")).expect("target fleet root");
    let fresh = !fleet.as_path().exists();
    let registry = if fresh { FleetRegistry::initialize(fleet.clone()) } else { FleetRegistry::open_existing(fleet.clone()) }
        .expect("target fleet registry");
    if fresh {
        let workspace = active.join("workspace");
        std::fs::create_dir(&workspace).expect("destination workspace");
        registry.register(AgentManifest::new(owner.clone(), WorkspaceBinding::new(workspace, &fleet).expect("target workspace binding"),
            ResourceBudget::local_default()).expect("owner manifest")).expect("target owner registration");
    }
    let record = registry.load_agent(&owner).expect("registered target owner");
    let mut copied = Vec::new();
    if fresh {
        copied.extend(copy_tree(&image.join("cognitive"), record.layout.cognitive_root()));
        copied.extend(copy_tree(&image.join("artifacts"), &active.join("artifacts")));
    }
    // The independently retained source anchor is checked before opening the
    // ordinary fixture owner. This is not a production writer-lease grant.
    let admitted = DurableCognitiveStore::open_read_only_recovery(&record.layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&manifest.pin().cognitive_anchor)).await.expect("full exact-cut cold image admission");
    assert_eq!(admitted.anchor(), &manifest.pin().cognitive_anchor);
    drop(admitted);
    let starting = registry.compare_and_transition(&owner, record.lifecycle.generation, AgentLifecycle::Starting).expect("target Starting");
    let config = AgentdConfig::load(fleet.as_path().to_path_buf(), owner.clone(), starting.generation,
        record.layout.home_root().to_path_buf(), record.layout.run_root().to_path_buf(), record.layout.home_root().to_path_buf(),
        record.manifest.workspace.as_path().to_path_buf()).expect("target exclusive Agentd writer");
    let identity = config.identity().clone();
    let state = Arc::new(AgentdState::new(identity.clone(), registry.clone(), /*event_capacity*/ 16).expect("target Agentd state"));
    let store = Arc::new(DurableCognitiveStore::open(&identity.layout).await.expect("actual destination SQLite owner"));
    let snapshot = store.memory_cell_snapshot(&CognitiveAccess::agent_private(owner.clone()), &CognitiveScope::AgentPrivate,
        super::super::unix_seconds().expect("clock")).await.expect("destination source snapshot");
    assert_eq!((snapshot.owner_agent_id(), snapshot.scope(), snapshot.owner_cut_digest()),
        (&owner, &manifest.pin().scope, manifest.pin().owner_cut_digest));
    checkpoint.root = active.join("artifacts");
    let selected = ProcessRelease::reopen(&snapshot, checkpoint);
    let bundle = selected.host.load_current().expect("destination signed selected parameters");
    assert_eq!((bundle.owner_cut_digest(), bundle.bundle_digest(), bundle.generation()),
        (manifest.pin().owner_cut_digest, manifest.pin().bundle_digest, manifest.pin().generation));
    state.attach_memory_cells(Arc::new(AgentdMemoryCellRuntimeV1::new(owner.clone(), starting.generation,
        CognitiveScope::AgentPrivate, Arc::clone(&selected.host), Arc::new(GateResolver::default())).expect("native destination runtime")))
        .expect("attach target cells");
    state.attach_cognitive_store(Arc::clone(&store)).expect("attach target store");
    let cancellation = CancellationToken::new();
    let server = AgentdControlServer::bind(identity.control_socket.clone(), Arc::clone(&state), cancellation.clone()).await.expect("target control socket");
    let control = tokio::spawn(server.run());
    let running = registry.compare_and_transition(&owner, starting.generation, AgentLifecycle::Running).expect("target Running");
    state.refresh_generation().expect("current lifecycle");
    state.mark_runtime_prerequisites_ready().expect("target stores and control ready");
    state.mark_app_server_ready().expect("explicit control-only fixture readiness");
    emit(json!({"pid":std::process::id(),"owner":owner,"spawn_generation":starting.generation,"socket":identity.control_socket,
        "pin":manifest.pin(),"copied_files":copied,"fresh":fresh,"source_roots_absent":unavailable_source,"active":active,
        "readiness_profile":"control-only fixture; no App Server process"}));
    let line = BufReader::new(tokio::io::stdin()).lines().next_line().await.expect("stop input");
    assert_eq!(line.as_deref(), Some("stop"));
    let draining = registry.compare_and_transition(&owner, running.generation, AgentLifecycle::Draining).expect("target Draining");
    cancellation.cancel();
    control.await.expect("target control joined").expect("target control stopped");
    drop(bundle); drop(state); drop(selected);
    store.as_ref().clone().close().await;
    drop(store); drop(config);
    let stopped = registry.compare_and_transition(&owner, draining.generation, AgentLifecycle::Stopped).expect("target Stopped");
    emit(json!({"stopped":true,"generation":stopped.generation}));
}
