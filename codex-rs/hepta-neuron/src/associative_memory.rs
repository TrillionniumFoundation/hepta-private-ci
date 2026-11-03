//! Bounded native execution of exported float32 associative memory parameters.
//!
//! Artifact admission and source freshness belong to the host. This loader pins
//! complete bytes, checks the numeric parameter digest, and preserves every
//! declared support and training dependency. A prediction is never a source fact.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::validate_memory_cell_value_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sha3::Shake256;
use sha3::digest::ExtendableOutput;
use sha3::digest::Update;
use sha3::digest::XofReader;

pub const MAX_ASSOCIATIVE_MEMORY_BYTES: usize = 32_000_000;
pub const ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1: &str = "hepta.memory.sha256-shake256-f64.v1";
pub const ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1: &str =
    "hepta.memory.f32-weights-f64-tanh-softmax.v1";
const MAX_SOURCES: usize = 65_536;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AssociativeMemoryError {
    InvalidArtifact,
    BindingMismatch,
    InvalidInput,
    InvalidConfiguration,
}

impl fmt::Display for AssociativeMemoryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AssociativeMemoryError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AssociativeMemoryAbstentionV1 {
    OutsideWrittenSupport,
    BelowSelectionThreshold,
}

/// Intermediate model prediction; the owner must independently revalidate all
/// training dependencies and the selected support before exposing a readout.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct AssociativeMemoryPredictionV1 {
    pub kind: MemoryCellKindV1,
    pub value: Option<Value>,
    pub confidence: f64,
    pub confidence_kind: &'static str,
    pub source_ids: Vec<String>,
    pub artifact_digest: String,
    pub parameter_digest: String,
    pub abstain: Option<AssociativeMemoryAbstentionV1>,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AssociativeArrays {
    pub input_weights: Vec<f32>,
    pub hidden_bias: Vec<f32>,
    pub output_weights: Vec<f32>,
    pub output_bias: Vec<f32>,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AssociativeWire {
    schema: String,
    pub kind: MemoryCellKindV1,
    address_profile: String,
    numeric_profile: String,
    pub dimension: usize,
    pub hidden: usize,
    pub catalog: Vec<Value>,
    pub supports: BTreeMap<String, Vec<String>>,
    pub lineage_sources: Vec<String>,
    pub threshold: f64,
    pub acceptance_enabled: bool,
    parameter_sha256: String,
    original_artifact_sha256: String,
    training_receipt_sha256: String,
    pub arrays: AssociativeArrays,
}

/// An immutable trained model. Catalog values are explicit and fully charged;
/// source-ID support contains no key-to-answer labels or predicted class index.
#[derive(Clone)]
pub struct AssociativeMemoryCellV1 {
    pub(super) model: AssociativeWire,
    digest: Digest32,
    parameters_digest: Digest32,
    serialized_bytes: usize,
}

impl AssociativeMemoryCellV1 {
    pub fn from_bytes(
        bytes: &[u8],
        expected_digest: Digest32,
    ) -> Result<Self, AssociativeMemoryError> {
        if bytes.is_empty() || bytes.len() > MAX_ASSOCIATIVE_MEMORY_BYTES {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let digest = Digest32::of_bytes(bytes);
        if expected_digest.is_zero() || digest != expected_digest {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        let model: AssociativeWire =
            serde_json::from_slice(bytes).map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
        if model.schema != "hepta.memory.associative-native.v1"
            || model.address_profile != ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1
            || model.numeric_profile != ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1
            || model.kind == MemoryCellKindV1::Event
            || !(8..=1024).contains(&model.dimension)
            || !(1..=256).contains(&model.hidden)
            || !(1..=4096).contains(&model.catalog.len())
            || !(1..=4096).contains(&model.supports.len())
            || !model.threshold.is_finite()
            || !(0.0..=1.0).contains(&model.threshold)
        {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let mut catalog = BTreeSet::new();
        for value in &model.catalog {
            validate_memory_cell_value_v1(model.kind, value)
                .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
            let encoded =
                serde_json::to_vec(value).map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
            if !catalog.insert(encoded) {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
        }
        if !valid_sources(&model.lineage_sources, MAX_SOURCES) {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        for (address, sources) in &model.supports {
            if !valid_digest(address)
                || !valid_sources(sources, 128)
                || sources
                    .iter()
                    .any(|source| model.lineage_sources.binary_search(source).is_err())
            {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
        }
        let arrays = &model.arrays;
        let expected = [
            model.dimension * model.hidden,
            model.hidden,
            model.hidden * model.catalog.len(),
            model.catalog.len(),
        ];
        let mut parameter_bytes = Vec::with_capacity(expected.iter().sum::<usize>() * 4);
        for (values, length) in [
            &arrays.input_weights,
            &arrays.hidden_bias,
            &arrays.output_weights,
            &arrays.output_bias,
        ]
        .into_iter()
        .zip(expected)
        {
            if values.len() != length || values.iter().any(|value| !value.is_finite()) {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            for value in values {
                parameter_bytes.extend_from_slice(&value.to_le_bytes());
            }
        }
        let parameters_digest = Digest32::of_bytes(&parameter_bytes);
        if model.parameter_sha256 != parameters_digest.to_string()
            || !valid_digest(&model.original_artifact_sha256)
            || !valid_digest(&model.training_receipt_sha256)
        {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        Ok(Self {
            model,
            digest,
            parameters_digest,
            serialized_bytes: bytes.len(),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn parameters_digest(&self) -> Digest32 {
        self.parameters_digest
    }
    pub fn kind(&self) -> MemoryCellKindV1 {
        self.model.kind
    }
    pub fn input_dimension(&self) -> usize {
        self.model.dimension
    }
    pub fn output_width(&self) -> usize {
        self.model.catalog.len().max(5)
    }
    pub fn serialized_bytes(&self) -> usize {
        self.serialized_bytes
    }
    pub fn lineage_sources(&self) -> &[String] {
        &self.model.lineage_sources
    }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> {
        &self.model.supports
    }

    pub fn head_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.memory.associative-head.v1",
            self.digest.as_array(),
            ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1.as_bytes(),
        ])
    }

    /// Value-independent SHA-256/SHAKE-256 features matching the Python trainer.
    pub fn encode_key(&self, key: &str) -> Result<Vec<f64>, AssociativeMemoryError> {
        if key.is_empty() || key.len() > 4096 {
            return Err(AssociativeMemoryError::InvalidInput);
        }
        let mut shake = Shake256::default();
        shake.update(Digest32::of_bytes(key.as_bytes()).as_array());
        let mut bytes = vec![0_u8; self.model.dimension];
        shake.finalize_xof().read(&mut bytes);
        let root = (self.model.dimension as f64).sqrt();
        Ok(bytes
            .into_iter()
            .map(|byte| (f64::from(byte) - 127.5) / 73.9002706355 / root)
            .collect())
    }

    /// Predict from tensors. Support lookup supplies dependency IDs only.
    pub fn predict(
        &self,
        key: &str,
    ) -> Result<AssociativeMemoryPredictionV1, AssociativeMemoryError> {
        let features = self.encode_key(key)?;
        let mut output = AssociativeMemoryPredictionV1 {
            kind: self.kind(),
            value: None,
            confidence: 0.0,
            confidence_kind: "uncalibrated-softmax",
            source_ids: Vec::new(),
            artifact_digest: self.digest.to_string(),
            parameter_digest: self.parameters_digest.to_string(),
            abstain: Some(AssociativeMemoryAbstentionV1::OutsideWrittenSupport),
        };
        let Some(sources) = self
            .model
            .supports
            .get(&Digest32::of_bytes(key.as_bytes()).to_string())
        else {
            return Ok(output);
        };
        let scores = self.logits(&features)?;
        let mut winner = 0;
        for index in 1..scores.len() {
            if scores[index] > scores[winner] {
                winner = index;
            }
        }
        let denominator: f64 = scores
            .iter()
            .map(|score| (score - scores[winner]).exp())
            .sum();
        output.confidence = 1.0 / denominator;
        output.abstain = Some(AssociativeMemoryAbstentionV1::BelowSelectionThreshold);
        if self.model.acceptance_enabled && output.confidence >= self.model.threshold {
            output.value = Some(self.model.catalog[winner].clone());
            output.source_ids.clone_from(sources);
            output.abstain = None;
        }
        Ok(output)
    }

    pub(super) fn logits(&self, features: &[f64]) -> Result<Vec<f64>, AssociativeMemoryError> {
        if features.len() != self.model.dimension
            || features
                .iter()
                .any(|value| !value.is_finite() || !(-1.0..=1.0).contains(value))
        {
            return Err(AssociativeMemoryError::InvalidInput);
        }
        let arrays = &self.model.arrays;
        let mut hidden = vec![0.0; self.model.hidden];
        for (column, activation) in hidden.iter_mut().enumerate() {
            let mut sum = f64::from(arrays.hidden_bias[column]);
            for (row, feature) in features.iter().enumerate() {
                sum += feature * f64::from(arrays.input_weights[row * self.model.hidden + column]);
            }
            *activation = sum.tanh();
        }
        let classes = self.model.catalog.len();
        let mut scores = vec![0.0; classes];
        for (column, score) in scores.iter_mut().enumerate() {
            *score = f64::from(arrays.output_bias[column]);
            for (row, activation) in hidden.iter().enumerate() {
                *score += activation * f64::from(arrays.output_weights[row * classes + column]);
            }
        }
        Ok(scores)
    }
}

fn valid_digest(value: &str) -> bool {
    value
        .parse::<Digest32>()
        .is_ok_and(|digest| !digest.is_zero())
}

fn valid_sources(values: &[String], limit: usize) -> bool {
    !values.is_empty()
        && values.len() <= limit
        && values.iter().all(|value| valid_digest(value))
        && values.windows(2).all(|pair| pair[0] < pair[1])
}

#[cfg(test)]
#[path = "associative_memory_tests.rs"]
mod tests;
