//! Bounded native inference for a frozen, zero-state nonlinear task Head.
//!
//! The payload contains only gate/down/up/task tensors, in that order, as LE
//! f32 values. Task classes never acquire action, value or effect authority.
//! Hashes bind bytes to an owner-supplied pin; they do not attest data quality.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const MAX_MANIFEST_BYTES: usize = 64 * 1024;
const MAX_PARAMETERS: usize = 262_144;
const KNOWN_MODALITIES: u8 = 0b1_1111; // text, image, audio, video, ui_event
const FEATURE_LAYOUT: &str = "concat-text-image-product-absolute-difference-cosine-v1";

/// Exact preprocessing, checkpoint and scope identity of the shared features.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskFeatureIdentityV1 {
    pub encoder_sha256: String,
    pub checkpoint_revision: String,
    pub preprocess_sha256: String,
    pub generation: u64,
    pub scope_id: String,
    pub purpose: String,
    pub revocation_epoch: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskHeadManifestV1 {
    schema: String,
    numeric_profile: String,
    state_contract: String,
    mode: String,
    authority: String,
    feature_identity: TaskFeatureIdentityV1,
    feature_layout: String,
    width: usize,
    state_width: usize,
    adapter_rank: usize,
    task_count: usize,
    required_present_mask: u8,
    temperature: f64,
    confidence_threshold: f64,
    source_head_manifest_sha256: String,
    source_head_weights_sha256: String,
    weights_sha256: String,
    weights_bytes: u64,
}

/// Validated immutable parameters. No Encoder, durable state or optimizer lives here.
pub struct LoadedTaskHeadV1 {
    manifest: TaskHeadManifestV1,
    manifest_sha256: Digest32,
    weights: Vec<f32>,
}

