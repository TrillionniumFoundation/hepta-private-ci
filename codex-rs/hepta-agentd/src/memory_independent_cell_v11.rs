//! A separately published cell using the existing signed artifact owner. The
//! V10 numeric payload remains unchanged; V11 binds its complete clean-fit
//! partition separately from the historical full acquisition cut.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_memory::MemoryTrainingProjectionV11;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use crate::memory_cell_release::core::MemoryReleaseBundle;
use crate::memory_cell_release::core::MemoryReleaseSlot;

const SCHEMA: &str = "hepta.memory.independent-cell.v11";
const MAX_BYTES: usize = 40 * 1024 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellWire {
    schema: String,
    owner_agent_id: AgentId,
    scope: ContractIdV1,
    selector: MemoryTrainingSelectorV11,
    generation: ContractGenerationV1,
    training_projection_digest: ContractDigestV1,
    acquisition_full_cut: ContractDigestV1,
    payload_digest: ContractDigestV1,
    payload: String,
}

/// Candidate creation authenticates sources through an owner-produced value;
/// neither a candidate nor its serialized projection grants selection authority.
pub struct MemoryCellCandidateV11 {
    bytes: Vec<u8>,
    decoded: SelectedMemoryCellV11,
}

impl MemoryCellCandidateV11 {
    pub fn from_projection(
        projection: &MemoryTrainingProjectionV11,
        generation: ContractGenerationV1,
        payload: &[u8],
    ) -> Result<Self, String> {
        if payload.is_empty() || payload.len() > MAX_BYTES {
            return Err("V11 numerical payload size bound".to_string());
        }
        let wire = CellWire {
            schema: SCHEMA.to_string(),
            owner_agent_id: projection.owner_agent_id().clone(),
            scope: projection.scope().clone(),
            selector: projection.selector().clone(),
            generation,
            training_projection_digest: projection.digest(),
            acquisition_full_cut: projection.acquisition_cut_digest(),
            payload_digest: contract(Digest32::of_bytes(payload))?,
            payload: std::str::from_utf8(payload)
                .map_err(|error| error.to_string())?
                .to_string(),
        };
        let bytes = serde_json::to_vec(&wire).map_err(|error| error.to_string())?;
        let decoded = SelectedMemoryCellV11::decode(&bytes, Digest32::of_bytes(&bytes))?;
        decoded.validate_projection(projection)?;
        Ok(Self { bytes, decoded })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn digest(&self) -> ContractDigestV1 {
        self.decoded.digest
    }

    pub fn bind_manifest(
        &self,
        mut manifest: LearningArtifactManifestV2,
    ) -> Result<LearningArtifactManifestV2, String> {
        self.decoded.bind_manifest(&mut manifest)?;
        Ok(manifest)
    }
}

/// Exact immutable cell bytes plus an evictable numerical cache. Only the
/// configured artifact owner and selector can make this payload current.
pub struct SelectedMemoryCellV11 {
    wire: CellWire,
    digest: ContractDigestV1,
    encoded_size_bytes: u64,
    model: Mutex<Option<MemoryResidualCellV1>>,
}

impl SelectedMemoryCellV11 {
    pub fn cell_id(&self) -> &ContractIdV1 {
        &self.wire.selector.cell_id
    }
    pub fn selector(&self) -> &MemoryTrainingSelectorV11 {
        &self.wire.selector
    }
    pub fn generation(&self) -> ContractGenerationV1 {
        self.wire.generation
    }
    pub fn digest(&self) -> ContractDigestV1 {
        self.digest
    }
    pub fn scope(&self) -> &ContractIdV1 {
        &self.wire.scope
    }
    pub fn training_projection_digest(&self) -> ContractDigestV1 {
        self.wire.training_projection_digest
    }
    pub fn payload_digest(&self) -> ContractDigestV1 {
        self.wire.payload_digest
    }

    pub fn validate_owner_snapshot(
        &self,
        owner: &MemoryInventoryOwnerSnapshotV1,
    ) -> Result<(), String> {
        let projection = owner
            .training_projection_v11(&self.wire.selector)
            .map_err(|error| error.to_string())?;
        self.validate_projection(&projection)
    }

