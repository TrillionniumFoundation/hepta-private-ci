//! Typed parameter payloads; construction alone grants no artifact selection.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_neuron::ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1;
use codex_hepta_neuron::ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1;
use codex_hepta_neuron::MemoryCellPopulationV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

const SCHEMA: &str = "hepta.memory.bundle.native.v1";
const POPULATION_SCHEMA: &str = "hepta.memory.bundle.native.v2";
const MAX_BUNDLE_BYTES: usize = 64 * 1024 * 1024;
const MAX_BUNDLE_LINEAGE: usize = 1_024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellPayload {
    digest: ContractDigestV1,
    // Preserve exact native JSON bytes, including their numeric spelling.
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

/// An authority-free candidate bound to an actual cognitive owner snapshot.
/// Its bytes still require publication, independent selection, and final use
/// checks against the live owner and artifact service.
pub struct MemoryCellBundleCandidateV1 {
    bytes: Vec<u8>,
    decoded: LoadedMemoryCellBundleV1,
}

impl MemoryCellBundleCandidateV1 {
    pub fn from_owner_snapshot(
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: ContractGenerationV1,
        semantic_bytes: &[u8],
        procedure_bytes: &[u8],
    ) -> Result<Self, String> {
        Self::from_owner_payloads(snapshot, generation, semantic_bytes, procedure_bytes, false)
    }

    /// Construct a partitioned candidate. Construction grants no activation;
    /// the existing signed release path still validates the exact owner cut.
    pub fn from_owner_populations(
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: ContractGenerationV1,
        semantic_bytes: &[u8],
        procedure_bytes: &[u8],
    ) -> Result<Self, String> {
        Self::from_owner_payloads(snapshot, generation, semantic_bytes, procedure_bytes, true)
    }

    fn from_owner_payloads(
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: ContractGenerationV1,
        semantic_bytes: &[u8],
        procedure_bytes: &[u8],
        population: bool,
    ) -> Result<Self, String> {
        let cell = |bytes: &[u8]| -> Result<CellPayload, String> {
            Ok(CellPayload {
                digest: contract(Digest32::of_bytes(bytes))?,
                payload: std::str::from_utf8(bytes)
                    .map_err(|error| error.to_string())?
                    .to_owned(),
            })
        };
        let semantic = cell(semantic_bytes)?;
        let procedure = cell(procedure_bytes)?;
        let semantic_model =
            MemoryCellPopulationV2::from_bytes(semantic_bytes, semantic.digest.digest())
                .map_err(|error| error.to_string())?;
        let procedure_model =
            MemoryCellPopulationV2::from_bytes(procedure_bytes, procedure.digest.digest())
                .map_err(|error| error.to_string())?;
        if semantic_model.is_population() != population
            || procedure_model.is_population() != population
        {
            return Err(
                "memory bundle factory requires its declared native payload version".to_string(),
            );
        }
        let wire = BundleWire {
            schema: if population {
                POPULATION_SCHEMA
            } else {
                SCHEMA
            }
            .to_string(),
            scope: snapshot.scope().clone(),
            owner_cut_digest: snapshot.owner_cut_digest(),
            generation,
            semantic,
            procedure,
            lineage_sources: complete_lineage(&semantic_model, &procedure_model)?,
        };
        let bytes = serde_json::to_vec(&wire).map_err(|error| error.to_string())?;
        let decoded = LoadedMemoryCellBundleV1::decode(&bytes, Digest32::of_bytes(&bytes))?;
        decoded.validate_owner_snapshot(snapshot)?;
        Ok(Self { bytes, decoded })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn digest(&self) -> ContractDigestV1 {
        self.decoded.bundle_digest
    }

    /// Fill fields determined by the payload. The host supplies producer,
    /// training code, device identity, validity and predecessor provenance in
    /// the template, then submits it to the existing withdrawal-bound owner.
    pub fn bind_manifest(
        &self,
        mut template: LearningArtifactManifestV2,
    ) -> Result<LearningArtifactManifestV2, String> {
        self.decoded.bind_manifest(&mut template)?;
        Ok(template)
    }
}

/// Decoded immutable parameters issued only by a verified release host. A
/// retained reference must pass that host's revalidation before final use.
pub struct LoadedMemoryCellBundleV1 {
    schema: String,
    generation: ContractGenerationV1,
    bundle_digest: ContractDigestV1,
    owner_cut_digest: ContractDigestV1,
    scope: ContractIdV1,
    semantic: MemoryCellPopulationV2,
    procedure: MemoryCellPopulationV2,
    lineage_sources: Vec<ContractDigestV1>,
    encoded_size_bytes: u64,
}

impl LoadedMemoryCellBundleV1 {
    pub fn generation(&self) -> ContractGenerationV1 {
        self.generation
    }
    pub fn bundle_digest(&self) -> ContractDigestV1 {
        self.bundle_digest
    }
    pub fn owner_cut_digest(&self) -> ContractDigestV1 {
        self.owner_cut_digest
    }
    pub fn scope(&self) -> &ContractIdV1 {
        &self.scope
    }
    pub fn semantic(&self) -> &MemoryCellPopulationV2 {
        &self.semantic
    }
    pub fn procedure(&self) -> &MemoryCellPopulationV2 {
        &self.procedure
    }

    pub(super) fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty()
            || bytes.len() > MAX_BUNDLE_BYTES
            || Digest32::of_bytes(bytes) != expected
        {
            return Err("memory bundle size or digest mismatch".to_string());
        }
        let wire: BundleWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if ![SCHEMA, POPULATION_SCHEMA].contains(&wire.schema.as_str())
            || wire.lineage_sources.is_empty()
            || wire.lineage_sources.len() > MAX_BUNDLE_LINEAGE
        {
            return Err("memory bundle schema or lineage limit".to_string());
        }
        let semantic = MemoryCellPopulationV2::from_bytes(
            wire.semantic.payload.as_bytes(),
            wire.semantic.digest.digest(),
        )
        .map_err(|error| error.to_string())?;
        let procedure = MemoryCellPopulationV2::from_bytes(
            wire.procedure.payload.as_bytes(),
            wire.procedure.digest.digest(),
        )
        .map_err(|error| error.to_string())?;
        let population = wire.schema == POPULATION_SCHEMA;
        if semantic.kind() != MemoryCellKindV1::Semantic
            || procedure.kind() != MemoryCellKindV1::Procedure
            || semantic.is_population() != population
            || procedure.is_population() != population
            || complete_lineage(&semantic, &procedure)? != wire.lineage_sources
        {
            return Err("memory bundle type or complete lineage mismatch".to_string());
        }
        Ok(Self {
            schema: wire.schema,
            generation: wire.generation,
            bundle_digest: contract(expected)?,
            owner_cut_digest: wire.owner_cut_digest,
            scope: wire.scope,
            semantic,
            procedure,
            lineage_sources: wire.lineage_sources,
            encoded_size_bytes: bytes.len() as u64,
        })
    }

    pub(crate) fn validate_owner_snapshot(
        &self,
        snapshot: &MemoryCellOwnerSnapshotV1,
    ) -> Result<(), String> {
        if self.scope != *snapshot.scope() || self.owner_cut_digest != snapshot.owner_cut_digest() {
            return Err("memory bundle owner cut or scope mismatch".to_string());
        }
        for model in [&self.semantic, &self.procedure] {
            let records = snapshot.training_records(model.kind());
            let sources: BTreeSet<_> = records
                .iter()
                .map(|row| row.source_id.to_string())
                .collect();
            let support: BTreeMap<_, _> = records
                .iter()
                .map(|row| {
                    (
                        Digest32::of_bytes(row.record.entity.as_str().as_bytes()).to_string(),
                        vec![row.source_id.to_string()],
                    )
                })
                .collect();
            if support.len() != records.len()
                || support != *model.supports()
                || sources.into_iter().collect::<Vec<_>>() != model.lineage_sources()
            {
                return Err("memory model does not cover the exact owner training cut".to_string());
            }
        }
        Ok(())
    }

    pub(super) fn validate_manifest(
        &self,
        manifest: &LearningArtifactManifestV2,
    ) -> Result<(), String> {
        let mut expected = manifest.clone();
        self.bind_manifest(&mut expected)?;
        if expected != *manifest
            || manifest.predecessor_ids.len() > 1
            || manifest.rollback_predecessor.is_some()
        {
            return Err("memory parameter manifest differs from its typed bundle".to_string());
        }
        Ok(())
    }

    fn bind_manifest(&self, manifest: &mut LearningArtifactManifestV2) -> Result<(), String> {
        manifest.kind = ArtifactKind::Parameters;
        manifest.generation =
            Generation::new(self.generation.get()).map_err(|error| error.to_string())?;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = vec![self.owner_cut_digest.digest()];
        manifest.lineage_digests = self
            .lineage_sources
            .iter()
            .map(|digest| digest.digest())
            .collect();
        manifest.bytes_digest = self.bundle_digest.digest();
        manifest.encoded_size_bytes = self.encoded_size_bytes;
        let mut runtime = b"hepta.memory.bundle.parameters.v1".to_vec();
        for model in [&self.semantic, &self.procedure] {
            for digest in [
                model.digest(),
                model.parameters_digest(),
                model.head_digest(),
            ] {
                runtime.extend_from_slice(digest.as_array());
            }
        }
        manifest.runtime_tuple_digest = Digest32::of_bytes(&runtime);
        manifest.objective_class_digest = Digest32::of_bytes(b"hepta.memory.typed-read.v1");
        manifest.compatibility_digest =
            Digest32::of_bytes(ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1.as_bytes());
        manifest.schema_profile_digest = Digest32::of_bytes(self.schema.as_bytes());
        manifest.normalization_digest =
            Digest32::of_bytes(ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1.as_bytes());
        Ok(())
    }
}

fn complete_lineage(
    semantic: &MemoryCellPopulationV2,
    procedure: &MemoryCellPopulationV2,
) -> Result<Vec<ContractDigestV1>, String> {
    let lineage: Result<BTreeSet<_>, _> = semantic
        .lineage_sources()
        .iter()
        .chain(procedure.lineage_sources())
        .map(|source| ContractDigestV1::parse(source).map_err(|error| error.to_string()))
        .collect();
    Ok(lineage?.into_iter().collect())
}

fn contract(digest: Digest32) -> Result<ContractDigestV1, String> {
    ContractDigestV1::from_digest(digest).map_err(|error| error.to_string())
}
