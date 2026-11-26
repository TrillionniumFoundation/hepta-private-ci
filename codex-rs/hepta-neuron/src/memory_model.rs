//! Integer parameter-memory execution through the existing neuron model port.
//!
//! The host supplies an admitted manifest/config and owns source revocation.
//! This module verifies immutable bytes and performs the actual integer model
//! computation. It neither authenticates a trainer nor grants serving authority.
//! Resource byte counts describe owned model and numerical-array storage, not
//! process RSS or allocator overhead. The backend has no forecasting head: its
//! temporal prediction is explicitly zero, and confidence remains the runtime
//! calibration owner's responsibility.

use std::error::Error as StdError;
use std::fmt;
use std::mem::size_of;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::NeuronRuntimeConfigV1;
use crate::canonical_model_output_digest_v1;

const Q12: i64 = 4_096;
const Q24: i64 = 1 << 24;
const HEADER_BYTES: usize = 24;
const MAX_INPUTS: usize = 512;
const MAX_HIDDEN: usize = 1_024;
const MAX_BITS: usize = 32;
const MAX_MANIFEST_BYTES: usize = 32_768;

/// Exact integer arithmetic and serialization contract shared with the writer.
pub const MEMORY_CELL_Q12_PROFILE_V1: &[u8] = b"hepta.memory.hard-tanh.q12.v1:input-round=floor(x*4096+0.5);hidden=clip(floor((dot+2048)/4096),-4096,4096);logit=int64-dot;bit=logit>=0;bit-order=little;weights=int16le;matrix-order=C;bias=last-row";

/// Maximum complete HMCELL3 artifact length; the header is included.
pub const MAX_MEMORY_CELL_ARTIFACT_BYTES: usize =
    HEADER_BYTES + 2 * ((MAX_INPUTS + 1) * MAX_HIDDEN + (MAX_HIDDEN + 1) * MAX_BITS);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryCellModelError {
    InvalidArtifact,
    InvalidManifest,
    BindingMismatch,
    InvalidInput,
}

impl fmt::Display for MemoryCellModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for MemoryCellModelError {}

/// Raw parameter output. A bit value is a prediction, not a source revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellReadoutV1 {
    pub value: u32,
    pub logits_q24: Vec<i64>,
}

/// Owned immutable integer tensors, decoded only after complete-length checks.
#[derive(Clone, Debug)]
pub struct MemoryCellArtifactV1 {
    input_dimension: usize,
    hidden_width: usize,
    output_bits: usize,
    weights: Vec<i16>,
    digest: Digest32,
}

impl MemoryCellArtifactV1 {
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, MemoryCellModelError> {
        if !(HEADER_BYTES..=MAX_MEMORY_CELL_ARTIFACT_BYTES).contains(&bytes.len())
            || &bytes[..8] != b"HMCELL3\0"
        {
            return Err(MemoryCellModelError::InvalidArtifact);
        }
        let word = |offset: usize| u16::from_le_bytes([bytes[offset], bytes[offset + 1]]) as usize;
        let integer = |offset: usize| {
            u32::from_le_bytes([
                bytes[offset],
                bytes[offset + 1],
                bytes[offset + 2],
                bytes[offset + 3],
            ]) as usize
        };
        let input_dimension = word(10);
        let hidden_width = word(12);
        let output_bits = word(14);
        if word(8) != 1
            || !(1..=MAX_INPUTS).contains(&input_dimension)
            || !(1..=MAX_HIDDEN).contains(&hidden_width)
            || !(1..=MAX_BITS).contains(&output_bits)
            || integer(16) != Q12 as usize
        {
            return Err(MemoryCellModelError::InvalidArtifact);
        }
        // The dimension limits above bound both dot products well within i64.
        let parameters = (input_dimension + 1) * hidden_width + (hidden_width + 1) * output_bits;
        if integer(20) != parameters || bytes.len() != HEADER_BYTES + 2 * parameters {
            return Err(MemoryCellModelError::InvalidArtifact);
        }
        let weights = bytes[HEADER_BYTES..]
            .chunks_exact(2)
            .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
            .collect();
        Ok(Self {
            input_dimension,
            hidden_width,
            output_bits,
            weights,
            digest: Digest32::of_bytes(bytes),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn head_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.memory.integer-head.v1",
            self.digest.as_array(),
            MEMORY_CELL_Q12_PROFILE_V1,
        ])
    }

