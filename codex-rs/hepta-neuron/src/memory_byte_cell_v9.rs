//! Catalog-free typed bytes reconstructed exclusively from learned parameters.
//!
//! A fixed byte alphabet is not a value catalog. Support maps contain source
//! IDs only. Every length bit, payload bit and padding bit participates in the
//! confidence bound; malformed or noncanonical typed output is declined.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::validate_memory_cell_value_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use sha3::Shake256;
use sha3::digest::ExtendableOutput;
use sha3::digest::Update;
use sha3::digest::XofReader;

use crate::ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1;
use crate::AssociativeMemoryAbstentionV1;
use crate::AssociativeMemoryError;
use crate::AssociativeMemoryPredictionV1;
use crate::associative_memory::AssociativeArrays;
use crate::memory_population_cost::ShardCost;

pub(super) const SCHEMA: &str = "hepta.memory.byte-native.v9";
pub const MEMORY_BYTE_NUMERIC_PROFILE_V9: &str = "hepta.memory.f32-f64-tanh-bytebits.v9";
const VALUE_BYTES: usize = 128;
const OUTPUT_BITS: usize = (VALUE_BYTES + 2) * 8;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ByteWire {
    schema: String,
    kind: MemoryCellKindV1,
    address_profile: String,
    numeric_profile: String,
    dimension: usize,
    hidden: usize,
    max_value_bytes: usize,
    threshold: f64,
    supports: BTreeMap<String, Vec<String>>,
    lineage_sources: Vec<String>,
    parameter_sha256: String,
    training_receipt_sha256: String,
    arrays: AssociativeArrays,
}

pub(super) struct MemoryByteCellV9 {
    wire: ByteWire,
    digest: Digest32,
    parameter_digest: Digest32,
}

