//! FP64 execution of the fixed 770D QA Head profile. No training or calibration.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::learned_cell_features::SharedLearnedFeatures770V1;

pub const LEARNED_HEAD_MAGIC_770_V1: &[u8] = b"HEPTA-CELL-HEAD-770-F64-V1\0";
const HEADER_BYTES: usize = LEARNED_HEAD_MAGIC_770_V1.len() + 105;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearnedHeadMode770V1 {
    Linear,
    Gated,
    Residual,
}

impl LearnedHeadMode770V1 {
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Self::Linear => "linear",
            Self::Gated => "gated",
            Self::Residual => "residual",
        }
    }

    fn layout(self) -> &'static [(&'static str, &'static str, usize)] {
        match self {
            Self::Linear => &[("W", "[770,2]", 1540), ("b", "[2]", 2)],
            Self::Gated => &[
                ("W", "[770,2]", 1540),
                ("a", "[770]", 770),
                ("b", "[2]", 2),
                ("g", "[770]", 770),
            ],
            Self::Residual => &[
                ("U", "[4,770]", 3080),
                ("V", "[770,4]", 3080),
                ("W", "[770,2]", 1540),
                ("a", "[770]", 770),
                ("b", "[2]", 2),
                ("g", "[770]", 770),
            ],
        }
    }
}

/// Caller-selected pins, including SHA256(task_id UTF-8) and the original
/// NumpyCellHead.digest(). A matching width alone never grants compatibility.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LearnedHeadPins770V1 {
    pub artifact_digest: Digest32,
    pub feature_identity_digest: Digest32,
    pub generation: Generation,
    pub task_digest: Digest32,
    pub predictor_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct LearnedCellHead770V1 {
    pins: LearnedHeadPins770V1,
    mode: LearnedHeadMode770V1,
    parameters: Arc<[f64]>,
}

impl LearnedCellHead770V1 {
    /// Import raw little-endian arrays in sorted parameter-name order, without
    /// quantizing or rewriting the trained values. Only width770/classes2/rank4
    /// is accepted. The complete envelope and original tensor digest are checked.
    pub fn import(
        bytes: &[u8],
        expected: &LearnedHeadPins770V1,
    ) -> Result<Self, LearnedHeadError770V1> {
        if !(HEADER_BYTES..=HEADER_BYTES + 9242 * 8).contains(&bytes.len())
            || [
                expected.artifact_digest,
                expected.feature_identity_digest,
                expected.task_digest,
                expected.predictor_digest,
            ]
            .iter()
            .any(|x| x.is_zero())
        {
            return Err(LearnedHeadError770V1::InvalidEnvelope);
        }
        if Digest32::of_bytes(bytes) != expected.artifact_digest {
            return Err(LearnedHeadError770V1::ArtifactDigestMismatch);
        }
        if !bytes.starts_with(LEARNED_HEAD_MAGIC_770_V1) {
            return Err(LearnedHeadError770V1::InvalidEnvelope);
        }
        let header = &bytes[LEARNED_HEAD_MAGIC_770_V1.len()..HEADER_BYTES];
        let mode = match header[0] {
            0 => LearnedHeadMode770V1::Linear,
            1 => LearnedHeadMode770V1::Gated,
            2 => LearnedHeadMode770V1::Residual,
            _ => return Err(LearnedHeadError770V1::InvalidEnvelope),
        };
        if &header[1..33] != expected.feature_identity_digest.as_array()
            || &header[41..73] != expected.task_digest.as_array()
            || &header[73..105] != expected.predictor_digest.as_array()
        {
            return Err(LearnedHeadError770V1::IdentityMismatch);
        }
        if header[33..41] != expected.generation.get().to_le_bytes() {
            return Err(LearnedHeadError770V1::GenerationMismatch);
        }
        let count: usize = mode.layout().iter().map(|x| x.2).sum();
        if bytes.len() != HEADER_BYTES + count * 8 {
            return Err(LearnedHeadError770V1::InvalidEnvelope);
        }
        let mut digest_input = format!("[770,2,\"{}\",4]", mode.name()).into_bytes();
        let mut offset = HEADER_BYTES;
        for (name, shape, count) in mode.layout() {
            digest_input.extend_from_slice(format!("[\"{name}\",{shape},\"<f8\"]").as_bytes());
            digest_input.extend_from_slice(&bytes[offset..offset + count * 8]);
            offset += count * 8;
        }
        if Digest32::of_bytes(&digest_input) != expected.predictor_digest {
            return Err(LearnedHeadError770V1::PredictorDigestMismatch);
        }
        let mut parameters = Vec::with_capacity(count);
        for chunk in bytes[HEADER_BYTES..].chunks_exact(8) {
            let mut value = [0_u8; 8];
            value.copy_from_slice(chunk);
            let value = f64::from_le_bytes(value);
            if !value.is_finite() {
                return Err(LearnedHeadError770V1::Nonfinite);
            }
            parameters.push(value);
        }
        Ok(Self {
            pins: *expected,
            mode,
            parameters: Arc::from(parameters),
        })
    }

