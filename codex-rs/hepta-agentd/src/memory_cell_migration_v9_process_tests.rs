//! Same-host real TCP/process qualification, not a cross-physical-host claim.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use crate::AgentdClient;
use crate::MemoryCellMigrationImageV9;
use crate::MemoryCellMigrationPinV9;
use crate::MemoryCellMigrationProviderV9;
use crate::MemoryCellMigrationStoreV9;
use super::process_release_test_support::ProcessRelease;
use super::process_test_support::ProcessFleet;
use super::test_support::request;

#[path = "memory_cell_migration_v9_process_support.rs"]
mod process_support;
#[path = "memory_cell_migration_v9_taskflow_support.rs"]
mod taskflow_support;
#[path = "memory_cell_migration_v9_target_support.rs"]
mod target_support;
#[path = "memory_cell_migration_v9_case_support.rs"]
mod case_support;
use process_support::*;

#[test]
#[ignore = "parent-only real migration TCP receiver"]
fn memory_cell_v9_migration_receiver_child() { receiver_child(); }

#[tokio::test]
#[ignore = "parent-only destination Agentd owner"]
async fn memory_cell_v9_migration_target_child() { target_support::target_child().await; }

fn descriptors(root: &Path, prefix: &str) -> BTreeMap<String, File> {
    let mut pending = vec![PathBuf::new()];
    let mut files = BTreeMap::new();
    while let Some(relative) = pending.pop() {
        let path = root.join(&relative);
        let metadata = path.symlink_metadata().expect("image inventory metadata");
        if metadata.is_dir() {
            for entry in std::fs::read_dir(path).expect("image inventory") {
                pending.push(relative.join(entry.expect("file entry").file_name()));
            }
        } else {
            assert!(metadata.is_file(), "no socket or redirected source file");
            let key = format!("{prefix}{}", relative.to_str().expect("source relative UTF-8 path"));
            files.insert(key, File::open(path).expect("quiescent source descriptor"));
        }
    }
    files
}

fn save_json(path: &Path, value: &impl serde::Serialize) {
    let mut file = File::create_new(path).expect("new immutable evidence");
    file.write_all(&serde_json::to_vec_pretty(value).expect("evidence JSON")).expect("write evidence");
    file.sync_all().expect("durable evidence");
}

