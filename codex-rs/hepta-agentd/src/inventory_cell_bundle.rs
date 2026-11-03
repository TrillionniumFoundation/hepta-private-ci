//! Original residual parameters and canonical encoder vectors at the real owner.

use crate::memory_cell_release::MemoryCellDecodeTokenV1;
use crate::memory_cell_release::MemoryCellReleaseBundleV1;
use crate::memory_cell_release::Sealed;
use codex_hepta_cognitive_types::INVENTORY_CELL_PROFILE_V1;
use codex_hepta_cognitive_types::InventoryCellKindV1;
use codex_hepta_cognitive_types::InventoryCellRouteV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_memory::InventoryCellOwnerSnapshotV1;
use codex_hepta_neuron::MEMORY_RESIDUAL_NUMERIC_PROFILE_V1;
use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_neuron::MemoryResidualOutputProfileV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;

const SCHEMA: &str = "hepta.memory.inventory-bundle.native.v1";
const CELL_SCHEMA: &str = "hepta.memory.inventory-bundle.native.v2";
const MAX_BUNDLE_BYTES: usize = 8 * 1024 * 1024;

/// Address-only canonical encoder input, with an explicit training-source to
/// SQLite-source mapping. This contains no cached answer or output logits.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellFeatureBindingV1 {
    pub kind: InventoryCellKindV1,
    pub key: ContractIdV1,
    pub training_source: ContractDigestV1,
    pub owner_source: ContractDigestV1,
    pub features: Vec<f32>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellPayload {
    digest: ContractDigestV1,
    payload: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellTrainingCuts {
    semantic: ContractDigestV1,
    skill: ContractDigestV1,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BundleWire {
    schema: String,
    scope: ContractIdV1,
    owner_cut_digest: ContractDigestV1,
    training_cut_digest: ContractDigestV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    cell_training_cuts: Option<CellTrainingCuts>,
    generation: ContractGenerationV1,
    semantic: CellPayload,
    skill: CellPayload,
    bindings: Vec<InventoryCellFeatureBindingV1>,
    lineage_sources: Vec<ContractDigestV1>,
}

pub struct InventoryCellBundleCandidateV1 {
    bytes: Vec<u8>,
    decoded: LoadedInventoryCellBundleV1,
}

impl InventoryCellBundleCandidateV1 {
    /// Construct an inactive candidate. Both original and native source IDs are
    /// preserved; publication and independent selection are still required.
    pub fn from_owner_snapshot(
        snapshot: &InventoryCellOwnerSnapshotV1,
        generation: ContractGenerationV1,
        semantic_bytes: &[u8],
        skill_bytes: &[u8],
        bindings: Vec<InventoryCellFeatureBindingV1>,
    ) -> Result<Self, String> {
        let cell = |bytes: &[u8]| -> Result<CellPayload, String> {
            Ok(CellPayload {
                digest: contract(Digest32::of_bytes(bytes))?,
                payload: std::str::from_utf8(bytes)
                    .map_err(|error| error.to_string())?
                    .to_owned(),
            })
        };
        let wire = BundleWire {
            schema: CELL_SCHEMA.to_string(),
            scope: snapshot.scope().clone(),
            owner_cut_digest: snapshot.owner_cut_digest(),
            training_cut_digest: snapshot
                .parameter_training_cut_digest()
                .map_err(|error| error.to_string())?,
            generation,
            cell_training_cuts: Some(CellTrainingCuts {
                semantic: snapshot
                    .cell_training_cut_digest(InventoryCellKindV1::Semantic)
                    .map_err(|error| error.to_string())?,
                skill: snapshot
                    .cell_training_cut_digest(InventoryCellKindV1::Skill)
                    .map_err(|error| error.to_string())?,
            }),
            semantic: cell(semantic_bytes)?,
            skill: cell(skill_bytes)?,
            lineage_sources: complete_lineage(&bindings),
            bindings,
        };
        let bytes = serde_json::to_vec(&wire).map_err(|error| error.to_string())?;
        let decoded = LoadedInventoryCellBundleV1::decode(
            &bytes,
            Digest32::of_bytes(&bytes),
            MemoryCellDecodeTokenV1::new(),
        )?;
        decoded.validate_owner_snapshot(snapshot)?;
        Ok(Self { bytes, decoded })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn digest(&self) -> ContractDigestV1 {
        self.decoded.bundle_digest
    }

    pub fn bind_manifest(
        &self,
        mut template: LearningArtifactManifestV2,
    ) -> Result<LearningArtifactManifestV2, String> {
        self.decoded.bind_manifest(&mut template)?;
        Ok(template)
    }
}

pub struct LoadedInventoryCellBundleV1 {
    schema: String,
    generation: ContractGenerationV1,
    bundle_digest: ContractDigestV1,
    owner_cut_digest: ContractDigestV1,
    training_cut_digest: ContractDigestV1,
    cell_training_cuts: Option<CellTrainingCuts>,
    scope: ContractIdV1,
    semantic: MemoryResidualCellV1,
    skill: MemoryResidualCellV1,
    bindings: Vec<InventoryCellFeatureBindingV1>,
    lineage_sources: Vec<ContractDigestV1>,
    encoded_size_bytes: u64,
}

impl LoadedInventoryCellBundleV1 {
    pub fn generation(&self) -> ContractGenerationV1 {
        self.generation
    }
    pub fn bundle_digest(&self) -> ContractDigestV1 {
        self.bundle_digest
    }
    /// Full training-export cut is provenance, not a current-read capability.
    pub fn owner_cut_digest(&self) -> ContractDigestV1 {
        self.owner_cut_digest
    }
    pub fn training_cut_digest(&self) -> ContractDigestV1 {
        self.training_cut_digest
    }
    pub fn scope(&self) -> &ContractIdV1 {
        &self.scope
    }
    pub fn encoder_digest(&self) -> Digest32 {
        self.semantic.encoder_digest()
    }

    pub(crate) fn model(&self, kind: InventoryCellKindV1) -> Result<&MemoryResidualCellV1, String> {
        match kind {
            InventoryCellKindV1::Semantic => Ok(&self.semantic),
            InventoryCellKindV1::Skill => Ok(&self.skill),
            _ => Err("exact inventory sources have no parameter model".to_string()),
        }
    }

    pub(crate) fn binding(
        &self,
        kind: InventoryCellKindV1,
        key: &ContractIdV1,
    ) -> Option<&InventoryCellFeatureBindingV1> {
        self.bindings
            .iter()
            .find(|row| row.kind == kind && row.key == *key)
    }

    /// Validate all training dependencies of every parameter model this route
    /// will execute. Publication still validates both models; final use still
    /// revalidates the selected release and the complete acquired owner cut.
    pub(crate) fn validate_route_owner_snapshot(
        &self,
        snapshot: &InventoryCellOwnerSnapshotV1,
        route: &InventoryCellRouteV1,
    ) -> Result<(), String> {
        route.validate().map_err(|error| error.to_string())?;
        if self.scope != *snapshot.scope() {
            return Err("inventory bundle scope differs".to_string());
        }
        let Some(cuts) = &self.cell_training_cuts else {
            return self.validate_owner_snapshot(snapshot);
        };
        let kinds: &[InventoryCellKindV1] = match route.operation {
            MemoryOperationV1::Semantic => &[InventoryCellKindV1::Semantic],
            MemoryOperationV1::Procedure => &[InventoryCellKindV1::Skill],
            MemoryOperationV1::Apply => {
                &[InventoryCellKindV1::Semantic, InventoryCellKindV1::Skill]
            }
            MemoryOperationV1::Current | MemoryOperationV1::History | MemoryOperationV1::Change => {
                &[]
            }
        };
        for &kind in kinds {
            let expected = match kind {
                InventoryCellKindV1::Semantic => cuts.semantic,
                _ => cuts.skill,
            };
            if expected
                != snapshot
                    .cell_training_cut_digest(kind)
                    .map_err(|error| error.to_string())?
            {
                return Err("inventory cell training cut differs".to_string());
            }
            self.validate_cell_sources(snapshot, kind)?;
        }
        Ok(())
    }

    fn validate_cell_sources(
        &self,
        snapshot: &InventoryCellOwnerSnapshotV1,
        kind: InventoryCellKindV1,
    ) -> Result<(), String> {
        let records = snapshot.training_records(kind);
        if records.len() != self.bindings.iter().filter(|row| row.kind == kind).count() {
            return Err("inventory model does not cover the exact owner training cut".to_string());
        }
        for row in records {
            let binding = self
                .binding(kind, &row.record.key)
                .ok_or("inventory training address absent")?;
            if binding.owner_source != row.source_id {
                return Err("inventory source mapping is stale".to_string());
            }
            if binding.training_source != binding.owner_source
                && (row.revision != 1
                    || row.record.training_origin != Some(binding.training_source))
            {
                return Err(
                    "inventory import lineage is absent or corrected; retraining required"
                        .to_string(),
                );
            }
        }
        Ok(())
    }

    fn bind_manifest(&self, manifest: &mut LearningArtifactManifestV2) -> Result<(), String> {
        manifest.kind = ArtifactKind::Parameters;
        manifest.generation =
            Generation::new(self.generation.get()).map_err(|error| error.to_string())?;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = match &self.cell_training_cuts {
            Some(cuts) => vec![cuts.semantic.digest(), cuts.skill.digest()],
            None => vec![self.training_cut_digest.digest()],
        };
        manifest.source_dataset_digests.sort_unstable();
        manifest.lineage_digests = self
            .lineage_sources
            .iter()
            .map(|digest| digest.digest())
            .collect();
        manifest.bytes_digest = self.bundle_digest.digest();
        manifest.encoded_size_bytes = self.encoded_size_bytes;
        let mut runtime = b"hepta.memory.inventory-parameters.v1".to_vec();
        for model in [&self.semantic, &self.skill] {
            for digest in [
                model.artifact_digest(),
                model.parameters_digest(),
                model.encoder_digest(),
                model.checkpoint_manifest_digest(),
                model.training_history_digest(),
            ] {
                runtime.extend_from_slice(digest.as_array());
            }
        }
        runtime.extend_from_slice(
            Digest32::of_bytes(
                &serde_json::to_vec(&self.bindings).map_err(|error| error.to_string())?,
            )
            .as_array(),
        );
        manifest.runtime_tuple_digest = Digest32::of_bytes(&runtime);
        manifest.objective_class_digest = Digest32::of_bytes(INVENTORY_CELL_PROFILE_V1.as_bytes());
        manifest.compatibility_digest =
            Digest32::of_bytes(MEMORY_RESIDUAL_NUMERIC_PROFILE_V1.as_bytes());
        manifest.schema_profile_digest = Digest32::of_bytes(self.schema.as_bytes());
        manifest.normalization_digest = self.encoder_digest();
        Ok(())
    }
}

impl Sealed for LoadedInventoryCellBundleV1 {}

impl MemoryCellReleaseBundleV1 for LoadedInventoryCellBundleV1 {
    type OwnerSnapshot = InventoryCellOwnerSnapshotV1;

    fn decode(
        bytes: &[u8],
        expected: Digest32,
        _token: MemoryCellDecodeTokenV1,
    ) -> Result<Self, String> {
        if bytes.is_empty()
            || bytes.len() > MAX_BUNDLE_BYTES
            || Digest32::of_bytes(bytes) != expected
        {
            return Err("inventory bundle size or digest mismatch".to_string());
        }
        let wire: BundleWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if (wire.schema != SCHEMA && wire.schema != CELL_SCHEMA)
            || (wire.schema == CELL_SCHEMA) != wire.cell_training_cuts.is_some()
            || wire.generation.get() >= 1_u64 << 53
            || wire.bindings.is_empty()
            || wire.bindings.len() > 256
        {
            return Err("inventory bundle schema or capacity".to_string());
        }
        let semantic = MemoryResidualCellV1::from_bytes(
            wire.semantic.payload.as_bytes(),
            wire.semantic.digest.digest(),
        )
        .map_err(|error| error.to_string())?;
        let skill = MemoryResidualCellV1::from_bytes(
            wire.skill.payload.as_bytes(),
            wire.skill.digest.digest(),
        )
        .map_err(|error| error.to_string())?;
        if semantic.output_profile() != MemoryResidualOutputProfileV1::InventorySemantic
            || skill.output_profile() != MemoryResidualOutputProfileV1::InventorySkill
            || semantic.encoder_digest() != skill.encoder_digest()
            || wire.lineage_sources != complete_lineage(&wire.bindings)
        {
            return Err("inventory parameter profile, encoder or lineage differs".to_string());
        }
        for (kind, model) in [
            (InventoryCellKindV1::Semantic, &semantic),
            (InventoryCellKindV1::Skill, &skill),
        ] {
            let rows: Vec<_> = wire
                .bindings
                .iter()
                .filter(|row| row.kind == kind)
                .collect();
            let keys: BTreeSet<_> = rows.iter().map(|row| row.key.as_str()).collect();
            let original: BTreeSet<_> = rows
                .iter()
                .map(|row| row.training_source.to_string())
                .collect();
            let actual: BTreeSet<_> = rows.iter().map(|row| row.owner_source).collect();
            if rows.is_empty()
                || keys.len() != rows.len()
                || original.len() != rows.len()
                || actual.len() != rows.len()
                || original.into_iter().collect::<Vec<_>>() != model.lineage_sources()
            {
                return Err(
                    "inventory model sources are not a complete one-to-one address map".to_string(),
                );
            }
        }
        if wire.bindings.iter().any(|row| {
            !matches!(
                row.kind,
                InventoryCellKindV1::Semantic | InventoryCellKindV1::Skill
            ) || row.features.len() != 384
                || row.features.iter().any(|value| !value.is_finite())
        }) {
            return Err("inventory feature profile or finite dimension differs".to_string());
        }
        Ok(Self {
            schema: wire.schema,
            cell_training_cuts: wire.cell_training_cuts,
            generation: wire.generation,
            bundle_digest: contract(expected)?,
            owner_cut_digest: wire.owner_cut_digest,
            training_cut_digest: wire.training_cut_digest,
            scope: wire.scope,
            semantic,
            skill,
            bindings: wire.bindings,
            lineage_sources: wire.lineage_sources,
            encoded_size_bytes: bytes.len() as u64,
        })
    }

    fn validate_owner_snapshot(&self, snapshot: &Self::OwnerSnapshot) -> Result<(), String> {
        if self.scope != *snapshot.scope()
            || self.training_cut_digest
                != snapshot
                    .parameter_training_cut_digest()
                    .map_err(|error| error.to_string())?
        {
            return Err("inventory bundle training cut or scope differs".to_string());
        }
        for kind in [InventoryCellKindV1::Semantic, InventoryCellKindV1::Skill] {
            self.validate_cell_sources(snapshot, kind)?;
            if let Some(cuts) = &self.cell_training_cuts {
                let expected = match kind {
                    InventoryCellKindV1::Semantic => cuts.semantic,
                    _ => cuts.skill,
                };
                if expected
                    != snapshot
                        .cell_training_cut_digest(kind)
                        .map_err(|error| error.to_string())?
                {
                    return Err("inventory cell training cut differs".to_string());
                }
            }
        }
        Ok(())
    }

    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String> {
        let mut expected = manifest.clone();
        self.bind_manifest(&mut expected)?;
        if expected != *manifest
            || manifest.predecessor_ids.len() > 1
            || manifest.rollback_predecessor.is_some()
        {
            return Err("inventory manifest differs from typed parameters".to_string());
        }
        Ok(())
    }
    fn generation(&self) -> ContractGenerationV1 {
        self.generation
    }
    fn bundle_digest(&self) -> ContractDigestV1 {
        self.bundle_digest
    }
    fn scope(&self) -> &ContractIdV1 {
        &self.scope
    }
}

fn complete_lineage(bindings: &[InventoryCellFeatureBindingV1]) -> Vec<ContractDigestV1> {
    bindings
        .iter()
        .flat_map(|row| [row.training_source, row.owner_source])
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}
fn contract(digest: Digest32) -> Result<ContractDigestV1, String> {
    ContractDigestV1::from_digest(digest).map_err(|error| error.to_string())
}
