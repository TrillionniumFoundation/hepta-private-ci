//! Faithful residual inventory payloads bound to a canonical owner cut.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Mutex;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use crate::memory_cell_release::core::MemoryReleaseBundle;

const SCHEMA: &str = "hepta.memory.inventory-bundle.v1";
const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_LINEAGE: usize = 8192;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellPayload {
    digest: ContractDigestV1,
    payload: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BundleWire {
    schema: String,
    scope: ContractIdV1,
    owner_cut_digest: ContractDigestV1,
    generation: ContractGenerationV1,
    semantic: CellPayload,
    procedure: CellPayload,
    lineage_sources: Vec<ContractDigestV1>,
}

/// A source-bound candidate. Construction neither publishes nor selects it.
pub struct MemoryInventoryBundleCandidateV1 {
    bytes: Vec<u8>,
    decoded: LoadedMemoryInventoryBundleV1,
}

impl MemoryInventoryBundleCandidateV1 {
    pub fn from_owner_snapshot(
        owner: &MemoryInventoryOwnerSnapshotV1,
        generation: ContractGenerationV1,
        semantic: &[u8],
        procedure: &[u8],
    ) -> Result<Self, String> {
        let payload = |bytes: &[u8]| -> Result<CellPayload, String> {
            Ok(CellPayload {
                digest: contract(Digest32::of_bytes(bytes))?,
                payload: std::str::from_utf8(bytes).map_err(|error| error.to_string())?.to_owned(),
            })
        };
        let semantic_model = MemoryResidualCellV1::from_bytes(semantic, Digest32::of_bytes(semantic))
            .map_err(|error| error.to_string())?;
        let procedure_model = MemoryResidualCellV1::from_bytes(procedure, Digest32::of_bytes(procedure))
            .map_err(|error| error.to_string())?;
        let wire = BundleWire {
            schema: SCHEMA.to_string(),
            scope: owner.scope().clone(),
            owner_cut_digest: owner.owner_cut_digest(),
            generation,
            semantic: payload(semantic)?,
            procedure: payload(procedure)?,
            lineage_sources: complete_lineage(&semantic_model, &procedure_model)?,
        };
        let bytes = serde_json::to_vec(&wire).map_err(|error| error.to_string())?;
        let decoded = LoadedMemoryInventoryBundleV1::decode(&bytes, Digest32::of_bytes(&bytes))?;
        decoded.validate_owner_snapshot(owner)?;
        Ok(Self { bytes, decoded })
    }

    pub fn bytes(&self) -> &[u8] { &self.bytes }
    pub fn digest(&self) -> ContractDigestV1 { self.decoded.bundle_digest }

    pub fn bind_manifest(
        &self,
        mut manifest: LearningArtifactManifestV2,
    ) -> Result<LearningArtifactManifestV2, String> {
        self.decoded.bind_manifest(&mut manifest)?;
        Ok(manifest)
    }
}

/// Immutable exact payloads plus a reclaimable decoded tensor cache. The
/// signed release slot, never this cache, determines the active generation.
pub struct LoadedMemoryInventoryBundleV1 {
    wire: BundleWire,
    bundle_digest: ContractDigestV1,
    encoded_size_bytes: u64,
    models: Mutex<Option<(MemoryResidualCellV1, MemoryResidualCellV1)>>,
}

impl LoadedMemoryInventoryBundleV1 {
    pub fn generation(&self) -> ContractGenerationV1 { self.wire.generation }
    pub fn bundle_digest(&self) -> ContractDigestV1 { self.bundle_digest }
    pub fn owner_cut_digest(&self) -> ContractDigestV1 { self.wire.owner_cut_digest }
    pub fn scope(&self) -> &ContractIdV1 { &self.wire.scope }
    pub fn encoded_size_bytes(&self) -> u64 { self.encoded_size_bytes }

    /// Drop decoded models; retained exact bytes and provenance remain charged.
    /// Subsequent use decodes and validates both complete payloads again.
    pub fn sleep(&self) -> Result<(), String> {
        *self.models.lock().map_err(|_| "inventory model cache lock poisoned")? = None;
        Ok(())
    }

    pub fn predict(
        &self,
        kind: MemoryCellKindV1,
        key: &str,
    ) -> Result<MemoryResidualPredictionV1, String> {
        self.with_models(|semantic, procedure| {
            let model = match kind {
                MemoryCellKindV1::Semantic => semantic,
                MemoryCellKindV1::Procedure => procedure,
                MemoryCellKindV1::Event => return Err("event records are not residual predictions".to_string()),
            };
            let prediction = model.predict(key).map_err(|error| error.to_string())?;
            if prediction.kind != kind
                || prediction.artifact_digest != model.digest().to_string()
                || prediction.parameter_digest != model.parameters_digest().to_string()
            {
                return Err("inventory prediction identity differs from selected parameters".to_string());
            }
            Ok(prediction)
        })
    }

    pub(crate) fn validate_owner_snapshot(&self, owner: &MemoryInventoryOwnerSnapshotV1) -> Result<(), String> {
        if self.scope() != owner.scope() || self.owner_cut_digest() != owner.owner_cut_digest() {
            return Err("inventory bundle owner cut or scope mismatch".to_string());
        }
        self.with_models(|semantic, procedure| {
            for (model, kind) in [(semantic, MemoryInventoryKindV1::Semantic), (procedure, MemoryInventoryKindV1::Procedure)] {
                let records = owner.training_records(kind);
                let sources = records.iter().map(|row| row.source_id.to_string()).collect::<BTreeSet<_>>();
                let supports = records.iter().map(|row| (
                    Digest32::of_bytes(row.record.key.as_str().as_bytes()).to_string(),
                    vec![row.source_id.to_string()],
                )).collect::<BTreeMap<_, _>>();
                if supports.len() != records.len()
                    || supports != *model.supports()
                    || sources.into_iter().collect::<Vec<_>>() != model.lineage_sources()
                    || model.owner_cut_digest() != owner.owner_cut_digest().digest()
                {
                    return Err("residual model does not cover the exact inventory owner training cut".to_string());
                }
            }
            Ok(())
        })
    }

    fn with_models<T>(&self, visit: impl FnOnce(&MemoryResidualCellV1, &MemoryResidualCellV1) -> Result<T, String>) -> Result<T, String> {
        let mut cached = self.models.lock().map_err(|_| "inventory model cache lock poisoned")?;
        if cached.is_none() { *cached = Some(decode_models(&self.wire)?); }
        let (semantic, procedure) = cached.as_ref().ok_or("inventory model cache unavailable")?;
        visit(semantic, procedure)
    }

    fn bind_manifest(&self, manifest: &mut LearningArtifactManifestV2) -> Result<(), String> {
        manifest.kind = ArtifactKind::Parameters;
        manifest.generation = Generation::new(self.generation().get()).map_err(|error| error.to_string())?;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = vec![self.owner_cut_digest().digest()];
        manifest.lineage_digests = self.wire.lineage_sources.iter().map(|source| source.digest()).collect();
        manifest.bytes_digest = self.bundle_digest.digest();
        manifest.encoded_size_bytes = self.encoded_size_bytes;
        manifest.objective_class_digest = Digest32::of_bytes(b"hepta.memory.inventory-read.v1");
        manifest.schema_profile_digest = Digest32::of_bytes(SCHEMA.as_bytes());
        self.with_models(|semantic, procedure| {
            let mut runtime = b"hepta.memory.inventory.parameters.v1".to_vec();
            for model in [semantic, procedure] {
                for digest in [model.digest(), model.parameters_digest(), model.head_digest(), model.encoder_digest()] {
                    runtime.extend_from_slice(digest.as_array());
                }
                runtime.extend_from_slice(model.output_profile().as_bytes());
            }
            manifest.runtime_tuple_digest = Digest32::of_bytes(&runtime);
            manifest.compatibility_digest = Digest32::of_bytes(semantic.numeric_profile().as_bytes());
            let binding = serde_json::to_vec(&(semantic.address_profile(), semantic.encoder_digest().to_string())).map_err(|error| error.to_string())?;
            manifest.normalization_digest = Digest32::of_bytes(&binding);
            Ok(())
        })
    }
}

impl MemoryReleaseBundle for LoadedMemoryInventoryBundleV1 {
    fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES || Digest32::of_bytes(bytes) != expected {
            return Err("inventory bundle size or digest mismatch".to_string());
        }
        let wire: BundleWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if wire.schema != SCHEMA || wire.generation.get() >= 1_u64 << 53
            || wire.lineage_sources.is_empty() || wire.lineage_sources.len() > MAX_LINEAGE {
            return Err("inventory bundle schema or lineage bound".to_string());
        }
        let models = decode_models(&wire)?;
        Ok(Self { wire, bundle_digest: contract(expected)?, encoded_size_bytes: bytes.len() as u64, models: Mutex::new(Some(models)) })
    }
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String> {
        let mut expected = manifest.clone();
        self.bind_manifest(&mut expected)?;
        if expected != *manifest || manifest.predecessor_ids.len() > 1 || manifest.rollback_predecessor.is_some() {
            return Err("inventory manifest differs from its complete residual bundle".to_string());
        }
        Ok(())
    }
    fn generation(&self) -> ContractGenerationV1 { self.generation() }
    fn bundle_digest(&self) -> ContractDigestV1 { self.bundle_digest() }
    fn scope(&self) -> &ContractIdV1 { self.scope() }
}

