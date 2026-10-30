//! Real SQLite and artifact owners, explicit test keys, analytic parameters.
//! These fixtures prove lifecycle behavior, never trained-model quality.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_memory::MemoryInventoryRecordV1;
use codex_hepta_memory::MemoryTrainingProjectionV11;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_neuron::MEMORY_RESIDUAL_ADDRESS_PROFILE_V1;
use codex_hepta_neuron::MEMORY_RESIDUAL_NUMERIC_PROFILE_V1;
use codex_hepta_neuron::MEMORY_RESIDUAL_POLICY_PROFILE_V1;
use codex_hepta_neuron::MEMORY_RESIDUAL_PROGRAM_PROFILE_V1;
use codex_hepta_neuron::MEMORY_RESIDUAL_SCHEMA_V1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

use crate::MemoryCellCandidateV11;
use crate::MemoryCellReleaseV11;
use crate::memory_cell_release::test_support::fixture_config_for_scope;
use crate::memory_cell_release::test_support::fixture_manifest_template;
use crate::memory_cell_release::test_support::fixture_selection;
use crate::memory_cell_release::test_support::id;
use crate::memory_cell_release::test_support::owner_key;
use crate::memory_cell_release::test_support::prepare_payload_request;
use crate::memory_cell_release::test_support::selection_trust;

pub fn key(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("key")
}
pub fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).expect("generation")
}
pub fn now() -> i64 {
    crate::memory_cell_runtime::now_unix_seconds().expect("host clock")
}

pub fn record(
    key_text: &str,
    kind: MemoryInventoryKindV1,
    value: Value,
) -> MemoryInventoryRecordV1 {
    MemoryInventoryRecordV1 {
        schema: "hepta.memory.inventory-record.v1".to_string(),
        key: key(key_text),
        kind,
        effective_at: 20,
        value,
    }
}

pub async fn owner_fixture() -> (TempDir, CognitiveStore, CognitiveAccess) {
    let root = tempfile::tempdir().expect("root");
    let path = root.path().join("fleet");
    std::fs::create_dir(&path).expect("fleet directory");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000094").expect("owner");
    let store = CognitiveStore::open(
        &HeptaFleetRoot::parse(path)
            .expect("fleet")
            .layout()
            .agent(&owner),
    )
    .await
    .expect("real SQLite owner");
    let access = CognitiveAccess::agent_private(owner);
    use MemoryInventoryKindV1::Event;
    use MemoryInventoryKindV1::Hold;
    use MemoryInventoryKindV1::Procedure;
    use MemoryInventoryKindV1::Semantic;
    for row in [
        record("item:a", Event, json!(4)),
        record("item:a", Hold, json!(false)),
        record(
            "item:a",
            Semantic,
            json!({"reserve":11,"pack":3,"limit":14}),
        ),
        record("item:b", Semantic, json!({"reserve":7,"pack":2,"limit":12})),
        record("flow:a", Procedure, json!({"opcodes":[1,2,3,6]})),
    ] {
        store
            .write_memory_inventory(
                &access,
                &CognitiveScope::AgentPrivate,
                &row,
                MemoryCellWriteModeV1::Create,
            )
            .await
            .expect("source write");
    }
    (root, store, access)
}

pub async fn snapshot(
    store: &CognitiveStore,
    access: &CognitiveAccess,
) -> MemoryInventoryOwnerSnapshotV1 {
    store
        .memory_inventory_snapshot(access, &CognitiveScope::AgentPrivate, now())
        .await
        .expect("owner snapshot")
}

pub fn request(owner: &MemoryInventoryOwnerSnapshotV1) -> MemoryInventoryRequestV1 {
    MemoryInventoryRequestV1 {
        schema: "hepta.memory.inventory-request.v1".to_string(),
        query_id: key("query:v11"),
        scope: owner.scope().clone(),
        entity_key: key("item:a"),
        workflow_key: key("flow:a"),
        text: "Apply flow:a to item:a".to_string(),
        at: 20,
        since: 20,
        max_hops: 3,
        max_cells: 4,
        max_steps: 4,
    }
}

pub struct CellFixture {
    pub host: Arc<MemoryCellReleaseV11>,
    pub service: Arc<Mutex<LearningArtifactOwnerService>>,
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub publication: LearningArtifactPublishRequestV1,
    pub selector: MemoryTrainingSelectorV11,
}

