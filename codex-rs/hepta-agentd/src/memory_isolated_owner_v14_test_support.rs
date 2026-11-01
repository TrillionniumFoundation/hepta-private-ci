//! Real V14 owner subprocess. Test keys/readiness are explicit; all user reads
//! travel through the existing Agentd control server and client.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_memory::MemoryInventoryRecordV1;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::io::BufReader;
use tokio_util::sync::CancellationToken;

use super::Spec;
use super::emit;
use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdMemoryInventoryRuntimeV1;
use crate::AgentdState;
use crate::MemoryCellReleaseV11;
use crate::MemoryIsolatedServiceV14;
use crate::memory_cell_release::test_support::fixture_config_for_scope;
use crate::memory_cell_release::test_support::id;
use crate::memory_cell_release::test_support::owner_key;
use crate::memory_cell_release::test_support::selection_trust;
use crate::memory_serving_plan_v11::learned_test_support::publish_trained;
use crate::memory_serving_plan_v11::test_support::CellFixture;
use crate::memory_serving_plan_v11::test_support::generation;
use crate::memory_serving_plan_v11::test_support::now;
use crate::memory_serving_plan_v11::test_support::record;

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
    manifest: ManifestPins,
    head_generation: u64,
    head_digest: String,
    predecessor: String,
    issued_at: u64,
}

/// Primitive integrity pins preserve every original manifest field. The real
/// manifest/admission types intentionally do not deserialize authority.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ManifestPins {
    artifact_id: String,
    kind: String,
    generation: u64,
    provenance_mode: String,
    source_dataset_digests: Vec<String>,
    lineage_digests: Vec<String>,
    predecessor_ids: Vec<String>,
    rollback_predecessor: Option<String>,
    bytes_digest: String,
    encoded_size_bytes: u64,
    training_code_digest: String,
    runtime_tuple_digest: String,
    device_profile_digest: String,
    objective_class_digest: String,
    compatibility_digest: String,
    schema_profile_digest: String,
    normalization_digest: String,
    producer_id: String,
    created_at: u64,
    expires_at: u64,
}

impl ManifestPins {
    fn capture(manifest: &LearningArtifactManifestV2) -> Self {
        assert_eq!(manifest.kind, ArtifactKind::Parameters);
        assert_eq!(manifest.provenance_mode, ProvenanceModeV1::DatasetDerived);
        let pins = Self {
            artifact_id: manifest.artifact_id.to_string(),
            kind: "parameters".to_string(),
            generation: manifest.generation.get(),
            provenance_mode: "dataset_derived".to_string(),
            source_dataset_digests: manifest
                .source_dataset_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            lineage_digests: manifest
                .lineage_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            predecessor_ids: manifest
                .predecessor_ids
                .iter()
                .map(ToString::to_string)
                .collect(),
            rollback_predecessor: manifest
                .rollback_predecessor
                .as_ref()
                .map(ToString::to_string),
            bytes_digest: manifest.bytes_digest.to_string(),
            encoded_size_bytes: manifest.encoded_size_bytes,
            training_code_digest: manifest.training_code_digest.to_string(),
            runtime_tuple_digest: manifest.runtime_tuple_digest.to_string(),
            device_profile_digest: manifest.device_profile_digest.to_string(),
            objective_class_digest: manifest.objective_class_digest.to_string(),
            compatibility_digest: manifest.compatibility_digest.to_string(),
            schema_profile_digest: manifest.schema_profile_digest.to_string(),
            normalization_digest: manifest.normalization_digest.to_string(),
            producer_id: manifest.producer_id.to_string(),
            created_at: manifest.created_at,
            expires_at: manifest.expires_at,
        };
        assert_eq!(
            &pins.restore(),
            manifest,
            "full original manifest preserved"
        );
        pins
    }