/// Advisory task prediction. An accepted class is not an authorized action.
#[derive(Debug, PartialEq, Serialize)]
pub struct TaskPredictionV1 {
    pub task_logits: Vec<f32>,
    pub task_probabilities: Vec<f64>,
    pub predicted_class: usize,
    pub accepted: bool,
    pub gate: f32,
    pub mode: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskHeadError {
    ArtifactBounds,
    ManifestDigestMismatch,
    ManifestEncoding,
    ManifestContract,
    WeightsDigestMismatch,
    WeightsShape,
    FeatureIdentityMismatch,
    InvalidPresenceMask,
    MissingRequiredModality,
    FeatureShape,
    NonFinite,
}

impl fmt::Display for TaskHeadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for TaskHeadError {}

impl LoadedTaskHeadV1 {
    /// Validate external manifest pin, all metadata and the exact bounded payload.
    /// This function reads no files and never resolves an untrusted payload path.
    pub fn from_artifact(
        manifest_bytes: &[u8],
        weights_le: &[u8],
        expected_manifest_sha256: Digest32,
    ) -> Result<Self, TaskHeadError> {
        if manifest_bytes.is_empty()
            || manifest_bytes.len() > MAX_MANIFEST_BYTES
            || weights_le.len() > MAX_PARAMETERS * 4
        {
            return Err(TaskHeadError::ArtifactBounds);
        }
        if expected_manifest_sha256.is_zero()
            || Digest32::of_bytes(manifest_bytes) != expected_manifest_sha256
        {
            return Err(TaskHeadError::ManifestDigestMismatch);
        }
        let manifest: TaskHeadManifestV1 =
            serde_json::from_slice(manifest_bytes).map_err(|_| TaskHeadError::ManifestEncoding)?;
        let parameter_count = validate_manifest(&manifest)?;
        if weights_le.len() != parameter_count * 4
            || manifest.weights_bytes != weights_le.len() as u64
        {
            return Err(TaskHeadError::WeightsShape);
        }
        if Digest32::of_bytes(weights_le) != parse_digest(&manifest.weights_sha256)? {
            return Err(TaskHeadError::WeightsDigestMismatch);
        }
        let weights = weights_le
            .chunks_exact(4)
            .map(|bytes| f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
            .collect::<Vec<_>>();
        if weights.iter().any(|value| !value.is_finite()) {
            return Err(TaskHeadError::NonFinite);
        }
        Ok(Self {
            manifest,
            manifest_sha256: expected_manifest_sha256,
            weights,
        })
    }

    pub fn feature_identity(&self) -> &TaskFeatureIdentityV1 {
        &self.manifest.feature_identity
    }

    pub fn manifest_sha256(&self) -> Digest32 {
        self.manifest_sha256
    }

    pub fn weights_bytes(&self) -> usize {
        self.weights.len() * 4
    }

    /// Score one feature row with the exact manifest identity and zero local state.
    /// Missing required modalities reject before any neural arithmetic or outputs.
    pub fn predict(
        &self,
        features: &[f32],
        identity: &TaskFeatureIdentityV1,
        present_mask: u8,
    ) -> Result<TaskPredictionV1, TaskHeadError> {
        let config = &self.manifest;
        if identity != &config.feature_identity {
            return Err(TaskHeadError::FeatureIdentityMismatch);
        }
        if present_mask & !KNOWN_MODALITIES != 0 {
            return Err(TaskHeadError::InvalidPresenceMask);
        }
        if present_mask & config.required_present_mask != config.required_present_mask {
            return Err(TaskHeadError::MissingRequiredModality);
        }
        let width = config.width;
        if features.len() != width {
            return Err(TaskHeadError::FeatureShape);
        }
        if features.iter().any(|value| !value.is_finite()) {
            return Err(TaskHeadError::NonFinite);
        }
        let rank = config.adapter_rank;
        let gate_bias = width + config.state_width;
        let down_start = gate_bias + 1;
        let up_start = down_start + rank * width;
        let task_start = up_start + width * rank;
        let task_bias = task_start + config.task_count * width;
        // State coefficients remain in the pinned payload, multiplied by exact zero.
        let gate_score = f64::from(affine(
            &self.weights[..width],
            features,
            self.weights[gate_bias],
        )?);
        let gate = if gate_score >= 0.0 {
            1.0 / (1.0 + (-gate_score).exp())
        } else {
            let exponential = gate_score.exp();
            exponential / (1.0 + exponential)
        } as f32;
        let mut hidden = Vec::with_capacity(rank);
        for row in 0..rank {
            let start = down_start + row * width;
            let x = affine(&self.weights[start..start + width], features, 0.0)?;
            let x64 = f64::from(x);
            hidden.push(checked_f32(
                0.5 * x64 * (1.0 + erf_bounded(x64 * std::f64::consts::FRAC_1_SQRT_2)),
            )?);
        }
        let mut adapted = Vec::with_capacity(width);
        for (row, feature) in features.iter().enumerate() {
            let start = up_start + row * rank;
            let residual = affine(&self.weights[start..start + rank], &hidden, 0.0)?;
            let value = *feature + gate * residual;
            if !value.is_finite() {
                return Err(TaskHeadError::NonFinite);
            }
            adapted.push(value);
        }
        let mut logits = Vec::with_capacity(config.task_count);
        for row in 0..config.task_count {
            let start = task_start + row * width;
            logits.push(affine(
                &self.weights[start..start + width],
                &adapted,
                self.weights[task_bias + row],
            )?);
        }
        let scaled: Vec<f64> = logits
            .iter()
            .map(|value| f64::from(*value) / config.temperature)
            .collect();
        if scaled.iter().any(|value| !value.is_finite()) {
            return Err(TaskHeadError::NonFinite);
        }
        let maximum = scaled.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let mut probabilities: Vec<f64> = scaled.iter().map(|v| (v - maximum).exp()).collect();
        let sum: f64 = probabilities.iter().sum();
        let mut predicted_class = 0;
        for (index, probability) in probabilities.iter_mut().enumerate() {
            *probability /= sum;
            if scaled[index] > scaled[predicted_class] {
                predicted_class = index;
            }
        }
        Ok(TaskPredictionV1 {
            accepted: probabilities[predicted_class] >= config.confidence_threshold,
            task_logits: logits,
            task_probabilities: probabilities,
            predicted_class,
            gate,
            mode: "SHADOW_ONLY",
            authority: "DENY_ALL",
        })
    }
}

fn validate_manifest(manifest: &TaskHeadManifestV1) -> Result<usize, TaskHeadError> {
    if manifest.schema != "hepta.native-task-head.v1"
        || manifest.numeric_profile != "f32-io-f64-accum-gelu-erf-v1"
        || manifest.state_contract != "zero_state_only"
        || manifest.mode != "SHADOW_ONLY"
        || manifest.authority != "DENY_ALL"
        || manifest.feature_layout != FEATURE_LAYOUT
        || !(5..=4096).contains(&manifest.width)
        || !(manifest.width - 1).is_multiple_of(4)
        || !(1..=64).contains(&manifest.state_width)
        || !(1..=16).contains(&manifest.adapter_rank)
        || !(2..=256).contains(&manifest.task_count)
        || manifest.required_present_mask != 0b11
        || !manifest.temperature.is_finite()
        || manifest.temperature <= 0.0
        || manifest.temperature > 100.0
        || !(0.0..=1.0).contains(&manifest.confidence_threshold)
    {
        return Err(TaskHeadError::ManifestContract);
    }
    let identity = &manifest.feature_identity;
    if identity.generation == 0
        || identity.checkpoint_revision.len() != 40
        || !identity
            .checkpoint_revision
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
        || !valid_name(&identity.scope_id)
        || !valid_name(&identity.purpose)
    {
        return Err(TaskHeadError::ManifestContract);
    }
    for value in [
        &identity.encoder_sha256,
        &identity.preprocess_sha256,
        &manifest.source_head_manifest_sha256,
        &manifest.source_head_weights_sha256,
        &manifest.weights_sha256,
    ] {
        parse_digest(value)?;
    }
    let count = manifest.width
        + manifest.state_width
        + 1
        + 2 * manifest.width * manifest.adapter_rank
        + manifest.task_count * (manifest.width + 1);
    if count > MAX_PARAMETERS {
        return Err(TaskHeadError::ArtifactBounds);
    }
    Ok(count)
}

fn valid_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|v| v.is_ascii_alphanumeric() || b"_.:-".contains(&v))
}

