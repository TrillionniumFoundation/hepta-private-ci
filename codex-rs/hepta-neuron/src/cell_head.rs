use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::SharedFeatureBatchV1;

const CELL_HEAD_Q24_SCALE: i128 = 1_i128 << 24;

/// Maximum magnitude accepted for Q24 inputs, parameters, and outputs.
pub const MAX_CELL_HEAD_Q24_V1: i64 = 8 * (1_i64 << 24);

/// Maximum feature width a light Cell head may consume.
pub const MAX_CELL_HEAD_INPUT_WIDTH_V1: usize = 4_096;

/// Maximum number of action logits emitted by one Cell head.
pub const MAX_CELL_HEAD_ACTION_WIDTH_V1: usize = 16;

/// Maximum number of affine parameters in one Cell head.
pub const MAX_CELL_HEAD_PARAMS_V1: usize = 262_144;

/// An immutable, per-Cell affine head attached to one shared Encoder artifact.
///
/// Rows are stored in row-major order. The first action_width rows are action
/// logits, followed by one value row and one uncertainty row. All values use
/// signed Q24 integers, so the head is deterministic and bounded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellHeadV1 {
    cell_id: StableId,
    generation: Generation,
    encoder_digest: Digest32,
    head_digest: Digest32,
    input_width: usize,
    action_width: usize,
    weights_q24: Arc<[i64]>,
    bias_q24: Arc<[i64]>,
    abstain_threshold_q24: i64,
}

impl CellHeadV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cell_id: StableId,
        generation: Generation,
        encoder_digest: Digest32,
        head_digest: Digest32,
        input_width: usize,
        action_width: usize,
        weights_q24: Vec<i64>,
        bias_q24: Vec<i64>,
        abstain_threshold_q24: i64,
    ) -> Result<Self, CellHeadError> {
        validate_head_shape(
            encoder_digest,
            head_digest,
            input_width,
            action_width,
            &weights_q24,
            &bias_q24,
            abstain_threshold_q24,
        )?;

        let expected_digest = canonical_cell_head_digest_v1(
            &cell_id,
            generation,
            encoder_digest,
            input_width,
            action_width,
            &weights_q24,
            &bias_q24,
            abstain_threshold_q24,
        );
        if expected_digest != head_digest {
            return Err(CellHeadError::ParameterDigestMismatch);
        }

        Ok(Self {
            cell_id,
            generation,
            encoder_digest,
            head_digest,
            input_width,
            action_width,
            weights_q24: Arc::from(weights_q24.into_boxed_slice()),
            bias_q24: Arc::from(bias_q24.into_boxed_slice()),
            abstain_threshold_q24,
        })
    }

    #[must_use]
    pub fn cell_id(&self) -> &StableId {
        &self.cell_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub const fn input_width(&self) -> usize {
        self.input_width
    }

    #[must_use]
    pub const fn action_width(&self) -> usize {
        self.action_width
    }

    #[must_use]
    pub fn weights_q24(&self) -> &[i64] {
        &self.weights_q24
    }

    #[must_use]
    pub fn bias_q24(&self) -> &[i64] {
        &self.bias_q24
    }

    #[must_use]
    pub const fn abstain_threshold_q24(&self) -> i64 {
        self.abstain_threshold_q24
    }

    /// Evaluate this Cell against the one immutable feature artifact.
    ///
    /// Binding and generation mismatches fail closed before any arithmetic is
    /// performed. All Cells therefore consume the same shared feature slice
    /// while keeping their parameters private and independently addressable.
    pub fn evaluate(
        &self,
        batch: &SharedFeatureBatchV1,
    ) -> Result<CellHeadOutputV1, CellHeadError> {
        if batch.encoder_digest() != self.encoder_digest {
            return Err(CellHeadError::EncoderBindingMismatch);
        }
        if batch.generation() != self.generation {
            return Err(CellHeadError::GenerationMismatch);
        }
        let features = batch
            .features_for_cell(&self.cell_id)
            .ok_or(CellHeadError::CellNotInBatch)?;
        if features.len() != self.input_width {
            return Err(CellHeadError::FeatureWidthMismatch);
        }

        let row_count = self.action_width + 2;
        let mut scores = Vec::with_capacity(row_count);
        for row in 0..row_count {
            let bias = i128::from(self.bias_q24[row])
                .checked_mul(CELL_HEAD_Q24_SCALE)
                .ok_or(CellHeadError::ArithmeticOverflow)?;
            let mut accumulator = bias;
            let row_start = row * self.input_width;
            for (offset, feature) in features.iter().copied().enumerate() {
                let weight = self.weights_q24[row_start + offset];
                let product = i128::from(feature)
                    .checked_mul(i128::from(weight))
                    .ok_or(CellHeadError::ArithmeticOverflow)?;
                accumulator = accumulator
                    .checked_add(product)
                    .ok_or(CellHeadError::ArithmeticOverflow)?;
            }
            let raw = accumulator
                .checked_div(CELL_HEAD_Q24_SCALE)
                .ok_or(CellHeadError::ArithmeticOverflow)?;
            let score = i64::try_from(raw).map_err(|_| CellHeadError::ArithmeticOverflow)?;
            if !(-MAX_CELL_HEAD_Q24_V1..=MAX_CELL_HEAD_Q24_V1).contains(&score) {
                return Err(CellHeadError::OutputRangeViolation);
            }
            scores.push(score);
        }

        let value_q24 = scores[self.action_width];
        let uncertainty_q24 = scores[self.action_width + 1];
        if uncertainty_q24 < 0 {
            return Err(CellHeadError::OutputRangeViolation);
        }
        let action_logits_q24: Arc<[i64]> =
            Arc::from(scores[..self.action_width].to_vec().into_boxed_slice());
        let abstain = uncertainty_q24 > self.abstain_threshold_q24;
        let action_digest = canonical_cell_head_action_digest_v1(
            self,
            batch,
            action_logits_q24.as_ref(),
            value_q24,
            uncertainty_q24,
            abstain,
        );
        Ok(CellHeadOutputV1 {
            cell_id: self.cell_id.clone(),
            head_digest: self.head_digest,
            action_digest,
            action_logits_q24,
            value_q24,
            uncertainty_q24,
            abstain,
        })
    }
}