    fn restore(&self) -> LearningArtifactManifestV2 {
        assert_eq!(self.kind, "parameters");
        assert_eq!(self.provenance_mode, "dataset_derived");
        let digest = |value: &str| {
            value
                .parse::<Digest32>()
                .expect("canonical manifest digest")
        };
        LearningArtifactManifestV2 {
            artifact_id: id(&self.artifact_id),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(self.generation).expect("manifest generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: self
                .source_dataset_digests
                .iter()
                .map(|value| digest(value))
                .collect(),
            lineage_digests: self
                .lineage_digests
                .iter()
                .map(|value| digest(value))
                .collect(),
            predecessor_ids: self.predecessor_ids.iter().map(|value| id(value)).collect(),
            rollback_predecessor: self.rollback_predecessor.as_ref().map(|value| id(value)),
            bytes_digest: digest(&self.bytes_digest),
            encoded_size_bytes: self.encoded_size_bytes,
            training_code_digest: digest(&self.training_code_digest),
            runtime_tuple_digest: digest(&self.runtime_tuple_digest),
            device_profile_digest: digest(&self.device_profile_digest),
            objective_class_digest: digest(&self.objective_class_digest),
            compatibility_digest: digest(&self.compatibility_digest),
            schema_profile_digest: digest(&self.schema_profile_digest),
            normalization_digest: digest(&self.normalization_digest),
            producer_id: id(&self.producer_id),
            created_at: self.created_at,
            expires_at: self.expires_at,
        }
    }
}

fn capture(cell: &CellFixture) -> CellCheckpoint {
    let head = &cell.publication.signed_current_head.witness;
    CellCheckpoint {
        selector: cell.selector.clone(),
        created_at: cell.config.now,
        manifest: ManifestPins::capture(&cell.publication.admission.validated_manifest.manifest),
        head_generation: head.generation.get(),
        head_digest: head.head_digest.to_string(),
        predecessor: head.predecessor_head_digest.to_string(),
        issued_at: head.issued_at,
    }
}

fn restore(
    root: PathBuf,
    owner: &MemoryInventoryOwnerSnapshotV1,
    checkpoint: CellCheckpoint,
) -> CellFixture {
    let manifest = checkpoint.manifest.restore();
    let mut config = fixture_config_for_scope(owner.scope(), root, checkpoint.created_at);
    config.storage_binding = Digest32::of_bytes(checkpoint.selector.cell_id.as_str().as_bytes());
    config.trust.registry_id = id(&format!("registry:{}", checkpoint.selector.cell_id));
    config.writer_lease.registry_id = config.trust.registry_id.clone();
    config.writer_lease.signature = owner_key()
        .sign(&config.writer_lease.signing_bytes())
        .to_bytes();
    let mut head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        binding: config.storage_binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: config.trust.registry_id.clone(),
            generation: Generation::new(checkpoint.head_generation).expect("head generation"),
            head_digest: checkpoint.head_digest.parse().expect("head digest"),
            predecessor_head_digest: checkpoint.predecessor.parse().expect("predecessor digest"),
            authority_epoch: 1,
            signer_id: id("memory-artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&owner_key().verifying_key().to_bytes()),
            issued_at: checkpoint.issued_at,
            expires_at: checkpoint.created_at + 3_600,
        },
        signature: [0; 64],
    };
    head.signature = owner_key().sign(&head.signing_bytes()).to_bytes();
    let service = Arc::new(Mutex::new(
        LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            required_current_head: Some(head.clone()),
            now: now() as u64,
            ..config.clone()
        })
        .expect("independent cold registry owner"),
    ));
    let payload = std::fs::read(config.root.join("payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.bytes_digest
    )))
    .expect("transferred exact MLP bytes");
    assert_eq!(Digest32::of_bytes(&payload), manifest.bytes_digest);
    let admission = {
        let locked = service.lock().expect("artifact owner");
        let frontier = locked.withdrawal_registry();
        admit_manifest_at_withdrawal_head_v3(
            frontier,
            frontier.head_digest(),
            manifest,
            now() as u64,
        )
        .expect("fresh admission against live restored frontier")
    };
    let publication = LearningArtifactPublishRequestV1 {
        operation_id: id(&format!(
            "memory-publication:{}",
            admission.validated_manifest.manifest.generation.get()
        )),
        admission,
        payload,
        expected_registry_predecessor_head: head.witness.predecessor_head_digest,
        signed_current_head: head,
        now: now() as u64,
    };
    let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust)
        .expect("fresh selection verifier");
    let host = Arc::new(MemoryCellReleaseV11::new(
        checkpoint.selector.cell_id.clone(),
        Arc::clone(&service),
        verifier,
    ));
    assert!(
        host.load_current().is_err(),
        "checkpoint alone grants no selected model"
    );
    let result = CellFixture {
        host,
        service,
        config,
        publication,
        selector: checkpoint.selector,
    };
    result.install();
    result
        .host
        .load_current()
        .expect("fresh authenticated selected bytes")
        .validate_owner_snapshot(owner)
        .expect("complete current partition");
    result
}

