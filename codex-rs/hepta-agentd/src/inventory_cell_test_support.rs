//! Real canonical owner and signed publication fixtures with original trained
//! formal-01 parameters. The trusted test resolver makes no language claim.

use std::fs::File;
use std::sync::{Arc, Mutex};
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellRequestV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1, ContractIdV1};
use codex_hepta_learning_artifacts::{ArtifactSelectionVerifierV1, LearningArtifactOwnerService, LearningArtifactOwnerServiceConfigV1, LearningArtifactPublishRequestV1};
use codex_hepta_memory::{CognitiveScope, InventoryCellOwnerSnapshotV1, InventoryCellRecordV1, MemoryCellWriteModeV1};
use codex_hepta_types::Digest32;
use serde::Deserialize;
use crate::{InventoryCellBundleCandidateV1, InventoryCellFeatureBindingV1, InventoryCellReleaseHostV1};
use crate::memory_cell_release::test_support::{fixture_config_for_scope, fixture_manifest_template, fixture_selection, prepare_bound_request, selection_trust};
use crate::memory_cell_test_support::ControlFixture;

#[derive(Deserialize)]
pub(crate) struct DataBinding {
    pub kind: InventoryCellKindV1,
    pub key: ContractIdV1,
    pub training_source: ContractDigestV1,
    pub features: Vec<f32>,
}
#[derive(Deserialize)]
pub(crate) struct OriginalData {
    pub records: Vec<InventoryCellRecordV1>,
    pub bindings: Vec<DataBinding>,
    pub semantic_json: String,
    pub skill_json: String,
    semantic_artifact_sha256: ContractDigestV1,
    skill_artifact_sha256: ContractDigestV1,
}
impl OriginalData {
    pub fn read() -> Self {
        let data: Self = serde_json::from_str(include_str!("../tests/fixtures/inventory/formal-731-owner.json")).unwrap();
        assert_eq!(Digest32::of_bytes(data.semantic_json.as_bytes()), data.semantic_artifact_sha256.digest());
        assert_eq!(Digest32::of_bytes(data.skill_json.as_bytes()), data.skill_artifact_sha256.digest());
        data
    }
    pub async fn import(&self, fixture: &ControlFixture) {
        for row in &self.records {
            fixture.store.write_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, row, MemoryCellWriteModeV1::Create).await.unwrap();
        }
    }
    pub fn bindings(&self, snapshot: &InventoryCellOwnerSnapshotV1) -> Vec<InventoryCellFeatureBindingV1> {
        self.bindings.iter().map(|row| InventoryCellFeatureBindingV1 {
            kind: row.kind, key: row.key.clone(), training_source: row.training_source,
            owner_source: snapshot.current(&row.key, row.kind).unwrap().source_id, features: row.features.clone(),
        }).collect()
    }
    pub fn candidate(&self, snapshot: &InventoryCellOwnerSnapshotV1, generation: u64) -> Result<InventoryCellBundleCandidateV1, String> {
        InventoryCellBundleCandidateV1::from_owner_snapshot(snapshot, ContractGenerationV1::new(generation).unwrap(), self.semantic_json.as_bytes(), self.skill_json.as_bytes(), self.bindings(snapshot))
    }
}

pub(crate) async fn snapshot(fixture: &ControlFixture) -> InventoryCellOwnerSnapshotV1 {
    fixture.store.inventory_cell_snapshot(&fixture.access(), &CognitiveScope::AgentPrivate, crate::memory_cell_runtime::now_unix_seconds().unwrap()).await.unwrap()
}
pub(crate) fn key(kind: &str, index: usize) -> ContractIdV1 { ContractIdV1::new(format!("inventory:{kind}:{index}")).unwrap() }
pub(crate) fn request(owner: &InventoryCellOwnerSnapshotV1) -> InventoryCellRequestV1 {
    InventoryCellRequestV1 { schema: "hepta.memory.inventory-request.v1".to_string(), query_id: ContractIdV1::new("query:inventory-control").unwrap(), scope: owner.scope().clone(), text: "Trusted integration resolver; not language evidence".to_string(), at: 15, since: 10, max_cells: 3, max_hops: 3, max_steps: 4 }
}

pub(crate) struct InventoryReleaseFixture {
    pub directory: tempfile::TempDir,
    pub service: Arc<Mutex<LearningArtifactOwnerService>>,
    pub host: Arc<InventoryCellReleaseHostV1>,
    pub initial_request: LearningArtifactPublishRequestV1,
    pub config: LearningArtifactOwnerServiceConfigV1,
}
impl InventoryReleaseFixture {
    pub fn new(snapshot: &InventoryCellOwnerSnapshotV1, data: &OriginalData) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let now = crate::memory_cell_runtime::now_unix_seconds().unwrap() as u64;
        let config = fixture_config_for_scope(snapshot.scope(), directory.path().to_path_buf(), now);
        let service = Arc::new(Mutex::new(LearningArtifactOwnerService::open(config.clone()).unwrap()));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).unwrap();
        let host = Arc::new(InventoryCellReleaseHostV1::new(Arc::clone(&service), verifier));
        let candidate = data.candidate(snapshot, 1).unwrap();
        let mut template = fixture_manifest_template(&config, 1, Digest32::of_bytes(b"native-import-integration-fixture"));
        template.device_profile_digest = Digest32::of_bytes(b"test-cpu-f32-factored");
        let manifest = candidate.bind_manifest(template).unwrap();
        let initial_request = prepare_bound_request(&service, &config, manifest, candidate.bytes().to_vec(), 1);
        let fixture = Self { directory, service, host, initial_request, config };
        fixture.host.publish(fixture.initial_request.clone(), snapshot).unwrap();
        fixture.install(&fixture.host, &fixture.initial_request).unwrap();
        fixture
    }
    pub fn install(&self, host: &InventoryCellReleaseHostV1, request: &LearningArtifactPublishRequestV1) -> Result<(), String> {
        let now = crate::memory_cell_runtime::now_unix_seconds().unwrap() as u64;
        let current = self.service.lock().unwrap().current_registry_view(now).map_err(|error| error.to_string())?;
        let signed = fixture_selection(&self.service, &self.config, request, &current);
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&self.config), &self.config.trust).map_err(|error| error.to_string())?;
        let selection = verifier.verify(&signed, &current, now).map_err(|error| error.to_string())?;
        let receipt = current.receipt();
        let registry = self.directory.path().join("registries").join(format!("{}-{}.snapshot", receipt.head_digest, receipt.file_digest));
        let manifest = &request.admission.validated_manifest.manifest;
        let payload = self.directory.path().join("payloads").join(format!("{}-{}.bin", manifest.artifact_id, manifest.bytes_digest));
        host.install_selected(File::open(registry).map_err(|error| error.to_string())?, File::open(payload).map_err(|error| error.to_string())?, selection, request.admission.clone())
    }
}