#[tokio::test]
async fn actual_memory_cell_v9_authorized_image_migration_recovery() {
    let started = Instant::now();
    let temporary = tempfile::tempdir().expect("qualification artifacts");
    let receipt = std::env::var_os("MEMORY_CELL_V9_MIGRATION_RECEIPT_PATH").map(PathBuf::from)
        .unwrap_or_else(|| temporary.path().join("migration-v9.json"));
    let parent = receipt.parent().expect("receipt parent");
    std::fs::create_dir_all(parent).expect("receipt parent");
    let receipt = parent.canonicalize().expect("canonical evidence parent").join(receipt.file_name().expect("receipt name"));
    let directory = receipt.with_extension("artifacts");
    std::fs::create_dir(&directory).expect("new artifacts directory");
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).expect("private artifacts");
    let mut fleet = ProcessFleet::new().await;
    let source_ready = fleet.nodes[0].ready.clone();
    let source_record = fleet.registry.load_agent(&source_ready.owner).expect("source layout");
    let mut checkpoint = source_ready.release.clone().expect("actual signed release checkpoint");
    let query = request(source_ready.scope.clone().expect("source scope"));
    let before = fleet.nodes[0].client.memory_cell_read(query.clone()).await.expect("source native read");
    assert_eq!(before.value, json!(29));
    fleet.nodes[0].crash().await;
    let store = DurableCognitiveStore::open(&source_record.layout).await.expect("quiesce recovered source owner WAL");
    let snapshot = store.memory_cell_snapshot(&CognitiveAccess::agent_private(source_ready.owner.clone()), &CognitiveScope::AgentPrivate,
        super::unix_seconds().expect("clock")).await.expect("actual current source cut");
    let anchor = store.recovery_anchor().await.expect("independently retained full source witness");
    let release = ProcessRelease::reopen(&snapshot, checkpoint.clone());
    let bundle = release.host.load_current().expect("actual selected source parameters");
    let pin = MemoryCellMigrationPinV9::from_source(&snapshot, &bundle, anchor).expect("source-bound migration vector");
    drop(bundle); drop(release);
    let database = store.path().to_path_buf();
    store.close().await;
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!PathBuf::from(format!("{}{suffix}", database.display())).exists(), "only a cold complete DB can be captured");
    }
    let mut input = descriptors(&checkpoint.root, "artifacts/");
    input.insert("cognitive/cognitive_1.sqlite3".into(), File::open(&database).expect("cold source DB descriptor"));
    let first = MemoryCellMigrationImageV9::capture(DESTINATION.into(), 1, None, pin.clone(), input).expect("full source image");
    let mut input = descriptors(&checkpoint.root, "artifacts/");
    input.insert("cognitive/cognitive_1.sqlite3".into(), File::open(&database).expect("cold source descriptor"));
    let second = MemoryCellMigrationImageV9::capture(DESTINATION.into(), 2, Some(first.digest()), pin.clone(), input).expect("coherent successor image");
    for (name, image) in [("source-v1", &first), ("source-v2", &second)] {
        let mut file = File::create_new(directory.join(format!("{name}.bin"))).expect("retain exact transferred payload");
        file.write_all(image.bytes()).expect("retain image"); file.sync_all().expect("image fsync");
        save_json(&directory.join(format!("{name}.manifest.json")), image.manifest());
    }
    let mut cases = Vec::new();
    for stage in ["received", "prepared", "current", "committed"] {
        let (evidence, _) = case_support::transfer_case(&directory, &directory.join(format!("receiver-{stage}")), &source_record.layout,
            &format!("migration-{stage}"), &first, Some(stage)).await;
        save_json(&directory.join(format!("{stage}-taskflow.json")), &evidence);
        cases.push(evidence);
    }
    let receiver_root = directory.join("receiver-final");
    let (normal, historical) = case_support::transfer_case(&directory, &receiver_root, &source_record.layout,
        "migration-normal", &first, None).await;
    cases.push(normal);
    let (successor, _) = case_support::transfer_case(&directory, &receiver_root, &source_record.layout,
        "migration-successor", &second, None).await;
    cases.push(successor);
    let stale = stale_release(&directory, &receiver_root, &first, &second, &historical).await;
    assert!(MemoryCellMigrationStoreV9::open(receiver_root.clone(), first.manifest().clone()).is_err());
    let destination = MemoryCellMigrationStoreV9::open(receiver_root.clone(), second.manifest().clone()).expect("successor provider");
    assert!(destination.committed_image(&first.digest()).is_err());
    let received_root = destination.committed_image(&second.digest()).expect("only the exact successor is available");
    assert_ne!(received_root, checkpoint.root);
    drop(destination);
    // Make accidental dependency on the original source data/artifacts fail.
    let unavailable_source = vec![source_record.layout.cognitive_root().to_path_buf(), checkpoint.root.clone()];
    for path in &unavailable_source {
        std::fs::rename(path, path.with_extension("v9-source-retired")).expect("remove original root from service");
        assert!(!path.exists());
    }
    checkpoint.root = PathBuf::from("/intentionally-unavailable-source-artifacts");
    let active = tempfile::tempdir().expect("short independent destination owner root");
    let active_root = active.path().canonicalize().expect("canonical target root");
    let mut targets = Vec::new();
    let mut old_client: Option<AgentdClient> = None;
    for generation in 1..=2 {
        let process = Process::spawn(&directory, &format!("target-{generation}"), Spec::Target { active: active_root.clone(),
            image_store: receiver_root.clone(), manifest: second.manifest().clone(), payload: second.digest(), checkpoint: checkpoint.clone(),
            unavailable_source: unavailable_source.clone() }).await;
        let client = AgentdClient::new(PathBuf::from(process.ready["socket"].as_str().expect("control path")), pin.owner_agent_id.clone(),
            process.ready["spawn_generation"].as_u64().expect("real spawn generation")).expect("destination control client");
        assert!(client.health().await.expect("destination health").ready);
        let readout = client.memory_cell_read(query.clone()).await.expect("destination-only native parameter readback");
        assert_eq!(readout.value, before.value);
        assert_eq!(readout.cell_digests.len(), 3);
        let stale_traffic = if let Some(stale) = old_client.take() {
            assert!(stale.memory_cell_read(query.clone()).await.is_err(), "old spawn identity remains fenced");
            Some(stale.traffic_snapshot())
        } else { None };
        let ready = process.ready.clone();
        targets.push(json!({"ready":ready,"readout":readout,"control_traffic":client.traffic_snapshot(),"stale_client_traffic":stale_traffic,
            "process":process.finish(/*crashed*/ false).await}));
        old_client = Some(client);
    }
    let target_files = target_support::copy_tree(&active_root.join("artifacts"), &directory.join("activated-artifacts"));
    let target_layout = codex_hepta_paths::HeptaFleetRoot::parse(active_root.join("fleet")).expect("target fleet").layout().agent(&pin.owner_agent_id);
    let target_database = target_support::copy_tree(target_layout.cognitive_root(), &directory.join("activated-cognitive"));
    let taskflow_files = target_support::copy_tree(source_record.layout.automation_root(), &directory.join("taskflow-owner"));
    let source_fleet_traffic = fleet.finish_with_traffic().await;
    let artifact_inventory: Vec<_> = descriptors(&directory, "").into_iter().map(|(path, file)| {
        let metadata = file.metadata().expect("evidence metadata");
        let raw = std::fs::read(directory.join(&path)).expect("complete retained evidence");
        json!({"path":path,"bytes":raw.len(),"sha256":Sha256Digest::for_bytes(&raw),"mode":metadata.permissions().mode() & 0o777})
    }).collect();
    save_json(&receipt, &json!({"schema":"hepta.memory.migration.actual.v9","source":source_ready,"source_readout":before,"pin":pin,
        "payload_sha256":second.digest(),"cases":cases,"stale_release":stale,"targets":targets,"source_fleet_traffic":source_fleet_traffic,
        "target_artifact_files":target_files,"target_cognitive_files":target_database,
        "taskflow_files":taskflow_files,"artifact_inventory":artifact_inventory,"total_lifecycle_ns":started.elapsed().as_nanos().to_string(),
        "limits":["same-host loopback TCP, independent processes and storage roots; not physical cross-host transport",
            "fixture authority and artifact-selector keys; no production writer lease or cross-machine ownership handoff",
            "single-class integration parameters and fixed Apply resolver; no training quality claim",
            "transport counts are application framing bytes, not TCP/IP wire, encryption or kernel retransmit bytes",
            "endpoint attempt timers overlap; crash receiver timer is interrupted, full parent process wall time is retained",
            "target App Server readiness is a control-only fixture seam"],"source_roots_unavailable_during_readback":true}));
    println!("V9 migration evidence: {}", receipt.display());
}

