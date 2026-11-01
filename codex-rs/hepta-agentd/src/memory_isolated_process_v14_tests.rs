//! Two distinct owner processes with real Agentd sockets and cold same-host TCP
//! transfer. This does not claim separate physical hosts or native Adam replay.

use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;

use super::process::IndependentSpecV14;
use super::process::NativeOwner;
use super::process::fleet;
use crate::memory_serving_plan_v11::test_support::record;

fn query(scope: &ContractIdV1, operation: &str) -> MemoryInventoryRequestV1 {
    MemoryInventoryRequestV1 {
        schema: "hepta.memory.inventory-request.v1".to_string(),
        query_id: ContractIdV1::new(format!("v14:{operation}")).expect("query"),
        scope: scope.clone(),
        entity_key: ContractIdV1::new("item:a").expect("entity"),
        workflow_key: ContractIdV1::new("flow:a").expect("workflow"),
        text: operation.to_string(),
        at: 20,
        since: 20,
        max_hops: 3,
        max_cells: 4,
        max_steps: 4,
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct FilePin {
    name: String,
    bytes: u64,
    sha256: String,
    mode: u32,
}

fn files(root: &Path, prefix: &str) -> Vec<(String, Vec<u8>, u32)> {
    let mut result = Vec::new();
    for entry in std::fs::read_dir(root).expect("cold directory") {
        let entry = entry.expect("directory entry");
        let name = format!(
            "{prefix}{}",
            entry.file_name().to_str().expect("fixture UTF8 path")
        );
        let kind = entry.file_type().expect("file type");
        assert!(
            !kind.is_symlink(),
            "migration fixture only transports regular files"
        );
        if kind.is_dir() {
            result.extend(files(&entry.path(), &format!("{name}/")));
        } else {
            assert!(kind.is_file());
            result.push((
                name,
                std::fs::read(entry.path()).expect("cold file bytes"),
                entry
                    .metadata()
                    .expect("cold file metadata")
                    .permissions()
                    .mode()
                    & 0o7777,
            ));
        }
    }
    result.sort_by(|a, b| a.0.cmp(&b.0));
    result
}

async fn transfer(
    source: &Path,
    cognitive: &Path,
    destination: &Path,
    target_cognitive: &Path,
) -> Value {
    let mut data = files(&source.join("artifacts"), "artifacts/");
    let database = cognitive.join(codex_hepta_cognitive_store::DURABLE_DATABASE_BASENAME);
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(
            !PathBuf::from(format!("{}{suffix}", database.display())).exists(),
            "source must be fully quiesced"
        );
    }
    data.push((
        "cognitive/database".to_string(),
        std::fs::read(&database).expect("closed real SQLite file"),
        std::fs::metadata(&database)
            .expect("cold SQLite metadata")
            .permissions()
            .mode()
            & 0o7777,
    ));
    let pins: Vec<_> = data
        .iter()
        .map(|(name, bytes, mode)| FilePin {
            name: name.clone(),
            bytes: bytes.len() as u64,
            sha256: Digest32::of_bytes(bytes).to_string(),
            mode: *mode,
        })
        .collect();
    assert!(pins.len() <= 256 && pins.iter().map(|p| p.bytes).sum::<u64>() <= 32 * 1024 * 1024);
    let manifest = serde_json::to_vec(&pins).expect("transfer inventory");
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("real TCP receiver");
    let address = listener.local_addr().expect("receiver address");
    let expected = pins.clone();
    let target = destination.to_path_buf();
    let cognitive = target_cognitive.to_path_buf();
    let receiving = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.expect("TCP accept");
        let count = stream.read_u64().await.expect("inventory byte length");
        assert!(count <= 65_536);
        let mut raw = vec![0_u8; count as usize];
        stream
            .read_exact(&mut raw)
            .await
            .expect("actual inventory bytes");
        let actual: Vec<FilePin> = serde_json::from_slice(&raw).expect("received inventory");
        assert_eq!(actual, expected, "independently held transport pins");
        for pin in actual {
            let mut bytes = vec![0_u8; pin.bytes as usize];
            stream
                .read_exact(&mut bytes)
                .await
                .expect("actual file transfer");
            assert_eq!(Digest32::of_bytes(&bytes).to_string(), pin.sha256);
            let path = if pin.name == "cognitive/database" {
                cognitive.join(codex_hepta_cognitive_store::DURABLE_DATABASE_BASENAME)
            } else {
                assert!(
                    pin.name.starts_with("artifacts/")
                        && !pin.name.split('/').any(|part| part == "..")
                );
                target.join(pin.name)
            };
            let parent = path.parent().expect("target directory");
            std::fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(parent)
                .expect("private target directories");
            std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700))
                .expect("private target parent");
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(pin.mode)
                .open(&path)
                .expect("distinct new target inode");
            file.write_all(&bytes).expect("received cold bytes");
            file.set_permissions(std::fs::Permissions::from_mode(pin.mode))
                .expect("preserve exact source file mode");
            file.sync_all().expect("durable target file");
            std::fs::File::open(parent)
                .and_then(|directory| directory.sync_all())
                .expect("durable target directory");
        }
        let mut extra = [0_u8; 1];
        assert_eq!(stream.read(&mut extra).await.expect("transfer EOF"), 0);
    });
    let mut stream = TcpStream::connect(address)
        .await
        .expect("actual TCP sender");
    stream
        .write_u64(manifest.len() as u64)
        .await
        .expect("inventory length");
    stream
        .write_all(&manifest)
        .await
        .expect("inventory transfer");
    for (_, bytes, _) in &data {
        stream.write_all(bytes).await.expect("raw file transfer");
    }
    stream.shutdown().await.expect("sender EOF");
    receiving.await.expect("receiver completed");
    json!({"transport":"same_host_loopback_TCP","receiver":"parent_test_transport_task",
        "files":pins,"wire_bytes":8 + manifest.len() as u64 + data.iter().map(|(_,b,_)|b.len() as u64).sum::<u64>()})
}