    /// Borrow one shared normalized feature buffer. No Encoder, feature copy,
    /// optimizer, probability calibration, or action authorization is created.
    /// Nonfinite intermediates fail even when later clipping or tanh could hide
    /// an overflow; parity is qualified for the accepted finite execution domain.
    pub fn evaluate(
        &self,
        batch: &SharedLearnedFeatures770V1,
    ) -> Result<LearnedCellLogits770V1, LearnedHeadError770V1> {
        if batch.feature_identity_digest() != self.pins.feature_identity_digest {
            return Err(LearnedHeadError770V1::IdentityMismatch);
        }
        if batch.generation() != self.pins.generation {
            return Err(LearnedHeadError770V1::GenerationMismatch);
        }
        let p = &self.parameters;
        let residual = self.mode == LearnedHeadMode770V1::Residual;
        let gated = self.mode != LearnedHeadMode770V1::Linear;
        let w_start = if residual { 6160 } else { 0 };
        let a_start = w_start + 1540;
        let b_start = a_start + if gated { 770 } else { 0 };
        let g_start = b_start + 2;
        let mut raw_logits = Vec::with_capacity(batch.rows());
        for x in batch.normalized.chunks_exact(770) {
            let mut hidden = [0.0_f64; 4];
            if residual {
                for (j, value) in hidden.iter_mut().enumerate() {
                    for (i, feature) in x.iter().enumerate() {
                        *value += feature * p[3080 + i * 4 + j];
                    }
                    if !value.is_finite() {
                        return Err(LearnedHeadError770V1::Nonfinite);
                    }
                    *value = value.tanh();
                }
            }
            let mut logits = [0.0_f64; 2];
            for (i, feature) in x.iter().copied().enumerate() {
                let mut value = feature;
                if gated {
                    let argument = feature * p[a_start + i] + p[g_start + i];
                    if !argument.is_finite() {
                        return Err(LearnedHeadError770V1::Nonfinite);
                    }
                    value *= 1.0 / (1.0 + (-argument.clamp(-40.0, 40.0)).exp());
                }
                if residual {
                    for (j, hidden) in hidden.iter().enumerate() {
                        value += hidden * p[j * 770 + i];
                    }
                }
                if !value.is_finite() {
                    return Err(LearnedHeadError770V1::Nonfinite);
                }
                for (j, logit) in logits.iter_mut().enumerate() {
                    *logit += value * p[w_start + i * 2 + j];
                }
            }
            for (j, logit) in logits.iter_mut().enumerate() {
                *logit += p[b_start + j];
                if !logit.is_finite() {
                    return Err(LearnedHeadError770V1::Nonfinite);
                }
            }
            raw_logits.push(logits);
        }
        Ok(LearnedCellLogits770V1 {
            predictor_digest: self.pins.predictor_digest,
            feature_identity_digest: self.pins.feature_identity_digest,
            feature_batch_digest: batch.artifact_digest(),
            generation: self.pins.generation,
            task_digest: self.pins.task_digest,
            raw_logits,
            calibration: LearnedCellCalibration770V1::Unavailable,
            mode: LearnedCellExecutionMode770V1::ShadowOnly,
            quality_qualified: false,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub const fn mode(&self) -> LearnedHeadMode770V1 {
        self.mode
    }

    /// Owned parameter bytes, excluding metadata, caller input and scratch.
    #[must_use]
    pub fn tensor_bytes(&self) -> usize {
        self.parameters.len() * std::mem::size_of::<f64>()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearnedCellExecutionMode770V1 {
    ShadowOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearnedCellCalibration770V1 {
    Unavailable,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LearnedCellLogits770V1 {
    pub predictor_digest: Digest32,
    pub feature_identity_digest: Digest32,
    pub feature_batch_digest: Digest32,
    pub generation: Generation,
    pub task_digest: Digest32,
    pub raw_logits: Vec<[f64; 2]>,
    pub calibration: LearnedCellCalibration770V1,
    pub mode: LearnedCellExecutionMode770V1,
    pub quality_qualified: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearnedHeadError770V1 {
    InvalidEnvelope,
    ArtifactDigestMismatch,
    IdentityMismatch,
    GenerationMismatch,
    PredictorDigestMismatch,
    Nonfinite,
}

impl fmt::Display for LearnedHeadError770V1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearnedHeadError770V1 {}

#[cfg(test)]
#[path = "learned_cell_head_tests.rs"]
mod tests;
