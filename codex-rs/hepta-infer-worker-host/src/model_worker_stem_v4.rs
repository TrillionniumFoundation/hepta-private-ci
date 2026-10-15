//! Research-only physical Q24 frozen projection Stem + V3 multi-Cell Reader.
//!
//! Executes a real CPU fixed-weight matrix projection ONCE per admitted source
//! sequence, then sends its one immutable FeatureSequence V3 to many Cell heads.
//! This is a bounded arithmetic reference, NOT a pretrained Transformer, model
//! signature, approved inference driver, source authenticity check, or FinalUse.
//! Full source bytes are transient, never retained in the returned observation.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_infer_core::sequence_feature_v3::FeatureCoordinatesV3;
use codex_hepta_infer_core::sequence_feature_v3::FeatureModalityV3;
use codex_hepta_infer_core::sequence_feature_v3::FeatureSequenceIdentityV3;
use codex_hepta_infer_core::sequence_feature_v3::ImmutableFeatureSequenceV3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::SequenceBatchObservationV3;
use super::SequenceCellHeadV3;
use super::SequenceReadFenceV3;
use super::evaluate_sequence_heads_v3;

const Q24: i64 = 1 << 24;
const MAX_Q24: i64 = 8 * Q24;
const MAX_ROWS: usize = 256;
const MAX_WIDTH: usize = 512;
const MAX_SOURCE_BYTES: usize = 65_536;
const MAX_ENCODER_MACS: u64 = 2_000_000;

/// Immutable model candidate. Selection and artifact authentication are external.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenProjectionProfileV4 {
    pub input_width: usize,
    pub output_width: usize,
    /// Row-major [output, input] tensor, each weight in [-1,+1] Q24.
    pub weights_q24: Vec<i64>,
    pub bias_q24: Vec<i64>,
    pub modality: FeatureModalityV3,
    pub tokenizer_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub quantization_digest: Digest32,
    pub preprocessing_digest: Digest32,
    pub adapter_digest: Digest32,
}

/// One complete original source PLUS the already typed, bounded numeric input.
/// This entry point does not tokenize source_bytes or prove they came from an
/// independent authenticated owner; both are only bound against a digest.
#[derive(Clone, Eq, PartialEq)]
pub struct StemSourceSequenceV4 {
    pub identity: FeatureSequenceIdentityV3,
    pub source_bytes: Vec<u8>,
    pub input_width: usize,
    pub values_q24: Vec<i64>,
    pub mask: Vec<u8>,
    pub coordinates: Vec<FeatureCoordinatesV3>,
    pub expires_at_ms: u64,
}

/// Reported counts describe real scalar operations executed by this function.
/// They exclude tokenizer, upstream numeric source conversion and OS RSS.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemPhysicalBatchReceiptV4 {
    pub encoder_digest: Digest32,
    pub source_digest: Digest32,
    pub feature_content_digest: Digest32,
    pub encoder_forwards_this_batch: u64,
    pub encoder_macs_this_batch: u64,
    pub cumulative_encoder_forwards: u64,
    pub cumulative_encoder_macs: u64,
    pub reader: SequenceBatchObservationV3,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StemPhysicalErrorV4 {
    InvalidProfile,
    InvalidSource,
    SourceIdentityMismatch,
    IncompatibleModel,
    Expired,
    BudgetExceeded,
    EncoderArithmetic,
    FeatureRejected,
    ReaderRejected,
}

impl fmt::Display for StemPhysicalErrorV4 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemPhysicalErrorV4 {}

/// A frozen reference CPU model. No optimizer, unsafe code or shared mutable
/// Cell state. The model's SHA identity changes when any frozen weight changes.
pub struct FrozenQ24ProjectionStemV4 {
    profile: FrozenProjectionProfileV4,
    digest: Digest32,
    forwards: u64,
    macs: u64,
}