impl MemoryByteCellV9 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, AssociativeMemoryError> {
        if bytes.is_empty() || bytes.len() > crate::MAX_ASSOCIATIVE_MEMORY_BYTES {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        if expected.is_zero() || Digest32::of_bytes(bytes) != expected {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        let wire: ByteWire = serde_json::from_slice(bytes)
            .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
        if wire.schema != SCHEMA || wire.kind == MemoryCellKindV1::Event
            || wire.address_profile != ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1
            || wire.numeric_profile != MEMORY_BYTE_NUMERIC_PROFILE_V9
            || !(8..=256).contains(&wire.dimension) || !(1..=64).contains(&wire.hidden)
            || wire.max_value_bytes != VALUE_BYTES || !(1..=4096).contains(&wire.supports.len())
            || !wire.threshold.is_finite() || !(0.5..=1.0).contains(&wire.threshold)
            || !valid_digest(&wire.training_receipt_sha256)
        {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let mut sources = BTreeSet::new();
        for (address, values) in &wire.supports {
            if !valid_digest(address) || values.is_empty() || values.len() > 128
                || values.iter().any(|value| !valid_digest(value))
                || values.windows(2).any(|pair| pair[0] >= pair[1])
            {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            sources.extend(values.iter().cloned());
        }
        if sources.len() > 65_536 || wire.lineage_sources != sources.into_iter().collect::<Vec<_>>() {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let lengths = [wire.dimension * wire.hidden, wire.hidden, wire.hidden * OUTPUT_BITS, OUTPUT_BITS];
        let mut parameters = Vec::with_capacity(lengths.iter().sum::<usize>() * 4);
        for (array, expected_len) in [
            &wire.arrays.input_weights, &wire.arrays.hidden_bias,
            &wire.arrays.output_weights, &wire.arrays.output_bias,
        ].into_iter().zip(lengths) {
            if array.len() != expected_len || array.iter().any(|value| !value.is_finite()) {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            for value in array {
                parameters.extend_from_slice(&value.to_le_bytes());
            }
        }
        let parameter_digest = Digest32::of_bytes(&parameters);
        if wire.parameter_sha256 != parameter_digest.to_string() {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        Ok(Self { wire, digest: expected, parameter_digest })
    }

    pub fn kind(&self) -> MemoryCellKindV1 { self.wire.kind }
    pub fn parameters_digest(&self) -> Digest32 { self.parameter_digest }
    pub fn head_digest(&self) -> Digest32 {
        Digest32::of_parts(&[b"hepta.memory.byte-head.v9", self.digest.as_array(), MEMORY_BYTE_NUMERIC_PROFILE_V9.as_bytes()])
    }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> { &self.wire.supports }
    pub fn lineage_sources(&self) -> &[String] { &self.wire.lineage_sources }

    pub fn cost(&self) -> Result<ShardCost, AssociativeMemoryError> {
        let arrays = &self.wire.arrays;
        Ok(ShardCost {
            parameters: ((arrays.input_weights.len() + arrays.hidden_bias.len()
                + arrays.output_weights.len() + arrays.output_bias.len()) * 4) as u64,
            catalog: 0,
            support: serde_json::to_vec(&self.wire.supports)
                .map_err(|_| AssociativeMemoryError::InvalidArtifact)?.len() as u64,
            lineage: serde_json::to_vec(&self.wire.lineage_sources)
                .map_err(|_| AssociativeMemoryError::InvalidArtifact)?.len() as u64,
        })
    }

    pub fn predict(&self, key: &str) -> Result<AssociativeMemoryPredictionV1, AssociativeMemoryError> {
        if key.is_empty() || key.len() > 4096 {
            return Err(AssociativeMemoryError::InvalidInput);
        }
        let mut result = AssociativeMemoryPredictionV1 {
            kind: self.kind(), value: None, confidence: 0.0,
            confidence_kind: "uncalibrated-minimum-byte-bit-margin",
            source_ids: Vec::new(), artifact_digest: self.digest.to_string(),
            parameter_digest: self.parameter_digest.to_string(),
            abstain: Some(AssociativeMemoryAbstentionV1::OutsideWrittenSupport),
        };
        let address = Digest32::of_bytes(key.as_bytes());
        let Some(sources) = self.wire.supports.get(&address.to_string()) else { return Ok(result); };
        let mut shake = Shake256::default();
        shake.update(address.as_array());
        let mut bytes = vec![0; self.wire.dimension];
        shake.finalize_xof().read(&mut bytes);
        let root = (self.wire.dimension as f64).sqrt();
        let features = bytes.into_iter().map(|byte| (f64::from(byte) - 127.5) / 73.9002706355 / root).collect::<Vec<_>>();
        let arrays = &self.wire.arrays;
        let mut hidden = vec![0.0_f64; self.wire.hidden];
        for (column, activation) in hidden.iter_mut().enumerate() {
            let mut sum = f64::from(arrays.hidden_bias[column]);
            for (row, feature) in features.iter().enumerate() {
                sum += feature * f64::from(arrays.input_weights[row * self.wire.hidden + column]);
            }
            *activation = sum.tanh();
        }
        let mut output = [0_u8; VALUE_BYTES + 2];
        result.confidence = 1.0;
        result.abstain = Some(AssociativeMemoryAbstentionV1::BelowSelectionThreshold);
        for column in 0..OUTPUT_BITS {
            let mut logit = f64::from(arrays.output_bias[column]);
            for (row, activation) in hidden.iter().enumerate() {
                logit += activation * f64::from(arrays.output_weights[row * OUTPUT_BITS + column]);
            }
            if !logit.is_finite() { return Err(AssociativeMemoryError::InvalidArtifact); }
            result.confidence = result.confidence.min(1.0 / (1.0 + (-logit.abs()).exp()));
            if logit >= 0.0 { output[column / 8] |= 1 << (7 - column % 8); }
        }
        if result.confidence < self.wire.threshold { return Ok(result); }
        let length = usize::from(u16::from_be_bytes([output[0], output[1]]));
        if !(1..=VALUE_BYTES).contains(&length) || output[2 + length..].iter().any(|byte| *byte != 0) {
            return Ok(result);
        }
        let payload = &output[2..2 + length];
        let Ok(value) = serde_json::from_slice::<Value>(payload) else { return Ok(result); };
        if validate_memory_cell_value_v1(self.kind(), &value).is_err() { return Ok(result); }
        let Some(object) = value.as_object() else { return Ok(result); };
        let canonical: BTreeMap<_, _> = object.iter().collect();
        if serde_json::to_vec(&canonical).map_err(|_| AssociativeMemoryError::InvalidArtifact)? != payload {
            return Ok(result);
        }
        result.value = Some(value);
        result.source_ids.clone_from(sources);
        result.abstain = None;
        Ok(result)
    }
}

fn valid_digest(value: &str) -> bool {
    value.parse::<Digest32>().is_ok_and(|digest| !digest.is_zero())
}

#[cfg(test)]
#[path = "memory_byte_cell_v9_tests.rs"]
mod tests;
