//! Real V14 owner subprocess. Test keys/readiness are explicit; all user reads
//! travel through the existing Agentd control server and client.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_learning_artifacts::{ArtifactSelectionVerifierV1, LearningArtifactManifestV2,
    LearningArtifactOwnerService, LearningArtifactOwnerServiceConfigV1, LearningArtifactPublishRequestV1,
    RegistryHeadWitnessV1, SignedCurrentArtifactHeadV1, admit_manifest_at_withdrawal_head_v3};
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::{CognitiveAccess, CognitiveRecoveryAnchor, CognitiveRecoveryRequirement,
    CognitiveScope, MemoryCellWriteModeV1, MemoryInventoryOwnerSnapshotV1,
    MemoryInventoryRecordV1, MemoryTrainingSelectorV11};
use codex_hepta_cognitive_types::{MemoryInventoryKindV1, hnmf::ContractDigestV1};
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::{Digest32, Generation};
use ed25519_dalek::Signer;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio_util::sync::CancellationToken;

use crate::{AgentdConfig, AgentdControlServer, AgentdMemoryInventoryRuntimeV1, AgentdState,
    MemoryCellReleaseV11, MemoryIsolatedServiceV14};
use crate::memory_cell_release::test_support::{fixture_config_for_scope, id, owner_key, selection_trust};
use crate::memory_serving_plan_v11::learned_test_support::publish_trained;
use crate::memory_serving_plan_v11::test_support::{CellFixture, generation, now, record};
use super::{Spec, emit};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct IndependentSpecV14 {
    pub checkpoint: Option<PathBuf>,
    pub unavailable_source: Option<PathBuf>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Checkpoint {
    owner_cut: ContractDigestV1,
    anchor: CognitiveRecoveryAnchor,
    cells: Vec<CellCheckpoint>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellCheckpoint {
    selector: MemoryTrainingSelectorV11,
    created_at: u64,
    manifest: LearningArtifactManifestV2,
    head_generation: u64,
    head_digest: Digest32,
    predecessor: Digest32,
    issued_at: u64,
}

fn capture(cell: &CellFixture) -> CellCheckpoint {
    let head = &cell.publication.signed_current_head.witness;
    CellCheckpoint { selector: cell.selector.clone(), created_at: cell.config.now,
        manifest: cell.publication.admission.validated_manifest.manifest.clone(),
        head_generation: head.generation.get(), head_digest: head.head_digest,
        predecessor: head.predecessor_head_digest, issued_at: head.issued_at }
}

fn restore(root: PathBuf, owner: &MemoryInventoryOwnerSnapshotV1, checkpoint: CellCheckpoint) -> CellFixture {
    let mut config = fixture_config_for_scope(owner.scope(), root, checkpoint.created_at);
    config.storage_binding = Digest32::of_bytes(checkpoint.selector.cell_id.as_str().as_bytes());
    config.trust.registry_id = id(&format!("registry:{}", checkpoint.selector.cell_id));
    config.writer_lease.registry_id = config.trust.registry_id.clone();
    config.writer_lease.signature = owner_key().sign(&config.writer_lease.signing_bytes()).to_bytes();
    let mut head = SignedCurrentArtifactHeadV1 { withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        binding: config.storage_binding, witness: RegistryHeadWitnessV1 {
            registry_id: config.trust.registry_id.clone(), generation: Generation::new(checkpoint.head_generation).expect("head generation"),
            head_digest: checkpoint.head_digest, predecessor_head_digest: checkpoint.predecessor,
            authority_epoch: 1, signer_id: id("memory-artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&owner_key().verifying_key().to_bytes()),
            issued_at: checkpoint.issued_at, expires_at: checkpoint.created_at + 3_600 }, signature: [0; 64] };
    head.signature = owner_key().sign(&head.signing_bytes()).to_bytes();
    let service = Arc::new(Mutex::new(LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        required_current_head: Some(head.clone()), now: now() as u64, ..config.clone()
    }).expect("independent cold registry owner")));
    let payload = std::fs::read(config.root.join("payloads").join(format!("{}-{}.bin",
        checkpoint.manifest.artifact_id, checkpoint.manifest.bytes_digest))).expect("transferred exact MLP bytes");
    assert_eq!(Digest32::of_bytes(&payload), checkpoint.manifest.bytes_digest);
    let admission = {
        let locked = service.lock().expect("artifact owner");
        let frontier = locked.withdrawal_registry();
        admit_manifest_at_withdrawal_head_v3(frontier, frontier.head_digest(), checkpoint.manifest, now() as u64)
            .expect("fresh admission against live restored frontier")
    };
    let publication = LearningArtifactPublishRequestV1 {
        operation_id: id(&format!("memory-publication:{}", admission.validated_manifest.manifest.generation.get())),
        admission, payload, expected_registry_predecessor_head: head.witness.predecessor_head_digest,
        signed_current_head: head, now: now() as u64 };
    let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).expect("fresh selection verifier");
    let host = Arc::new(MemoryCellReleaseV11::new(checkpoint.selector.cell_id.clone(), Arc::clone(&service), verifier));
    assert!(host.load_current().is_err(), "checkpoint alone grants no selected model");
    let result = CellFixture { host, service, config, publication, selector: checkpoint.selector };
    result.install();
    result.host.load_current().expect("fresh authenticated selected bytes").validate_owner_snapshot(owner).expect("complete current partition");
    result
}