impl CellFixture {
    pub fn new(
        root: PathBuf,
        owner: &MemoryInventoryOwnerSnapshotV1,
        cell_id: &str,
        kind: MemoryInventoryKindV1,
        member: &str,
    ) -> Self {
        let mut config = fixture_config_for_scope(owner.scope(), root, now() as u64);
        config.storage_binding = Digest32::of_bytes(cell_id.as_bytes());
        config.trust.registry_id = id(&format!("registry:{cell_id}"));
        config.writer_lease.registry_id = config.trust.registry_id.clone();
        config.writer_lease.signature = owner_key()
            .sign(&config.writer_lease.signing_bytes())
            .to_bytes();
        let service = Arc::new(Mutex::new(
            LearningArtifactOwnerService::open(config.clone())
                .expect("real independent artifact registry"),
        ));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust)
            .expect("selector");
        let host = Arc::new(MemoryCellReleaseV11::new(
            key(cell_id),
            Arc::clone(&service),
            verifier,
        ));
        let selector = MemoryTrainingSelectorV11 {
            cell_id: key(cell_id),
            kind,
            keys: vec![key(member)],
        };
        let publication = Self::prepare(&service, &config, owner, &selector, 1);
        host.publish(publication.clone(), owner)
            .expect("publish cell");
        let fixture = Self {
            host,
            service,
            config,
            publication,
            selector,
        };
        fixture.install();
        fixture
    }

    fn prepare(
        service: &Mutex<LearningArtifactOwnerService>,
        config: &LearningArtifactOwnerServiceConfigV1,
        owner: &MemoryInventoryOwnerSnapshotV1,
        selector: &MemoryTrainingSelectorV11,
        revision: u64,
    ) -> LearningArtifactPublishRequestV1 {
        let projection = owner
            .training_projection_v11(selector)
            .expect("authenticated projection");
        let candidate = MemoryCellCandidateV11::from_projection(
            &projection,
            generation(revision),
            &analytic_model(&projection),
        )
        .expect("candidate");
        let manifest = candidate
            .bind_manifest(fixture_manifest_template(
                config,
                revision,
                Digest32::of_bytes(b"analytic-lifecycle-fixture-no-training-claim"),
            ))
            .expect("manifest");
        prepare_payload_request(
            service,
            config,
            manifest,
            candidate.bytes().to_vec(),
            revision,
        )
    }

    pub fn replace(&mut self, owner: &MemoryInventoryOwnerSnapshotV1) {
        let revision = self
            .publication
            .admission
            .validated_manifest
            .manifest
            .generation
            .get()
            + 1;
        let request = Self::prepare(&self.service, &self.config, owner, &self.selector, revision);
        self.host
            .publish(request.clone(), owner)
            .expect("independent successor");
        self.publication = request;
        self.install();
    }

    pub fn install(&self) {
        self.try_install().expect("install cell");
    }

    pub fn try_install(&self) -> Result<(), String> {
        self.try_install_admission(self.publication.admission.clone())
    }

    /// Refresh only eligibility metadata against the actual owner frontier.
    /// The published manifest, payload, generation and CURRENT are unchanged.
    pub fn readmit_same_version(&self) -> Result<(), String> {
        let admission = {
            let service = self.service.lock().map_err(|error| error.to_string())?;
            let frontier = service.withdrawal_registry();
            admit_manifest_at_withdrawal_head_v3(
                frontier,
                frontier.head_digest(),
                self.publication
                    .admission
                    .validated_manifest
                    .manifest
                    .clone(),
                now() as u64,
            )
            .map_err(|error| error.to_string())?
        };
        self.try_install_admission(admission)
    }

    fn try_install_admission(
        &self,
        admission: WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), String> {
        let current = self
            .service
            .lock()
            .expect("service")
            .current_registry_view(now() as u64)
            .expect("current");
        let signed = fixture_selection(&self.service, &self.config, &self.publication, &current);
        let verifier =
            ArtifactSelectionVerifierV1::new(selection_trust(&self.config), &self.config.trust)
                .expect("selector");
        let selection = verifier
            .verify(&signed, &current, now() as u64)
            .expect("verified independent selection");
        let receipt = current.receipt();
        let manifest = &self.publication.admission.validated_manifest.manifest;
        self.host.install_selected(
            File::open(self.config.root.join("registries").join(format!(
                "{}-{}.snapshot",
                receipt.head_digest, receipt.file_digest
            )))
            .expect("registry bytes"),
            File::open(self.config.root.join("payloads").join(format!(
                "{}-{}.bin",
                manifest.artifact_id, manifest.bytes_digest
            )))
            .expect("payload bytes"),
            selection,
            admission,
        )
    }

    pub fn reopen(self) -> Self {
        let result = self.reopen_unselected();
        result.install();
        result
    }

    pub fn reopen_unselected(self) -> Self {
        let Self {
            host,
            service,
            mut config,
            publication,
            selector,
        } = self;
        drop(host);
        drop(service);
        config.required_current_head = Some(publication.signed_current_head.clone());
        config.now = now() as u64;
        let service = Arc::new(Mutex::new(
            LearningArtifactOwnerService::open(config.clone()).expect("reopen durable registry"),
        ));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust)
            .expect("selector");
        let host = Arc::new(MemoryCellReleaseV11::new(
            selector.cell_id.clone(),
            Arc::clone(&service),
            verifier,
        ));
        assert!(
            host.load_current().is_err(),
            "checkpoint cannot grant selection"
        );
        Self {
            host,
            service,
            config,
            publication,
            selector,
        }
    }
}