async fn stale_release(directory: &Path, root: &Path, first: &MemoryCellMigrationImageV9, second: &MemoryCellMigrationImageV9,
    historical: &ProviderEffectIntent) -> Value {
    let receiver = Process::spawn(directory, "stale-receiver", Spec::Receiver { root: root.to_path_buf(), manifest: second.manifest().clone(), crash: None }).await;
    let provider = MemoryCellMigrationProviderV9::new(receiver.ready["endpoint"].as_str().expect("endpoint").parse().expect("TCP address"),
        DESTINATION.into(), source_key(), receiver_key().verifying_key()).expect("same destination provider");
    let stale = ProviderEffectIntent::new(ProviderEffectKey::for_logical_effect(DESTINATION, "probe:stale-new-key").expect("probe key"), first.digest());
    assert_eq!(provider.dispatch_with_payload(&stale, first.bytes()).await, ProviderEffectDispatch::Unknown);
    assert_eq!(provider.lookup_for_intent(&stale).await, ProviderEffectLookup::NotFound);
    let status = provider.lookup_for_intent(historical).await;
    assert!(matches!(status, ProviderEffectLookup::Ack(_)), "historical completion survives successor publication");
    json!({"stale_intent":stale,"stale_not_published":true,"historical_completion":status,"traffic":provider.traffic().expect("traffic"),
        "process":receiver.finish(/*crashed*/ false).await})
}
