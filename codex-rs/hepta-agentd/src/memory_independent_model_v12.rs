//! Explicit payload version dispatch. Existing V11 envelopes still decode only
//! the original residual profile; nonlinear tensors require a V12 envelope.

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;

use crate::memory_mlp_v12::MemoryMlpCellV12;

pub(crate) const ENVELOPE_V11: &str = "hepta.memory.independent-cell.v11";
pub(crate) const ENVELOPE_V12: &str = "hepta.memory.independent-cell.v12";

pub(crate) enum IndependentCellModel {
    Residual(MemoryResidualCellV1),
    Mlp(MemoryMlpCellV12),
}

impl IndependentCellModel {
    pub fn decode(schema: &str, payload: &[u8], expected: Digest32) -> Result<Self, String> {
        match schema {
            ENVELOPE_V11 => MemoryResidualCellV1::from_bytes(payload, expected)
                .map(Self::Residual).map_err(|error| error.to_string()),
            ENVELOPE_V12 => MemoryMlpCellV12::from_bytes(payload, expected).map(Self::Mlp),
            _ => Err("independent memory cell envelope version unsupported".to_string()),
        }
    }

    pub fn kind(&self) -> MemoryCellKindV1 {
        match self { Self::Residual(model) => model.kind(), Self::Mlp(model) => model.kind() }
    }
    pub fn owner_cut_digest(&self) -> Digest32 {
        match self { Self::Residual(model) => model.owner_cut_digest(), Self::Mlp(model) => model.owner_cut_digest }
    }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> {
        match self { Self::Residual(model) => model.supports(), Self::Mlp(model) => model.supports() }
    }
    pub fn lineage_sources(&self) -> &[String] {
        match self { Self::Residual(model) => model.lineage_sources(), Self::Mlp(model) => model.lineage_sources() }
    }
    pub fn predict(&self, key: &str) -> Result<MemoryResidualPredictionV1, String> {
        match self {
            Self::Residual(model) => model.predict(key).map_err(|error| error.to_string()),
            Self::Mlp(model) => model.predict(key),
        }
    }
    pub fn bind_manifest(&self, manifest: &mut LearningArtifactManifestV2) -> Result<(), String> {
        let (artifact, parameters, head, encoder, output, numeric, address) = match self {
            Self::Residual(model) => (model.digest(), model.parameters_digest(), model.head_digest(),
                model.encoder_digest(), model.output_profile(), model.numeric_profile(), model.address_profile()),
            Self::Mlp(model) => (model.digest, model.parameters_digest, model.head_digest,
                model.encoder_digest, model.output_profile(), model.numeric_profile(), model.address_profile()),
        };
        manifest.lineage_digests = self.lineage_sources().iter().map(|source|
            source.parse::<Digest32>().map_err(|error| error.to_string())
        ).collect::<Result<_, _>>()?;
        let tuple = serde_json::to_vec(&(artifact.to_string(), parameters.to_string(), head.to_string(), encoder.to_string(), output))
            .map_err(|error| error.to_string())?;
        manifest.runtime_tuple_digest = Digest32::of_bytes(&tuple);
        manifest.compatibility_digest = Digest32::of_bytes(numeric.as_bytes());
        let normalization = serde_json::to_vec(&(address, encoder.to_string())).map_err(|error| error.to_string())?;
        manifest.normalization_digest = Digest32::of_bytes(&normalization);
        Ok(())
    }
}