    pub fn input_dimension(&self) -> usize {
        self.input_dimension
    }

    pub fn hidden_width(&self) -> usize {
        self.hidden_width
    }

    pub fn output_bits(&self) -> usize {
        self.output_bits
    }

    pub fn output_width(&self) -> usize {
        self.output_bits.max(5)
    }

    pub fn predict_q12(
        &self,
        features: &[i16],
    ) -> Result<MemoryCellReadoutV1, MemoryCellModelError> {
        if features.len() != self.input_dimension
            || features
                .iter()
                .any(|value| !(-Q12..=Q12).contains(&i64::from(*value)))
        {
            return Err(MemoryCellModelError::InvalidInput);
        }
        let mut hidden = Vec::with_capacity(self.hidden_width + 1);
        for column in 0..self.hidden_width {
            let bias = i64::from(self.weights[self.input_dimension * self.hidden_width + column]);
            let accumulator =
                features
                    .iter()
                    .enumerate()
                    .fold(Q12 * bias, |sum, (row, feature)| {
                        sum + i64::from(*feature)
                            * i64::from(self.weights[row * self.hidden_width + column])
                    });
            hidden.push(((accumulator + Q12 / 2).div_euclid(Q12)).clamp(-Q12, Q12));
        }
        hidden.push(Q12);
        let second = (self.input_dimension + 1) * self.hidden_width;
        let mut logits_q24 = Vec::with_capacity(self.output_bits);
        let mut value = 0;
        for bit in 0..self.output_bits {
            let logit = hidden
                .iter()
                .enumerate()
                .fold(0_i64, |sum, (row, activation)| {
                    sum + *activation
                        * i64::from(self.weights[second + row * self.output_bits + bit])
                });
            if logit >= 0 {
                value |= 1_u32 << bit;
            }
            logits_q24.push(logit);
        }
        Ok(MemoryCellReadoutV1 { value, logits_q24 })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MemoryManifest {
    schema: String,
    model_id: String,
    generation: u64,
    weights_sha256: String,
    encoder_sha256: String,
    preprocessor_sha256: String,
    source_set_sha256: String,
    input_dimension: usize,
    hidden_width: usize,
    output_bits: usize,
}

/// Real integer model backend for an already selected neuron configuration.
///
/// The caller authenticates runtime/device identities, the selected manifest,
/// source-cut freshness and source authority. This local port verifies artifact
/// and manifest bytes, request generation/tuple, and every numerical bound.
pub struct MemoryCellModelPortV1 {
    artifact: MemoryCellArtifactV1,
    selected: NeuronRuntimeConfigV1,
    source_set_digest: Digest32,
    manifest: Vec<u8>,
}

impl MemoryCellModelPortV1 {
    pub fn from_bytes(
        artifact_bytes: &[u8],
        manifest_bytes: &[u8],
        selected: &NeuronRuntimeConfigV1,
    ) -> Result<Self, MemoryCellModelError> {
        if manifest_bytes.is_empty() || manifest_bytes.len() > MAX_MANIFEST_BYTES {
            return Err(MemoryCellModelError::InvalidManifest);
        }
        let artifact = MemoryCellArtifactV1::from_bytes(artifact_bytes)?;
        let manifest: MemoryManifest = serde_json::from_slice(manifest_bytes)
            .map_err(|_| MemoryCellModelError::InvalidManifest)?;
        let parse_digest = |value: &str| {
            value
                .parse::<Digest32>()
                .map_err(|_| MemoryCellModelError::InvalidManifest)
        };
        let source_set_digest = parse_digest(&manifest.source_set_sha256)?;
        if manifest.schema != "hepta.memory.native-model.v1"
            || source_set_digest.is_zero()
            || manifest.model_id != selected.model_id.as_str()
            || manifest.generation != selected.generation.get()
            || parse_digest(&manifest.weights_sha256)? != artifact.digest()
            || parse_digest(&manifest.encoder_sha256)? != selected.encoder_digest
            || parse_digest(&manifest.preprocessor_sha256)? != selected.preprocessor_digest
            || manifest.input_dimension != artifact.input_dimension
            || manifest.hidden_width != artifact.hidden_width
            || manifest.output_bits != artifact.output_bits
            || Digest32::of_bytes(manifest_bytes) != selected.model_manifest_digest
            || artifact.digest() != selected.weights_digest
            || artifact.head_digest() != selected.head_digest
            || selected.quantization_digest != Digest32::of_bytes(MEMORY_CELL_Q12_PROFILE_V1)
            || selected.input_feature_dimension != artifact.input_dimension
            || selected.state_width != artifact.output_width()
        {
            return Err(MemoryCellModelError::BindingMismatch);
        }
        Ok(Self {
            artifact,
            selected: selected.clone(),
            source_set_digest,
            manifest: manifest_bytes.to_vec(),
        })
    }

    pub fn source_set_digest(&self) -> Digest32 {
        self.source_set_digest
    }

    pub fn predict_q12(
        &self,
        features: &[i16],
    ) -> Result<MemoryCellReadoutV1, MemoryCellModelError> {
        self.artifact.predict_q12(features)
    }
}

impl NeuronModelPort for MemoryCellModelPortV1 {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        if request.config_id != self.selected.config_id
            || request.generation != self.selected.generation
            || request.model_id != self.selected.model_id
            || request.encoder_digest != self.selected.encoder_digest
            || request.head_digest != self.artifact.head_digest()
            || request.weights_digest != self.artifact.digest()
            || request.expected_output_width != self.artifact.output_width()
            || request.input_digest.is_zero()
            || request.feature_vector_q24.len() != self.artifact.input_dimension
            || request
                .feature_vector_q24
                .iter()
                .any(|value| !(-Q24..=Q24).contains(value))
        {
            return Err(NeuronModelError::Rejected);
        }
        let started = Instant::now();
        let features = request
            .feature_vector_q24
            .iter()
            .map(|value| ((*value + Q12 / 2).div_euclid(Q12)) as i16)
            .collect::<Vec<_>>();
        let readout = self
            .artifact
            .predict_q12(&features)
            .map_err(|_| NeuronModelError::Rejected)?;
        let mut drive_q24 = readout
            .logits_q24
            .iter()
            .map(|value| (*value).clamp(-8 * Q24, 8 * Q24))
            .collect::<Vec<_>>();
        drive_q24.resize(self.artifact.output_width(), 0);
        let prediction_q24 = vec![0; self.artifact.output_width()];
        let latency_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.selected.model_id.clone(),
            model_manifest_digest: self.selected.model_manifest_digest,
            weights_digest: self.artifact.digest(),
            tokenizer_digest: self.selected.tokenizer_digest,
            preprocessor_digest: self.selected.preprocessor_digest,
            quantization_id: StableId::new("memory.int16.q12.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            quantization_digest: Digest32::of_bytes(MEMORY_CELL_Q12_PROFILE_V1),
            backend_id: StableId::new("memory.integer.cpu.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            runtime_digest: self.selected.runtime_digest,
            device_identity_digest: self.selected.device_digest,
            latency_micros,
            resident_bytes: (size_of::<Self>()
                + self.artifact.weights.capacity() * size_of::<i16>()
                + self.manifest.capacity()
                + self.selected.model_id.as_str().len()
                + self.selected.config_id.as_str().len()) as u64,
        };
        let output_digest =
            canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &runtime_receipt)
                .map_err(|_| NeuronModelError::Rejected)?;
        let transient_allocation_bytes = ((self.artifact.hidden_width
            + 1
            + readout.logits_q24.capacity()
            + drive_q24.capacity()
            + prediction_q24.capacity())
            * size_of::<i64>()
            + features.capacity() * size_of::<i16>())
            as u64;
        Ok(NeuronModelOutputV1 {
            encoder_digest: self.selected.encoder_digest,
            head_digest: self.artifact.head_digest(),
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            transient_allocation_bytes,
            runtime_receipt,
        })
    }
}

#[cfg(test)]
#[path = "memory_model_tests.rs"]
mod tests;