fn parse_digest(value: &str) -> Result<Digest32, TaskHeadError> {
    let digest: Digest32 = value.parse().map_err(|_| TaskHeadError::ManifestContract)?;
    if digest.is_zero() {
        return Err(TaskHeadError::ManifestContract);
    }
    Ok(digest)
}

fn affine(weights: &[f32], inputs: &[f32], bias: f32) -> Result<f32, TaskHeadError> {
    checked_f32(
        weights
            .iter()
            .zip(inputs)
            .fold(f64::from(bias), |sum, (w, x)| {
                sum + f64::from(*w) * f64::from(*x)
            }),
    )
}

fn checked_f32(value: f64) -> Result<f32, TaskHeadError> {
    let result = value as f32;
    if !result.is_finite() {
        return Err(TaskHeadError::NonFinite);
    }
    Ok(result)
}

// GELU's erf definition, not its tanh approximation. A convergent power series
// on |x|<3 avoids a library dependency; for 3<=|x|<6 use the equivalent Laplace
// continued fraction (https://dlmf.nist.gov/7.9.E1). Beyond 6 the omitted tail
// is below f64 rounding at 1. Both loops have fixed work bounds.
fn erf_bounded(value: f64) -> f64 {
    let x = value.abs();
    let result = if x < 3.0 {
        let mut term = x;
        let mut sum = x;
        for n in 1..80 {
            term *= -x * x / f64::from(n);
            sum += term / f64::from(2 * n + 1);
        }
        std::f64::consts::FRAC_2_SQRT_PI * sum
    } else if x < 6.0 {
        let mut fraction = 0.0;
        for n in (1..=64).rev() {
            fraction = 0.5 * f64::from(n) / (x + fraction);
        }
        1.0 - 0.5 * std::f64::consts::FRAC_2_SQRT_PI * (-x * x).exp() / (x + fraction)
    } else {
        1.0
    };
    result.copysign(value)
}

#[cfg(test)]
#[path = "task_head_native_tests.rs"]
mod tests;