fn decode_models(wire: &BundleWire) -> Result<(MemoryResidualCellV1, MemoryResidualCellV1), String> {
    let semantic = MemoryResidualCellV1::from_bytes(wire.semantic.payload.as_bytes(), wire.semantic.digest.digest()).map_err(|error| error.to_string())?;
    let procedure = MemoryResidualCellV1::from_bytes(wire.procedure.payload.as_bytes(), wire.procedure.digest.digest()).map_err(|error| error.to_string())?;
    if semantic.kind() != MemoryCellKindV1::Semantic || procedure.kind() != MemoryCellKindV1::Procedure
        || semantic.owner_cut_digest() != wire.owner_cut_digest.digest()
        || procedure.owner_cut_digest() != wire.owner_cut_digest.digest()
        || semantic.encoder_digest() != procedure.encoder_digest()
        || semantic.address_profile() != procedure.address_profile()
        || semantic.numeric_profile() != procedure.numeric_profile()
        || complete_lineage(&semantic, &procedure)? != wire.lineage_sources
    {
        return Err("inventory model kind, profile, encoder, owner cut or lineage mismatch".to_string());
    }
    Ok((semantic, procedure))
}

fn complete_lineage(semantic: &MemoryResidualCellV1, procedure: &MemoryResidualCellV1) -> Result<Vec<ContractDigestV1>, String> {
    let sources: Result<BTreeSet<_>, _> = semantic.lineage_sources().iter().chain(procedure.lineage_sources())
        .map(|source| ContractDigestV1::parse(source).map_err(|error| error.to_string())).collect();
    Ok(sources?.into_iter().collect())
}

fn contract(digest: Digest32) -> Result<ContractDigestV1, String> {
    ContractDigestV1::from_digest(digest).map_err(|error| error.to_string())
}