#[tokio::test]
async fn memory_v14_two_process_control_and_cold_migration() {
    let temporary = tempfile::tempdir().expect("isolated two-process experiment");
    let origin = temporary.path().join("origin");
    std::fs::create_dir(&origin).expect("origin");
    let (registry, owner) = fleet(&origin);
    let mut first = NativeOwner::spawn_independent(
        &origin,
        &registry,
        owner.clone(),
        IndependentSpecV14 {
            checkpoint: None,
            unavailable_source: None,
        },
    )
    .await;
    let source = first
        .client
        .memory_inventory_snapshot(
            /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 16,
        )
        .await
        .expect("real control source page");
    let scope = source.scope;
    let initial = first
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("first process learned control read");
    assert_eq!(
        (initial.prediction_kind, initial.value.clone()),
        (
            MemoryPredictionKindV1::ModelPrediction,
            json!({"reserve":11,"pack":3,"limit":14})
        )
    );
    let procedure = first
        .client
        .memory_inventory_read(query(&scope, "procedure"))
        .await
        .expect("procedure read");
    first
        .command(
            json!({"op":"correct","record":record("item:a",MemoryInventoryKindV1::Semantic,
        json!({"reserve":14,"pack":2,"limit":15})),"revision":1}),
        )
        .await;
    let fallback = first
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("real control fallback");
    assert_eq!(
        (
            fallback.prediction_kind,
            fallback.value.clone(),
            fallback.cell_digests.clone()
        ),
        (
            MemoryPredictionKindV1::SourceEvidence,
            json!({"reserve":14,"pack":2,"limit":15}),
            Vec::new()
        )
    );
    assert_ne!(initial.source_ids, fallback.source_ids);
    let preserved = first
        .client
        .memory_inventory_read(query(&scope, "procedure"))
        .await
        .expect("independent procedure");
    assert_eq!(
        (preserved.value, preserved.cell_digests),
        (procedure.value.clone(), procedure.cell_digests.clone())
    );
    let training = first
        .command(json!({"op":"retrain","cell":"cell:semantic"}))
        .await;
    let learned = first
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("actual retrained artifact");
    assert_eq!(
        (learned.prediction_kind, learned.value.clone()),
        (
            MemoryPredictionKindV1::ModelPrediction,
            fallback.value.clone()
        )
    );
    assert_ne!(initial.cell_digests, learned.cell_digests);
    let checkpoint = first.command(json!({"op":"checkpoint"})).await["checkpoint"].clone();
    let first_stop = first.stop(&registry, &owner).await;
    assert!(
        first
            .client
            .memory_inventory_read(query(&scope, "semantic"))
            .await
            .is_err()
    );
    let destination = temporary.path().join("destination");
    std::fs::create_dir(&destination).expect("independent destination");
    let (target_registry, target_owner) = fleet(&destination);
    assert_eq!(target_owner, owner);
    let old = registry.load_agent(&owner).expect("quiesced source layout");
    let target = target_registry
        .load_agent(&owner)
        .expect("independent destination layout");
    let transport = tokio::time::timeout(
        std::time::Duration::from_secs(30),
        transfer(
            &origin,
            old.layout.cognitive_root(),
            &destination,
            target.layout.cognitive_root(),
        ),
    )
    .await
    .expect("bounded transfer");
    let checkpoint_path = destination.join("v14-checkpoint.json");
    std::fs::write(
        &checkpoint_path,
        serde_json::to_vec(&checkpoint).expect("checkpoint pins"),
    )
    .expect("independent pins");
    std::fs::rename(&origin, temporary.path().join("retained-source-evidence"))
        .expect("original source root becomes unavailable");
    assert!(!origin.exists());
    let mut second = NativeOwner::spawn_independent(
        &destination,
        &target_registry,
        owner.clone(),
        IndependentSpecV14 {
            checkpoint: Some(checkpoint_path),
            unavailable_source: Some(origin.clone()),
        },
    )
    .await;
    assert_ne!(
        first.ready["pid"], second.ready["pid"],
        "distinct actual owner processes"
    );
    let restored = second
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("cold recovered read through AgentdClient");
    assert_eq!(
        (
            restored.value.clone(),
            restored.source_ids.clone(),
            restored.cell_digests.clone()
        ),
        (
            learned.value.clone(),
            learned.source_ids.clone(),
            learned.cell_digests.clone()
        )
    );
    let applied = second
        .client
        .memory_inventory_read(query(&scope, "apply"))
        .await
        .expect("cold recovered composition");
    assert_eq!(
        (
            applied.value["value"].clone(),
            applied.prediction_kind,
            applied.cell_digests.len()
        ),
        (json!(15), MemoryPredictionKindV1::Mixed, 2)
    );
    second
        .command(
            json!({"op":"correct","record":record("item:a",MemoryInventoryKindV1::Semantic,
        json!({"reserve":3,"pack":2,"limit":8})),"revision":2}),
        )
        .await;
    let corrected = second
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("destination source fallback");
    assert_eq!(
        (corrected.prediction_kind, corrected.value.clone()),
        (
            MemoryPredictionKindV1::SourceEvidence,
            json!({"reserve":3,"pack":2,"limit":8})
        )
    );
    second.command(json!({"op":"forget","record":record("item:a",MemoryInventoryKindV1::Semantic,json!(null)),"revision":3})).await;
    let refused = second
        .client
        .memory_inventory_read(query(&scope, "semantic"))
        .await
        .expect("destination withdrawal refusal");
    assert_eq!(
        (
            refused.status,
            refused.value.clone(),
            refused.source_ids.clone(),
            refused.cell_digests.clone()
        ),
        (
            MemoryReadStatusV1::Abstain,
            json!(null),
            Vec::new(),
            Vec::new()
        )
    );
    let survivor = second
        .client
        .memory_inventory_read(query(&scope, "procedure"))
        .await
        .expect("destination independent procedure");
    assert_eq!(
        (survivor.value.clone(), survivor.cell_digests.clone()),
        (procedure.value.clone(), procedure.cell_digests.clone())
    );
    let second_stop = second.stop(&target_registry, &owner).await;
    let evidence = json!({"schema":"hepta.memory.native-two-process.v14","parent_pid":std::process::id(),
        "processes":[first_stop,second_stop],"transport":transport,"checkpoint":checkpoint,
        "reads":{"initial":initial,"fallback":fallback,"learned":learned,"restored":restored,
            "composition":applied,"destination_correction":corrected,"withdrawn":refused,"survivor":survivor},
        "training":training,"same_host":true,"cross_physical_host_claim":false,
        "native_optimizer_continuation_claim":false,"resolver":"explicit_oracle_test_seam"});
    if let Some(path) = std::env::var_os("HEPTA_MEMORY_V14_NATIVE_EVIDENCE") {
        std::fs::write(
            path,
            serde_json::to_vec_pretty(&evidence).expect("evidence JSON"),
        )
        .expect("persist process evidence");
    }
    println!(
        "V14_NATIVE_TWO_PROCESS:{}",
        serde_json::to_string(&evidence).expect("bounded process evidence")
    );
}