    fn validate_projection(&self, projection: &MemoryTrainingProjectionV11) -> Result<(), String> {
        if self.wire.owner_agent_id != *projection.owner_agent_id()
            || self.scope() != projection.scope()
            || self.selector() != projection.selector()
            || self.training_projection_digest() != projection.digest()
        {
            return Err("V11 cell training projection changed".to_string());
        }
        self.with_model(|model| {
            let supports = projection
                .records()
                .iter()
                .map(|row| {
                    (
                        Digest32::of_bytes(row.record.key.as_str().as_bytes()).to_string(),
                        vec![row.source_id.to_string()],
                    )
                })
                .collect::<BTreeMap<_, _>>();
            let lineage = projection
                .records()
                .iter()
                .map(|row| row.source_id.to_string())
                .collect::<BTreeSet<_>>();
            if *model.supports() != supports
                || model.lineage_sources() != lineage.into_iter().collect::<Vec<_>>()
            {
                return Err(
                    "V11 cell does not cover every clean-fit partition dependency".to_string(),
                );
            }
            Ok(())
        })
    }

    pub(crate) fn predict(&self, key: &str) -> Result<MemoryResidualPredictionV1, String> {
        self.with_model(|model| model.predict(key).map_err(|error| error.to_string()))
    }

    fn with_model<T>(
        &self,
        visit: impl FnOnce(&MemoryResidualCellV1) -> Result<T, String>,
    ) -> Result<T, String> {
        let mut model = self
            .model
            .lock()
            .map_err(|_| "V11 cell cache lock poisoned")?;
        if model.is_none() {
            *model = Some(decode_model(&self.wire)?);
        }
        visit(model.as_ref().ok_or("V11 cell cache absent")?)
    }

    fn bind_manifest(&self, manifest: &mut LearningArtifactManifestV2) -> Result<(), String> {
        manifest.kind = ArtifactKind::Parameters;
        manifest.generation =
            Generation::new(self.generation().get()).map_err(|error| error.to_string())?;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = vec![self.training_projection_digest().digest()];
        manifest.bytes_digest = self.digest.digest();
        manifest.encoded_size_bytes = self.encoded_size_bytes;
        manifest.schema_profile_digest = Digest32::of_bytes(SCHEMA.as_bytes());
        let objective = serde_json::to_vec(&(SCHEMA, self.cell_id(), self.selector().kind))
            .map_err(|error| error.to_string())?;
        manifest.objective_class_digest = Digest32::of_bytes(&objective);
        self.with_model(|model| {
            manifest.lineage_digests = model
                .lineage_sources()
                .iter()
                .map(|source| {
                    source
                        .parse::<Digest32>()
                        .map_err(|error| error.to_string())
                })
                .collect::<Result<_, _>>()?;
            let tuple = serde_json::to_vec(&(
                model.digest().to_string(),
                model.parameters_digest().to_string(),
                model.head_digest().to_string(),
                model.encoder_digest().to_string(),
                model.output_profile(),
            ))
            .map_err(|error| error.to_string())?;
            manifest.runtime_tuple_digest = Digest32::of_bytes(&tuple);
            manifest.compatibility_digest = Digest32::of_bytes(model.numeric_profile().as_bytes());
            let normalization =
                serde_json::to_vec(&(model.address_profile(), model.encoder_digest().to_string()))
                    .map_err(|error| error.to_string())?;
            manifest.normalization_digest = Digest32::of_bytes(&normalization);
            Ok(())
        })
    }
}

impl MemoryReleaseBundle for SelectedMemoryCellV11 {
    fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES || Digest32::of_bytes(bytes) != expected {
            return Err("V11 cell size or digest mismatch".to_string());
        }
        let wire: CellWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        wire.selector
            .validate()
            .map_err(|error| error.to_string())?;
        if wire.schema != SCHEMA || wire.generation.get() >= 1_u64 << 53 {
            return Err("V11 cell schema or generation".to_string());
        }
        let model = decode_model(&wire)?;
        Ok(Self {
            wire,
            digest: contract(expected)?,
            encoded_size_bytes: bytes.len() as u64,
            model: Mutex::new(Some(model)),
        })
    }
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String> {
        let mut expected = manifest.clone();
        self.bind_manifest(&mut expected)?;
        if expected != *manifest
            || manifest.predecessor_ids.len() > 1
            || manifest.rollback_predecessor.is_some()
        {
            return Err(
                "V11 cell manifest does not bind complete parameters and dependencies".to_string(),
            );
        }
        Ok(())
    }
    fn generation(&self) -> ContractGenerationV1 {
        self.generation()
    }
    fn bundle_digest(&self) -> ContractDigestV1 {
        self.digest
    }
    fn scope(&self) -> &ContractIdV1 {
        self.scope()
    }
}