pub fn analytic_model(projection: &MemoryTrainingProjectionV11) -> Vec<u8> {
    let row = &projection.records()[0];
    let (kind, profile, bias): (_, _, Vec<f32>) = match projection.selector().kind {
        MemoryInventoryKindV1::Semantic => (
            MemoryCellKindV1::Semantic,
            MEMORY_RESIDUAL_POLICY_PROFILE_V1,
            ["reserve", "pack", "limit"]
                .iter()
                .flat_map(|name| {
                    (0..4).map(move |bit| {
                        if row.record.value[*name].as_u64().expect("integer") & (1 << bit) != 0 {
                            2.0
                        } else {
                            -2.0
                        }
                    })
                })
                .collect(),
        ),
        MemoryInventoryKindV1::Procedure => (
            MemoryCellKindV1::Procedure,
            MEMORY_RESIDUAL_PROGRAM_PROFILE_V1,
            row.record.value["opcodes"]
                .as_array()
                .expect("opcodes")
                .iter()
                .flat_map(|op| (0..7).map(move |i| if op.as_u64() == Some(i) { 2.0 } else { -2.0 }))
                .collect(),
        ),
        MemoryInventoryKindV1::Event | MemoryInventoryKindV1::Hold => panic!("not parametric"),
    };
    let mut arrays = BTreeMap::new();
    let mut parameter_bytes = Vec::new();
    for (name, shape, values) in [
        ("A", vec![1, 384], vec![0_f32; 384]),
        ("B", vec![384, 1], vec![0_f32; 384]),
        ("head.bias", vec![bias.len()], bias.clone()),
        (
            "head.weight",
            vec![bias.len(), 384],
            vec![0_f32; bias.len() * 384],
        ),
    ] {
        let raw: Vec<u8> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
        parameter_bytes
            .extend(serde_json::to_vec(&(name, &shape, "float32")).expect("tensor header"));
        parameter_bytes.extend(&raw);
        arrays.insert(name, json!({"shape":shape,"f32le_hex":hex(&raw)}));
    }
    let mut supports = BTreeMap::new();
    let mut features = BTreeMap::new();
    let mut lineage = BTreeSet::new();
    let feature = vec![0_u8; 384 * 4];
    for source in projection.records() {
        assert_eq!(
            source.record.value, row.record.value,
            "analytic test fixture predicts a constant"
        );
        let address = Digest32::of_bytes(source.record.key.as_str().as_bytes()).to_string();
        supports.insert(address.clone(), vec![source.source_id.to_string()]);
        lineage.insert(source.source_id.to_string());
        features.insert(address, json!({"canonical_text_sha256":Digest32::of_bytes(source.record.key.as_str().as_bytes()).to_string(),
            "feature_sha256":Digest32::of_bytes(&feature).to_string(),"f32le_hex":hex(&feature)}));
    }
    serde_json::to_vec(&json!({"schema":MEMORY_RESIDUAL_SCHEMA_V1,"kind":kind,
        "address_profile":MEMORY_RESIDUAL_ADDRESS_PROFILE_V1,"numeric_profile":MEMORY_RESIDUAL_NUMERIC_PROFILE_V1,
        "output_profile":profile,"dimension":384,"rank":1,"minimum_margin":0.001,
        "encoder_sha256":Digest32::of_bytes(b"analytic-zero-feature-no-encoder-claim").to_string(),
        "owner_cut_sha256":projection.acquisition_cut_digest().to_string(),
        "parameter_sha256":Digest32::of_bytes(&parameter_bytes).to_string(),
        "checkpoint_sha256":Digest32::of_bytes(b"analytic-checkpoint").to_string(),
        "training_receipt_sha256":Digest32::of_bytes(b"analytic-fixture-not-training").to_string(),
        "supports":supports,"lineage_sources":lineage,"features":features,"arrays":arrays})).expect("numeric fixture")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