pub(super) async fn child_main(spec: Spec) {
    let independent = spec.independent.expect("V14 launch profile");
    if let Some(path) = &independent.unavailable_source {
        assert!(!path.exists(), "source root must be unavailable during cold recovery");
    }
    let checkpoint: Option<Checkpoint> = independent.checkpoint.map(|path|
        serde_json::from_slice(&std::fs::read(path).expect("checkpoint bytes")).expect("authority-free checkpoint pins"));
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(spec.fleet_root.clone()).expect("fleet root")).expect("fleet");
    let registration = registry.load_agent(&spec.owner).expect("owner");
    if let Some(checkpoint) = &checkpoint {
        let recovered = DurableCognitiveStore::open_read_only_recovery(&registration.layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&checkpoint.anchor)).await.expect("cold SQLite exact recovery anchor");
        assert!(recovered.anchor() == &checkpoint.anchor);
        drop(recovered);
    }
    let config = AgentdConfig::load(spec.fleet_root, spec.owner.clone(), spec.spawn_generation,
        registration.layout.home_root().to_path_buf(), registration.layout.run_root().to_path_buf(),
        registration.layout.home_root().to_path_buf(), registration.manifest.workspace.as_path().to_path_buf()).expect("real exclusive Agentd lock");
    let identity = config.identity().clone();
    let state = Arc::new(AgentdState::new(identity.clone(), registry, 16).expect("real Agentd state"));
    let store = Arc::new(DurableCognitiveStore::open(&identity.layout).await.expect("real SQLite owner"));
    let access = CognitiveAccess::agent_private(spec.owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let mut cells = if let Some(checkpoint) = checkpoint {
        let owner = store.memory_inventory_snapshot(&access, &scope, now()).await.expect("restored source cut");
        assert_eq!(owner.owner_cut_digest(), checkpoint.owner_cut);
        checkpoint.cells.into_iter().map(|cell| {
            let directory = if cell.selector.kind == MemoryInventoryKindV1::Semantic { "semantic" } else { "procedure" };
            restore(spec.artifact_root.join(directory), &owner, cell)
        }).collect::<Vec<_>>()
    } else {
        for row in [record("item:a", MemoryInventoryKindV1::Event, json!(4)),
            record("item:a", MemoryInventoryKindV1::Hold, json!(false)),
            record("item:a", MemoryInventoryKindV1::Semantic, json!({"reserve":11,"pack":3,"limit":14})),
            record("flow:a", MemoryInventoryKindV1::Procedure, json!({"opcodes":[1,2,3,6]}))] {
            store.write_memory_inventory(&access, &scope, &row, MemoryCellWriteModeV1::Create).await.expect("authored source ingestion");
        }
        let owner = store.memory_inventory_snapshot(&access, &scope, now()).await.expect("initial source cut");
        let mut cells = vec![
            CellFixture::new(spec.artifact_root.join("semantic"), &owner, "cell:semantic", MemoryInventoryKindV1::Semantic, "item:a"),
            CellFixture::new(spec.artifact_root.join("procedure"), &owner, "cell:procedure", MemoryInventoryKindV1::Procedure, "flow:a")];
        for cell in &mut cells { publish_trained(cell, &owner); }
        cells
    };
    let owner = store.memory_inventory_snapshot(&access, &scope, now()).await.expect("startup owner");
    let service = Arc::new(MemoryIsolatedServiceV14::new(&owner, generation(1), cells.iter()
        .map(|cell| (cell.selector.clone(), Arc::clone(&cell.host))).collect()).expect("native isolated service"));
    let runtime = AgentdMemoryInventoryRuntimeV1::with_independent_cells(spec.owner.clone(), spec.spawn_generation,
        scope.clone(), service, Arc::new(super::child::OracleGate::default())).expect("native existing runtime");
    state.attach_memory_inventory(Arc::new(runtime)).expect("runtime attachment");
    state.attach_cognitive_store(Arc::clone(&store)).expect("store attachment");
    let cancellation = CancellationToken::new();
    let server = AgentdControlServer::bind(identity.control_socket, Arc::clone(&state), cancellation.clone()).await.expect("real control socket");
    let control = tokio::spawn(server.run());
    emit(json!({"pid":std::process::id(),"owner":spec.owner,"spawn_generation":spec.spawn_generation,
        "profile":"V14_independent_trained_MLP","resolver":"explicit_oracle_test_seam",
        "source_root_unavailable":independent.unavailable_source}));
    let mut input = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = input.next_line().await.expect("control fixture command") {
        let command: Value = serde_json::from_str(&line).expect("test command");
        let response = match command["op"].as_str().expect("command kind") {
            "activate" => {
                state.refresh_generation().expect("Running fence");
                state.mark_runtime_prerequisites_ready().expect("stores ready");
                state.mark_app_server_ready().expect("explicit control-only readiness seam");
                json!({"ready":true})
            }
            "correct" => {
                let row: MemoryInventoryRecordV1 = serde_json::from_value(command["record"].clone()).expect("typed source");
                store.write_memory_inventory(&access, &scope, &row, MemoryCellWriteModeV1::Correct {
                    expected_revision: command["revision"].as_u64().expect("source revision") }).await.expect("actual correction");
                json!({"corrected":true})
            }
            "retrain" => {
                let owner = store.memory_inventory_snapshot(&access, &scope, now()).await.expect("current source cut");
                let cell = cells.iter_mut().find(|cell| cell.selector.cell_id.as_str() == command["cell"].as_str().expect("cell ID")).expect("registered cell");
                publish_trained(cell, &owner);
                json!({"trained":true,"artifact":cell.host.load_current().expect("selected learned cell").digest()})
            }
            "forget" => {
                let row: MemoryInventoryRecordV1 = serde_json::from_value(command["record"].clone()).expect("typed source");
                store.forget_memory_inventory(&access, &scope, &row.address(), command["revision"].as_u64().expect("revision"),
                    "V14 explicit source withdrawal", now()).await.expect("actual withdrawal");
                json!({"forgotten":true})
            }
            "checkpoint" => {
                let owner = store.memory_inventory_snapshot(&access, &scope, now()).await.expect("checkpoint source cut");
                json!({"checkpoint":Checkpoint { owner_cut:owner.owner_cut_digest(),
                    anchor:store.recovery_anchor().await.expect("exact current SQLite anchor"), cells:cells.iter().map(capture).collect() }})
            }
            "stop" => { cancellation.cancel(); break; }
            _ => panic!("unknown V14 fixture command"),
        };
        emit(response);
    }
    cancellation.cancel();
    control.await.expect("join actual control").expect("control stopped");
    drop(state);
    drop(cells);
    store.as_ref().clone().close().await;
    drop(store);
    drop(config);
    emit(json!({"stopped":true,"profile":"V14_independent_trained_MLP"}));
}