pub(super) async fn child_main(spec: Spec) {
    let independent = spec.independent.expect("V14 launch profile");
    if let Some(path) = &independent.unavailable_source {
        assert!(
            !path.exists(),
            "source root must be unavailable during cold recovery"
        );
    }
    let checkpoint: Option<Checkpoint> = independent.checkpoint.map(|path| {
        serde_json::from_slice(&std::fs::read(path).expect("checkpoint bytes"))
            .expect("authority-free checkpoint pins")
    });
    let registry = FleetRegistry::open_existing(
        HeptaFleetRoot::parse(spec.fleet_root.clone()).expect("fleet root"),
    )
    .expect("fleet");
    let registration = registry.load_agent(&spec.owner).expect("owner");
    if let Some(checkpoint) = &checkpoint {
        let recovered = DurableCognitiveStore::open_read_only_recovery(
            &registration.layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&checkpoint.anchor),
        )
        .await
        .expect("cold SQLite exact recovery anchor");
        assert!(recovered.anchor() == &checkpoint.anchor);
        drop(recovered);
    }
    let config = AgentdConfig::load(
        spec.fleet_root,
        spec.owner.clone(),
        spec.spawn_generation,
        registration.layout.home_root().to_path_buf(),
        registration.layout.run_root().to_path_buf(),
        registration.layout.home_root().to_path_buf(),
        registration.manifest.workspace.as_path().to_path_buf(),
    )
    .expect("real exclusive Agentd lock");
    let identity = config.identity().clone();
    let state =
        Arc::new(AgentdState::new(identity.clone(), registry, 16).expect("real Agentd state"));
    let store = Arc::new(
        DurableCognitiveStore::open(&identity.layout)
            .await
            .expect("real SQLite owner"),
    );
    let access = CognitiveAccess::agent_private(spec.owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let mut cells = if let Some(checkpoint) = checkpoint {
        let owner = store
            .memory_inventory_snapshot(&access, &scope, now())
            .await
            .expect("restored source cut");
        assert_eq!(owner.owner_cut_digest(), checkpoint.owner_cut);
        checkpoint
            .cells
            .into_iter()
            .map(|cell| {
                let directory = if cell.selector.kind == MemoryInventoryKindV1::Semantic {
                    "semantic"
                } else {
                    "procedure"
                };
                restore(spec.artifact_root.join(directory), &owner, cell)
            })
            .collect::<Vec<_>>()
    } else {
        for row in [
            record("item:a", MemoryInventoryKindV1::Event, json!(4)),
            record("item:a", MemoryInventoryKindV1::Hold, json!(false)),
            record(
                "item:a",
                MemoryInventoryKindV1::Semantic,
                json!({"reserve":11,"pack":3,"limit":14}),
            ),
            record(
                "flow:a",
                MemoryInventoryKindV1::Procedure,
                json!({"opcodes":[1,2,3,6]}),
            ),
        ] {
            store
                .write_memory_inventory(&access, &scope, &row, MemoryCellWriteModeV1::Create)
                .await
                .expect("authored source ingestion");
        }
        let owner = store
            .memory_inventory_snapshot(&access, &scope, now())
            .await
            .expect("initial source cut");
        let mut cells = vec![
            CellFixture::new(
                spec.artifact_root.join("semantic"),
                &owner,
                "cell:semantic",
                MemoryInventoryKindV1::Semantic,
                "item:a",
            ),
            CellFixture::new(
                spec.artifact_root.join("procedure"),
                &owner,
                "cell:procedure",
                MemoryInventoryKindV1::Procedure,
                "flow:a",
            ),
        ];
        for cell in &mut cells {
            publish_trained(cell, &owner);
        }
        cells
    };
    let owner = store
        .memory_inventory_snapshot(&access, &scope, now())
        .await
        .expect("startup owner");
    let service = Arc::new(
        MemoryIsolatedServiceV14::new(
            &owner,
            generation(1),
            cells
                .iter()
                .map(|cell| (cell.selector.clone(), Arc::clone(&cell.host)))
                .collect(),
        )
        .expect("native isolated service"),
    );
    let runtime = AgentdMemoryInventoryRuntimeV1::with_independent_cells(
        spec.owner.clone(),
        spec.spawn_generation,
        scope.clone(),
        service,
        Arc::new(super::child::OracleGate::default()),
    )
    .expect("native existing runtime");
    state
        .attach_memory_inventory(Arc::new(runtime))
        .expect("runtime attachment");
    state
        .attach_cognitive_store(Arc::clone(&store))
        .expect("store attachment");
    let cancellation = CancellationToken::new();
    let server = AgentdControlServer::bind(
        identity.control_socket,
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await
    .expect("real control socket");
    let control = tokio::spawn(server.run());
    emit(
        json!({"pid":std::process::id(),"owner":spec.owner,"spawn_generation":spec.spawn_generation,
        "profile":"V14_independent_trained_MLP","resolver":"explicit_oracle_test_seam",
        "source_root_unavailable":independent.unavailable_source}),
    );
    let mut input = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = input.next_line().await.expect("control fixture command") {
        let command: Value = serde_json::from_str(&line).expect("test command");
        let response = match command["op"].as_str().expect("command kind") {
            "activate" => {
                state.refresh_generation().expect("Running fence");
                state
                    .mark_runtime_prerequisites_ready()
                    .expect("stores ready");
                state
                    .mark_app_server_ready()
                    .expect("explicit control-only readiness seam");
                json!({"ready":true})
            }
            "correct" => {
                let row: MemoryInventoryRecordV1 =
                    serde_json::from_value(command["record"].clone()).expect("typed source");
                store
                    .write_memory_inventory(
                        &access,
                        &scope,
                        &row,
                        MemoryCellWriteModeV1::Correct {
                            expected_revision: command["revision"]
                                .as_u64()
                                .expect("source revision"),
                        },
                    )
                    .await
                    .expect("actual correction");
                json!({"corrected":true})
            }
            "retrain" => {
                let owner = store
                    .memory_inventory_snapshot(&access, &scope, now())
                    .await
                    .expect("current source cut");
                let cell = cells
                    .iter_mut()
                    .find(|cell| {
                        cell.selector.cell_id.as_str() == command["cell"].as_str().expect("cell ID")
                    })
                    .expect("registered cell");
                publish_trained(cell, &owner);
                json!({"trained":true,"artifact":cell.host.load_current().expect("selected learned cell").digest()})
            }
            "forget" => {
                let row: MemoryInventoryRecordV1 =
                    serde_json::from_value(command["record"].clone()).expect("typed source");
                store
                    .forget_memory_inventory(
                        &access,
                        &scope,
                        &row.address(),
                        command["revision"].as_u64().expect("revision"),
                        "V14 explicit source withdrawal",
                        now(),
                    )
                    .await
                    .expect("actual withdrawal");
                json!({"forgotten":true})
            }
            "checkpoint" => {
                let owner = store
                    .memory_inventory_snapshot(&access, &scope, now())
                    .await
                    .expect("checkpoint source cut");
                json!({"checkpoint":Checkpoint { owner_cut:owner.owner_cut_digest(),
                    anchor:store.recovery_anchor().await.expect("exact current SQLite anchor"), cells:cells.iter().map(capture).collect() }})
            }
            "stop" => {
                cancellation.cancel();
                break;
            }
            _ => panic!("unknown V14 fixture command"),
        };
        emit(response);
    }
    cancellation.cancel();
    control
        .await
        .expect("join actual control")
        .expect("control stopped");
    drop(state);
    drop(cells);
    store.as_ref().clone().close().await;
    drop(store);
    drop(config);
    emit(json!({"stopped":true,"profile":"V14_independent_trained_MLP"}));
}