fn decode_model(wire: &CellWire) -> Result<MemoryResidualCellV1, String> {
    let model =
        MemoryResidualCellV1::from_bytes(wire.payload.as_bytes(), wire.payload_digest.digest())
            .map_err(|error| error.to_string())?;
    let kind = match wire.selector.kind {
        MemoryInventoryKindV1::Semantic => MemoryCellKindV1::Semantic,
        MemoryInventoryKindV1::Procedure => MemoryCellKindV1::Procedure,
        MemoryInventoryKindV1::Event | MemoryInventoryKindV1::Hold => {
            return Err("V11 parameter cell kind".to_string());
        }
    };
    if model.kind() != kind || model.owner_cut_digest() != wire.acquisition_full_cut.digest() {
        return Err("V11 numerical payload kind or historical acquisition cut differs".to_string());
    }
    Ok(model)
}

fn contract(digest: Digest32) -> Result<ContractDigestV1, String> {
    ContractDigestV1::from_digest(digest).map_err(|error| error.to_string())
}

/// Configure one existing signed artifact registry per cell. Sharing a registry
/// would couple CURRENT refreshes again; a plan rejects duplicate storage bindings.
pub struct MemoryCellReleaseV11 {
    cell_id: ContractIdV1,
    service: Arc<Mutex<LearningArtifactOwnerService>>,
    inner: MemoryReleaseSlot<SelectedMemoryCellV11>,
}

impl MemoryCellReleaseV11 {
    pub fn new(
        cell_id: ContractIdV1,
        service: Arc<Mutex<LearningArtifactOwnerService>>,
        verifier: ArtifactSelectionVerifierV1,
    ) -> Self {
        Self {
            cell_id,
            service: Arc::clone(&service),
            inner: MemoryReleaseSlot::new(service, verifier),
        }
    }
    pub fn cell_id(&self) -> &ContractIdV1 {
        &self.cell_id
    }
    pub(crate) fn registry_binding(&self) -> Result<Digest32, String> {
        Ok(self
            .service
            .lock()
            .map_err(|_| "V11 artifact owner lock poisoned")?
            .current_registry_view(crate::memory_cell_release::core::now()?)
            .map_err(|error| error.to_string())?
            .receipt()
            .binding)
    }
    pub fn publish(
        &self,
        request: LearningArtifactPublishRequestV1,
        owner: &MemoryInventoryOwnerSnapshotV1,
    ) -> Result<ArtifactPublicationReceiptV1, String> {
        self.inner.publish(request, |cell| {
            if cell.cell_id() != self.cell_id() {
                return Err("V11 release cell identity differs".to_string());
            }
            cell.validate_owner_snapshot(owner)
        })
    }
    pub fn install_selected(
        &self,
        snapshot: File,
        mut payload: File,
        selection: VerifiedArtifactSelectionV1,
        admission: WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), String> {
        let mut bytes = Vec::new();
        (&mut payload)
            .take((MAX_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|error| error.to_string())?;
        let candidate = SelectedMemoryCellV11::decode(
            &bytes,
            admission.validated_manifest.manifest.bytes_digest,
        )?;
        if candidate.cell_id() != self.cell_id() {
            return Err("V11 selected cell identity differs".to_string());
        }
        payload
            .seek(SeekFrom::Start(0))
            .map_err(|error| error.to_string())?;
        self.inner
            .install_selected(snapshot, payload, selection, admission)
    }
    pub fn load_current(&self) -> Result<Arc<SelectedMemoryCellV11>, String> {
        self.inner.load_current()
    }
    pub(crate) fn revalidate(&self, cell: &SelectedMemoryCellV11) -> Result<(), String> {
        self.inner.revalidate(cell)
    }
    pub fn sleep_selected(&self) -> Result<(), String> {
        let cell = self.load_current()?;
        *cell
            .model
            .lock()
            .map_err(|_| "V11 cell cache lock poisoned")? = None;
        self.revalidate(&cell)
    }
}