impl FrozenQ24ProjectionStemV4 {
    pub fn new(profile: FrozenProjectionProfileV4) -> Result<Self, StemPhysicalErrorV4> {
        if profile.input_width == 0
            || profile.input_width > MAX_WIDTH
            || profile.output_width == 0
            || profile.output_width > MAX_WIDTH
            || profile.weights_q24.len()
                != profile
                    .input_width
                    .checked_mul(profile.output_width)
                    .ok_or(StemPhysicalErrorV4::InvalidProfile)?
            || profile.bias_q24.len() != profile.output_width
            || profile
                .weights_q24
                .iter()
                .any(|weight| !(-Q24..=Q24).contains(weight))
            || profile
                .bias_q24
                .iter()
                .any(|bias| !(-MAX_Q24..=MAX_Q24).contains(bias))
            || [
                profile.tokenizer_digest,
                profile.normalizer_digest,
                profile.quantization_digest,
                profile.preprocessing_digest,
                profile.adapter_digest,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(StemPhysicalErrorV4::InvalidProfile);
        }
        let mut bytes = b"hepta.stem.frozen-projection.q24.v4\0".to_vec();
        bytes.extend_from_slice(&(profile.input_width as u64).to_be_bytes());
        bytes.extend_from_slice(&(profile.output_width as u64).to_be_bytes());
        bytes.push(profile.modality as u8);
        for digest in [
            profile.tokenizer_digest,
            profile.normalizer_digest,
            profile.quantization_digest,
            profile.preprocessing_digest,
            profile.adapter_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in profile.weights_q24.iter().chain(profile.bias_q24.iter()) {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Self {
            profile,
            digest: Digest32::of_bytes(&bytes),
            forwards: 0,
            macs: 0,
        })
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    #[must_use]
    pub fn completed_forwards(&self) -> u64 {
        self.forwards
    }

    #[must_use]
    pub fn completed_macs(&self) -> u64 {
        self.macs
    }

    fn validate_source(
        &self,
        input: &StemSourceSequenceV4,
        now_ms: u64,
    ) -> Result<(Digest32, usize, u64), StemPhysicalErrorV4> {
        let source = canonical_stem_source_digest_v4(input)?;
        let expected = &input.identity;
        if expected
            .digest()
            .map_err(|_| StemPhysicalErrorV4::SourceIdentityMismatch)?
            .is_zero()
            || expected.base.input_digest != source
        {
            return Err(StemPhysicalErrorV4::SourceIdentityMismatch);
        }
        if expected.base.encoder_digest != self.digest
            || expected.base.tokenizer_digest != self.profile.tokenizer_digest
            || expected.base.normalizer_digest != self.profile.normalizer_digest
            || expected.base.quantization_digest != self.profile.quantization_digest
            || expected.preprocessing_digest != self.profile.preprocessing_digest
            || expected.adapter_digest != self.profile.adapter_digest
            || expected.modality != self.profile.modality
            || input.input_width != self.profile.input_width
        {
            return Err(StemPhysicalErrorV4::IncompatibleModel);
        }
        if now_ms >= input.expires_at_ms {
            return Err(StemPhysicalErrorV4::Expired);
        }
        // Canonical V3 coordinates and masked-padding rules are checked here,
        // before expensive Encoder arithmetic, and also by V3 snapshot build.
        let mut previous_time = None;
        let mut active = 0_u64;
        for (row, (&mask, coordinate)) in
            input.mask.iter().zip(&input.coordinates).enumerate()
        {
            if mask == 0 {
                if *coordinate != FeatureCoordinatesV3::default()
                    || input.values_q24
                        [row * input.input_width..(row + 1) * input.input_width]
                        .iter()
                        .any(|value| *value != 0)
                {
                    return Err(StemPhysicalErrorV4::InvalidSource);
                }
                continue;
            }
            active += 1;
            if coordinate.x > 8192 || coordinate.y > 8192 {
                return Err(StemPhysicalErrorV4::InvalidSource);
            }
            match expected.modality {
                FeatureModalityV3::Text
                    if coordinate.x != 0 || coordinate.y != 0 || coordinate.time_micros != 0 =>
                {
                    return Err(StemPhysicalErrorV4::InvalidSource);
                }
                FeatureModalityV3::Image if coordinate.time_micros != 0 => {
                    return Err(StemPhysicalErrorV4::InvalidSource);
                }
                FeatureModalityV3::Audio if coordinate.x != 0 || coordinate.y != 0 => {
                    return Err(StemPhysicalErrorV4::InvalidSource);
                }
                _ => {}
            }
            if matches!(
                expected.modality,
                FeatureModalityV3::Audio
                    | FeatureModalityV3::Video
                    | FeatureModalityV3::Multimodal
            ) {
                if previous_time.is_some_and(|time| coordinate.time_micros < time) {
                    return Err(StemPhysicalErrorV4::InvalidSource);
                }
                previous_time = Some(coordinate.time_micros);
            }
        }
        let macs = active
            .checked_mul(self.profile.input_width as u64)
            .and_then(|count| count.checked_mul(self.profile.output_width as u64))
            .ok_or(StemPhysicalErrorV4::EncoderArithmetic)?;
        if macs > MAX_ENCODER_MACS {
            return Err(StemPhysicalErrorV4::BudgetExceeded);
        }
        Ok((source, input.mask.len(), macs))
    }

    /// Physically performs a bounded, fixed-weight Q24 CPU forward. This is not
    /// a mock return value. A failing source never increments the forward meter.
    fn encode(
        &mut self,
        input: &StemSourceSequenceV4,
        now_ms: u64,
    ) -> Result<(Arc<ImmutableFeatureSequenceV3>, Digest32, u64), StemPhysicalErrorV4> {
        let (source, rows, macs) = self.validate_source(input, now_ms)?;
        let width = self.profile.output_width;
        let mut output = vec![0_i64; rows * width];
        for row in 0..rows {
            if input.mask[row] == 0 {
                continue;
            }
            let raw = &input.values_q24
                [row * input.input_width..(row + 1) * input.input_width];
            for out in 0..width {
                let weights = &self.profile.weights_q24
                    [out * input.input_width..(out + 1) * input.input_width];
                let total = weights.iter().zip(raw).fold(
                    0_i128,
                    |acc, (weight, value)| {
                        acc + i128::from(*weight) * i128::from(*value)
                    },
                );
                let projected = round_q24(total)?
                    .saturating_add(self.profile.bias_q24[out])
                    .clamp(-MAX_Q24, MAX_Q24);
                output[row * width + out] = projected;
            }
        }
        let snapshot = Arc::new(
            ImmutableFeatureSequenceV3::build(
                input.identity.clone(),
                input.expires_at_ms,
                rows,
                width,
                Arc::from(output),
                Arc::from(input.mask.clone()),
                Arc::from(input.coordinates.clone()),
            )
            .map_err(|_| StemPhysicalErrorV4::FeatureRejected)?,
        );
        let next_calls = self
            .forwards
            .checked_add(1)
            .ok_or(StemPhysicalErrorV4::EncoderArithmetic)?;
        let next_macs = self
            .macs
            .checked_add(macs)
            .ok_or(StemPhysicalErrorV4::EncoderArithmetic)?;
        self.forwards = next_calls;
        self.macs = next_macs;
        Ok((snapshot, source, macs))
    }

    /// One actual Encoder forward followed by independently parameterized
    /// sequence-aware Heads. The returned receipt grants NO model use/effects.
    pub fn encode_and_read(
        &mut self,
        input: &StemSourceSequenceV4,
        heads: &[Arc<SequenceCellHeadV3>],
        now_ms: u64,
        attention_pairs_cap: u64,
    ) -> Result<StemPhysicalBatchReceiptV4, StemPhysicalErrorV4> {
        if heads.is_empty()
            || heads.len() > 32
            || attention_pairs_cap == 0
            || attention_pairs_cap > 2_000_000
        {
            return Err(StemPhysicalErrorV4::BudgetExceeded);
        }
        // Admit the source and *all* Heads before the physical CPU forward.
        // An incompatible Head or impossible attention budget must not consume
        // an Encoder forward and then silently disappear as a failed batch.
        self.validate_source(input, now_ms)?;
        let valid = input.mask.iter().filter(|mask| **mask == 1).count() as u64;
        let mut distinct_cells = BTreeSet::new();
        let mut pairs = 0_u64;
        for head in heads {
            if !distinct_cells.insert(head.cell_id().clone())
                || !head.compatible_with(&input.identity, self.profile.output_width)
            {
                return Err(StemPhysicalErrorV4::ReaderRejected);
            }
            pairs = pairs
                .checked_add(head.attention_pairs_for(valid))
                .ok_or(StemPhysicalErrorV4::EncoderArithmetic)?;
        }
        if pairs > attention_pairs_cap {
            return Err(StemPhysicalErrorV4::BudgetExceeded);
        }
        let (snapshot, source, macs) = self.encode(input, now_ms)?;
        let fence = SequenceReadFenceV3 {
            now_ms,
            expected_identity: input.identity.clone(),
            expected_content_digest: snapshot.content_digest(),
            maximum_attention_pairs: attention_pairs_cap,
        };
        let reader = evaluate_sequence_heads_v3(&fence, &snapshot, heads)
            .map_err(|_| StemPhysicalErrorV4::ReaderRejected)?;
        let mut bytes = b"hepta.stem.physical-batch-receipt.v4\0".to_vec();
        for digest in [
            self.digest,
            source,
            snapshot.content_digest(),
            reader.observation_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.forwards.to_be_bytes());
        bytes.extend_from_slice(&self.macs.to_be_bytes());
        bytes.extend_from_slice(&macs.to_be_bytes());
        bytes.extend_from_slice(&now_ms.to_be_bytes());
        Ok(StemPhysicalBatchReceiptV4 {
            encoder_digest: self.digest,
            source_digest: source,
            feature_content_digest: snapshot.content_digest(),
            encoder_forwards_this_batch: 1,
            encoder_macs_this_batch: macs,
            cumulative_encoder_forwards: self.forwards,
            cumulative_encoder_macs: self.macs,
            reader,
            receipt_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// Bind the COMPLETE source bytes and the exact numeric input to the source
/// identity. This is a deterministic binding, NOT a provenance signature.
pub fn canonical_stem_source_digest_v4(
    input: &StemSourceSequenceV4,
) -> Result<Digest32, StemPhysicalErrorV4> {
    let rows = input.mask.len();
    if rows == 0
        || rows > MAX_ROWS
        || input.input_width == 0
        || input.input_width > MAX_WIDTH
        || input.source_bytes.is_empty()
        || input.source_bytes.len() > MAX_SOURCE_BYTES
        || input.values_q24.len() != rows * input.input_width
        || input.coordinates.len() != rows
        || !input.mask.contains(&1)
        || input.mask.iter().any(|value| *value > 1)
        || input
            .values_q24
            .iter()
            .any(|value| !(-MAX_Q24..=MAX_Q24).contains(value))
    {
        return Err(StemPhysicalErrorV4::InvalidSource);
    }
    let mut bytes = b"hepta.stem.complete-source.q24.v4\0".to_vec();
    bytes.extend_from_slice(&(input.source_bytes.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&input.source_bytes);
    bytes.extend_from_slice(&(rows as u64).to_be_bytes());
    bytes.extend_from_slice(&(input.input_width as u64).to_be_bytes());
    for value in &input.values_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&input.mask);
    for coordinate in &input.coordinates {
        bytes.extend_from_slice(&coordinate.x.to_be_bytes());
        bytes.extend_from_slice(&coordinate.y.to_be_bytes());
        bytes.extend_from_slice(&coordinate.time_micros.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn round_q24(product: i128) -> Result<i64, StemPhysicalErrorV4> {
    let magnitude = product.abs();
    let divisor = i128::from(Q24);
    let quotient = magnitude / divisor;
    let remainder = magnitude % divisor;
    let increment = if remainder * 2 > divisor
        || (remainder * 2 == divisor && quotient % 2 != 0)
    {
        1_i128
    } else {
        0_i128
    };
    let value = (quotient + increment) * product.signum();
    i64::try_from(value).map_err(|_| StemPhysicalErrorV4::EncoderArithmetic)
}

#[cfg(test)]
#[path = "model_worker_stem_v4_tests.rs"]
mod tests;