/// Deterministic result emitted by one Cell head.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellHeadOutputV1 {
    pub cell_id: StableId,
    pub head_digest: Digest32,
    pub action_digest: Digest32,
    pub action_logits_q24: Arc<[i64]>,
    pub value_q24: i64,
    pub uncertainty_q24: i64,
    pub abstain: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellHeadError {
    EmptyDigest(&'static str),
    InvalidInputWidth,
    InvalidActionWidth,
    ParameterLimitExceeded(usize),
    ParameterShapeMismatch,
    ParameterDigestMismatch,
    ParameterRangeViolation,
    ThresholdRangeViolation,
    EncoderBindingMismatch,
    GenerationMismatch,
    CellNotInBatch,
    FeatureWidthMismatch,
    ArithmeticOverflow,
    OutputRangeViolation,
}

impl fmt::Display for CellHeadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellHeadError {}

/// Canonical digest of the immutable Cell head definition.
#[allow(clippy::too_many_arguments)]
pub fn canonical_cell_head_digest_v1(
    cell_id: &StableId,
    generation: Generation,
    encoder_digest: Digest32,
    input_width: usize,
    action_width: usize,
    weights_q24: &[i64],
    bias_q24: &[i64],
    abstain_threshold_q24: i64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.cell-head.v1");
    push_id(&mut bytes, cell_id);
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(encoder_digest.as_array());
    push_len(&mut bytes, input_width);
    push_len(&mut bytes, action_width);
    bytes.extend_from_slice(&abstain_threshold_q24.to_be_bytes());
    push_q24_vector(&mut bytes, weights_q24);
    push_q24_vector(&mut bytes, bias_q24);
    Digest32::of_bytes(&bytes)
}

fn canonical_cell_head_action_digest_v1(
    head: &CellHeadV1,
    batch: &SharedFeatureBatchV1,
    action_logits_q24: &[i64],
    value_q24: i64,
    uncertainty_q24: i64,
    abstain: bool,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.cell-head.action.v1");
    push_id(&mut bytes, &head.cell_id);
    bytes.extend_from_slice(&head.generation.get().to_be_bytes());
    bytes.extend_from_slice(head.encoder_digest.as_array());
    bytes.extend_from_slice(head.head_digest.as_array());
    bytes.extend_from_slice(batch.input_digest().as_array());
    bytes.extend_from_slice(batch.feature_digest().as_array());
    push_q24_vector(&mut bytes, action_logits_q24);
    bytes.extend_from_slice(&value_q24.to_be_bytes());
    bytes.extend_from_slice(&uncertainty_q24.to_be_bytes());
    bytes.push(u8::from(abstain));
    Digest32::of_bytes(&bytes)
}

fn validate_head_shape(
    encoder_digest: Digest32,
    head_digest: Digest32,
    input_width: usize,
    action_width: usize,
    weights_q24: &[i64],
    bias_q24: &[i64],
    abstain_threshold_q24: i64,
) -> Result<(), CellHeadError> {
    if encoder_digest.is_zero() {
        return Err(CellHeadError::EmptyDigest("encoder"));
    }
    if head_digest.is_zero() {
        return Err(CellHeadError::EmptyDigest("head"));
    }
    if !(1..=MAX_CELL_HEAD_INPUT_WIDTH_V1).contains(&input_width) {
        return Err(CellHeadError::InvalidInputWidth);
    }
    if !(1..=MAX_CELL_HEAD_ACTION_WIDTH_V1).contains(&action_width) {
        return Err(CellHeadError::InvalidActionWidth);
    }
    let row_count = action_width + 2;
    let parameter_count = row_count * input_width;
    if parameter_count > MAX_CELL_HEAD_PARAMS_V1 {
        return Err(CellHeadError::ParameterLimitExceeded(parameter_count));
    }
    if weights_q24.len() != parameter_count || bias_q24.len() != row_count {
        return Err(CellHeadError::ParameterShapeMismatch);
    }
    if weights_q24
        .iter()
        .chain(bias_q24.iter())
        .any(|value| !(-MAX_CELL_HEAD_Q24_V1..=MAX_CELL_HEAD_Q24_V1).contains(value))
    {
        return Err(CellHeadError::ParameterRangeViolation);
    }
    if !(0..=MAX_CELL_HEAD_Q24_V1).contains(&abstain_threshold_q24) {
        return Err(CellHeadError::ThresholdRangeViolation);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_q24_vector(bytes: &mut Vec<u8>, values: &[i64]) {
    push_len(bytes, values.len());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}

#[cfg(test)]
#[path = "cell_head_tests.rs"]
mod tests;
