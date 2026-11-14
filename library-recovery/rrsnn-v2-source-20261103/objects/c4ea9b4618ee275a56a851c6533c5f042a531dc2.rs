//! Offline feature projection through the unmodified upstream neuron types.
//!
//! This produces a prospective input only. It never creates a runtime receipt,
//! invokes a model owner, commits a journal, or replaces the sparse neuron core.
use std::str::FromStr;

use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_neuron::decode_neuron_tick_input_v1;
use codex_hepta_neuron::encode_neuron_tick_input_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub type Result<T> = std::result::Result<T, String>;
const Q24: f64 = 16_777_216.0;
const MAX_FEATURES: usize = 512;
pub const MAX_INPUT_BYTES: usize = 262_144;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FeatureRequest {
    pub schema: String,
    pub tick_id: String,
    pub subject_id: String,
    pub logical_sequence: u64,
    pub monotonic_time_micros: u64,
    pub checkpoint_digest: String,
    pub objective_digest: String,
    pub ndu_snapshot_digest: String,
    pub body_generation: Option<u64>,
    pub modulator_digest: Option<String>,
    pub features: Vec<f64>,
    pub source_artifact_sha256: String,
    pub source_kind: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShadowInput {
    pub schema: &'static str,
    pub upstream_commit: &'static str,
    pub official_input: serde_json::Value,
    pub official_input_semantic_digest: String,
    pub feature_vector_q24: Vec<i64>,
    pub maximum_absolute_quantization_error: f64,
    pub source_artifact_sha256: String,
    pub source_kind: String,
    pub official_owner_executed: bool,
    pub official_runtime_receipt: Option<serde_json::Value>,
    pub checkpoint_is_committed_owner_state: bool,
    pub authority: &'static str,
    pub production_activation_allowed: bool,
}

pub fn quantize_features(values: &[f64]) -> Result<Vec<i64>> {
    if !(1..=MAX_FEATURES).contains(&values.len()) {
        return Err("feature count must be between 1 and 512".into());
    }
    values
        .iter()
        .map(|value| {
            if !value.is_finite() || !(-8.0..=8.0).contains(value) {
                return Err("feature must be finite and within [-8, 8]; no clipping".into());
            }
            Ok((value * Q24).round_ties_even() as i64)
        })
        .collect()
}

pub fn prepare_shadow_input(request: &FeatureRequest) -> Result<ShadowInput> {
    if request.schema != "rrsnn.hepta-shadow-feature-request.v1"
        || request.source_artifact_sha256.len() != 64
        || !request
            .source_artifact_sha256
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        || !matches!(
            request.source_kind.as_str(),
            "synthetic_execution_state" | "trained_model_latent_observation"
        )
    {
        return Err("invalid research request schema or source provenance".into());
    }
    let features = quantize_features(&request.features)?;
    let tick = NeuronTickInputV1 {
        tick_id: StableId::new(request.tick_id.clone()).map_err(|e| e.to_string())?,
        subject_id: StableId::new(request.subject_id.clone()).map_err(|e| e.to_string())?,
        logical_sequence: request.logical_sequence,
        monotonic_time_micros: request.monotonic_time_micros,
        checkpoint_digest: Digest32::from_str(&request.checkpoint_digest)
            .map_err(|e| e.to_string())?,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features.clone(),
        objective_digest: Digest32::from_str(&request.objective_digest)
            .map_err(|e| e.to_string())?,
        ndu_snapshot_digest: Digest32::from_str(&request.ndu_snapshot_digest)
            .map_err(|e| e.to_string())?,
        body_generation: request.body_generation,
        modulator_digest: request
            .modulator_digest
            .as_deref()
            .map(Digest32::from_str)
            .transpose()
            .map_err(|e| e.to_string())?,
    };
    let encoded = encode_neuron_tick_input_v1(&tick).map_err(|e| e.to_string())?;
    let decoded = decode_neuron_tick_input_v1(&encoded).map_err(|e| e.to_string())?;
    if decoded != tick {
        return Err("upstream codec roundtrip changed the official input".into());
    }
    let maximum_error = request
        .features
        .iter()
        .zip(&features)
        .map(|(value, raw)| (value - *raw as f64 / Q24).abs())
        .fold(0.0_f64, f64::max);
    Ok(ShadowInput {
        schema: "rrsnn.hepta-typed-shadow-input.v1",
        upstream_commit: "f8c9419df6ddeb36ff8b522a50219981fb8d9345",
        official_input: serde_json::from_slice(&encoded).map_err(|e| e.to_string())?,
        official_input_semantic_digest: tick
            .semantic_digest()
            .map_err(|e| e.to_string())?
            .to_string(),
        feature_vector_q24: features,
        maximum_absolute_quantization_error: maximum_error,
        source_artifact_sha256: request.source_artifact_sha256.clone(),
        source_kind: request.source_kind.clone(),
        official_owner_executed: false,
        official_runtime_receipt: None,
        checkpoint_is_committed_owner_state: false,
        authority: "none",
        production_activation_allowed: false,
    })
}
