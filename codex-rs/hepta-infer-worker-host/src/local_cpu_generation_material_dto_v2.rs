//! Complete adapters for original immutable material; no runtime serde or authority.
use crate::CpuNeuronGenerationPlanV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

#[derive(Serialize, Deserialize)]
#[serde(remote = "InhibitoryEdge", deny_unknown_fields)]
pub(super) struct Edge {
    pub source: usize,
    pub target: usize,
    pub weight_q24: i64,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "SparseConfig", deny_unknown_fields)]
pub(super) struct Sparse {
    #[serde(with = "digest")]
    pub model_digest: Digest32,
    #[serde(with = "digest")]
    pub normalization_digest: Digest32,
    #[serde(with = "generation")]
    pub generation: Generation,
    pub width: usize,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    #[serde(with = "edges")]
    pub inhibition: Vec<InhibitoryEdge>,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronCalibrationProfileV1", deny_unknown_fields)]
pub(super) struct Calibration {
    #[serde(with = "digest")]
    pub calibration_artifact_digest: Digest32,
    #[serde(with = "digest")]
    pub ood_artifact_digest: Digest32,
    #[serde(with = "generation")]
    pub generation: Generation,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub zero_confidence_error_q24: i64,
    pub maximum_in_domain_error_q24: i64,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_active_ppm: u32,
    pub maximum_active_ppm: u32,
    pub maximum_projection_count: u32,
    pub measured_ece_ppm: u32,
    pub maximum_ece_ppm: u32,
    pub measured_false_acceptance_ppm: u32,
    pub maximum_false_acceptance_ppm: u32,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronResourceEnvelopeV1", deny_unknown_fields)]
pub(super) struct Resources {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronRuntimeConfigV1", deny_unknown_fields)]
pub(super) struct Runtime {
    #[serde(with = "stable_id")]
    pub config_id: StableId,
    #[serde(with = "generation")]
    pub generation: Generation,
    #[serde(with = "stable_id")]
    pub model_id: StableId,
    #[serde(with = "digest")]
    pub model_manifest_digest: Digest32,
    #[serde(with = "digest")]
    pub encoder_digest: Digest32,
    #[serde(with = "digest")]
    pub head_digest: Digest32,
    #[serde(with = "digest")]
    pub weights_digest: Digest32,
    #[serde(with = "digest")]
    pub tokenizer_digest: Digest32,
    #[serde(with = "digest")]
    pub preprocessor_digest: Digest32,
    #[serde(with = "digest")]
    pub quantization_digest: Digest32,
    #[serde(with = "digest")]
    pub runtime_digest: Digest32,
    #[serde(with = "digest")]
    pub device_digest: Digest32,
    #[serde(with = "digest")]
    pub normalization_digest: Digest32,
    #[serde(with = "digest")]
    pub native_config_digest: Digest32,
    pub input_feature_dimension: usize,
    pub state_width: usize,
    pub modulator_dimension: usize,
    #[serde(with = "Calibration")]
    pub calibration: NeuronCalibrationProfileV1,
    #[serde(with = "Resources")]
    pub resource_envelope: NeuronResourceEnvelopeV1,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "JournalScope", deny_unknown_fields)]
pub(super) struct Scope {
    #[serde(with = "digest")]
    pub scope_digest: Digest32,
    #[serde(with = "digest")]
    pub objective_digest: Digest32,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronBodyBundleIdentityV1", deny_unknown_fields)]
pub(super) struct Body {
    #[serde(with = "digest")]
    pub body_manifest_digest: Digest32,
    #[serde(with = "generation")]
    pub body_generation: Generation,
    #[serde(with = "digest")]
    pub base_bundle_digest: Digest32,
    #[serde(with = "stable_id")]
    pub organ_id: StableId,
    #[serde(with = "digest")]
    pub organ_bundle_digest: Digest32,
    #[serde(with = "optional_id")]
    pub cell_slot_id: Option<StableId>,
    #[serde(with = "optional_digest")]
    pub cell_bundle_digest: Option<Digest32>,
    #[serde(with = "digest")]
    pub effective_parameter_digest: Digest32,
    #[serde(with = "digest")]
    pub source_revision_digest: Digest32,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronGenerationStoreContextV2", deny_unknown_fields)]
pub(super) struct StoreContext {
    #[serde(with = "generation")]
    pub generation: Generation,
    #[serde(with = "Scope")]
    pub scope: JournalScope,
    #[serde(with = "digest")]
    pub runtime_config_digest: Digest32,
    #[serde(with = "digest")]
    pub body_bundle_digest: Digest32,
    pub max_records: usize,
    pub max_pending_witness: usize,
    pub max_checkpoint_bytes: usize,
    pub max_full_receipt_bytes: usize,
    pub max_file_bytes: u64,
    pub max_startup_replay_bytes: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronRuntimeIndexContextV2", deny_unknown_fields)]
pub(super) struct IndexContext {
    #[serde(with = "generation")]
    pub generation: Generation,
    #[serde(with = "Scope")]
    pub scope: JournalScope,
    #[serde(with = "digest")]
    pub runtime_config_digest: Digest32,
    #[serde(with = "digest")]
    pub body_bundle_digest: Digest32,
    pub max_records: usize,
    pub max_file_bytes: u64,
    pub max_startup_replay_bytes: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronWitnessContextV2", deny_unknown_fields)]
pub(super) struct WitnessContext {
    #[serde(with = "generation")]
    pub generation: Generation,
    #[serde(with = "Scope")]
    pub scope: JournalScope,
    pub key_epoch: u64,
    pub deletion_epoch: u64,
    pub max_records: usize,
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "CpuNeuronGenerationPlanV1", deny_unknown_fields)]
pub(super) struct Plan {
    pub model_manifest: PathBuf,
    #[serde(with = "digest")]
    pub model_manifest_digest: Digest32,
    pub generation_store: PathBuf,
    pub runtime_index: PathBuf,
    pub witness: PathBuf,
    #[serde(with = "Sparse")]
    pub native: SparseConfig,
    #[serde(with = "Scope")]
    pub scope: JournalScope,
    #[serde(with = "Runtime")]
    pub runtime: NeuronRuntimeConfigV1,
    #[serde(with = "Body")]
    pub body: NeuronBodyBundleIdentityV1,
    #[serde(with = "StoreContext")]
    pub store_context: NeuronGenerationStoreContextV2,
    #[serde(with = "IndexContext")]
    pub index_context: NeuronRuntimeIndexContextV2,
    #[serde(with = "WitnessContext")]
    pub witness_context: NeuronWitnessContextV2,
}

mod digest {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Digest32,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.to_string())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Digest32, D::Error> {
        let text = String::deserialize(deserializer)?;
        let value: Digest32 = text.parse().map_err(serde::de::Error::custom)?;
        if value.to_string() != text {
            return Err(serde::de::Error::custom("noncanonical material digest"));
        }
        Ok(value)
    }
}
mod generation {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Generation,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_u64(value.get())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Generation, D::Error> {
        Generation::new(u64::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}
mod stable_id {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &StableId,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(value.as_str())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<StableId, D::Error> {
        StableId::new(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}
mod optional_id {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Option<StableId>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.as_ref().map(StableId::as_str).serialize(serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<StableId>, D::Error> {
        Option::<String>::deserialize(deserializer)?
            .map(|v| StableId::new(v).map_err(serde::de::Error::custom))
            .transpose()
    }
}
mod optional_digest {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Option<Digest32>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.map(|v| v.to_string()).serialize(serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<Digest32>, D::Error> {
        Option::<String>::deserialize(deserializer)?
            .map(|text| {
                let value: Digest32 = text.parse().map_err(serde::de::Error::custom)?;
                if value.to_string() != text {
                    return Err(serde::de::Error::custom("noncanonical optional digest"));
                }
                Ok(value)
            })
            .transpose()
    }
}
mod edges {
    use super::*;
    #[derive(Serialize)]
    struct BorrowedEdge<'a>(#[serde(with = "Edge")] &'a InhibitoryEdge);
    #[derive(Deserialize)]
    struct OwnedEdge(#[serde(with = "Edge")] InhibitoryEdge);
    pub fn serialize<S: serde::Serializer>(
        value: &[InhibitoryEdge],
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeSeq;
        let mut sequence = serializer.serialize_seq(Some(value.len()))?;
        for edge in value {
            sequence.serialize_element(&BorrowedEdge(edge))?;
        }
        sequence.end()
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Vec<InhibitoryEdge>, D::Error> {
        Ok(Vec::<OwnedEdge>::deserialize(deserializer)?
            .into_iter()
            .map(|v| v.0)
            .collect())
    }
}
